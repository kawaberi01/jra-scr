from jra_srb.jra_prediction_engine import _build_wide_tickets


TOP = [
    {"horse_no": "1", "horse_name": "軸"},
    {"horse_no": "2", "horse_name": "相手A"},
    {"horse_no": "3", "horse_name": "相手B"},
]


def test_wide_tickets_are_not_created_without_market_odds():
    assert _build_wide_tickets(TOP, {}, 1000, "202607110301") == []


def test_wide_tickets_use_only_available_combinations():
    tickets = _build_wide_tickets(
        TOP,
        {("1", "3"): 5.2},
        1000,
        "202607110301",
    )

    assert [(ticket["selection"], ticket["amount"]) for ticket in tickets] == [("1-3", 1000)]
    assert "5.2倍" in tickets[0]["reason"]
