# Numbers

Constants only. The test for inclusion is whether *"why that value and not half it?"* has a
meaningful answer. If the alternative is a different **magnitude**, it belongs here. If the
alternative is a different **option**, it is a policy choice and belongs in AMBIGUITIES.md.

Rounding mode, tie-break rule, interest basis, residual hold release and replay ordering are
all policy choices. They are not in this file. Where a constant depends on a policy choice,
the AMBIGUITIES item is cross-referenced by number and never restated: one decision, one
home.

---

## Given

Not our choices. Listed for completeness, and so that the boundary between what was handed
to us and what we decided is legible.

| Constant | Value | Source |
|----------|-------|--------|
| Overdraft fee (AED) | 25.00 | Brief, non-negotiable rules |
| Daily interest rate | 0.04% per day (`Fraction(4, 10000)`) | Brief |
| Window | Day 1 to Day 6 inclusive | Brief |
| AED precision | 2 decimal places | Brief |
| BHD precision | 3 decimal places | Brief |
| Opening balances | 0.00 (ACC-001), 0.000 (ACC-002) | Brief |

The daily rate is held as an exact rational, not as 0.0004. See AMBIGUITIES item 16 for why
the representation is not a free choice.

---

## Chosen

### Authorisation expiry window: **7 days**

**Why.** Matches common card scheme defaults for a standard (non-incremental, non-travel)
authorisation. It is long enough that a merchant capturing on a normal settlement cycle is
never cut off, and short enough that an abandoned authorisation stops suppressing the
customer's available balance within about a week.

**Halved to 3 days, or doubled to 14.** No observable change on this dataset. Auth-A settles
on Day 4, two days after approval, and Auth-B is declined at request time so no hold is ever
created. No authorisation in this window is ever both approved and unsettled for long enough
to expire under any of the three values.

**Recorded honestly as a constant that does not bind here.** It is nonetheless load-bearing
for any authorisation that neither settles nor is declined: without an expiry window there
is no code path that releases such a hold, and it would suppress available balance forever.
The value is arbitrary within a range; the *existence* of the value is not. See AMBIGUITIES
item 10.

### Maximum fee reconciliation passes: **1 per day per account, per reconciler run**

**Why.** Justified by the acyclicity argument in AMBIGUITIES item 2 — a day's fee depends
only on non-fee entries and on fees from strictly earlier days, so one ascending pass over
Days 1–6 reaches the correct answer and a second pass would find nothing to do.

**Halved.** Not meaningful — zero passes assesses no fees.

**Doubled.** Would mask a design error rather than fix one. If a second pass ever *did* find
work, the acyclicity assumption would have been violated, and the right response is to find
out why, not to iterate until the numbers stop moving. The limit is enforced by an assertion
that fails loudly rather than by a loop bound that fails quietly.

### BHD overdraft fee tariff: **2.500**, at a fixed 1.00 AED : 0.100 BHD

**Why.** A published fee tariff, not an FX conversion. Justification and the rejected
alternative are in AMBIGUITIES item 11.

**Doubled to 5.000, or halved to 1.250.** Both diverge sharply from the AED fee's economic
weight under the dollar pegs. The exact peg-derived equivalent of AED 25.00 is BHD 2.560, so
2.500 is a round tariff approximation carrying a deliberate 2.3% divergence; 5.000 would be
roughly double the AED fee in real terms and 1.250 roughly half. Neither is defensible as
"the same fee, denominated in the account's currency", which is what the constant is for.

### Overdraft threshold: **0.00, exclusive**

**Why.** A fee is assessed when the closing balance is *strictly* below this figure. See
AMBIGUITIES item 12 for the zero-balance boundary.

**Raised to any positive value.** Fees would be assessed on solvent accounts — a bank
charging an overdraft fee to a customer who is not overdrawn.

**Lowered to a negative value** (a tolerance band, e.g. −10.00). A defensible product
feature, and common as a "buffer" on current accounts, but it is a different product rather
than a different magnitude of the same one.

**Interaction worth noting.** Day 3's closing balance of 5.00 sits five dirhams above this
threshold. The threshold and the fee tariff interact: a fee of 30.00 or more against a
threshold of 0.00 would push Day 3 negative and trigger a second-order fee cascade. Two
constants that appear independent are not. See AMBIGUITIES item 3.

### Python version floor: **3.11**

**Why.** `typing.assert_never` and `enum.StrEnum`, which together give exhaustive `match`
dispatch over entry and event types. Every site that dispatches on an entry type ends in an
`assert_never` arm, so adding a seventh entry type makes a type checker report every place
that fails to handle it — before the code runs. That matters here specifically because
correctness depends on `OVERDRAFT_FEE`, `FEE_REVERSAL` and `INTEREST_CAPITALISATION` being
handled *distinctly* wherever they appear; a silent `else` branch would make a new entry type
default into the wrong arm and quietly produce wrong balances.

**Lowered to 3.9.** `assert_never`, `StrEnum` and structural pattern matching are all
unavailable, and `slots=True` on dataclasses (3.10) is too. Exhaustiveness would become a
runtime `raise` in an `else` branch — an error found by whoever runs the code, if they are
lucky, rather than by the type checker.

**Raised to 3.12 or above.** Nothing is gained. The 3.12 type parameter syntax and 3.13
free-threading are both unused by this design, and each version climbed narrows the set of
environments the code runs in for no return.

Developed and tested against **CPython 3.11.13** on macOS.
