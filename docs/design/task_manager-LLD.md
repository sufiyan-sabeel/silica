# task_manager — low-level design

Status: implemented (`examples/task_manager.sc`, 198 lines).
Capabilities: **`fs.read`, `fs.write`** — scoped to the directory it is run in.

## 1. Overview and scope

A terminal task list that persists to a JSON file between runs. It exists to show
the two things a real application needs beyond arithmetic: durable state and input
that cannot be trusted.

In scope: add, list, mark done, undo, remove, quit; a monotonic id per task; a
created timestamp; a store that survives being corrupted.

Out of scope: editing a title, priorities, due dates, multiple lists, search,
concurrency. Every one of those is a straightforward extension once the store and
the command loop are right.

Users: someone who wants a scratch task list on a machine with Python and nothing
else — no database, no daemon, no account.

## 2. Architecture and component breakdown

Layered, one file. The command loop never touches the file directly; it works on an
in-memory `List` of task maps and asks `save` to persist it.

```
main (loop)
 ├── load()      store → List, with repair
 ├── show()      List → stdout
 ├── next_id()   List → Int
 ├── find()      List, Int → index (or -1)
 ├── with_done() List, Int, Bool → List   (pure: returns a new list)
 ├── without()   List, Int → List         (pure)
 └── save()      List → store
```

The two mutating operations return new lists rather than editing in place, because
Silica has no index assignment (`list[i] = v` does not exist). That constraint
shapes the design rather than being worked around.

## 3. Module and file structure

| File | Role |
|---|---|
| `examples/task_manager.sc` | the application |
| `tasks.json` | the store, created in the working directory on first save |
| `tests/test_apps.py` | drives the program and inspects the resulting file |
| `docs/design/task_manager-LLD.md` | this document |

Imports: `fs`, `json`, `time`, `string`.

## 4. Data models and data flow

A task is a map with four keys, all required:

| Key | Type | Meaning |
|---|---|---|
| `id` | `Int` | stable, monotonic, never reused |
| `title` | `String` | the text after `add `, trailing space stripped |
| `done` | `Bool` | completion flag |
| `created` | `Float` | `time.now()` at creation, seconds since the epoch |

The store is a JSON **array** of those maps, written with two-space indentation so a
human can read and edit it.

Flow for `add`:

```
line → trim → verb == "add" → strip the "add " prefix → title
     → next_id(tasks) → new map → push(tasks, task) → save(tasks) → print "added #<id>: <title>"
```

Flow for `done`/`remove`: parse the id, `find` the index, then `with_done`/`without`
to build the replacement list, `save`, print the outcome.

## 5. Function signatures and responsibilities

| Function | Signature | Responsibility |
|---|---|---|
| `is_digits` | `(s: String) -> Bool` | validate an id before `int()` |
| `words` | `(line: String) -> List` | split a command line |
| `load` | `() -> List` | read the store; return `[]` when absent, empty or invalid |
| `save` | `(tasks: List)` | write the store as indented JSON |
| `next_id` | `(tasks: List) -> Int` | highest existing id + 1, starting at 1 |
| `find` | `(tasks: List, id: Int) -> Int` | index of the task, or `-1` |
| `show` | `(tasks: List)` | print each task with a `[x]`/`[ ]` marker |
| `with_done` | `(tasks: List, id: Int, flag: Bool) -> List` | new list with one `done` changed |
| `without` | `(tasks: List, id: Int) -> List` | new list without that task |
| `main` | `() -> Unit` | the command loop |

## 6. UI/UX structure

```
tasks> list
[ ] #1 buy milk
[x] #2 write the LLD
tasks> add call the dentist
added #3: call the dentist
tasks> done 1
marked #1 done
tasks> remove 2
removed task 2
tasks> quit
bye
```

Prompt `tasks> `. Every command reports what it did and which id it acted on, so the
user never has to re-list to confirm. Unknown commands print the available verbs
rather than failing silently.

## 7. Error handling and validation

The store is treated as untrusted input, because it is a file a user can edit:

| Condition | Behaviour |
|---|---|
| store missing | start with an empty list, no error |
| store empty or whitespace | start empty |
| store is not a JSON array | warning naming the file, start empty |
| an entry is not a map | warning, start empty |
| an entry lacks `id`, `title` or `done` | warning, start empty |
| unknown command | list the available verbs |
| non-numeric id | message naming the token; no `int()` call |
| id not found | `no task with id <n>` |

Starting empty rather than crashing is deliberate: the alternative is an application
that cannot start until the user hand-repairs JSON. The warning makes the loss
visible.

## 8. Security and capability requirements

Requires `fs.read` and `fs.write`. Both are granted by the runner, scoped to a
directory; the program does no path building of its own, so it can only touch
`tasks.json` in the working directory.

The boundary is the runtime's, not this program's: `fs.*` resolves symlinks with
`realpath` and refuses paths outside the granted root. Run it with
`--allow-fs-read . --allow-fs-write .` and it cannot reach `~/.ssh` even if the
store contents ask it to — the store holds data, never paths.

Titles are stored as JSON strings and printed with `sprint`; nothing is evaluated,
so a title containing shell syntax or JSON fragments is inert. `json.parse` on load
is the only parser, and a malformed document is rejected rather than trusted.

## 9. Dependencies and external integrations

| Dependency | Kind | Notes |
|---|---|---|
| `fs` | Silica stdlib | `exists`, `read_text`, `write_text` |
| `json` | Silica stdlib | `parse`, `stringify(tasks, 2)` |
| `time` | Silica stdlib | `now()` for `created` |
| `string` | Silica stdlib | `trim`, `split`, `replace`, `starts_with` |

No third-party packages, no network, no subprocess.

## 10. Testing strategy and acceptance criteria

`tests/test_apps.py` runs the program with piped stdin **and** asserts on
`tasks.json` afterwards, so persistence is verified rather than assumed.

Acceptance criteria:

1. `add` creates a task with id 1 and prints `added #1: <title>`.
2. A second `add` gets id 2; ids never repeat after a removal.
3. `list` shows `[ ]` for open and `[x]` for done tasks.
4. `done 1` flips the flag and the change is on disk after the program exits.
5. `remove 1` deletes the task and the store no longer contains it.
6. `tasks.json` is valid JSON with the four keys per task after every run.
7. A corrupted store produces a warning and the program still starts.
8. A non-numeric id prints a message and does not crash.
9. Running with no capability flags fails with a capability error, not a traceback.
10. `quit` exits with status 0.

## 11. Implementation phases

1. `is_digits` and `words` — the parsing primitives both the store and the loop need.
2. `load`/`save` with repair — persistence first, so every later step can be tested
   against a real file.
3. `next_id`, `find`, `show` — read-only views over the list.
4. `with_done`, `without` — the pure transformations that stand in for mutation.
5. `main` — the command loop wiring the verbs to those functions.
6. Tests that inspect the store, plus the skip-list entry in
   `tests/test_optimizer.py`.

## Deviations from the original implementation

Two defects were found by the tests and fixed during implementation:

- **Column padding in `show`**: the marker and id were concatenated without spacing,
  so `[ ]#1` printed instead of `[ ] #1`.
- **Non-map entries in the store**: `load` accepted any JSON array, so an entry that
  was a bare string reached `task["id"]` and failed. It now validates each entry and
  falls back to an empty list with a warning.

## Limitations

- No in-place mutation: every edit rebuilds the list, which is fine at this size and
  honest about the language.
- Single store file, single process; no locking, so two concurrent runs would race.
- Titles cannot be edited — remove and re-add.
