"""Textual TUI: pick DC/world, search a recipe, enter quantities, see profit."""

from __future__ import annotations

import json
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Input, Label, OptionList, Select, Static, Switch
from textual.widgets.option_list import Option

from .api import Api
from .model import BUY, CRAFT, Node, calculate

CONFIG = Path.home() / ".config" / "xiv-craftcalc" / "config.json"


def gil(n: float | int | None) -> str:
    return "—" if n is None else f"{round(n):,}"


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def as_int(text: str) -> int:
    try:
        return max(0, int(text.replace(",", "")))
    except ValueError:
        return 0


class MatRow(Horizontal):
    """One material: name, buy/craft toggle, need, price, bought, cost, market."""

    def __init__(self, node: Node, depth: int) -> None:
        super().__init__(classes="row")
        self.node = node
        self.depth = depth

    def compose(self) -> ComposeResult:
        n = self.node
        pad = "  " * self.depth + ("└ " if self.depth else "")
        yield Static(f"{pad}{n.name}", classes="c-name")
        if n.craftable:
            yield Button(self._mode_label(), classes="c-mode", compact=True)
        else:
            yield Static("", classes="c-mode")
        yield Static("", classes="c-need")
        yield Input(str(n.price), type="integer", classes="c-price", compact=True)
        yield Input(str(n.bought) if n.bought else "", placeholder="0", type="integer",
                    classes="c-bought", compact=True)
        yield Static("", classes="c-cost")
        yield Static("", classes="c-short")
        yield Static("", classes="c-mkt")

    def _mode_label(self) -> str:
        return "⚒ craft" if self.node.mode == CRAFT else "⛁ buy"

    @on(Button.Pressed)
    def toggle_mode(self, event: Button.Pressed) -> None:
        event.stop()
        self.node.mode = BUY if self.node.mode == CRAFT else CRAFT
        event.button.label = self._mode_label()
        if self.node.mode == CRAFT:
            self.query_one(".c-bought", Input).value = ""
        self.app.recalc()

    @on(Input.Changed, ".c-price")
    def price_changed(self, event: Input.Changed) -> None:
        self.node.price = as_int(event.value)
        self.app.recalc()

    @on(Input.Changed, ".c-bought")
    def bought_changed(self, event: Input.Changed) -> None:
        self.node.bought = as_int(event.value)
        self.app.recalc()

    def set_price(self, price: int) -> None:
        self.query_one(".c-price", Input).value = str(price)

    def refresh_values(self) -> None:
        n, m = self.node, self.node.market
        self.set_class(not n.active, "inactive")
        # crafting it: its own boxes are unused. Buying it: its mats are unused.
        locked = not n.active or (n.mode == CRAFT and n.craftable)
        for box in self.query(".c-price, .c-bought").results(Input):
            box.disabled = locked
        if not n.active and n.bought:
            self.query_one(".c-bought", Input).value = ""
        self.query_one(".c-need", Static).update(gil(n.need) if n.active else "·")
        cost = n.bought * n.price
        self.query_one(".c-cost", Static).update(gil(cost) if n.active and cost else "")
        short = max(0, n.need - n.bought)
        if n.active and n.mode == CRAFT and n.craftable:
            self.query_one(".c-short", Static).update(f"[#ff9f1c]⚒{n.crafts}[/]")
        elif n.active and short:
            self.query_one(".c-short", Static).update(f"[#ff4f6d]{gil(short)}[/]")
        elif n.active and n.need:
            self.query_one(".c-short", Static).update("[#3cff8f]✔[/]")
        else:
            self.query_one(".c-short", Static).update("")
        mkt = f"[#ffd23f]{gil(m.buy_min)}[/] [#6c7a96]@{m.buy_world or '?'}[/]  [#4fc3f7]⌀{gil(m.buy_avg)}[/]"
        craft = n.craft_unit_cost()
        if craft is not None:
            mkt += f"  [#c77dff]⚒{gil(craft)}[/]"
        self.query_one(".c-mkt", Static).update(mkt)


