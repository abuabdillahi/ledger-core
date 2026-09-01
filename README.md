# ledger-core

An in-memory, append-only double-entry account ledger core.

*(Skeleton. Run instructions and output guide land in the final documentation pass, once
there is something to run. The analysis documents below are complete and were written
first.)*

- [REJECTED.md](REJECTED.md) — the eight acceptance criteria, each evaluated independently
- [AMBIGUITIES.md](AMBIGUITIES.md) — what the brief does not settle, and what was chosen
- [NUMBERS.md](NUMBERS.md) — constants: given, and chosen
- [WORKLOG.md](WORKLOG.md) — what was done, when

## Architecture in three sentences

The journal is the only state: an append-only list of immutable entries, with a monotonic
sequence counter and no update or delete operation. Every other value — a day's closing
balance, an available balance, whether a fee is currently warranted, an authorisation's
state — is a pure function computed over that list on demand, never a stored field. This is
what makes the back-value cascade fall out for free: appending a Day-2-value-dated entry on
Day 5 propagates nothing forward, because there is nothing to propagate to, and every
subsequent query simply returns a different answer because its input set grew.
