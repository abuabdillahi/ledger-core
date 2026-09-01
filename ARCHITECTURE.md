# Architecture and trade-offs

*Companion to the ledger core. Markdown source for the 2–4 page PDF deliverable.*

---

## 1. Append-only at scale

**What breaks first is query cost, not memory.**

Every balance in this system is a full scan of the journal. `projections.balance` folds the
entire entry list and filters by account and date, which is O(n) per query. That is not the
expensive part on its own. The expensive part is the fee reconciler: it calls `balance` once
per day of the window per account, and the replay loop invokes it after every event that
appends financial entries. The cost of a replay is therefore roughly *events × days ×
entries* — quadratic in the length of the stream, with the window length as the constant.

At the scale in this brief that is ten events over six days and it does not matter. At 100×
volume it is the only thing that matters. Memory is not close: an entry is a slotted frozen
dataclass holding six small fields and two references, on the order of a couple of hundred
bytes, so a million entries is a few hundred megabytes and ten million is where a single
process starts to hurt. The quadratic scan makes the system unusable at a fraction of that.

**Where the design accumulates unbounded state.** Two places. The journal itself grows
without bound by design — that is what append-only means, and under UAE AML record-keeping
obligations it cannot simply be truncated, because retained records must remain sufficient
to reconstruct individual transactions for five years. And the fee reconciler's assessment
window grows with the ledger: it currently walks every day from Day 1, so its per-invocation
cost grows as the account ages, indefinitely.

**The cheapest structural change that defers the problem** is periodic snapshotting of
value-dated daily closing balances per account, with replay only of entries appended after
the snapshot point. A snapshot is not new truth — it is a memoised projection, derivable
from the journal at any time and safe to delete — so it preserves the append-only guarantee
completely, which is exactly why it is the cheapest change available. Nothing about the
write path changes; only the read path gains a starting point other than zero. Query cost
falls from "the whole history" to "since the last snapshot", which is bounded by snapshot
frequency rather than by account age.

**The tension is that back-valued entries invalidate snapshots after their value date.** A
snapshot asserting "ACC-001 closed Day 2 at 250.00" stops being true the moment an entry
value-dated to Day 2 is appended, however long afterwards. So the snapshot strategy has to
be value-date aware rather than sequence-aware: each snapshot records the account, the day
it covers, and the highest journal sequence included, and appending an entry with
`value_date <= D` invalidates every snapshot for that account covering day D or later. The
invalidation is cheap because back-valuation is rare in practice, but it must be automatic
and it must be part of the append path — a snapshot that is stale and does not know it is
worse than no snapshot at all, because it converts an expensive correct answer into a fast
wrong one.

A second, cheaper measure worth taking at the same time: bound the fee reconciler's window.
Real banks close accounting periods, and a fee assessment reaching back to the account's
opening is not a feature anyone wants. Restricting reconciliation to a rolling window — with
anything older requiring an explicit adjustment posting — bounds the reconciler's cost and
matches the operational reality that a closed period is not silently reopened.

## 2. Value-dated entries in production

**The operational and regulatory surface.** Back-valuation retroactively changes daily
balances, and daily balances are an input to almost everything a bank computes: profit or
interest accrual, overdraft and fee assessment, average-balance product qualification,
liquidity and regulatory reporting, and statements already issued to the customer. A
back-valued posting is therefore never a single correction. It is a correction plus an
unknown number of downstream recomputations, and the risk is not that the ledger gets the
new balance wrong — it is that the ledger gets it right while six downstream systems
continue to hold the old one.

**The two-timeline problem.** Posting basis and value basis answer different questions and a
production system needs both, permanently. The value basis is the calculation timeline: what
the balance *was*, as currently understood, and therefore what profit should have accrued.
The posting basis is the audit and customer-communication timeline: what the ledger
contained at a given moment, and therefore what the customer was told and what any report
issued that day legitimately said. A system that keeps only the value basis cannot explain
why last month's statement said something different; a system that keeps only the posting
basis cannot restate. Both projections must be reproducible from the journal for as long as
the records are retained — which is where append-only stops being an engineering preference
and becomes a regulatory requirement, since AML rules require that retained records permit
the reconstruction of individual transactions. A ledger that restates in place destroys
exactly the thing it is obliged to keep.

**Why this is sharper under a mudaraba structure.** In a profit-sharing deposit pool, each
depositor's entitlement is a function of their value-dated balances over the profit period.
The value date does not merely determine one customer's profit figure — it determines the
*share* they take from a common pool, so an error moves money between depositors, and
between the depositors and the bank as mudarib. That makes a value-date error a Shari'ah
compliance failure and a matter for the Internal Shari'ah Supervision Committee, not merely
an accounting one, and it is materially harder to remedy than a mispayment: profit already
distributed to other depositors cannot be quietly clawed back, so the correction usually has
to be funded rather than reversed. The engineering consequence is that value dating in an
Islamic institution deserves controls closer to those applied to payments than to those
applied to bookkeeping.

