"""Amounts are kept as integer cents."""


def to_cents(amount: str) -> int:
    """Parse a decimal amount such as "12.50" or "7" into cents."""
    value = float(amount.strip())
    return int(value * 100)


def format_cents(cents: int) -> str:
    """Format cents as a decimal string with two places, e.g. 1250 -> "12.50"."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
