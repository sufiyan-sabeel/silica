# Application examples

Three complete programs that run on the current engine. They use only APIs that
exist in this repository — no invented functions, no placeholder output — and each
one is executed by `tests/test_apps.py`, which checks the transcript *and* the
files the program writes.

Every command below assumes you are in the repository root, and that Silica is
installed or runnable as `python3 -m silica`.

---

## 1. Calculator — `examples/calculator_app.sc`

A line-oriented calculator. Reads one expression per line, validates every part
before converting it, and reports a specific error instead of crashing.

**Capabilities:** none. It computes and reads stdin.

```bash
printf '12 * 4\n7 / 2\n1 / 0\nabc + 2\n12 *\n\n5 %% 3\nquit\n' \
  | python3 -m silica run examples/calculator_app.sc
```

Expected output:

```text
Silica calculator
type an expression such as '12 * 4', or 'quit' to leave
calc> 48.0
calc> 3.5
calc> error: cannot divide by zero
calc> error: 'abc' is not a number
calc> error: expected three parts, like '12 * 4'
calc> error: empty input
calc> error: unknown operator '%' (use + - * /)
calc> bye
```

What it validates: the number of parts, that both operands are numbers (digits
with an optional sign and one decimal point), that the operator is one of
`+ - * /`, and division by zero. Because Silica has no exceptions, validation is
preventive: `int()`/`float()` are only called on strings already proven numeric.

---

## 2. Task manager — `examples/task_manager.sc`

A persistent task list. State lives in `tasks.json` in the working directory and
is loaded at start-up and saved after every change.

**Capabilities:** `fs.read` and `fs.write`, scoped to the directory you pass.

```bash
mkdir -p /tmp/silica-tasks && cd /tmp/silica-tasks
printf 'add buy milk\nadd write docs\nlist\ndone 1\nlist\nquit\n' \
  | python3 -m silica run --allow-fs-read . --allow-fs-write . \
      /path/to/silica/examples/task_manager.sc
```

Expected output (first run, empty directory):

```text
Silica task manager - 0 task(s) in tasks.json
commands: add <title> | list | done <id> | remove <id> | quit
task> added #1: buy milk
task> added #2: write docs
task> [ ] 1. buy milk
[ ] 2. write docs
2 task(s), 2 still open
task> task 1 is done
task> [x] 1. buy milk
[ ] 2. write docs
2 task(s), 1 still open
task> bye
```

Run it again in the same directory and it says `1 task(s)` and prints the saved
task: state really is on disk, not in memory.

`tasks.json` afterwards:

```json
[
  {
    "id":1,
    "title":"buy milk",
    "done":true,
    "created":1793537045
  }
]
```

What it validates: an empty command, a missing title, a non-numeric id, an id that
does not exist, an unknown verb, and a store that is not a list of tasks — each
gets its own message and the program keeps going. Without the capability flags it
fails before touching the disk:

```text
capability error: capability 'fs.read' (read files) is not granted
```

---

## 3. Data report — `examples/data_report.sc`

A data-driven report. Reads `sales.csv` from the working directory, aggregates
revenue per region, prints a text report and writes `report.json`.

**Capabilities:** `fs.read` and `fs.write`, scoped to the directory.

```bash
mkdir -p /tmp/silica-report && cd /tmp/silica-report
cp /path/to/silica/examples/data/sales.csv .
python3 -m silica run --allow-fs-read . --allow-fs-write . \
    /path/to/silica/examples/data_report.sc
```

Expected output:

```text
reading 8 row(s) from sales.csv

region      revenue
-------------------
north       787.50
south       577.50
east        450.00
west        337.50
-------------------
total       2152.50
units       450
best        north
wrote report.json
```

`report.json` carries the same numbers in machine-readable form, with a per-region
breakdown:

```json
{
  "source":"sales.csv",
  "rows":8,
  "units":450,
  "revenue":2152.5,
  "best":"north",
  "skipped":0,
  "regions":[
    {"region":"north","revenue":787.5},
    {"region":"south","revenue":577.5},
    {"region":"east","revenue":450.0},
    {"region":"west","revenue":337.5}
  ]
}
```

The CSV format is `region,units,unit_price` with a header. Malformed rows are
counted and skipped, not fatal:

```text
warning: line 3 does not have three fields
warning: line 4 has a non-numeric value
skipped     2 bad row(s)
```

A missing `sales.csv` stops with a message and writes no report:

```text
error: sales.csv not found in this directory
copy examples/data/sales.csv here and run again
```

---

## What these examples are not

- **No GUI, TUI, mobile or desktop application.** Silica has a UI DSL that emits
  HTML (see `examples/ui_*.sc`) and a TUI, but these three are terminal programs
  that use stdin, stdout and files. No Android, iOS or desktop build pipeline
  exists, so none is claimed.
- **No network.** `http` and `net` are still planned modules and fail loudly.
- **Tested on Linux x86_64 only.** Termux and other platforms remain unverified
  (see the platform table in `README.md`).

## Language limits these examples ran into

Worth knowing, because they shape how the programs are written:

- **No exceptions.** A failed conversion (`int("abc")`) raises a runtime error
  that cannot be caught, so input is validated before conversion. Every loop that
  reads input ends on an explicit `quit` command rather than at end-of-file,
  because `input()` raises when the stream ends.
- **No index assignment.** `list[i] = value` and `map["k"] = value` are not part of
  the language, so a mutation rebuilds the list. `task_manager.sc` and
  `data_report.sc` both do this, deliberately and visibly.
- **Map literals stay on one line.** A map literal that breaks across lines does
  not parse.
- **`oder` is not a keyword.** The boolean operators are `und` and `ou`.