**One control to add before go-live: mandatory second-person approval for any posting
back-valued beyond a defined window, coupled with automatic recomputation and reporting of
every affected downstream calculation.** Maker-checker on its own is not enough, because the
checker cannot see the consequences of what they are approving; the automatic downstream
impact report is what makes the approval meaningful. Concretely: the request states which
days' closing balances change and by how much, which profit or fee calculations those days
feed, which already-issued statements or regulatory returns are affected, and whether the
affected period is closed. The window itself should be set at the profit-calculation period
boundary rather than at an arbitrary number of days — inside the current period a
back-valuation is an ordinary correction, and across the boundary it is a restatement with
Shari'ah and reporting consequences. Those are different acts and should not share an
approval path.

## 3. Authorisation lifecycle

Every way an authorisation can end other than a settlement that matches it exactly.

**Declined at request time.** Insufficient available balance, or a risk or velocity rule
fires. Nothing is held and no money moves, but the decision is durable: the customer will
ask why, and "we have no record" is not an answer. Recorded here as a decision record.

**Expiry without settlement.** The merchant abandons the transaction or never captures — an
online order cancelled before dispatch, a hotel booking never taken up. The hold must
auto-release on a defined schedule. The expiry window is a chosen constant, and it must be
enforced by time-triggered processing, because no inbound event will ever prompt it; a
system that only acts on messages leaves the customer's available balance suppressed
indefinitely and has no code path that will ever fix it.

**Void or cancellation before settlement.** The merchant explicitly reverses the
authorisation — a mis-keyed amount, a customer changing their mind at the counter. This is a
message rather than a timeout, and the correct behaviour is immediate release rather than
waiting for expiry: the merchant has told us the money will not be claimed.

**Partial settlement with residual release.** The merchant captures less than authorised, as
a fuel pump or a restaurant tip margin routinely does. The settlement is accepted for the
lesser amount and the residual is released; the alternative, holding the residual until
expiry, protects against a later incremental capture at the cost of suppressing the
customer's available balance for money nobody intends to take. Which is right depends on the
merchant category, which is why production systems drive this from the MCC rather than from
a single global rule.

**Over-settlement above the authorised amount.** Scheme rules permit capture above the
authorisation by a defined tolerance — commonly a percentage for restaurants and similar
gratuity-bearing categories, and specific allowances elsewhere. Within tolerance the issuer
must honour it; beyond tolerance the transaction loses its authorisation protection and
becomes a chargeback candidate. Either way the correct behaviour is to post and flag, not to
refuse: the money has already changed hands at the point of sale.

**Settlement arriving after expiry (late presentment).** The hold no longer exists, but the
transaction is real and scheme rules may still oblige the issuer to honour it. The account
may no longer have the funds the hold once protected, which is precisely how an authorised
transaction becomes an unauthorised overdraft. Mandated behaviour is to post, to treat the
resulting shortfall under the account's overdraft terms rather than as a decline, and to
raise an exception case if the presentment is outside the scheme's presentment window.

**Settlement with no matching authorisation at all (forced post).** Offline-authorised
transactions, terminals operating in fallback, and genuine merchant error all produce these.
This implementation rejects them, which is defensible only because it has no scheme
integration and no way to tell a legitimate forced post from a malformed message. A real
issuer that hard-rejects every unmatched settlement is not running a safe system; it is
running one that fails its scheme obligations. Production behaviour is to post, flag for
exception handling, and use chargeback as the recourse.

## 4. What I cut, and the risk each deferral carries

- **No durability and no write-ahead log.** The entire ledger lives in one process's memory
  and is lost on termination. In production the append is the only operation that must
  survive a crash, and it must be durable *before* it is acknowledged; everything else here
  is derived and can be rebuilt.
- **No concurrency control.** Replay is single-threaded and totally ordered, which defers the
  whole lost-update problem. Two concurrent appends against the same account need either a
  per-account serialisation point or optimistic concurrency on a sequence number, and the
  choice determines the system's throughput ceiling.
- **No idempotency keys.** A duplicated event double-posts, silently. Payment networks
  retry, and any real ingress path needs a deduplication key with a retention window at
  least as long as the upstream retry window.
- **No multi-currency transactions.** Every entry is single-currency and no transaction has
  legs in two currencies, so there are no FX positions, no rate source, no rate timestamp,
  and no revaluation. The BHD overdraft tariff sidesteps rather than solves this.
- **No sub-ledger to general-ledger aggregation.** This is a customer sub-ledger only.
  Nothing summarises into GL accounts, so nothing proves the sub-ledger and the GL agree —
  which is the reconciliation that most often catches ledger bugs in production.
- **No reconciliation against external settlement systems, and no external reference
  identifiers on entries.** An entry cannot currently be tied back to a scheme transaction
  id, a payment message reference or a nostro movement, so a break cannot be investigated
  from the ledger side.
- **No authorisation expiry inside the window.** The mechanism exists and is tested, but the
  six-day window and the seven-day expiry mean it is never exercised by this data. Untested
  in anger is untested.
- **No Shari'ah-specific product structures.** No murabaha or ijara posting models, no
  purification account for non-compliant income, no profit-pool allocation across depositors.
  These are not additions to a conventional ledger; they change what a posting *means*, and
  retrofitting them is substantially harder than designing for them.
- **No snapshotting.** Query cost grows without bound, as set out in section 1. It is the
  first thing to add, and the section above says why it is also the cheapest.
