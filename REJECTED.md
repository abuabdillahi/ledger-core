# Rejected acceptance criteria and pivots

The brief warns that some of the supplied acceptance criteria are incorrect. Each of the
eight was therefore evaluated **independently**, against the replayed event stream and a
hand calculation performed before any code existed — not against the other criteria, and
not against an assumption that a fixed number of them must be wrong.

That independence matters in both directions. Rejecting a correct criterion because its
neighbours are wrong is itself a failure mode, and one that is easy to fall into once you
have found the first genuine error. Four of the eight are rejected outright and are the
subject of this document; the other four (two accepted directly, one with a qualification,
one as a true statement about an unreachable case) are not detailed here.

| # | Criterion (in substance) | Verdict |
|---|--------------------------|---------|
| 2 | E7 causes exactly one overdraft fee, on Day 2 | **Rejected** |
| 6 | After E9, all balances *and fees* return to pre-E7 values | **Rejected** |
| 7 | The three BHD instalments are each BHD 3.334 | **Rejected** |
| 8 | Interest rounding remainder is discarded | **Rejected** |

---

## Criterion 2 — "E7 causes exactly one overdraft fee to be assessed, on Day 2"

**REJECTED.** E7 causes **three** fees, on Days 2, 4 and 5.

Back-valuing a 620.00 debit to Day 2 shifts *every* subsequent day's closing balance by
the same amount, because each day's closing balance is the sum of all entries with a value
date on or before that day — and once E7 is in that set for Day 2, it is in it for Days 3
through 6 as well. The effect does not stop at the value date; the value date is where it
*starts*.

Evaluated after E7 and before E9:

| Day | Closing balance (assessment basis) | Fee |
|-----|-----------------------------------|-----|
| 1 | 250.00 | no |
| 2 | −370.00 | **yes** |
| 3 | 5.00 | no |
| 4 | −180.00 | **yes** |
| 5 | −205.00 | **yes** |

Day 3 escapes, and the reason it escapes is itself instructive. The 400.00 credit lifts
Day 3 to 30.00 — but the Day 2 fee is value-dated to Day 2, so it too propagates forward
like any other back-valued entry, leaving Day 3 at 5.00. Positive, so no fee, but only by
five dirhams. (See AMBIGUITIES item 3: a fee larger than 30.00 would have pushed Day 3
negative and triggered a genuine second-order cascade.)

Asserting a single fee treats a back-valued entry as affecting only its value date. That is
precisely the misunderstanding E7 exists to expose, and it is the difference between a
ledger that recomputes from its journal and one that patches a stored balance field.

## Criterion 6 — "After E9, all balances and fees return to their pre-E7 values"

**REJECTED.** Balances do. Fees do not, automatically.

E9 reverses the *ledger effect* of E7 — a compensating +620.00 entry value-dated to Day 2,
which restores every day's closing balance to its pre-E7 figure. That half of the criterion
is correct.

The three overdraft fees are separate postings. They are not children of E7; they are
independent entries in an append-only journal, and nothing in an append-only journal
un-happens on its own. Absent an explicit policy, Day 2 would close at 225.00 rather than
the pre-E7 250.00, and the customer would be 75.00 down on a debit that was reversed.

This implementation adopts a **recompute-and-reverse** policy, so the fees *are* reversed —
but by three further appended compensating entries, produced by the same reconciler that
appended them, as a deliberate design decision. The criterion asserts that the unwinding
happens by itself. In an append-only ledger nothing happens by itself, and a criterion that
assumes otherwise is describing a mutable-balance system.

The alternative policy — that a fee correctly assessed on the information available at the
time stands until explicitly waived — is equally real bank behaviour and would leave the
three fees standing for a final balance of 390.00. See AMBIGUITIES item 4, and
`tests/test_known_failure.py`, which asserts that alternative and fails.

## Criterion 7 — "The three BHD instalments in E10 must each be BHD 3.334"

**REJECTED.** 3.334 × 3 = 10.002.

The instalments would overstate the credit by two fils. The postings would no longer sum to
the transaction they represent, and the fundamental double-entry invariant — that the parts
of a transaction net to the whole — would be broken by construction, on every replay,
forever.

The correct split by largest remainder is **3.334 / 3.333 / 3.333**, summing to exactly
10.000. The exact share is 3.3333… so every instalment floors to 3.333, leaving one fils of
shortfall to distribute; it goes to the first instalment.

All three weights tie at a fractional part of .333, so the tie-break rule is load-bearing
here. It is lowest-index-wins. The specific rule matters less than the property it must
have: determinism. A non-deterministic tie-break (iteration over an unordered set, a hash
seed, a random choice) would make replaying the log produce different balances than the
original run — silent corruption on recovery, of the kind that is discovered months later
during a reconciliation break. See AMBIGUITIES item 17.

## Criterion 8 — "If the rounded daily interest accruals do not sum to the capitalized total, the remainder is discarded"

**REJECTED**, on two independent grounds.

First, it directly contradicts the brief's own non-negotiable rule that "the rounded daily
accruals must sum exactly to the capitalised total". A criterion cannot discard a remainder
that the rules require to be zero.

Second — and this holds even if the brief had said nothing — a capitalisation credit that
does not equal the sum of its constituent accruals is an unbalanced posting. The daily
accruals are the audit trail for the credit. If they do not add up to it, the ledger cannot
answer "where did this figure come from", which is the one question a ledger exists to
answer.

The divergence is real on this data, not merely theoretical: ACC-001's exact accrual total
is 1.018, while the sum of the rounded daily accruals is 1.03. Something must be done about
the difference; discarding it is the one option that is not available. The resolution
adopted — define the capitalised total *as* the sum of the rounded dailies — is documented
in AMBIGUITIES item 6, along with the alternative allocation that was considered and why it
was not taken.

---

## Approaches abandoned mid-build

Recorded as they happened rather than reconstructed afterwards.

**No architectural approach was abandoned.** The first design — journal as sole state, every
other value a pure projection, fee assessment as a reconciler over desired-versus-actual —
held from the hand calculation through to the final commit without needing to be reworked.

That is worth explaining rather than merely claiming, because "the first design held" is
also what someone says when they did not look hard enough. The design held because the two
hard parts of this brief turn out to be the same problem. The back-value cascade and the fee
unwind both ask "what happens to things already computed when new information arrives about
a day that has closed", and *storing nothing* answers both at once: there is no computed
thing to update, so there is nothing to keep in step. Had balances been stored, E7 would
have needed forward-propagation code and E9 would have needed an unwind path, and the two
would have been separate mechanisms with separate bugs.

Three smaller things were tried and dropped:

- **A structural test asserting the reconciler had exactly one code path**, by inspecting
  its source for two `journal.append` calls. It passed, and it would have broken on any
  harmless refactor while proving nothing a behavioural test does not. Deleted in the same
  commit that introduced it. The claim is now made by the behavioural tests: the same call
  appends fees in one situation and reversals in another.
- **The `journal` parameter on the day-advance hook**, which the brief's sketch shows.
  Everything that hook does — releasing holds whose authorisation has expired — moves no
  money and appends no ledger entry, so the parameter would have been present only in case
  it was needed later, which is a claim the code does not support. Dropped, with a docstring
  note that the signature should change deliberately if that ever stops being true.
- **Two weak assertions**, one in the back-value test and one in the scenario test, that
  were passing while asserting almost nothing. Both were replaced with the claim they were
  meant to make. Recorded because a test that passes for the wrong reason is worse than no
  test, and finding two of them in one's own work is the normal case rather than a
  confession.
