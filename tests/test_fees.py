"""The fee reconciler: assessment, the cascade, and reversal by appending."""

from ledger.entries import Direction, EntryType
from ledger.fees import OVERDRAFT_FEE_TARIFF, assessment_basis, reconcile, standing_fee
from ledger.journal import Journal
from ledger.money import Money
from ledger.projections import balance


def aed(literal: str) -> Money:
    return Money.from_major(literal, "AED")


def post(journal, day, direction, amount, *, value_date=None, account="ACC-001",
         entry_type=None, origin="test"):
    currency = "AED" if account == "ACC-001" else "BHD"
    return journal.append(
        booking_day=day,
        value_date=day if value_date is None else value_date,
        account_id=account,
        direction=direction,
        amount=Money.from_major(amount, currency),
        entry_type=entry_type
        or (EntryType.CREDIT if direction is Direction.CREDIT else EntryType.DEBIT),
        origin_ref=origin,
    )


def acc_001_before_e7() -> Journal:
    journal = Journal()
    post(journal, 1, Direction.CREDIT, "1200.00", origin="E1")
    post(journal, 1, Direction.DEBIT, "950.00", origin="E2")
    post(journal, 3, Direction.CREDIT, "400.00", origin="E4")
    post(journal, 4, Direction.DEBIT, "185.00", origin="E5")
    return journal


def fee_days(journal) -> list[int]:
    return sorted(
        entry.value_date
        for entry in journal
        if entry.entry_type is EntryType.OVERDRAFT_FEE
    )


def reversal_days(journal) -> list[int]:
    return sorted(
        entry.value_date
        for entry in journal
        if entry.entry_type is EntryType.FEE_REVERSAL
    )


def test_no_fee_on_a_solvent_account():
    journal = acc_001_before_e7()
    assert reconcile(journal, "ACC-001", 6) == []


def test_zero_is_not_an_overdraft():
    journal = Journal()
    post(journal, 1, Direction.CREDIT, "100.00")
    post(journal, 1, Direction.DEBIT, "100.00")
    assert reconcile(journal, "ACC-001", 1) == []


def test_one_fils_below_zero_is():
    journal = Journal()
    post(journal, 1, Direction.CREDIT, "100.00")
    post(journal, 1, Direction.DEBIT, "100.01")
    assert len(reconcile(journal, "ACC-001", 1)) == 1


def test_e7_causes_three_fees_not_one():
    """REJECTED criterion 2, demonstrated."""
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")

    appended = reconcile(journal, "ACC-001", 5)

    assert fee_days(journal) == [2, 4, 5]
    assert len(appended) == 3
    assert all(entry.amount == aed("25.00") for entry in appended)


def test_day_three_escapes_by_five_dirhams():
    """30.00 less the Day 2 fee, which is value-dated to Day 2 and propagates."""
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    reconcile(journal, "ACC-001", 5)

    assert balance(journal, "ACC-001", 3) == aed("5.00")
    assert standing_fee(journal, "ACC-001", 3) is None


def test_assessment_bases_after_e7_match_the_hand_calculation():
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    reconcile(journal, "ACC-001", 5)

    assert [str(assessment_basis(journal, "ACC-001", d)) for d in range(1, 6)] == [
        "250.00 AED",
        "-370.00 AED",
        "5.00 AED",
        "-180.00 AED",
        "-205.00 AED",
    ]


def test_a_fee_is_booked_when_found_and_value_dated_to_the_day_assessed():
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    appended = reconcile(journal, "ACC-001", 5)

    day_two_fee = next(entry for entry in appended if entry.value_date == 2)
    assert day_two_fee.booking_day == 5  # discovered on Day 5
    assert day_two_fee.value_date == 2   # counts towards Day 2


