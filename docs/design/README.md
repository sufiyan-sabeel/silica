# Design documents — LLD first

**No application code before the LLD.** Every Silica application in this repository
has a low-level design here, written before the code and kept in step with it.

This applies to everything: demos, prototypes, throwaway scripts that end up in
`examples/`, and changes to an existing application (in which case the LLD describes
the current architecture and the proposed change before it is made).

## Platform architecture

The LLD policy above governs applications. Cross-cutting design work sits
alongside it and is reviewed the same way — as a document first:

| Document | Status | Scope |
|---|---|---|
| [SILICA_PLATFORM_ARCHITECTURE.md](SILICA_PLATFORM_ARCHITECTURE.md) | approved direction, revised for review | how Silica targets web, desktop, Android, GUI/TUI and system software; the recorded decisions on error model, concurrency, desktop backend, WASM, packaging; the design for first-class functions and closures; and the Rust VM migration strategy; parity contract pinned in `tests/parity/` |

## Where they live

```
docs/design/<example-basename>-LLD.md
```

`examples/task_manager.sc` → `docs/design/task_manager-LLD.md`. The packaging test
suite enforces the pairing, so an application without a design fails CI.

## What an LLD must contain

A real engineering document, not an outline and not a design written after the code:

1. Overview and scope — purpose, users, use cases
2. Architecture and component breakdown
3. Module and file structure
4. Data models and data flow
5. Function signatures and responsibilities
6. UI/UX structure, where applicable
7. Error handling and validation
8. Security and capability requirements
9. Dependencies and external integrations
10. Testing strategy and acceptance criteria
11. Implementation phases

`tests/test_design_docs.py` checks that every section is present and that each
capability the code needs is declared in the design.

## Feasibility gate

Before an API is proposed, confirm it exists in the current Silica language and
standard library. Do not invent syntax, modules, methods or capabilities. Where
something is missing, say so in the LLD under limitations rather than designing
around a feature that does not exist.

Known language limits worth checking first: no index assignment (`list[i] = v`,
`map["k"] = v`), map literals on one line, `und`/`ou` for boolean operators,
`Int / Int` truncates, no exceptions, `input()` raises at EOF.

## Index

| Application | Design | Capabilities |
|---|---|---|
| `examples/calculator_app.sc` | [calculator_app-LLD.md](calculator_app-LLD.md) | none |
| `examples/task_manager.sc` | [task_manager-LLD.md](task_manager-LLD.md) | `fs.read`, `fs.write` |
| `examples/data_report.sc` | [data_report-LLD.md](data_report-LLD.md) | `fs.read`, `fs.write` |
| `examples/scientific_calculator.sc` | [scientific_calculator-LLD.md](scientific_calculator-LLD.md) | `fs.read`, `fs.write` |
