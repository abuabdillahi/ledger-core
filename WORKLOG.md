# Worklog

Timestamps are real. Pre-implementation entries were performed before the repository
existed and are marked `[TIME TBC]` for the author to fill in from their own notes; every
entry from the first commit onwards carries an actual clock time.

Times are as reported by the machine the work was done on (UTC+03).

---

## Pre-implementation

**[TIME TBC] — Background research.** Read up on Mal, the role, and the operating
environment: CBUAE as regulator, the mandatory application of AAOIFI Shari'ah standards for
Islamic financial institutions in the UAE, the Internal Shari'ah Supervision Committee
governance model, and AML record-keeping obligations — five-year retention, with the
specific requirement that retained records be sufficient to *reconstruct individual
transactions*. That last requirement is the one that shapes the architecture: it is an
argument for an append-only journal on regulatory grounds, independent of any engineering
preference.

**[TIME TBC] — Core banking ledger fundamentals.** Double-entry invariants; money
representation in integer minor units and why floating point is disqualifying; concurrency
models for ledgers; idempotency and duplicate-event handling; write-ahead durability;
sequencing and total order; reversal semantics (compensating entry versus deletion).

**[TIME TBC] — Domain concepts.** Chart of accounts and the sub-ledger / general-ledger
boundary; posting versus settlement; nostro reconciliation; value dating; and the
distinction between a core banking ledger and a payment orchestrator — the latter moves
money, the former is the book of record, and conflating them is a common architectural
error.

**[TIME TBC] — Islamic finance primitives.** Murabaha, ijara, wakala, mudaraba and qard
hasan, and how each posts differently. Relevant here mainly through mudaraba: under a
profit-sharing deposit structure, value-dated balances directly determine each depositor's
share of the pool, so a value-date error is a Shari'ah compliance failure and not merely an
accounting one. Noted for the Part 2 document.

**[TIME TBC] — Hand calculation.** Computed the full day-by-day balance table on paper
before writing any code, including the E7 back-value cascade and the three overdraft fees it
triggers. Doing this first is what made criterion 2 obviously wrong rather than arguably
wrong.

**[TIME TBC] — Recomputation after an error.** Found an error in the initial treatment of
E6 (had provisionally posted the unmatched settlement before concluding it must be
rejected), recomputed the whole table independently, and arrived at the verified figures.
Recorded here rather than quietly corrected, because the first pass being wrong is the
normal case and the log should say so.

**[TIME TBC] — Acceptance criteria.** Evaluated all eight individually against the hand
calculation, deliberately not against each other. Identified criteria 2, 6, 7 and 8 as
incorrect, criterion 5 as sound but unreachable, and criterion 4 as correct-as-scoped with
two production qualifications.

**[TIME TBC] — Architecture.** Settled on: the journal is the only state; every other value
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
Added a half-up mode alongside half-even purely so that the AMBIGUITIES item 17 claim — that
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
