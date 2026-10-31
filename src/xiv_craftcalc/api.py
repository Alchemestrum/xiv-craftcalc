"""XIVAPI (recipes) and Universalis (prices) clients."""

from __future__ import annotations

import httpx

from .model import Market, Node

XIVAPI = "https://v2.xivapi.com/api"
UNIVERSALIS = "https://universalis.app/api/v2"
HEADERS = {"User-Agent": "xiv-craftcalc (github.com/Alchemestrum/xiv-craftcalc)"}

RECIPE_FIELDS = ",".join(
    [
        "AmountResult",
        "CraftType.Name",
        "ItemResult.Name",
        "ItemResult.CanBeHq",
        "Ingredient[].Name",
        "AmountIngredient",
    ]
)

# Shards, crystals and clusters (item ids 2-19) have no recipe; skip the lookup.
CRYSTAL_IDS = range(2, 20)


class Api:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(headers=HEADERS, timeout=20)
        self.worlds: dict[int, str] = {}
        self._recipes: dict[int, dict | None] = {}

    async def close(self) -> None:
        await self.http.aclose()

    # ── data centers ────────────────────────────────────────────
    async def data_centers(self) -> list[dict]:
        """[{name, region, worlds: [names]}], sorted by region then name."""
        dcs = (await self.http.get(f"{UNIVERSALIS}/data-centers")).json()
        worlds = (await self.http.get(f"{UNIVERSALIS}/worlds")).json()
        self.worlds = {w["id"]: w["name"] for w in worlds}
        out = []
        for dc in dcs:
            names = sorted(self.worlds[w] for w in dc["worlds"] if w in self.worlds)
            if names:
                out.append({"name": dc["name"], "region": dc["region"], "worlds": names})
        return sorted(out, key=lambda d: (d["region"], d["name"]))

    # ── recipes ─────────────────────────────────────────────────
    async def search_recipes(self, text: str, limit: int = 30) -> list[dict]:
        """[{recipe_id, item_id, name, job}] for recipes whose result matches text."""
        text = text.replace('"', "")
        r = await self.http.get(
            f"{XIVAPI}/search",
            params={
                "sheets": "Recipe",
                "query": f'ItemResult.Name~"{text}"',
                "fields": "ItemResult.Name,CraftType.Name",
                "limit": limit,
            },
        )
        r.raise_for_status()
        out = []
        for row in r.json().get("results", []):
            f = row["fields"]
            out.append(
                {
                    "recipe_id": row["row_id"],
                    "item_id": f["ItemResult"]["row_id"],
                    "name": f["ItemResult"]["fields"]["Name"],
                    "job": f["CraftType"]["fields"]["Name"],
                }
            )
        return out

    async def _recipes_for(self, item_ids: list[int]) -> None:
        """Cache the first recipe (or None) for each item id."""
        todo = [i for i in item_ids if i not in self._recipes and i not in CRYSTAL_IDS]
        for i in item_ids:
            if i in CRYSTAL_IDS:
                self._recipes[i] = None
        if not todo:
            return
        r = await self.http.get(
            f"{XIVAPI}/search",
            params={
                "sheets": "Recipe",
                "query": " ".join(f"ItemResult={i}" for i in todo),
                "fields": RECIPE_FIELDS,
                "limit": 100,
            },
        )
        r.raise_for_status()
        for i in todo:
            self._recipes.setdefault(i, None)
        for row in r.json().get("results", []):
            item = row["fields"]["ItemResult"]["row_id"]
            if self._recipes.get(item) is None:
                self._recipes[item] = row["fields"]

    async def recipe(self, recipe_id: int) -> Node:
        """Full ingredient tree for a recipe, sub-recipes included."""
        r = await self.http.get(
            f"{XIVAPI}/sheet/Recipe/{recipe_id}", params={"fields": RECIPE_FIELDS}
        )
        r.raise_for_status()
        root = self._node(r.json()["fields"], amount=1)
        await self._expand(root.children, depth=0)
        return root

    def _node(self, f: dict, amount: int) -> Node:
        item = f["ItemResult"]
        node = Node(
            item_id=item["row_id"],
            name=item["fields"]["Name"],
            amount=amount,
            yields=f["AmountResult"] or 1,
            job=f["CraftType"]["fields"]["Name"],
            can_hq=bool(item["fields"].get("CanBeHq")),
        )
        for ing, amt in zip(f["Ingredient"], f["AmountIngredient"]):
            if amt and ing["row_id"]:
                node.children.append(
                    Node(item_id=ing["row_id"], name=ing["fields"]["Name"], amount=amt)
                )
        return node

    async def _expand(self, nodes: list[Node], depth: int) -> None:
        if not nodes or depth > 5:
            return
        await self._recipes_for([n.item_id for n in nodes])
        deeper: list[Node] = []
        for n in nodes:
            f = self._recipes.get(n.item_id)
            if f:
                sub = self._node(f, n.amount)
                n.yields, n.job, n.children = sub.yields, sub.job, sub.children
                deeper.extend(n.children)
        await self._expand(deeper, depth + 1)

    # ── prices ──────────────────────────────────────────────────
    async def prices(self, root: Node, world: str, hq: bool) -> None:
        """Fill .market (and default .price) for every node from Universalis.

        One aggregated call against the sell world returns both the world's
        numbers (for selling) and the whole DC's numbers (for buying).
        """
        nodes = [root] + [n for _, n in root.walk()]
        ids = sorted({n.item_id for n in nodes})
        data: dict[int, dict] = {}
        for i in range(0, len(ids), 100):
            chunk = ",".join(map(str, ids[i : i + 100]))
            r = await self.http.get(f"{UNIVERSALIS}/aggregated/{world}/{chunk}")
            r.raise_for_status()
            for res in r.json().get("results", []):
                data[res["itemId"]] = res
        for n in nodes:
            n.market = self._market(data.get(n.item_id), hq if n is root else None)
            if n is not root:
                n.price = n.market.buy_min or n.market.buy_avg or 0

    def _market(self, res: dict | None, sell_hq: bool | None) -> Market:
        m = Market()
        if not res:
            return m
        # buying: cheapest of NQ / HQ across the DC
        best = None
        for q in ("nq", "hq"):
            dc = res[q]["minListing"].get("dc")
            if dc and (best is None or dc["price"] < best["price"]):
                best = dc
        if best:
            m.buy_min = best["price"]
            m.buy_world = self.worlds.get(best.get("worldId"), "")
        avgs = [res[q]["averageSalePrice"].get("dc", {}).get("price") for q in ("nq", "hq")]
        avgs = [a for a in avgs if a]
        m.buy_avg = round(min(avgs)) if avgs else None
        # selling: chosen quality on the sell world
        if sell_hq is not None:
            q = res["hq" if sell_hq else "nq"]
            m.sell_min = (q["minListing"].get("world") or {}).get("price")
            avg = (q["averageSalePrice"].get("world") or {}).get("price")
            m.sell_avg = round(avg) if avg else None
            m.velocity = (q["dailySaleVelocity"].get("world") or {}).get("quantity")
        return m
