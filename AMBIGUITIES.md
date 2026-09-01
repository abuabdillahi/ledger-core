# Ambiguities

Every item below is a question the brief does not settle, or settles only by implication.
Each records the ambiguity, the options available, the choice made, and what would be different had the other option been taken.

---

## 1. Does a back-valued entry trigger retroactive fee assessment for days already closed?

**Options.** (a) Retroactive: recompute every day in the window whose closing balance the
back-valued entry changed, and assess fees on any that now close negative. (b) Forward-only:
the entry affects balances retroactively for reporting, but fees are assessed only from the
booking day onward, because Day 2 is closed and a closed day is not reopened.

**Chosen: retroactive.** The brief's own framing of acceptance criterion 1 — "the Day 2
closing balance, evaluated at end of Day 5, before any fee is assessed" — presupposes that
a fee is about to be assessed against a restated Day 2, which only makes sense
retroactively.

**Consequence of the alternative.** E7 would produce one fee, not three. Only Day 5, the
booking day, closes negative at the time of booking, so a forward-only policy assesses
25.00 rather than 75.00. Real banks do both; forward-only is common precisely because
reopening closed days disturbs already-issued statements. This is a defensible policy that
would change the customer's balance by 50.00.

## 2. Does a day's own overdraft fee count towards its own assessment basis?

**Options.** (a) Exclude the day's own fee from the basis on which that day is assessed.
(b) Include it, so the basis is the true closing balance including everything value-dated to
that day.

**Chosen: exclude.** Prior days' fees count — they are history, and they propagate forward
like any other entry. The same day's fee does not, because it would be self-referential:
the fee is the output of the assessment, so it cannot also be an input to it.

**Consequence of the alternative.** Including it introduces a self-edge in the dependency
graph. Day D's fee depends on Day D's fee, so a single pass no longer suffices and the
reconciler needs iteration to a fixed point — with all the questions that follow about
whether it converges, and what to do if it does not. Worse, it permits a fee to justify its
own existence: an account closing at +10.00 would be pushed to −15.00 by a fee that is only
warranted because it was charged. Excluding it makes the dependency graph acyclic by day
(day D depends only on non-fee entries and on fees from days strictly earlier than D), so a
single ascending pass over Days 1–6 is provably sufficient.

## 3. Does a fee, being itself value-dated, cascade into further fees?

**Options.** (a) A fee is an ordinary entry and propagates forward like any other, so it can
push a *later* day negative and trigger a further fee. (b) Fees are excluded from all
assessment bases, so they never beget fees.

**Chosen: (a), ordinary entry.** It follows directly from item 2 — prior days' fees are
history — and terminates by construction, because a day's fee can only be caused by fees
from strictly earlier days.

**This is live on the data, and nearly bites.** Day 3 closes at 5.00 — that is 30.00 less
the Day 2 fee. A fee of 30.00 or more would have taken Day 3 to zero or below and triggered
a genuine second-order cascade. The specified 25.00 sits five dirhams from changing system
behaviour. The implementation handles the cascade correctly whether or not the given data
exercises it; the fact that it does not exercise it is a property of the numbers, not
evidence that the code is right, which is why it is written down here.

## 4. Does the Day 6 reversal trigger fee recomputation?

**Options.** (a) Recompute and reverse: fees are a pure function of the current journal, so
when the journal changes such that a fee is no longer warranted, a compensating reversal is
appended. (b) Assessed is assessed: each fee was correct on the information available when
it was assessed, and stands until a human explicitly waives it.

**Chosen: recompute and reverse.**

**Consequence of the alternative.** Three 25.00 fees stand, and ACC-001's Day 6 closing
balance is 390.00 rather than 465.00 — a 75.00 difference to the customer. Both are real
bank behaviour. (b) has a strong argument behind it: the fee was a true statement about the
account's state at the time, and a bank that silently un-charges fees loses the ability to
say what it charged and why. In production this belongs behind a configuration flag with an
audit trail, not a hardcoded behaviour. `tests/test_known_failure.py` asserts (b) and fails,
deliberately, to keep the unresolved question visible in the test suite rather than buried
in a document.

