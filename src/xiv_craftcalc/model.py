"""Recipe tree and the cost / profit math. No I/O here, so it is easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

BUY = "buy"
CRAFT = "craft"


@dataclass
class Market:
    """What one item costs on the data center and sells for on the chosen world."""

    buy_min: int | None = None  # cheapest listing on the DC (NQ or HQ)
    buy_world: str = ""  # world that cheapest listing is on
    buy_avg: int | None = None  # average recent sale on the DC
    sell_min: int | None = None  # cheapest listing on the sell world
    sell_avg: int | None = None  # average recent sale on the sell world
    velocity: float | None = None  # units sold per day on the sell world


@dataclass
class Node:
    item_id: int
    name: str
    amount: int = 1  # how many the parent recipe uses per craft
    yields: int = 1  # how many one craft of this node makes
    job: str = ""
    can_hq: bool = False
    children: list[Node] = field(default_factory=list)
    mode: str = BUY
    market: Market = field(default_factory=Market)
    price: int = 0  # unit price used in the math (user can override)
    bought: int = 0  # how many the user already has / bought

    # filled in by calculate()
    need: int = 0
    crafts: int = 0
    active: bool = True

    @property
    def craftable(self) -> bool:
        return bool(self.children)

    def walk(self, depth: int = 0):
        """Yield (depth, node) for every ingredient below this node."""
        for child in self.children:
            yield depth, child
            yield from child.walk(depth + 1)

    def craft_unit_cost(self) -> float | None:
        """Cost of one unit made from cheapest-way ingredients."""
        if not self.children:
            return None
        total = 0.0
        for c in self.children:
            unit = c.best_unit_cost()
            if unit is None:
                return None
            total += unit * c.amount
        return total / self.yields

    def best_unit_cost(self) -> float | None:
        options = [p for p in (self.price or None, self.craft_unit_cost()) if p is not None]
        return min(options) if options else None

    def pick_cheapest_mode(self) -> None:
        """Default each sub-craft to whichever of buy/craft is cheaper."""
        for _, node in self.walk():
            if node.craftable:
                craft = node.craft_unit_cost()
                if craft is not None and (not node.price or craft < node.price):
                    node.mode = CRAFT


@dataclass
class Result:
    target: int
    crafts_needed: int
    planned_items: int
    planned_cost: int
    planned_revenue: int
    can_craft: int  # crafts possible with what was bought
    can_make: int  # items that makes
    spent: int
    revenue: int
    limiting: str  # name of the material that runs out first

    @property
    def planned_profit(self) -> int:
        return self.planned_revenue - self.planned_cost

    @property
    def profit(self) -> int:
        return self.revenue - self.spent


def _plan(node: Node, parent_crafts: int, active: bool) -> int:
    """Set need/crafts down the tree. Returns planned gil for this subtree."""
    node.active = active
    node.need = parent_crafts * node.amount if active else 0
    if node.mode == CRAFT and node.craftable and active:
        node.crafts = ceil(max(0, node.need - node.bought) / node.yields)
        cost = node.bought * node.price
        for c in node.children:
            cost += _plan(c, node.crafts, True)
        return cost
    node.crafts = 0
    for c in node.children:
        _plan(c, 0, False)
    return node.need * node.price if active else 0


def _available(node: Node) -> tuple[int | None, str]:
    """Units of this node on hand. None = left at 0, assumed owned / free."""
    if node.mode == CRAFT and node.craftable:
        crafts, limiting = _possible_crafts(node)
        if crafts is None:
            return None, ""
        return node.bought + crafts * node.yields, limiting
    if not node.bought:
        return None, ""
    return node.bought, node.name


def _possible_crafts(recipe: Node) -> tuple[int | None, str]:
    """Crafts the entered quantities allow. None = nothing entered limits it."""
    best, limiting = None, ""
    for c in recipe.children:
        have, lim = _available(c)
        if have is None:
            continue
        n = have // c.amount
        if best is None or n < best:
            best, limiting = n, lim
    return best, limiting


def calculate(root: Node, target: int, sell_price: int, tax: float) -> Result:
    crafts = ceil(max(target, 0) / root.yields)
    planned_cost = sum(_plan(c, crafts, True) for c in root.children)
    planned_items = crafts * root.yields

    can_craft, limiting = _possible_crafts(root)
    if can_craft is None:  # every material left at 0: assume all on hand
        can_craft = crafts
    spent = sum(n.bought * n.price for _, n in root.walk() if n.active)
    can_make = can_craft * root.yields

    keep = 1 - tax
    return Result(
        target=target,
        crafts_needed=crafts,
        planned_items=planned_items,
        planned_cost=planned_cost,
        planned_revenue=round(planned_items * sell_price * keep),
        can_craft=can_craft,
        can_make=can_make,
        spent=spent,
        revenue=round(can_make * sell_price * keep),
        limiting=limiting,
    )
