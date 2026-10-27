"""Working days for HKP deadlines: Mon–Fri excluding statutory holidays (HKP-RL §5(2), §6(5)).

Bavaria has two municipality-level rules the Land calendar can't express:
Mariä Himmelfahrt (Aug 15) is a holiday only in mainly Catholic municipalities,
and the city of Augsburg adds the Friedensfest (Aug 8). Heiligabend and
Silvester are working days by law, but many practices and Kassen are closed;
that is a policy switch, not a fact.
"""

import datetime as dt
from functools import lru_cache
from typing import Literal

import holidays

ClosedDayPolicy = Literal["working_day", "closed"]

# Mainly Catholic → Mariä Himmelfahrt is a holiday. Bayerisches Landesamt für Statistik
# publishes the full list; unknown Bavarian municipalities default to True (the large majority).
ASSUMPTION_DAY_BY_MUNICIPALITY: dict[str, bool] = {
    "Augsburg": True,
    "Deggendorf": True,
    "München": True,
    "Nürnberg": False,
}


class WorkingDayCalendar:
    def __init__(
        self,
        subdiv: str = "BY",
        municipality: str | None = None,
        *,
        assumption_day: bool | None = None,
        heiligabend: ClosedDayPolicy = "working_day",
        silvester: ClosedDayPolicy = "working_day",
    ):
        self.subdiv = subdiv
        self.municipality = municipality
        if assumption_day is None:
            assumption_day = subdiv == "BY" and ASSUMPTION_DAY_BY_MUNICIPALITY.get(
                municipality or "", True
            )
        self.assumption_day = assumption_day
        self.heiligabend = heiligabend
        self.silvester = silvester
        # Augsburg is its own subdivision in `holidays` (BY + Friedensfest).
        self._subdiv = "Augsburg" if subdiv == "BY" and municipality == "Augsburg" else subdiv
        categories = ("public", "catholic") if assumption_day else ("public",)
        self._holidays = holidays.Germany(subdiv=self._subdiv, categories=categories)

    def holiday_name(self, day: dt.date) -> str | None:
        name = self._holidays.get(day)
        if name is None and day.month == 12:
            if day.day == 24 and self.heiligabend == "closed":
                name = "Heiligabend"
            elif day.day == 31 and self.silvester == "closed":
                name = "Silvester"
        return name

    def is_working_day(self, day: dt.date) -> bool:
        return day.weekday() < 5 and self.holiday_name(day) is None

    def add_working_days(self, start: dt.date, n: int) -> dt.date:
        """The n-th working day after `start` (start itself never counts); n < 0 goes back."""
        step = dt.timedelta(days=1 if n >= 0 else -1)
        day, left = start, abs(n)
        while left:
            day += step
            if self.is_working_day(day):
                left -= 1
        return day

    def last_working_days(self, end: dt.date, n: int) -> list[dt.date]:
        """The n working days on or before `end`, earliest first."""
        days: list[dt.date] = []
        day = end
        while len(days) < n:
            if self.is_working_day(day):
                days.append(day)
            day -= dt.timedelta(days=1)
        return days[::-1]

    def working_days_between(self, start: dt.date, end: dt.date) -> int:
        """Working days in (start, end]: 1 means `end` is the first working day after `start`."""
        count, day = 0, start
        while day < end:
            day += dt.timedelta(days=1)
            count += self.is_working_day(day)
        return count


@lru_cache(maxsize=64)
def calendar_for(
    subdiv: str = "BY",
    municipality: str | None = None,
    heiligabend: ClosedDayPolicy = "working_day",
    silvester: ClosedDayPolicy = "working_day",
) -> WorkingDayCalendar:
    return WorkingDayCalendar(subdiv, municipality, heiligabend=heiligabend, silvester=silvester)


def is_working_day(day: dt.date, calendar: WorkingDayCalendar | None = None) -> bool:
    return (calendar or calendar_for()).is_working_day(day)


def add_working_days(start: dt.date, n: int, calendar: WorkingDayCalendar | None = None) -> dt.date:
    return (calendar or calendar_for()).add_working_days(start, n)
