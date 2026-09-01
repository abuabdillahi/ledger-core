# Worklog

Pre-implementation entries were performed before the repository
existed and the timestamps for these events may not be 100% accurate. In general, they 
represent the time that an activity was completed, not when it was started.
Every entry from the first commit onwards carries an actual clock time.

Times are as reported by the machine the work was done on (UTC+03).

Implementation was agent-assisted against a specification I wrote; the analysis,
architecture and all documented decisions are my own.

---

## Pre-implementation

**2026-08-28 21:49 +0300 — Background research.** Read up on Mal, the role, and the operating
environment: CBUAE as regulator, the mandatory application of AAOIFI Shari'ah standards for
Islamic financial institutions in the UAE, the Internal Shari'ah Supervision Committee
governance model, and AML record-keeping obligations — five-year retention, with the
specific requirement that retained records be sufficient to *reconstruct individual
transactions*. That last requirement is the one that shapes the architecture: it is an
argument for an append-only journal on regulatory grounds, independent of any engineering
preference.

**2026-08-28 22:13 +0300 — Core banking ledger fundamentals.** Double-entry invariants; money
representation in integer minor units and why floating point is disqualifying; concurrency
models for ledgers; idempotency and duplicate-event handling; write-ahead durability;
sequencing and total order; reversal semantics (compensating entry versus deletion).

**2026-08-29 19:55 +0300 — Domain concepts.** Chart of accounts and the sub-ledger / general-ledger
boundary; posting versus settlement; nostro reconciliation; value dating; and the
distinction between a core banking ledger and a payment orchestrator — the latter moves
money, the former is the book of record, and conflating them is a common architectural
error.

**2026-08-29 19:55 +0300 — Islamic finance primitives.** Murabaha, ijara, wakala, mudaraba and qard
hasan, and how each posts differently. Relevant here mainly through mudaraba: under a
profit-sharing deposit structure, value-dated balances directly determine each depositor's
share of the pool, so a value-date error is a Shari'ah compliance failure and not merely an
accounting one. Noted for the Part 2 document.

**2026-09-01 11:58 +0300 — Hand calculation.** Computed the full day-by-day balance table on paper
before writing any code, including the E7 back-value cascade and the three overdraft fees it
triggers. Doing this first is what made criterion 2 obviously wrong rather than arguably
wrong.

**2026-09-01 12:46 +0300 — Recomputation after an error.** Found an error in the initial treatment of
E6 (had provisionally posted the unmatched settlement before concluding it must be
rejected), recomputed the whole table independently, and arrived at the verified figures.
Recorded here rather than quietly corrected, because the first pass being wrong is the
normal case and the log should say so.

**2026-09-01 13:50 +0300 — Acceptance criteria.** Evaluated all eight individually against the hand
calculation, deliberately not against each other. Identified criteria 2, 6, 7 and 8 as
incorrect, criterion 5 as sound but unreachable, and criterion 4 as correct-as-scoped with
two production qualifications.

**2026-09-01 19:39 +0300 — Architecture.** Settled on: the journal is the only state; every other value
(balances, available balance, fee status, authorisation state) is a pure function of it; fee
assessment is a reconciler computing desired-versus-actual rather than an assessor with
separate assess and unwind paths. The back-value cascade then falls out for free — appending
E7 propagates nothing, and later queries simply return different answers because their input
set grew.

---

## Implementation

**2026-09-01 19:55 +0300 — Commit 1: documentation.** REJECTED.md, AMBIGUITIES.md and NUMBERS.md written in
full before any code exists, which is the honest sequence — the analysis genuinely preceded
the implementation and the history should say so. Repository initialised, Python 3.11.13
virtualenv created with pytest as the sole (development-only) dependency.

**2026-09-01 19:56 +0300 — Commit 2: money and the currency registry.** Money is an integer count of minor
units with the currency attached; `float` is refused at construction, at the major-unit
constructor and at the rounding entry point, so "no floating point" is enforced by the type
rather than by grep. Rounding lives in this module alone and takes an explicit named mode.
Added a half-up mode alongside half-even purely so that the AMBIGUITIES item 16 claim — that
the mode does not change the output on this dataset — is a passing test rather than a
sentence.

**2026-09-01 19:57 +0300 — Commit 3: largest-remainder allocator.** One implementation, two callers (the BHD
instalment split and the interest allocation). Confirmed by test that the alternative
interest allocation from AMBIGUITIES item 6 does produce 0.10 / 0.10 / 0.26 / 0.19 / 0.19 /
0.18, and that the three-way tie at .639 resolves to Days 4 and 5 under lowest-index-wins —
the alternative is documented from a computed result, not from an assumption.

