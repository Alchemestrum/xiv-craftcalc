# xiv-craftcalc

A terminal UI for working out whether an FFXIV craft is worth making for profit.

Pick a data center and the world you'll sell on, search a recipe, say how many you want, and type in what you managed to buy. It tells you how many you can actually craft and what you'll make after market tax.

Prices come from [Universalis](https://universalis.app) and recipes from [XIVAPI](https://v2.xivapi.com). No accounts or API keys needed.

## Features

- **Data center + sell world picker** (every region Universalis tracks), remembered between runs
- **Recipe search** with the full ingredient tree, sub-crafts included
- **Want N items**: rounds up to whole crafts using the recipe's yield (e.g. 10 potions at 3/craft = 4 crafts, 12 potions)
- **Per-material prices** pre-filled from the cheapest listing on your DC (`ctrl+b` switches to average sale price), editable if you paid something else
- **Bought column**: type what you have and it works out how many crafts that covers, which material runs out first, and your real profit
- **Buy or craft** toggle for sub-crafts (like Sanctified Water), defaulting to whichever is cheaper
- **HQ / NQ** sell price, units sold per day on the sell world, and adjustable tax (5% default, 3% or 0% in cheaper cities)

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/Alchemestrum/xiv-craftcalc.git
cd xiv-craftcalc
uv venv && uv pip install -e .
.venv/bin/craftcalc
```

Or with plain pip: `python -m venv .venv && .venv/bin/pip install -e .`

## Keys

| Key | Action |
|---|---|
| `ctrl+f` | Jump to recipe search |
| `ctrl+r` | Refresh prices |
| `ctrl+b` | Toggle material prices between cheapest listing and average sale |
| `ctrl+n` | Clear all bought quantities |
| `tab` | Move between fields |
| `ctrl+q` | Quit |

## Reading the screen

| Column | Meaning |
|---|---|
| need | How many the plan needs (greyed out if the parent is set to buy) |
| price ea | Unit price used in the math |
| bought | What you bought for this craft; leave 0 for anything already on hand (free, never limits crafts) |
| spent | bought x price |
| to buy | Still missing (red), covered (✔), or ⚒N sub-crafts to make |
| DC cheapest | Cheapest listing on the DC and its world, ⌀ average sale, ⚒ cost to craft one yourself |

The **plan** panel assumes you buy exactly what's needed. The **with what you bought** panel uses only your bought column.

## Caveats

Universalis data is crowdsourced from players' uploads, so quiet items can be hours or days stale, and the cheapest listing is often only a few units. Check the in-game board before buying in bulk.

Config is stored at `~/.config/xiv-craftcalc/config.json`.

## Tests

```bash
uv pip install -e '.[dev]' && .venv/bin/pytest
```
