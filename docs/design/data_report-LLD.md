# data_report — low-level design

Status: implemented (`examples/data_report.sc`, 156 lines).
Capabilities: **`fs.read`, `fs.write`** — scoped to the directory it is run in.

## 1. Overview and scope

Reads a CSV of sales rows, aggregates revenue by region, prints a table, and writes
the result as JSON. It exists to demonstrate the pipeline that most real scripts
actually are: file in, parse, aggregate, file out — with every malformed row
reported rather than silently dropped.

In scope: a header row, three columns (`region,units,unit_price`), per-region
aggregation of units and revenue, a grand total, a count of skipped rows, a printed
table with aligned columns, and a JSON report.

Out of scope: quoted CSV fields, embedded commas or newlines, other delimiters,
sorting options, multi-file input, and streaming very large files (the whole file is
read into memory).

Users: anyone with a CSV export and no wish to open a spreadsheet; and a reader
learning how Silica handles files, numbers and output formatting.

## 2. Architecture and component breakdown

One file, a straight pipeline with a formatting layer:

```
sales.csv → read_text → split lines → skip header
          → per row: split on ',' → 3 cells? → numeric? → accumulate into parallel lists
          → totals
          → print table (padded columns, money formatting)
          → write report.json
```

Aggregation uses two parallel lists (`regions`, `totals`) plus
`collections.index_of` to find an existing region — the idiomatic approach in a
language without maps-with-default or index assignment.

## 3. Module and file structure

| File | Role |
|---|---|
| `examples/data_report.sc` | the application |
| `examples/data/sales.csv` | the sample input, copied to the working directory |
| `report.json` | the output, written next to the input |
| `tests/test_apps.py` | runs it and asserts both the table and the JSON |
| `docs/design/data_report-LLD.md` | this document |

Imports: `fs`, `json`, `string`, `collections`.

## 4. Data models and data flow

Input, `examples/data/sales.csv`:

```csv
region,units,unit_price
north,120,4.50
south,80,5.25
```

Accumulators during the run:

| Value | Type | Meaning |
|---|---|---|
| `regions` | `List` | region names, in first-seen order |
| `totals` | `List` | parallel revenue totals |
| `revenue` | `Float` | grand total revenue |
| `units` | `Int` | grand total units |
| `bad` | `Int` | rows skipped, with a reason printed for each |
| `line_number` | `Int` | for messages; starts at 1 for the header |

Output, `report.json`:

```json
{
  "units": 200,
  "revenue": 960.0,
  "regions": [{"region": "north", "revenue": 540.0}, ...],
  "skipped_rows": 0
}
```

Flow: `fs.read_text(SOURCE)` → `string.trim` → `string.split("\n")` → per row
`string.split(",", 3)` → validate → `int`/`float` → `collections.index_of` →
accumulate → print → `json.stringify(report, 2)` → `fs.write_text`.

## 5. Function signatures and responsibilities

| Function | Signature | Responsibility |
|---|---|---|
| `is_digits` | `(s: String) -> Bool` | units must be plain digits |
| `is_number` | `(s: String) -> Bool` | optional `-`, digits, optional `.` digits — for prices |
| `pad` | `(text: String, width: Int) -> String` | right-pad with spaces so columns align |
| `money` | `(value: Float) -> String` | two-decimal formatting for a revenue figure |
| `main` | `() -> Unit` | the pipeline |

`is_number` exists separately from `is_digits` because a price may be `4.50` while a
unit count may not be `4.5`.

## 6. UI/UX structure

```
reading 3 row(s) from sales.csv
units       450
best        north
wrote report.json
```

Column widths are computed from the data, not hardcoded, so a longer region name
does not break the alignment. Warnings go to stdout above the summary and name the
line number and the reason:

```
warning: line 4 does not have three fields
warning: line 5 has a non-numeric value
```

## 7. Error handling and validation

| Condition | Behaviour |
|---|---|
| input file missing | `error: sales.csv not found in this directory`, hint to copy the sample, exit 1 |
| fewer than two lines | `error: sales.csv needs a header and at least one row`, exit 1 |
| row without exactly three cells | warning naming the line, row skipped, counted |
| non-numeric units or price | warning naming the line, row skipped, counted |
| every row bad | totals stay zero; the report is still written, `skipped_rows` says why |

A skipped row never aborts the run: a 10,000-row export with one bad line should
produce a report and a warning, not nothing. `halt(1)` is reserved for the two
conditions where there is nothing to report at all.

## 8. Security and capability requirements

Requires `fs.read` and `fs.write`, scoped to a directory. The program builds no
paths from input — `SOURCE` and `REPORT` are constants — so the CSV cannot direct a
read or write elsewhere.

The runtime's `fs` boundary resolves symlinks with `realpath` and refuses anything
outside the granted root; running with `--allow-fs-read . --allow-fs-write .` keeps
both the read and the write inside the working directory.

Cell values are only ever compared, converted to numbers, or written into JSON.
Nothing is evaluated, and the output is produced by `json.stringify`, so a region
name containing quotes or braces cannot corrupt the report.

## 9. Dependencies and external integrations

| Dependency | Kind | Notes |
|---|---|---|
| `fs` | Silica stdlib | `exists`, `read_text`, `write_text` |
| `json` | Silica stdlib | `stringify(report, 2)` |
| `string` | Silica stdlib | `trim`, `split` |
| `collections` | Silica stdlib | `index_of` for the region lookup |

No third-party packages, no network, no subprocess.

## 10. Testing strategy and acceptance criteria

`tests/test_apps.py` copies the sample CSV into a temporary directory, runs the
program there, and asserts both the printed summary and the parsed `report.json`.

Acceptance criteria:

1. The sample input produces `units 450` and `best north`.
2. `report.json` exists, parses as JSON, and its `units` and `revenue` match the
   printed totals.
3. Per-region revenue sums to the grand total.
4. A row with two fields produces a warning naming its line number and is skipped.
5. A row with a non-numeric price produces a warning and is skipped.
6. `skipped_rows` in the JSON equals the number of warnings printed.
7. A missing input file exits 1 with the guidance message.
8. A file with only a header exits 1 with the "needs a header and at least one row"
   message.
9. Running without capability flags fails with a capability error.
10. Region names of differing lengths keep the table aligned.

## 11. Implementation phases

1. `is_digits`, `is_number`, `pad`, `money` — the primitives, each testable alone.
2. Read and split the file; validate the header and row count before looping.
3. The accumulation loop with `collections.index_of`, counting skipped rows.
4. The table output, with widths derived from the data.
5. The JSON report and `fs.write_text`.
6. Tests for the happy path, each error branch, and the alignment case.

## Deviations from the original implementation

One defect was found by the tests and fixed: the printed table used a fixed width,
so a region name longer than the assumed width broke the column alignment. Widths
are now computed from the actual data.

## Limitations

- The whole file is held in memory; fine for thousands of rows, not millions.
- CSV parsing is `split(",")`, so quoted fields containing commas are not supported —
  a deliberate trade for a readable example, stated here rather than discovered later.
- Aggregation order follows first appearance, not revenue or alphabet.
- Money is formatted for display only; revenue is accumulated as `Float`, so very
  large totals could drift in the last decimal.
