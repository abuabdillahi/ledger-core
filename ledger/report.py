"""Rendering: what happened, per day and per account.

Everything printed here is read back out of the journal, the auth log and the
decision log. The reporter computes nothing that the ledger does not already
know how to answer.

Two reporting choices are deliberate. Day 6's closing balance is shown both
before and after the interest capitalisation credit, separately, so neither
question has to be inferred (AMBIGUITIES item 13). And where the value and
posting bases disagree, both are shown, because "what the balance was" and
"what we believed at the time" are different questions with different right
answers.
"""

from __future__ import annotations

from fractions import Fraction

from ledger.entries import Entry, EntryType
from ledger.interest import Capitalisation
from ledger.journal import DecisionRecord
from ledger.money import Money
from ledger.projections import Basis, balance
from ledger.replay import ReplayResult, replay

RULE = "=" * 78
THIN = "-" * 78


def exact_decimal(value: Fraction) -> str:
    """Exact decimal text for a rational. No float, at any point."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    denominator = magnitude.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:  # not a terminating decimal; show the fraction
        return f"{sign}{magnitude.numerator}/{magnitude.denominator}"
    places = max(twos, fives)
    scaled = magnitude * 10**places
    digits = f"{int(scaled):0{places + 1}d}"
    if places == 0:
        return f"{sign}{digits}"
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def _entry_line(entry: Entry) -> str:
    return (
        f"      seq {entry.sequence:>3}  {entry.entry_type:<24} "
        f"{entry.direction:<7} {str(entry.amount):>14}   "
        f"value Day {entry.value_date}   {entry.origin_ref}"
    )


def _decision_line(record: DecisionRecord) -> str:
    return f"      seq {record.sequence:>3}  {record.decision}: {record.reason}"


def render_days(result: ReplayResult) -> list[str]:
    lines = [RULE, "DAY BY DAY", RULE]
    for day in result.days:
        lines.append("")
        lines.append(f"Day {day}")
        lines.append(THIN)
        for account_id in result.accounts:
            value_basis = balance(result.journal, account_id, day, Basis.VALUE)
            posting_basis = balance(result.journal, account_id, day, Basis.POSTING)
            line = f"  {account_id}  closing {str(value_basis):>14}"
            if posting_basis != value_basis:
                line += f"   (posting basis {posting_basis}, as believed on the day)"
            lines.append(line)

            booked = [
                entry
                for entry in result.journal
                if entry.account_id == account_id and entry.booking_day == day
            ]
            if booked:
                lines.append("    booked today:")
                lines.extend(_entry_line(entry) for entry in booked)

            fees = [
                entry
                for entry in result.journal
                if entry.account_id == account_id
                and entry.value_date == day
                and entry.entry_type
                in (EntryType.OVERDRAFT_FEE, EntryType.FEE_REVERSAL)
            ]
            if fees:
                lines.append("    fees value-dated to this day:")
                lines.extend(_entry_line(entry) for entry in fees)

        transitions = [t for t in result.auth_log if t.day == day]
        if transitions:
            lines.append("    authorisations:")
            lines.extend(f"      {transition}" for transition in transitions)

        decisions = [d for d in result.journal.decisions if d.booking_day == day]
        if decisions:
            lines.append("    decisions recorded:")
            lines.extend(_decision_line(record) for record in decisions)
    return lines


def render_interest(result: ReplayResult) -> list[str]:
    lines = ["", RULE, "INTEREST", RULE]
    for capitalisation in result.capitalisations:
        lines.append("")
        lines.append(f"  {capitalisation.account_id}")
        lines.append(
            f"      {'Day':<5}{'Basis':>16}{'Exact accrual':>18}{'Rounded':>16}"
        )
        for accrual in capitalisation.accruals:
            lines.append(
                f"      {accrual.day:<5}{str(accrual.basis):>16}"
                f"{exact_decimal(accrual.exact):>18}{str(accrual.rounded):>16}"
            )
        lines.append(
            f"      exact total {exact_decimal(capitalisation.exact_total):>10}"
            f"    capitalised {str(capitalisation.total):>14}"
        )
        if capitalisation.exact_total != capitalisation.total.as_major():
            lines.append(
                "      (the two differ; the capitalised total is the sum of the "
                "rounded dailies -- AMBIGUITIES item 6)"
            )
    return lines


def render_closing(result: ReplayResult) -> list[str]:
    lines = ["", RULE, "CLOSING POSITION", RULE, ""]
    last_day = result.days[-1]
    by_account = {c.account_id: c for c in result.capitalisations}
    for account_id in result.accounts:
        capitalisation = by_account.get(account_id)
        credit = (
            capitalisation.total
            if capitalisation is not None
            else Money.zero(balance(result.journal, account_id, last_day).currency)
        )
        final = balance(result.journal, account_id, last_day)
        lines.append(f"  {account_id}")
        lines.append(
            f"      Day {last_day} closing, before capitalisation "
            f"{str(final - credit):>14}"
        )
        lines.append(f"      interest capitalised                {str(credit):>14}")
        lines.append(f"      Day {last_day} closing, after capitalisation  {str(final):>14}")
    return lines


def render_authorisations(result: ReplayResult) -> list[str]:
    lines = ["", RULE, "AUTHORISATIONS", RULE, ""]
    for auth_ref in result.auth_log.references():
        history = result.auth_log.history(auth_ref)
        lines.append(f"  {auth_ref}: {history[-1].state}")
        lines.extend(f"      {transition}" for transition in history)
    return lines


def render_errors(result: ReplayResult) -> list[str]:
    lines = ["", RULE, "ERRORS AND REJECTIONS", RULE, ""]
    if not result.journal.decisions:
        lines.append("  none")
        return lines
    for record in result.journal.decisions:
        lines.append(f"  {record.event_id} (Day {record.booking_day}): {record.reason}")
    lines.append("")
    lines.append(
        "  Recorded, not discarded: in an append-only ledger a decision not to "
        "post is still a decision."
    )
    return lines


def render(result: ReplayResult) -> str:
    lines = [
        RULE,
        f"LEDGER REPLAY  --  Day {result.days[0]} to Day {result.days[-1]}",
        RULE,
        "",
    ]
    lines += render_days(result)
    lines += render_interest(result)
    lines += render_closing(result)
    lines += render_authorisations(result)
    lines += render_errors(result)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(replay()))
