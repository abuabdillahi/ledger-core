# ledger-core

An in-memory, append-only double-entry account ledger core: two accounts, ten events, six
days, and the questions those events raise about back-valued entries, overdraft fees,
authorisation holds and interest rounding.

## Requirements

**Python 3.11 or newer. No runtime dependencies — standard library only.**

The 3.11 floor buys `typing.assert_never` and `enum.StrEnum`, which together give exhaustive
`match` dispatch over the entry and event types: a new entry type becomes a type-check error
at every site that fails to handle it, rather than a wrong balance at runtime. The floor is
not raised further, because nothing in this design uses 3.12's type parameter syntax or
3.13's free-threading, and each version climbed narrows compatibility for no return.
NUMBERS.md sets this out in full.

`pytest` is a **development dependency only** — as is `mypy`, which is optional and used
only to check the exhaustiveness claim above. Neither is imported by any module under
`ledger/`, so the no-runtime-dependency claim stands: the package runs on a bare
interpreter, and `python3.11 -m ledger.report` works with nothing installed at all.

That the claim holds is checked rather than asserted: adding a seventh member to `EntryType`
makes `mypy` fail at the `assert_never` arm of the fee reconciler's dispatch, which is the
one site that classifies entry types, rather than the new type silently defaulting to "not a
fee" and changing every assessment basis in the system.

Developed and tested against **CPython 3.11.13** on macOS 15 (Darwin 25.3.0).

## Running it

```sh
python3.11 -m venv .venv
.venv/bin/pip install pytest

.venv/bin/python -m pytest          # the test suite
.venv/bin/python -m ledger.report   # replay the event stream and print the report
```

Optionally, to check the exhaustive-dispatch claim below:

```sh
.venv/bin/pip install mypy && .venv/bin/python -m mypy ledger/
```

The suite should report **90 passed, 1 xfailed**. The expected failure is deliberate and is
the subject of `tests/test_known_failure.py`; it is marked strict, so it will also be
reported if it ever starts passing.

## Reading the output

`python -m ledger.report` replays all ten events and prints five sections.

**DAY BY DAY** — for each day, each account's closing balance, the entries *booked* that
day, the fees *value-dated* to that day, the state and hold of every authorisation the
ledger has heard of by then, and any decisions recorded. Authorisation state is shown on
every day, not only on the days it changes — a 200.00 hold suppressing available balance
through a quiet Day 3 is exactly what a per-day report exists to make visible — with the
transition that caused it listed underneath on the day it happened. Booking day and value date differ for several entries, which is why they are shown
separately: Day 5 lists E7 as booked, while E7's 620.00 appears in Day 2's balance.

Where the two balance bases disagree, both are printed. On Day 5, ACC-001 reads
`465.00 AED` on the value basis with `(posting basis -230.00 AED, as believed on the day)`
beside it. Both are true. The value basis is what we now understand Day 5 to have been, once
E9 reversed E7; the posting basis is what the ledger contained at the time, and what the
customer would have been told.

**INTEREST** — the daily accrual schedule per account: the balance accrued on, the exact
accrual as a rational, and the rounded figure posted. ACC-001's exact total (1.018) and its
capitalised total (1.03) differ, and the report says so rather than quietly reconciling
them; AMBIGUITIES item 6 explains which was chosen and why.

**CLOSING POSITION** — Day 6 before capitalisation, the capitalisation credit, and Day 6
after, on three separate lines, so neither figure has to be inferred from the other.

**AUTHORISATIONS** — each authorisation's full transition history, not just its end state.
Auth-A shows approval against an available balance of 250.00 and settlement for 185.00 with
its 15.00 residual released.

**ERRORS AND REJECTIONS** — E6's rejected settlement and E8's declined authorisation. These
are records, not log lines: in an append-only ledger a decision not to post is still a
decision, and it is the one an auditor asks about.

## Architecture

The journal is the only state: an append-only list of immutable entries with a monotonic
sequence counter, and no update or delete operation anywhere in the package. Every other
value — a day's closing balance, an available balance, whether a fee is currently warranted,
an authorisation's state — is a pure function computed over that list on demand, never a
stored field. This is what makes the back-value cascade fall out for free: appending E7,
value-dated to a day that has already closed, propagates nothing forward, and every
subsequent query simply returns a different answer because its input set grew. Overdraft
fees follow the same principle from the other direction — the reconciler diffs the fees the
journal warrants against the fees standing and appends the difference, so E7's three fees
and E9's three reversals come out of one mechanism rather than two.

## The documents

- [REJECTED.md](REJECTED.md) — the four supplied acceptance criteria that do not hold, and
  why (the other four were accepted; all eight were evaluated independently)
- [AMBIGUITIES.md](AMBIGUITIES.md) — eighteen things the brief does not settle, and what was
  chosen in each case
- [NUMBERS.md](NUMBERS.md) — constants, split into given and chosen
- [ARCHITECTURE.md](ARCHITECTURE.md) — append-only at scale, value dating in production, the
  authorisation lifecycle, and what was cut
- [WORKLOG.md](WORKLOG.md) — what was done, and when
