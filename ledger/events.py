"""Inbound events: what the outside world asks the ledger to do.

Events are *requests*, not postings. The distinction is load-bearing and the
relationship is not one to one:

* E10 (one credit, three instalments) produces three entries;
* E6 (a settlement with no matching authorisation) produces none;
* overdraft fees and interest capitalisation produce entries with no
  originating event at all.

Keeping the two types apart is what makes those cases expressible rather than
special-cased. Every event carries an id, the day it was booked, the day it is
value-dated to, and the account it concerns; the rest is type-specific.
"""

from __future__ import annotations

from dataclasses import dataclass

from ledger.money import Money


@dataclass(frozen=True, slots=True)
class Credit:
    """Money into the account.

    ``instalments`` splits the amount into that many equal postings by largest
    remainder, which is how E10's BHD 10.000 becomes 3.334 / 3.333 / 3.333.
    """

    event_id: str
    booking_day: int
    value_date: int
    account_id: str
    amount: Money
    instalments: int = 1


@dataclass(frozen=True, slots=True)
class Debit:
    """Money out of the account."""

    event_id: str
    booking_day: int
    value_date: int
    account_id: str
    amount: Money


@dataclass(frozen=True, slots=True)
class Authorization:
    """A request to place a hold. Never a ledger entry: holds do not move money."""

    event_id: str
    booking_day: int
    value_date: int
    account_id: str
    auth_ref: str
    amount: Money


@dataclass(frozen=True, slots=True)
class Settlement:
    """A merchant claiming against a prior authorisation.

    May be for less than the authorised amount, which is ordinary card
    behaviour, or reference an authorisation that does not exist, which is not.
    """

    event_id: str
    booking_day: int
    value_date: int
    account_id: str
    auth_ref: str
    amount: Money


@dataclass(frozen=True, slots=True)
class Reversal:
    """Undo the ledger effect of an earlier event.

    Carries no amount. What gets reversed is whatever the referenced event
    actually posted, read back from the journal at reversal time -- so a
    reversal of a multi-entry event reverses every entry, and a reversal cannot
    disagree with the thing it reverses.

    The value date is the *original's* value date, not the day the reversal is
    booked, or the correction would only apply from the booking day forward
    (AMBIGUITIES item 15).
    """

    event_id: str
    booking_day: int
    value_date: int
    account_id: str
    reverses_event_id: str


Event = Credit | Debit | Authorization | Settlement | Reversal
