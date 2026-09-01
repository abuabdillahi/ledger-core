"""Ledger entries: immutable postings, the only thing the journal holds.

An entry is created once and never changed. Corrections are further entries,
never edits -- there is no code path in this package that mutates or removes
one, which is what "append-only" has to mean if it is to mean anything.

The six entry types are kept distinct rather than collapsed into
credit-or-debit because the fee and interest logic must treat OVERDRAFT_FEE,
FEE_REVERSAL and INTEREST_CAPITALISATION differently from ordinary postings.
Every dispatch over this enum is an exhaustive ``match`` ending in
``assert_never``, so a seventh type would be a type-check error at every site
that fails to handle it rather than a wrong balance at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from ledger.money import Money


class Direction(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class EntryType(StrEnum):
    #: An ordinary credit or debit originating from an inbound event.
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    #: Assessed by the fee reconciler; no originating event.
    OVERDRAFT_FEE = "OVERDRAFT_FEE"
    #: Appended by the fee reconciler when a fee is no longer warranted.
    FEE_REVERSAL = "FEE_REVERSAL"
    #: Compensating entry for an earlier event (E9 reversing E7).
    REVERSAL = "REVERSAL"
    #: The single end-of-window interest credit; no originating event.
    INTEREST_CAPITALISATION = "INTEREST_CAPITALISATION"


@dataclass(frozen=True, slots=True)
class Entry:
    """One posting.

    ``booking_day`` is when it happened; ``value_date`` is the day it counts
    towards. They differ for every interesting entry in this brief, and the two
    balance bases in ``projections`` exist because they differ.

    ``origin_ref`` names what caused the entry: an event id for postings that
    have one, or a description of the mechanism for those that do not.
    """

    sequence: int
    booking_day: int
    value_date: int
    account_id: str
    direction: Direction
    amount: Money
    entry_type: EntryType
    origin_ref: str

    @property
    def signed_minor_units(self) -> int:
        """The entry's effect on a balance, positive for credits."""
        match self.direction:
            case Direction.CREDIT:
                return self.amount.minor_units
            case Direction.DEBIT:
                return -self.amount.minor_units
            case _:
                assert_never(self.direction)

    def opposite_direction(self) -> Direction:
        match self.direction:
            case Direction.CREDIT:
                return Direction.DEBIT
            case Direction.DEBIT:
                return Direction.CREDIT
            case _:
                assert_never(self.direction)