## 5. Which balance basis does interest use?

**Options.** (a) Final value-dated closing balances, computed after all ten events have been
replayed. (b) The balance as it stood when each day actually closed, accruing against
history as it was believed at the time.

**Chosen: (a), final value-dated closing balances.**

**Consequence of the alternative.** Interest would accrue against the transient negative
balances that existed between E7 and E9 — that is, against a debit that was subsequently
reversed. Days 2, 4 and 5 would attract no accrual at all (negative balances do not accrue),
and Day 3 would accrue on 5.00 rather than 650.00. The customer would be permanently worse
off because of an error that was corrected. Choosing (a) means the corrected history is the
history.

## 6. How is the interest rounding remainder resolved?

The exact accrual total for ACC-001 is 1.018. The sum of the six rounded daily accruals is
1.03. Both cannot be the capitalised total.

**Options.** (a) Define the capitalised total as the sum of the rounded dailies: 1.03.
(b) Round the exact total to 1.02, then allocate that back across the six days by largest
remainder, giving 0.10 / 0.10 / 0.26 / 0.19 / 0.19 / **0.18**.

**Chosen: (a).** It satisfies the brief's rule — that the rounded dailies sum exactly to the
capitalised total — *by construction*, with no allocation step that could itself go wrong.
Each day's posted accrual is exactly the rounding of that day's own exact accrual, which is
the property a customer or an auditor would expect when reading a daily accrual schedule.

**Consequence of the alternative.** (b) is one fils closer to the exact figure and is the
more defensible answer to "what is the true total interest". Its cost is that Day 6's posted
accrual of 0.18 is not the rounding of Day 6's exact accrual of 0.186 — an unexplainable
line in the schedule, differing from the identical Days 4 and 5 for no reason visible in the
data. The chosen policy trades one fils of accuracy for an explainable schedule. Note that
under (b) three days tie at a fractional remainder of .639, so the tie-break rule (item 17)
determines which two of Days 4, 5 and 6 round up.

## 7. Booking chronology conflicts with stream order

E9 is booked on Day 6 and E10 on Day 5, but the stream lists E9 first.

**Options.** (a) Replay in stream order as given. (b) Sort the stream by booking day first,
on the grounds that a ledger processes events as they occur.

**Chosen: (a), stream order governs.** The brief says the events are "replayed in this
order", and that is the closest thing to an explicit instruction available. Booking day is
retained as data on every event and entry, so the posting-basis timeline is fully
recoverable.

**Consequence of the alternative.** Sorting would change nothing about the final balances —
E9 and E10 touch different accounts and neither is order-dependent on the other — but it
would change the internal clock's path, and it would mean the system silently reorders its
input, which is exactly the behaviour that makes an audit trail unreliable. The concrete
implementation of this choice is in `replay.py`: the day clock advances only forwards, so
when E10 (booked Day 5) arrives after E9 (booked Day 6), the clock is already at 6 and
simply does not move. It never runs backwards.

## 8. Are authorisation decisions revisited when history is back-valued?

Auth-A was approved on Day 2 against an available balance of 250.00. E7 later restates Day 2
to −370.00. Was the approval wrong?

**Options.** (a) No: authorisation decisions are made on the information available at the
time and are never retroactively invalidated. (b) Yes: re-evaluate approvals whenever the
balances they were based on change.

**Chosen: (a).**

**Consequence of the alternative.** A settled authorisation could become retroactively
unauthorised — money has already moved to the merchant, the goods have been handed over, and
the ledger would be asserting the transaction should never have been approved. There is no
sane real-world behaviour on the other side of that: the bank cannot un-approve a completed
purchase. The decision is a historical fact; the balance it was based on is a restatement.
Both are true, and the ledger records both.