**2026-09-01 19:58 +0300 — Commit 4: event and entry types.** Kept events and entries as separate types.
Decided that `Reversal` should carry no amount and instead reverse whatever its referenced
event actually posted, read back from the journal: a reversal then cannot disagree with the
thing it reverses, and multi-entry originals (E10-shaped) reverse correctly without special
handling.

**2026-09-01 19:58 +0300 — Commit 5: journal and decision log.** Settled the "where does a rejection live"
question: `auth.py` will own the decision *logic*, the journal owns the *record*, and both
logs draw on one sequence counter so a decision's position relative to surrounding postings
is unambiguous. Noted in the module docstring that production would normally split these
into an upstream event store and a downstream postings-only ledger.

**2026-09-01 19:59 +0300 — Commit 6: balance projections.** Both bases implemented. Kept `projections` free of
any dependency on `auth` by declaring the hold source as a structural `Protocol` — balances
are arithmetic over the journal and have no business knowing what an authorisation is. Added
one `exclude` predicate to `balance`, for the single caller that needs a basis excluding a
day's own fee.

**2026-09-01 20:00 +0300 — Commit 7: back-value cascade test, before fees exist.** Wrote the cascade proof
against the projections alone. First attempt at one assertion was an unreadable arithmetic
expression that also happened to be wrong; replaced it with a before/after comparison that
states the actual claim — every day from the value date onwards moves by the full 620.00,
Day 1 does not move at all. Also added a test that demonstrates the AMBIGUITIES item 14 bug
directly: a reversal value-dated to its booking day is right on Day 6 and wrong on every
day before it.

**2026-09-01 20:02 +0300 — Commit 8: hold register and authorisation lifecycle.** Auth state is folded from a
transition log rather than stored, so "what state is Auth-A in" always comes with its own
audit trail. `AuthorizationLog` satisfies the `HoldRegistry` protocol, so holds reach the
available-balance calculation without balances depending on the authorisation module.
Three states in the enum (PARTIALLY_SETTLED, RELEASED, VOIDED) have no producing code path
in this scope because no event represents incremental settlement, merchant release or void;
they are documented as modelled-but-unreachable rather than quietly dropped, and Part 2
covers what each would mean.

**2026-09-01 20:19 +0300 — Commit 9: fee reconciler.** Written as desired-versus-actual rather than as an
assessor with a separate unwind path, so E7's three fees and E9's three reversals come out
of the same loop. Wrote and then deleted a test that asserted this structurally by
inspecting the source for two `journal.append` calls — a cute test that would break on any
harmless refactor, and the behavioural tests (same call, fees in one situation, reversals in
the other) already make the point. Replaced the "one pass is enough" comment with a checked
assertion: after reconciling, a second read-only pass must find nothing to do, so the
acyclicity claim in AMBIGUITIES item 2 fails loudly if it ever stops holding.

**2026-09-01 20:20 +0300 — Commit 10: interest accrual and capitalisation.** Verified figures reproduce: ACC-001
accrues 0.10 / 0.10 / 0.26 / 0.19 / 0.19 / 0.19 for a capitalised 1.03 against an exact
1.018, and ACC-002 accrues 0.004 on Days 5 and 6 for 0.008 with no divergence at all.
Chose to keep zero-accrual days in the accrual list rather than filtering them, so the
report can show Days 1–4 of ACC-002 accruing nothing on a zero balance — an absent line and
a zero line are different statements.

**2026-09-01 20:22 +0300 — Commit 11: replay orchestrator and reporter.** Full stream replays to the verified
figures on the first run: 250 / 250 / 650 / 465 / 465 / 465 pre-capitalisation on ACC-001,
10.000 on ACC-002, capitalising 1.03 and 0.008. Dropped the `journal` argument from
`advance_to` that the brief's sketch shows: everything the day-advance hook does moves no
money, and a parameter that exists only in case it is needed later is a claim the code does
not support. Noted in its docstring that the signature should change deliberately if that
ever stops being true. The reporter surfaced something worth keeping — on Day 5 the value
basis reads 465.00 and the posting basis −230.00, so the report prints both and says which
is which.

