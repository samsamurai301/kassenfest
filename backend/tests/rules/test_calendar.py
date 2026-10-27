"""Working-day boundary cases from docs/02 §8."""

from datetime import date as D

import pytest

from kassenfest.rules.calendar import (
    WorkingDayCalendar,
    add_working_days,
    calendar_for,
    is_working_day,
)

DEGGENDORF = calendar_for("BY", "Deggendorf")


def test_oct_3_on_a_saturday_is_not_counted_twice():
    # Thu Oct 1 → Fri 2, (Sat 3 = Tag der Deutschen Einheit), Mon 5, Tue 6, Wed 7
    assert DEGGENDORF.add_working_days(D(2026, 10, 1), 4) == D(2026, 10, 7)


def test_month_boundary_with_allerheiligen_on_a_sunday():
    # Thu Oct 29 → Fri 30, Mon Nov 2, Tue 3, Wed 4
    assert DEGGENDORF.add_working_days(D(2026, 10, 29), 4) == D(2026, 11, 4)


@pytest.mark.parametrize(
    ("policy", "deadline"),
    [
        ("working_day", D(2026, 12, 30)),  # Dec 24 (by law), 28, 29, 30
        ("closed", D(2026, 12, 31)),  # Dec 28, 29, 30, 31
    ],
)
def test_christmas_with_heiligabend_policy(policy, deadline):
    cal = calendar_for("BY", "Deggendorf", heiligabend=policy)
    assert cal.add_working_days(D(2026, 12, 23), 4) == deadline


def test_silvester_policy():
    assert calendar_for("BY", "Deggendorf").is_working_day(D(2026, 12, 31))
    assert not calendar_for("BY", "Deggendorf", silvester="closed").is_working_day(D(2026, 12, 31))


def test_maria_himmelfahrt_depends_on_the_municipality():
    # 2026-08-15 is a Saturday; 2025-08-15 is a Friday, so test the switch there.
    assert DEGGENDORF.holiday_name(D(2025, 8, 15)) == "Mariä Himmelfahrt"
    nuernberg = calendar_for("BY", "Nürnberg")
    assert nuernberg.is_working_day(D(2025, 8, 15))
    assert DEGGENDORF.add_working_days(D(2025, 8, 14), 4) == D(2025, 8, 21)
    assert nuernberg.add_working_days(D(2025, 8, 14), 4) == D(2025, 8, 20)
    assert DEGGENDORF.add_working_days(D(2026, 8, 14), 4) == D(2026, 8, 20)


def test_unknown_bavarian_municipality_defaults_to_catholic_and_can_be_overridden():
    assert not WorkingDayCalendar("BY", "Irgendwo").is_working_day(D(2025, 8, 15))
    assert WorkingDayCalendar("BY", "Irgendwo", assumption_day=False).is_working_day(D(2025, 8, 15))


def test_augsburg_friedensfest():
    augsburg = calendar_for("BY", "Augsburg")
    assert augsburg.holiday_name(D(2025, 8, 8)) == "Augsburger Hohes Friedensfest"
    assert DEGGENDORF.is_working_day(D(2025, 8, 8))


def test_fronleichnam_is_bavarian_not_berlin():
    # Tue Jun 2 → Jun 3, (Jun 4 Fronleichnam), Jun 5, Jun 8, Jun 9; in Berlin Jun 8
    assert DEGGENDORF.add_working_days(D(2026, 6, 2), 4) == D(2026, 6, 9)
    assert calendar_for("BE").add_working_days(D(2026, 6, 2), 4) == D(2026, 6, 8)


def test_leap_year_february_2028():
    assert DEGGENDORF.add_working_days(D(2028, 2, 25), 2) == D(2028, 2, 29)
    assert DEGGENDORF.add_working_days(D(2028, 2, 28), 2) == D(2028, 3, 1)


def test_backwards_and_window_helpers():
    assert DEGGENDORF.add_working_days(D(2026, 10, 7), -4) == D(2026, 10, 1)
    assert DEGGENDORF.last_working_days(D(2026, 10, 14), 3) == [
        D(2026, 10, 12),
        D(2026, 10, 13),
        D(2026, 10, 14),
    ]
    # Expiry on a Sunday: the window is the three working days before it.
    assert DEGGENDORF.last_working_days(D(2026, 10, 4), 3) == [
        D(2026, 9, 30),
        D(2026, 10, 1),
        D(2026, 10, 2),
    ]
    assert DEGGENDORF.working_days_between(D(2026, 10, 1), D(2026, 10, 8)) == 5


def test_module_level_helpers_use_bavaria():
    assert not is_working_day(D(2026, 6, 4))  # Fronleichnam
    assert add_working_days(D(2026, 10, 1), 4) == D(2026, 10, 7)
