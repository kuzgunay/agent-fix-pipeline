"""Due dates for monthly billing."""
import datetime


def is_leap_year(year: int) -> bool:
    return year % 4 == 0


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if is_leap_year(year) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def add_months(day: datetime.date, months: int) -> datetime.date:
    """The same day `months` later, clamped to the last day of a shorter month (Jan 31 + 1 month -> Feb 28/29)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return datetime.date(year, month, min(day.day, days_in_month(year, month)))