**2026-09-01 20:24 +0300 — Commit 12: full scenario test.** Every figure in section 4 of the brief reproduces
without adjustment. Writing the truncated replay for the post-E7 intermediate state surfaced
a genuine new ambiguity: fee assessment here is event-triggered, so a day that closes
negative with no later event is never assessed — invisible on the full stream, visible the
moment you stop after E7 and look at Day 6. Added as AMBIGUITIES item 18 in this commit
rather than retrospectively, and asserted in the scenario test rather than hidden. Also
replaced a scenario assertion that was technically passing while asserting almost nothing
(`(day, after) != (day, before) or day == 1 or day == 3`) with the claim it was meant to
make.

**2026-09-01 20:24 +0300 — Commit 13: the annotated failing test.** Marked `xfail(strict=True)` rather than
plain xfail, so that if the implementation ever switches to the alternative policy the suite
reports an unexpected pass instead of quietly going green. Verified with `--runxfail` that
it fails on the intended assertion (three fee reversals exist where the alternative policy
expects none) rather than incidentally somewhere else.

**2026-09-01 20:27 +0300 — Commit 14: Part 2 architecture and trade-offs document.** Grounded the scale section
in the actual implementation rather than in generalities: the bottleneck is the fee
reconciler calling an O(n) balance projection once per day per account after every financial
event, which is quadratic in stream length, and it bites long before memory does. Wrote the
snapshot proposal with its value-date invalidation rule, since a snapshot that is stale and
does not know it turns an expensive correct answer into a fast wrong one.

**2026-09-01 20:28 +0300 — Commit 15: final documentation pass.** README given run instructions, an output
guide keyed to the five report sections, the Python 3.11 justification and the explicit
statement that pytest is a development dependency only and is imported by nothing under
`ledger/`. Filled in REJECTED.md's abandoned-approaches section: no architectural approach
was abandoned, and rather than leave that as a bare claim, wrote down *why* the first design
held — the back-value cascade and the fee unwind are the same problem, and storing nothing
answers both at once. Three smaller things were tried and dropped and are listed. Ran the
verification checklist: no `float` anywhere outside the guards that reject it, no
assignment to any entry field outside the two tests asserting that it raises, no delete or
mutate path in the package, BHD at three decimal places throughout.

**2026-09-01 20:29 +0300 — Commit 16: type-check pass.** Ran mypy over the package to check that the
exhaustive-dispatch claim in NUMBERS.md is actually true rather than merely intended. It
found one real problem: the `exclude` predicate in `fees.assessment_basis` was a lambda
with a default argument capturing the day, which mypy cannot infer against the declared
`Callable[[Entry], bool]`. Replaced with a named nested function, which reads better
anyway. Then tested the claim directly by temporarily adding a seventh `EntryType` member:
mypy failed at the `assert_never` arm in the fee reconciler, as intended. Added mypy to the
dev extras and recorded the check in the README, since a claim about type-checking that has
never been type-checked is not worth much.

**2026-09-01 22:24 +0300 — Commit 17: documentation review pass.** Reread the documents as a set rather than
one at a time, which surfaced two things. REJECTED.md was carrying full write-ups of the
four criteria that hold, and those were restating conclusions the code already makes; scoped
the document to the four that do not hold, and moved the substance that was worth keeping to
where the behaviour lives — the unmatched-settlement caveat into `decide_settlement`'s
docstring, criterion 5's claim into the test that proves it. And AMBIGUITIES item 12, on
whether a zero closing balance is negative, was not really a policy choice with two live
options: it is the exclusivity of the overdraft threshold, which NUMBERS.md already
documents as a constant. Folded it there and renumbered items 13–19 to 12–18, moving every
cross-reference in the package, the tests and the other documents with them. Also started
attributing acceptance criteria to the brief explicitly, since the repository keeps its own
numbered lists and the two read confusingly side by side. Filled in the real pre-implementation
timestamps and recorded that implementation was agent-assisted.

**2026-09-01 22:27 +0300 — Commit 18: trimmed the ARCHITECTURE.md preamble.** Removed the subtitle describing
the file's role in the submission. It addressed a reader of the assessment rather than a
reader of the system, and the document stands on its own without it.

**2026-09-01 22:41 +0300 — Commit 19: per-day authorisation states.** Audited the repository against the brief
line by line and found one real gap: the brief asks the script to print authorisation states
per day, and the report was printing transitions, so Day 3 said nothing about Auth-A while it
held 200.00 of the customer's available balance and Day 6 said nothing at all. Put the
as-at-a-day fold on `AuthorizationLog` (`state_on`, `known_on`) rather than in the
reporter, beside the existing `hold_for`, so the reporter still computes nothing the ledger
cannot answer for itself. Kept the transition lines underneath, so the report shows both what
was true and what changed.