def test_a_days_own_fee_does_not_justify_itself():
    """The self-reference AMBIGUITIES item 2 excludes."""
    journal = Journal()
    post(journal, 1, Direction.DEBIT, "10.00")
    reconcile(journal, "ACC-001", 1)

    assert fee_days(journal) == [1]
    assert balance(journal, "ACC-001", 1) == aed("-35.00")
    # Day 1 now closes 35.00 down, but a second run must not stack a second fee
    # on top of the first.
    assert reconcile(journal, "ACC-001", 1) == []


def test_a_prior_days_fee_can_cause_a_later_one():
    """The genuine second-order cascade of AMBIGUITIES item 3."""
    journal = Journal()
    post(journal, 1, Direction.CREDIT, "100.00")
    post(journal, 2, Direction.DEBIT, "110.00")   # Day 2 closes at -10.00
    post(journal, 3, Direction.CREDIT, "20.00")   # Day 3 would close at +10.00

    reconcile(journal, "ACC-001", 3)

    # ... but the Day 2 fee takes Day 3 to -15.00, so Day 3 is assessed too.
    assert fee_days(journal) == [2, 3]
    assert balance(journal, "ACC-001", 3) == aed("-40.00")


def test_reconciliation_is_idempotent():
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    reconcile(journal, "ACC-001", 5)
    entries_after_first_run = journal.entries

    assert reconcile(journal, "ACC-001", 5) == []
    assert journal.entries == entries_after_first_run


def test_reversal_produces_compensating_entries_not_deletions():
    """REJECTED criterion 6: fees do not un-happen, they are reversed."""
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    reconcile(journal, "ACC-001", 5)
    fees_posted = [e for e in journal if e.entry_type is EntryType.OVERDRAFT_FEE]

    # E9 reverses E7, value-dated to Day 2 like the original.
    post(journal, 6, Direction.CREDIT, "620.00", value_date=2,
         entry_type=EntryType.REVERSAL, origin="E7")
    appended = reconcile(journal, "ACC-001", 6)

    assert len(appended) == 3
    assert reversal_days(journal) == [2, 4, 5]
    # The original fees are still there, untouched. Nothing was deleted.
    assert [e for e in journal if e.entry_type is EntryType.OVERDRAFT_FEE] == fees_posted
    assert balance(journal, "ACC-001", 2) == aed("250.00")
    assert balance(journal, "ACC-001", 6) == aed("465.00")


def test_fee_reversals_carry_the_original_value_date():
    journal = acc_001_before_e7()
    post(journal, 5, Direction.DEBIT, "620.00", value_date=2, origin="E7")
    reconcile(journal, "ACC-001", 5)
    post(journal, 6, Direction.CREDIT, "620.00", value_date=2,
         entry_type=EntryType.REVERSAL, origin="E7")
    appended = reconcile(journal, "ACC-001", 6)

    for reversal in appended:
        assert reversal.booking_day == 6  # when the correction happened
    assert sorted(r.value_date for r in appended) == [2, 4, 5]  # what it corrects
    # Every day is restored, not just the last one.
    assert [str(balance(journal, "ACC-001", d)) for d in range(1, 7)] == [
        "250.00 AED", "250.00 AED", "650.00 AED",
        "465.00 AED", "465.00 AED", "465.00 AED",
    ]


def test_bhd_accounts_are_assessed_in_bhd():
    journal = Journal()
    post(journal, 1, Direction.DEBIT, "1.000", account="ACC-002")
    appended = reconcile(journal, "ACC-002", 1)

    assert len(appended) == 1
    assert appended[0].amount == OVERDRAFT_FEE_TARIFF["BHD"]
    assert str(appended[0].amount) == "2.500 BHD"
    assert balance(journal, "ACC-002", 1) == Money.from_major("-3.500", "BHD")


def test_acc_002_never_closes_negative_on_this_data():
    journal = Journal()
    for value in ("3.334", "3.333", "3.333"):
        post(journal, 5, Direction.CREDIT, value, account="ACC-002", origin="E10")
    assert reconcile(journal, "ACC-002", 6) == []
