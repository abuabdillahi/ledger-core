"""A test that fails on purpose, because the question it asks is unresolved.

Subject: what happens to overdraft fees when the debit that caused them is
reversed.

This implementation recomputes and reverses. The fee reconciler compares the
fees the journal currently warrants against the fees standing, and when E9
removes the reason for the three fees, it appends three compensating reversals.
ACC-001 closes Day 6 at 465.00 before interest.

The other policy is that a fee correctly assessed on the information available
at the time stands until a human explicitly waives it. On that reading E9
reverses the debit and nothing else: the three 25.00 fees remain, and ACC-001
closes Day 6 at 390.00 before interest.

Both are real bank behaviour, and both have a serious argument:

* Recompute-and-reverse says the customer should not pay for a transaction that
  did not, in the end, happen. The fees were a consequence of an entry that has
  been withdrawn, so the consequence should be withdrawn too.
* Assessed-is-assessed says the fee was a true statement about the account's
  state at the moment it was assessed, and a bank that silently un-charges fees
  loses the ability to say what it charged and why. Unwinding should be an
  explicit act with a named approver, not an emergent property of a
  recomputation.

The brief does not specify which applies. The choice moves the customer's
balance by 75.00 -- three fees at 25.00 -- which is a large enough number that
it should be a decision someone made rather than a decision that fell out of an
implementation. In production this belongs behind a configuration flag with an
audit trail recording which policy was in force when a given ledger was
computed, so that a balance can be reproduced years later under the rules that
actually applied at the time.

The test below asserts the policy this implementation did *not* adopt. It is
marked strict, so if the implementation ever changes to the alternative policy
this test starts passing and pytest reports it as an unexpected pass -- the
suite notices the change of behaviour either way, which is the point of keeping
the losing option in the test suite rather than only in a document.

See AMBIGUITIES item 4 and REJECTED criterion 6.
"""

import pytest

from ledger.entries import EntryType
from ledger.money import Money
from ledger.projections import balance
from ledger.replay import replay


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Implemented policy is recompute-and-reverse (AMBIGUITIES item 4). This "
        "test asserts the alternative -- a correctly assessed fee stands until "
        "explicitly waived -- which is equally defensible and gives a different "
        "customer balance by 75.00."
    ),
)
def test_fees_stand_after_the_reversal_that_removed_their_cause():
    result = replay(capitalise_interest=False)
    journal = result.journal

    # Under 'assessed is assessed', the three fees E7 caused survive E9 ...
    standing_fees = [e for e in journal if e.entry_type is EntryType.OVERDRAFT_FEE]
    reversals = [e for e in journal if e.entry_type is EntryType.FEE_REVERSAL]
    assert len(standing_fees) == 3
    assert reversals == []  # FAILS HERE: the reconciler appended three

    # ... so every day from Day 2 onwards carries the fees value-dated to it or
    # earlier, and Day 6 closes 75.00 below the recompute-and-reverse figure.
    assert [str(balance(journal, "ACC-001", day)) for day in range(1, 7)] == [
        "250.00 AED",
        "225.00 AED",  # 250.00 less the Day 2 fee
        "625.00 AED",
        "415.00 AED",  # less the Day 2 and Day 4 fees
        "390.00 AED",  # less all three
        "390.00 AED",
    ]
    assert balance(journal, "ACC-001", 6) == aed("390.00")

    # The 75.00 in question. Whichever policy is chosen, this figure is the one
    # a customer would ring up about, and the reason the choice cannot be left
    # implicit.
    assert balance(journal, "ACC-001", 6) == aed("465.00") - aed("75.00")
