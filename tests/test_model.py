from xiv_craftcalc.model import BUY, CRAFT, Node, calculate


def gemdraught() -> Node:
    """Grade 4 Gemdraught: makes 3, uses a Sanctified Water sub-craft (makes 3)."""
    water = Node(2, "Sanctified Water", amount=1, yields=3, price=400, children=[
        Node(10, "Spring Water", amount=2, price=70),
        Node(11, "Weeds", amount=2, price=5),
        Node(12, "Water Crystal", amount=8, price=45),
    ])
    return Node(1, "Gemdraught", yields=3, can_hq=True, children=[
        Node(3, "Yollal", amount=1, price=2000),
        water,
        Node(4, "Parsley", amount=1, price=100),
    ])


def by_name(root: Node, name: str) -> Node:
    return next(n for _, n in root.walk() if n.name == name)


def test_target_rounds_up_to_whole_crafts():
    r = calculate(gemdraught(), target=10, sell_price=0, tax=0)
    assert r.crafts_needed == 4
    assert r.planned_items == 12


def test_needs_follow_mode():
    root = gemdraught()
    calculate(root, 30, 0, 0)  # 10 crafts, water bought
    assert by_name(root, "Sanctified Water").need == 10
    assert by_name(root, "Weeds").need == 0
    assert not by_name(root, "Weeds").active

    by_name(root, "Sanctified Water").mode = CRAFT
    calculate(root, 30, 0, 0)  # 10 water -> 4 sub-crafts
    assert by_name(root, "Sanctified Water").crafts == 4
    assert by_name(root, "Weeds").need == 8
    assert by_name(root, "Water Crystal").need == 32


def test_bought_intermediate_reduces_subcrafts():
    root = gemdraught()
    water = by_name(root, "Sanctified Water")
    water.mode, water.bought = CRAFT, 4
    calculate(root, 30, 0, 0)  # need 10, have 4 -> 6 more -> 2 crafts
    assert water.crafts == 2
    assert by_name(root, "Weeds").need == 4


def test_planned_profit():
    r = calculate(gemdraught(), target=3, sell_price=4000, tax=0.05)
    # 1 craft: 2000 + 400 + 100 = 2500; revenue 3 * 4000 * 0.95 = 11400
    assert r.planned_cost == 2500
    assert r.planned_revenue == 11400
    assert r.planned_profit == 8900


def test_actual_limited_by_scarcest_material():
    root = gemdraught()
    water = by_name(root, "Sanctified Water")
    water.mode = CRAFT
    for name, qty in {"Yollal": 6, "Parsley": 10, "Spring Water": 8,
                      "Weeds": 8, "Water Crystal": 40}.items():
        by_name(root, name).bought = qty
    r = calculate(root, 30, 1000, 0)
    # water: 4 sub-crafts -> 12 water; yollal 6 is the cap
    assert r.can_craft == 6
    assert r.can_make == 18
    assert r.limiting == "Yollal"
    assert r.spent == 6 * 2000 + 10 * 100 + 8 * 70 + 8 * 5 + 40 * 45
    assert r.profit == 18 * 1000 - r.spent


def test_subcraft_can_be_the_limit():
    root = gemdraught()
    water = by_name(root, "Sanctified Water")
    water.mode = CRAFT
    for name, qty in {"Yollal": 99, "Parsley": 99, "Spring Water": 2,
                      "Weeds": 99, "Water Crystal": 99}.items():
        by_name(root, name).bought = qty
    r = calculate(root, 30, 1000, 0)
    assert r.can_craft == 3  # one sub-craft -> 3 water
    assert r.limiting == "Spring Water"


def test_pick_cheapest_mode():
    root = gemdraught()
    root.pick_cheapest_mode()  # craft = (140 + 10 + 360) / 3 = 170 < 400
    assert by_name(root, "Sanctified Water").mode == CRAFT
    by_name(root, "Sanctified Water").mode = BUY
    by_name(root, "Sanctified Water").price = 100
    root.pick_cheapest_mode()
    assert by_name(root, "Sanctified Water").mode == BUY


def test_zero_means_on_hand_and_free():
    root = gemdraught()
    by_name(root, "Yollal").bought = 6  # only Yollal entered
    r = calculate(root, target=30, sell_price=1000, tax=0)
    assert r.can_craft == 6
    assert r.limiting == "Yollal"
    assert r.spent == 12000
    assert r.profit == 18 * 1000 - 12000


def test_nothing_entered_uses_target():
    r = calculate(gemdraught(), target=30, sell_price=1000, tax=0)
    assert r.can_craft == 10
    assert r.can_make == 30
    assert r.spent == 0
    assert r.limiting == ""


def test_zero_subcraft_mats_are_free():
    root = gemdraught()
    by_name(root, "Sanctified Water").mode = CRAFT
    by_name(root, "Spring Water").bought = 2  # 1 sub-craft -> 3 water
    r = calculate(root, target=30, sell_price=1000, tax=0)
    assert r.can_craft == 3
    assert r.limiting == "Spring Water"
