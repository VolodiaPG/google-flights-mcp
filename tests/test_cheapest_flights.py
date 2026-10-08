from datetime import date

import pytest

from cheapest_flights import build_searches, find_cheapest, parse_args


def test_one_way_covers_every_day_inclusive():
    s = build_searches("CDG", "LIS", date(2026, 12, 1), date(2026, 12, 3), None)
    assert [x.depart.day for x in s] == [1, 2, 3]
    assert all(x.ret is None for x in s)


def test_round_trip_return_never_after_end():
    s = build_searches("CDG", "LIS", date(2026, 12, 1), date(2026, 12, 6), (3, 5))
    pairs = {(x.depart, x.ret) for x in s}
    assert all(r <= date(2026, 12, 6) for _, r in pairs)
    assert (date(2026, 12, 1), date(2026, 12, 6)) in pairs
    assert (date(2026, 12, 2), date(2026, 12, 7)) not in pairs


def test_bad_input_rejected():
    base = ["CDG", "LIS", "--start", "2026-12-01", "--end", "2026-12-05"]
    assert parse_args(base).origin == "CDG"
    for bad in (["CDGX"] + base[1:], base + ["--nights", "5-2"]):
        with pytest.raises(SystemExit):
            parse_args(bad)


def test_invalid_window_rejected():
    with pytest.raises(ValueError, match="before start"):
        find_cheapest("CDG", "LIS", date(2026, 12, 5), date(2026, 12, 1))
    with pytest.raises(ValueError, match="past"):
        find_cheapest("CDG", "LIS", date(2020, 1, 1), date(2020, 1, 2))