## 9. What releases Auth-A's 15.00 residual?

**Options.** (a) Release immediately on partial settlement. (b) Hold the residual until the
authorisation expires, in case a further (incremental) settlement arrives against the same
authorisation.

**Chosen: (a), immediate release.**

**Consequence of the alternative.** (b) protects against incremental settlement — a hotel or
car rental adding charges against one authorisation is the standard case — but it suppresses
the customer's available balance by 15.00 for up to the full expiry window, for money the
merchant has already signalled it does not want. The choice is a trade between customer
experience and protection against a scenario that does not arise in this event stream. In
production this is normally driven by the merchant category code rather than being a single
global rule.

## 10. What happens to Auth-B, never settled inside the window?

**Chosen:** the question is moot on this data — Auth-B is declined at request time, so no
hold is ever created and there is nothing to expire. The model nonetheless defines the
expiry path for an approved-but-unsettled authorisation, because omitting it would leave a
hold suppressing available balance indefinitely with no code path able to release it. Expiry
is evaluated by the day-advance hook rather than by any inbound event; see NUMBERS.md for
the expiry window constant.

## 11. The overdraft fee is denominated in AED, but ACC-002 is BHD

Does not arise on this data — ACC-002 never closes negative — but the design must define the
behaviour rather than crash or silently post an AED amount into a BHD account.

**Options.** (a) A published fee tariff per currency: a fixed, round figure in each
currency, set by the bank, not derived at posting time. (b) FX conversion of the AED fee at
a rate obtained when the fee is posted.

**Chosen: (a), a published tariff of BHD 2.500**, at a fixed 1.00 AED : 0.100 BHD.

Both currencies are pegged to the US dollar — AED at 3.6725 and BHD at 0.376 — so the cross
rate is stable by construction rather than by market, and a fixed rate is defensible without
a rate source at all. The peg-derived cross rate is 0.376 / 3.6725 = 0.10238 BHD per AED,
which would give a fee of BHD 2.560. The chosen 2.500 diverges from that by 2.3%. That
divergence is recorded here deliberately, so the approximation is visible rather than
implied by a suspiciously round number.

The justification for a round figure is not arithmetic convenience. Banks publish fee
schedules per currency and do not convert a fee at posting time; a customer is told "the
overdraft fee is BHD 2.500", not "the overdraft fee is 25 dirhams converted at whatever rate
applied on the day". A round tariff is both operationally normal and stable against peg
revisions.

**Consequence of the alternative.** Live FX conversion requires a rate source, a rate
timestamp, and a policy for which day's rate applies to a *back-valued* fee — the rate on the
value date, or on the booking day? Nothing in this scope can answer that, and inventing an
answer would be worse than declining the approach.

## 12. Does the interest capitalisation credit itself accrue, or trigger fee reassessment?

**Chosen: no to both.** It is posted after the final accrual has been computed, so it is not
in any day's accrual basis; and being a credit, it cannot make a balance negative, so it
cannot warrant a fee.

**Consequence of the alternative.** Accruing on the capitalisation credit would mean interest
on interest posted the same day — daily compounding applied to a figure that did not exist
during the day it would compound over. Running fee reassessment afterwards is harmless but
pointless work, and pointless work in a ledger is a future bug: someone eventually changes
the capitalisation entry to a debit-capable type and the harmless pass starts assessing
fees.

## 13. Is the reported Day 6 closing balance before or after capitalisation?

**Chosen: report both**, separately — the pre-capitalisation closing balance and the
capitalisation credit as its own line, with the post-capitalisation figure derivable from
them.

**Consequence of the alternative.** Reporting a single number forces a choice between a Day 6
balance that does not include a credit value-dated to Day 6 (confusing) and one that folds
in a credit whose derivation is invisible (unauditable). Reporting both costs one line and
answers both questions.

## 14. What value date does a fee reversal carry?

**Options.** (a) The value date of the original fee it reverses. (b) The day the reversal is
booked.

