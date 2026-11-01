"""A minimal invoice: lines, a total and a due date."""
import dataclasses
import datetime

from ledger.dates import add_months
from ledger.money import format_cents, to_cents


@dataclasses.dataclass
class Line:
    description: str
    amount: str  # as typed by the user, e.g. "19.99"
    quantity: int = 1

    @property
    def cents(self) -> int:
        return to_cents(self.amount) * self.quantity


@dataclasses.dataclass
class Invoice:
    issued: datetime.date
    lines: list[Line] = dataclasses.field(default_factory=list)
    terms_months: int = 1

    @property
    def total_cents(self) -> int:
        return sum(line.cents for line in self.lines)

    @property
    def due(self) -> datetime.date:
        return add_months(self.issued, self.terms_months)

    def summary(self) -> str:
        return f"Total {format_cents(self.total_cents)}, due {self.due.isoformat()}"
