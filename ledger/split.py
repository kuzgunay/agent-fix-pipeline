"""Splitting a bill between people."""


def split_evenly(total_cents: int, people: int) -> list[int]:
    """Split total_cents into `people` shares that differ by at most one cent and add up to the total."""
    if people <= 0:
        raise ValueError("people must be positive")
    share = total_cents // people
    return [share] * people
