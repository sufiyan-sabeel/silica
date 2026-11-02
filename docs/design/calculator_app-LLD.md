# calculator_app — low-level design

Status: implemented (`examples/calculator_app.sc`, 106 lines).
Capabilities: **none** — the program touches no files, no network and no process.

## 1. Overview and scope

A terminal calculator that evaluates a single binary arithmetic expression per
line, then asks for the next one. It exists to demonstrate that Silica can carry a
complete, well-behaved interactive program with the language alone: string
handling, control flow, numeric conversion, and error reporting that a user can act
on.

In scope: `+ - * /` on two numbers, negative and decimal operands, a `quit`
command, and a specific message for every way the input can be wrong.

Out of scope, deliberately: operator precedence, parentheses, chained expressions,
variables, history, and scientific functions. Each would need a parser and a
grammar; the point here is a small program that is correct, not a big one.

Users: someone learning Silica, and anyone running `silica run` for the first time
and wanting something interactive that needs no capabilities.

## 2. Architecture and component breakdown

A single file with no module boundary — the whole program is one `main` plus five
pure helpers. Input is read a line at a time, tokenised, validated, then evaluated.

```
stdin line
   ↓ trim
   ↓ "quit"?  → print "bye", stop
   ↓ empty?   → "error: empty input"
   ↓ split on spaces → exactly 3 tokens?
   ↓ operand 1 is a number?
   ↓ operand 2 is a number?
   ↓ apply(operator)
   ↓ print result, or the reason it failed
```

Validation happens before conversion, so a malformed token produces a message
naming it rather than a crash.

## 3. Module and file structure

| File | Role |
|---|---|
| `examples/calculator_app.sc` | the entire application |
| `tests/test_apps.py` | transcript tests: exact output for given stdin |
| `docs/design/calculator_app-LLD.md` | this document |

`use string` is the only import.

## 4. Data models and data flow

No persistent data and no structs. The working values are locals in `main`:

| Value | Type | Meaning |
|---|---|---|
| `line` | `String` | one trimmed input line |
| `parts` | `List` | tokens from splitting on single spaces |
| `left`, `right` | `Float` | the operands, after validation |
| `ok` | `Bool` | whether `apply` printed a result |

Data flow is one-way: `input` → `trim` → `words` → `is_number` ×2 → `float` →
`apply` → `sprint`. Nothing is retained between iterations, so a failed expression
cannot corrupt the next one.

## 5. Function signatures and responsibilities

| Function | Signature | Responsibility |
|---|---|---|
| `is_digits` | `(s: String) -> Bool` | true when every character is `0`–`9`; false for empty |
| `is_number` | `(s: String) -> Bool` | accepts an optional leading `-`, then digits, or digits `.` digits |
| `words` | `(line: String) -> List` | split on spaces, dropping empty parts |
| `apply` | `(left: Float, op: String, right: Float) -> Bool` | print the result; false when the operator is unknown or divides by zero |
| `main` | `() -> Unit` | the read-eval loop |

`is_number` is stricter than `float()`, which matters: `float("abc")` would raise,
and Silica has no exceptions, so the guard is what keeps the loop alive.

## 6. UI/UX structure

Line-oriented terminal, no TUI widgets.

```
Silica calculator
type an expression such as '12 * 4', or 'quit' to leave
calc> 6 * 7
42.0
calc> quit
bye
```

The prompt is `calc> `. Results print as floats (`42.0`), which is honest about the
arithmetic being floating point. Every error message quotes the offending token and
says what was expected, so the user can correct it without guessing.

## 7. Error handling and validation

Silica has no exceptions; every failure is a check and a message.

| Condition | Message |
|---|---|
| empty line | `error: empty input` |
| not three tokens | `error: expected three parts, like '12 * 4'` |
| operand 1 not numeric | `error: '<token>' is not a number` |
| operand 2 not numeric | `error: '<token>' is not a number` |
| unknown operator | `error: unknown operator '<op>' (use + - * /)` |
| division by zero | `error: cannot divide by zero` |
| end of input | `input()` raises at EOF, which ends the program |

Order matters: the token count is checked before the operands, so `12 *` reports the
missing part rather than claiming `*` is not a number.

## 8. Security and capability requirements

**None.** The program reads only stdin and writes only stdout. It declares no
`use fs`, opens no socket, starts no process. It runs under the default deny
policy with no `--allow-*` flags, which is the strongest demonstration that the
capability system is not in the way of ordinary programs.

Input is treated as hostile by construction: every token is validated by shape
before conversion, and nothing from the input reaches a path, a command or an
interpreter.

## 9. Dependencies and external integrations

| Dependency | Kind | Notes |
|---|---|---|
| `string` | Silica standard library | `trim`, `split`, `replace`, `starts_with` |
| `input`, `sprint`, `float`, `len`, `str` | built-ins | no imports |
| CPython | runtime | none directly used |

No third-party packages, no network, no external services.

## 10. Testing strategy and acceptance criteria

`tests/test_apps.py` drives the real program with piped stdin and asserts the exact
transcript, so the prompt, the result format and every error string are pinned.

Acceptance criteria:

1. `6 * 7` prints `42.0`.
2. `10 / 4` prints `2.5` — float division, unlike `Int / Int` which truncates.
3. `-3 + 1.5` prints `-1.5`; a leading minus and a decimal point are both accepted.
4. `5 / 0` prints the divide-by-zero message and the loop continues.
5. `1 % 2` prints the unknown-operator message naming `%`.
6. An empty line prints the empty-input message.
7. `12 *` prints the three-parts message.
8. `abc * 2` names `abc` as not a number.
9. `quit` prints `bye` and exits with status 0.
10. The program runs with no capability flags.

## 11. Implementation phases

1. `is_digits`, then `is_number` — validation before anything else, because every
   later step depends on it.
2. `words` and `apply` — tokenising and arithmetic, each testable in isolation.
3. `main` — the loop, with the error ladder in the order the checks must run.
4. Transcript tests in `tests/test_apps.py`, including one case per error branch.
5. Added to the example skip list in `tests/test_optimizer.py` where the constant
   folder would otherwise try to evaluate an interactive program.

## Limitations

- No precedence or parentheses: `1 + 2 * 3` is rejected as five tokens.
- Operands must be separated by single spaces (`6*7` is one token).
- Results are floats even when integral, because `/` is float division.
