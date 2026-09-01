# Rejected and accepted acceptance criteria

The brief warns that some of the supplied acceptance criteria are incorrect. Each of the
eight was therefore evaluated **independently**, against the replayed event stream and a
hand calculation performed before any code existed — not against the other criteria, and
not against an assumption that a fixed number of them must be wrong.

That independence matters in both directions. Rejecting a correct criterion because its
neighbours are wrong is itself a failure mode, and one that is easy to fall into once you
have found the first genuine error. Four criteria are accepted, one is accepted with a
qualification, one is accepted as a true statement about an unreachable case, and two are
rejected outright.

| # | Criterion (in substance) | Verdict |
|---|--------------------------|---------|
| 1 | Day 2 closes at AED −370.00 at end of Day 5, pre-fee | **Accepted** |
| 2 | E7 causes exactly one overdraft fee, on Day 2 | **Rejected** |
| 3 | The Day 4 settlement is accepted | **Accepted** |
| 4 | A settlement with no matching authorisation is rejected, funds do not move | **Accepted, with qualification** |
| 5 | If Auth-B is approved it reduces available but not ledger balance | **Accepted as stated; premise unreachable** |
| 6 | After E9, all balances *and fees* return to pre-E7 values | **Rejected** |
| 7 | The three BHD instalments are each BHD 3.334 | **Rejected** |
| 8 | Interest rounding remainder is discarded | **Rejected** |

---

## Criterion 1 — "The Day 2 closing ledger balance, evaluated at end of Day 5 and before any fee is assessed, is AED −370.00"

**ACCEPTED. Correct.**

At end of Day 5 the entries carrying a value date on or before Day 2 are E1 (+1,200.00),
E2 (−950.00) and E7 (−620.00). Their sum is −370.00.

The point of interest is E7. It is *booked* on Day 5 but *value-dated* to Day 2, so it
enters the Day 2 closing balance even though Day 2 had already closed by the time the
entry arrived. A value-basis balance is a sum over a set defined by value date, and E7
joins that set retroactively. The criterion states this correctly.

This is recorded explicitly rather than passed over in silence, because the criterion is
adjacent to two that are wrong and it would be easy to reject it by association.

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
five dirhams. (See AMBIGUITIES items 3 and 12: a fee larger than 30.00 would have pushed
Day 3 negative and triggered a genuine second-order cascade.)

Asserting a single fee treats a back-valued entry as affecting only its value date. That is
precisely the misunderstanding E7 exists to expose, and it is the difference between a
ledger that recomputes from its journal and one that patches a stored balance field.

## Criterion 3 — "The Day 4 settlement is accepted"

**ACCEPTED. Correct.**

Auth-A held 200.00 and settles for 185.00. Settlement below the authorised amount is
entirely ordinary card behaviour — a fuel pump pre-authorises a round figure, a restaurant
authorises with a tip margin, a merchant ships part of an order. There is no reason to
reject it.

The design question this event actually poses is not *whether* to accept, but what happens
to the 15.00 residual. This implementation releases it immediately on settlement, so the
customer's available balance is restored the moment the merchant's intent is known. See
AMBIGUITIES item 9 for the alternative (hold to expiry) and why it was not chosen.

## Criterion 4 — "Any settlement referencing an authorisation ID not present in the ledger must be rejected and the funds must not leave the account"

**ACCEPTED, with two qualifications recorded honestly.**

Correct for this system as scoped. With no scheme integration and no external reference
data, debiting a customer against an authorisation we have no record of is indefensible —
we cannot distinguish a legitimate late presentment from a malformed or fraudulent message.
E6 is rejected and no funds move.

**Qualification 1: in a real card-issuing system this rule is wrong.** Forced posts and late
presentments arrive without a matching authorisation routinely — offline-authorised
transactions, terminals that captured after the hold expired, scheme-mandated fallbacks.
Scheme rules generally oblige the issuer to honour them, with chargeback as the recourse
rather than refusal at the door. An issuer that hard-rejects every unmatched settlement
does not have a safe system; it has a system that fails its scheme obligations. The correct
production behaviour is to post the transaction and raise an exception case, not to drop it.

**Qualification 2: "rejected" cannot mean "discarded" in an append-only ledger.** A decision
not to post is still a decision, and it is the decision an auditor is most likely to ask
about. E6's rejection is written to a durable decision record that shares the journal's
sequence space, so its position relative to surrounding postings is unambiguous.

## Criterion 5 — "If Auth-B is approved, it reduces available balance but not ledger balance"

**ACCEPTED as stated — but the premise is unreachable.**

The consequent is definitionally true in this model: holds are not ledger entries at all,
so they cannot touch the ledger balance, and available balance is defined as ledger balance
minus active holds. If Auth-B were approved, the criterion would describe exactly what
happens.

Auth-B is never approved. At the point E8 is processed, ACC-001's ledger balance on Day 5 is
−155.00 before fees and −230.00 after the three fees E7 triggered. Available balance equals
the ledger balance (Auth-A's residual having been released on Day 4), so applying a 90.00
hold cannot leave it at or above zero under either figure. Under the stated approval rule,
Auth-B is **declined**.

The criterion is therefore true of a case that does not arise. It is recorded here rather
than rejected, because the statement itself is sound — the fault is in its applicability,
not its content. Note also that the outcome is robust to the fee-timing ambiguity: −155.00
and −230.00 both decline a 90.00 hold, so nothing about this conclusion depends on
resolving AMBIGUITIES item 1.

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
during a reconciliation break. See AMBIGUITIES item 18.

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

Recorded here as they happened, not reconstructed afterwards.

*(This section is appended to during implementation. If it ends up empty, that is stated
plainly along with the reason, rather than being padded.)*