class CraftCalc(App):
    CSS_PATH = "app.tcss"
    TITLE = "xiv-craftcalc"
    BINDINGS = [
        Binding("ctrl+f", "focus_search", "⌕ search"),
        Binding("ctrl+r", "refresh_prices", "⟳ prices"),
        Binding("ctrl+b", "price_basis", "⇄ min/avg"),
        Binding("ctrl+n", "clear_bought", "⌫ bought"),
        Binding("ctrl+q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.api = Api()
        self.cfg = load_config()
        self.dcs: dict[str, list[str]] = {}
        self.root: Node | None = None
        self.basis = self.cfg.get("basis", "min")
        self._search_timer = None

    # ── layout ──────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Label("◈", classes="sym dc")
            yield Select([], prompt="data center", id="dc", compact=True)
            yield Label("⌂", classes="sym world")
            yield Select([], prompt="sell world", id="world", compact=True)
            yield Label("★HQ", classes="sym hq")
            yield Switch(value=self.cfg.get("hq", True), id="hq")
            yield Label("% tax", classes="sym tax")
            yield Input(f"{self.cfg.get('tax', 5):g}", type="number", id="tax", compact=True)
            yield Static("", id="status")
        with Vertical(id="searchbox"):
            yield Input(placeholder="⌕  type a recipe name…", id="search")
            yield OptionList(id="results")
        with Horizontal(id="recipebar"):
            yield Static("[#6c7a96]no recipe loaded[/]", id="title")
            yield Label("◎ want", classes="sym want")
            yield Input("", placeholder="0", type="integer", id="target", compact=True)
            yield Label("⇡ sell @", classes="sym sell")
            yield Input("", placeholder="0", type="integer", id="sellprice", compact=True)
            yield Static("", id="sellinfo")
        with Horizontal(id="header", classes="row"):
            yield Static("material", classes="c-name")
            yield Static("", classes="c-mode")
            yield Static("need", classes="c-need")
            yield Static("price ea", classes="c-price")
            yield Static("bought", classes="c-bought")
            yield Static("spent", classes="c-cost")
            yield Static("to buy", classes="c-short")
            yield Static("DC cheapest @world  ⌀avg  ⚒craft cost", classes="c-mkt")
        yield VerticalScroll(id="mats")
        with Horizontal(id="summary"):
            yield Static("", id="plan", classes="panel")
            yield Static("", id="actual", classes="panel")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#results").display = False
        self.query_one("#plan").border_title = "◎ plan"
        self.query_one("#actual").border_title = "⛁ with what you bought"
        self.load_dcs()

    async def on_unmount(self) -> None:
        await self.api.close()

    def status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    # ── data center / world ─────────────────────────────────────
    @work(exclusive=True, group="dcs")
    async def load_dcs(self) -> None:
        self.status("[#ffd23f]⟳ loading data centers…[/]")
        try:
            dcs = await self.api.data_centers()
        except Exception as e:  # noqa: BLE001 - show any network failure
            self.status(f"[#ff4f6d]✖ {e}[/]")
            return
        self.dcs = {d["name"]: d["worlds"] for d in dcs}
        sel = self.query_one("#dc", Select)
        sel.set_options([(f"{d['name']}  ({d['region']})", d["name"]) for d in dcs])
        if self.cfg.get("dc") in self.dcs:
            sel.value = self.cfg["dc"]
        self.status("")

    @on(Select.Changed, "#dc")
    def dc_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        worlds = self.dcs.get(event.value, [])
        wsel = self.query_one("#world", Select)
        wsel.set_options([(w, w) for w in worlds])
        want = self.cfg.get("world")
        if want in worlds:
            wsel.value = want
        elif worlds:
            wsel.value = worlds[0]
        self.cfg["dc"] = event.value
        save_config(self.cfg)

    @on(Select.Changed, "#world")
    def world_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK:
            return
        self.cfg["world"] = event.value
        save_config(self.cfg)
        if self.root:
            self.fetch_prices()

    @on(Switch.Changed, "#hq")
    def hq_changed(self, event: Switch.Changed) -> None:
        self.cfg["hq"] = event.value
        save_config(self.cfg)
        if self.root:
            self.fetch_prices()

    @on(Input.Changed, "#tax")
    def tax_changed(self, event: Input.Changed) -> None:
        try:
            self.cfg["tax"] = max(0.0, min(100.0, float(event.value)))
        except ValueError:
            return
        save_config(self.cfg)
        self.recalc()

    # ── recipe search ───────────────────────────────────────────
    @on(Input.Changed, "#search")
    def search_changed(self, event: Input.Changed) -> None:
        if self._search_timer:
            self._search_timer.stop()
        text = event.value.strip()
        if len(text) < 3:
            self.query_one("#results").display = False
            return
        self._search_timer = self.set_timer(0.35, lambda: self.run_search(text))

    @on(Input.Submitted, "#search")
    def search_submitted(self) -> None:
        results = self.query_one("#results", OptionList)
        if results.display and results.option_count:
            results.focus()
            results.highlighted = 0

    @work(exclusive=True, group="search")
    async def run_search(self, text: str) -> None:
        try:
            found = await self.api.search_recipes(text)
        except Exception as e:  # noqa: BLE001
            self.status(f"[#ff4f6d]✖ search: {e}[/]")
            return
        results = self.query_one("#results", OptionList)
        results.clear_options()
        results.add_options(
            Option(f"{r['name']}  [#6c7a96]{r['job']}[/]", id=str(r["recipe_id"]))
            for r in found
        )
        results.display = bool(found)

    @on(OptionList.OptionSelected, "#results")
    def recipe_chosen(self, event: OptionList.OptionSelected) -> None:
        self.query_one("#results").display = False
        self.load_recipe(int(event.option.id))

    @work(exclusive=True, group="recipe")
    async def load_recipe(self, recipe_id: int) -> None:
        self.status("[#ffd23f]⟳ loading recipe…[/]")
        try:
            root = await self.api.recipe(recipe_id)
        except Exception as e:  # noqa: BLE001
            self.status(f"[#ff4f6d]✖ recipe: {e}[/]")
            return
        self.root = root
        self.query_one("#hq", Switch).value = root.can_hq and self.cfg.get("hq", True)
        self.query_one("#title", Static).update(
            f"[b #00e5ff]{root.name}[/]  [#c77dff]{root.job}[/]  [#6c7a96]×{root.yields}/craft[/]"
        )
        mats = self.query_one("#mats", VerticalScroll)
        await mats.remove_children()
        await mats.mount_all(MatRow(n, d) for d, n in root.walk())
        if not self.query_one("#target", Input).value:
            self.query_one("#target", Input).value = str(root.yields)
        self.fetch_prices()
        self.query_one("#target", Input).focus()

    # ── prices ──────────────────────────────────────────────────
    @work(exclusive=True, group="prices")
    async def fetch_prices(self) -> None:
        world = self.query_one("#world", Select).value
        if not self.root or world is Select.BLANK:
            self.status("[#ffd23f]◈ pick a data center / world[/]")
            return
        self.status(f"[#ffd23f]⟳ prices @ {world}…[/]")
        hq = self.query_one("#hq", Switch).value
        try:
            await self.api.prices(self.root, world, hq)
        except Exception as e:  # noqa: BLE001
            self.status(f"[#ff4f6d]✖ prices: {e}[/]")
            return
        self.apply_basis()
        self.root.pick_cheapest_mode()
        for row in self.query(MatRow):
            if row.node.craftable:
                row.query_one(Button).label = row._mode_label()
        m = self.root.market
        sell = m.sell_min or m.sell_avg or 0
        self.query_one("#sellprice", Input).value = str(sell)
        self.status(f"[#3cff8f]✔ {world}[/] [#6c7a96]({self.basis} prices)[/]")
        self.recalc()

    def apply_basis(self) -> None:
        for row in self.query(MatRow):
            m = row.node.market
            first, second = (m.buy_min, m.buy_avg) if self.basis == "min" else (m.buy_avg, m.buy_min)
            row.set_price(first or second or 0)

    # ── math ────────────────────────────────────────────────────
    @on(Input.Changed, "#target, #sellprice")
    def numbers_changed(self) -> None:
        self.recalc()

    def recalc(self) -> None:
        if not self.root:
            return
        target = as_int(self.query_one("#target", Input).value)
        sell = as_int(self.query_one("#sellprice", Input).value)
        tax = self.cfg.get("tax", 5) / 100
        r = calculate(self.root, target, sell, tax)
        for row in self.query(MatRow):
            row.refresh_values()

        m = self.root.market
        q = "★HQ" if self.query_one("#hq", Switch).value else "NQ"
        vel = f"{m.velocity:,.0f}/day" if m.velocity is not None else "—"
        self.query_one("#sellinfo", Static).update(
            f"[#6c7a96]{q} low[/] [#ffd23f]{gil(m.sell_min)}[/]  "
            f"[#6c7a96]⌀[/][#4fc3f7]{gil(m.sell_avg)}[/]  [#6c7a96]sold[/] [#3cff8f]{vel}[/]"
        )

        def money(n: int) -> str:
            color = "#3cff8f" if n >= 0 else "#ff4f6d"
            return f"[b {color}]{'+' if n >= 0 else ''}{gil(n)}[/]"

        def per(n: int, items: int) -> str:
            return gil(n / items) if items else "—"

        self.query_one("#plan", Static).update(
            f"[#6c7a96]crafts[/]   [#c77dff]{r.crafts_needed}[/] [#6c7a96]→[/] "
            f"[#00e5ff]{r.planned_items}[/] [#6c7a96]items[/]\n"
            f"[#6c7a96]cost[/]     [#ffd23f]{gil(r.planned_cost)}[/]\n"
            f"[#6c7a96]revenue[/]  [#4fc3f7]{gil(r.planned_revenue)}[/] [#6c7a96]after tax[/]\n"
            f"[#6c7a96]profit[/]   {money(r.planned_profit)}  "
            f"[#6c7a96]({per(r.planned_profit, r.planned_items)} ea)[/]"
        )
        limit = f"  [#6c7a96]limit:[/] [#ff9f1c]{r.limiting}[/]" if r.limiting else ""
        self.query_one("#actual", Static).update(
            f"[#6c7a96]crafts[/]   [#c77dff]{r.can_craft}[/] [#6c7a96]→[/] "
            f"[#00e5ff]{r.can_make}[/] [#6c7a96]items[/]{limit}\n"
            f"[#6c7a96]spent[/]    [#ffd23f]{gil(r.spent)}[/]\n"
            f"[#6c7a96]revenue[/]  [#4fc3f7]{gil(r.revenue)}[/] [#6c7a96]after tax[/]\n"
            f"[#6c7a96]profit[/]   {money(r.profit)}  [#6c7a96]({per(r.profit, r.can_make)} ea)[/]"
        )

    # ── actions ─────────────────────────────────────────────────
    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_refresh_prices(self) -> None:
        if self.root:
            self.fetch_prices()

    def action_price_basis(self) -> None:
        self.basis = "avg" if self.basis == "min" else "min"
        self.cfg["basis"] = self.basis
        save_config(self.cfg)
        if self.root:
            self.apply_basis()
            self.status(f"[#6c7a96]price basis:[/] [#ffd23f]{self.basis}[/]")

    def action_clear_bought(self) -> None:
        for row in self.query(MatRow):
            row.query_one(".c-bought", Input).value = ""


def main() -> None:
    CraftCalc().run()


if __name__ == "__main__":
    main()