**Chosen: (a).** A compensating entry only nets to zero on *every* day's balance if it shares
the original's value date.

**Consequence of the alternative.** Booking a Day 6 reversal of a Day 2 fee with value date
Day 6 would leave Days 2 through 5 permanently 25.00 lower while correcting only Day 6 — a
ledger that is right on the last day and wrong on every day before it. That is precisely the
retroactive-effect bug that E7 exists to test, reintroduced through the back door. The brief
independently confirms the principle by specifying that E9's reversal of E7 carries value
date Day 2 rather than Day 6. Booking day still records when the reversal actually happened,
so the posting-basis timeline remains intact and an auditor can see that the correction was
made on Day 6.

## 15. Where is the rounding point?

**Options.** (a) Carry exact rational arithmetic throughout and round exactly once, at the
moment a ledger entry is created. (b) Round at each intermediate step.

**Chosen: (a), via `fractions.Fraction`.**

**Consequence of the alternative, concretely.** The daily rate is exactly `Fraction(4,
10000)`, so 465.00 × rate is exactly 0.186. Round that to 0.19 and carry 0.19 forward into
any further computation and a 0.004 error is baked in, then compounds across six days. This
is a binary choice — round once or round often — rather than a tunable magnitude, which is
why it lives here and not in NUMBERS.md.

## 16. Which rounding mode?

**Chosen: half-even (banker's rounding).** It avoids the upward bias that half-up accumulates
over many operations, which is the conventional choice in financial systems.

**Honest note: this choice does not bind on this dataset.** No intermediate value lands on a
half boundary. The only recurring fraction is 0.186, which rounds to 0.19 under either mode,
and 10.000 × 0.0004 = 0.004 is exact at three decimal places. Half-up would produce
byte-identical output. It is documented because the choice is real and had to be made
explicitly — `round_to_precision` takes a named mode rather than defaulting silently — not
because it changes anything here.

## 17. How are ties broken in largest-remainder allocation?

**Chosen: lowest index wins.**

Ties occur twice in this data: all three BHD instalments tie at a fractional part of .333,
and under the alternative interest policy (item 6) three days tie at .639.

**Consequence of the alternative.** Highest-index-wins and round-robin-with-a-persisted-cursor
are equally valid — the cursor variant is fairer across many allocations, since it stops the
first element receiving every rounding benefit forever, at the cost of carrying state that
must itself be persisted and replayed. What matters is not which rule but that the rule is
*deterministic*. A non-deterministic tie-break — iterating an unordered set, a
hash-seed-dependent sort — would make replaying the log produce different balances than the
original run.

## 18. Is fee assessment triggered by events or by the passage of time?

*Surfaced during implementation, while writing the truncated replay that makes the
post-E7 intermediate state testable. Added in the commit that encountered it.*

**Options.** (a) Event-triggered: run the fee reconciler after every event that appends
financial entries. (b) Time-triggered: run it in the day-advance hook, as end-of-day batch
processing.

**Chosen: (a), event-triggered**, which is what the brief's architecture specifies. The
day-advance hook is reserved for authorisation expiry, which appends no ledger entry.

**Consequence, and the artefact it leaves.** Under (a) a day that closes negative is only
assessed when some later event prompts a reconciliation. On the full ten-event stream this
is invisible — E10 is the last financial event and triggers a reconciliation covering the
whole window — but it is plainly visible on a truncated replay: stopping after E7 leaves
Day 6 closing at −230.00 with no fee assessed, because nothing after E7 ever runs the
reconciler over it. `tests/test_scenario.py` asserts this rather than hiding it.

Option (b) would assess that day, and is what a real core banking system does: overdraft fee
assessment is archetypal end-of-day batch work, triggered by the clock and by nothing else.
The two options agree on this event stream and disagree on any stream whose final days are
quiet. The reconciler itself is basis-driven and would need no change to move; only its call
site would.
