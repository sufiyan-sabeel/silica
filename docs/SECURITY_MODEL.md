# Security model

What Silica v0.10.0 actually enforces, what it merely documents, and what it does
not protect against. `SECURITY.md` covers how to report a vulnerability; this
document is the engineering description of the boundary.

Everything here was verified by a test in `tests/`, and the test is named.

---

## 1. The one authorization point

A Silica program starts with **no capabilities**. Every privileged operation —
filesystem, speech, TUI, GUI, and the Python worker — passes through a single
function in the VM:

```python
# silica/vm.py, CALL_NATIVE
if native.requires is not None:
    args = self.capabilities.authorize_call(native, args)
result = native.fn(ctx, args)
```

A native never re-checks, and never re-resolves a path it is handed. There is no
second place where privilege is decided, so there is no second place to audit.

* Evidence: `tests/test_capabilities.py::test_vm_denies_before_the_native_body_runs`
  (the native body is never reached when the grant is missing).

## 2. Before execution

| Check | Where | Evidence |
|---|---|---|
| Bytecode structure, operands, jump targets, stack discipline | verifier, on load | `tests/test_bytecode.py` |
| Unknown opcodes and bad constant types | verifier | `tests/test_bytecode.py` |
| Native existence and arity at load | verifier | `tests/test_bytecode.py` |
| Capability set built before the VM starts | `silica/capabilities.py` | `tests/test_capabilities.py` |
| Granted roots resolved with `realpath` | `_normalise_root` | `tests/test_capabilities.py` |
| Unknown capability kinds refused | `CapabilitySet.__init__`, provider registry | `tests/test_capabilities.py`, `tests/test_interop.py` |

A program cannot grant itself anything: the set is built outside it, and
`derive()` can only narrow.

## 3. During execution

### Filesystem boundary

`fs.*` declares `requires` (`fs.read` / `fs.write` / `fs.list`) and `path_arg`.
The VM authorises, resolves and **substitutes** the resolved path, and only then
calls the native.

The check is `os.path.realpath` on both the granted root and the requested path,
then a component-boundary prefix comparison. That means:

| Attempt | Result | Evidence |
|---|---|---|
| Read a file inside the granted root | allowed | `tests/test_capabilities.py` |
| `../outside/secret` | refused | `tests/test_capabilities.py` |
| Absolute path outside the root | refused | `tests/test_capabilities.py` |
| **Symlink to a file outside** | refused | `tests/test_capabilities.py::test_symlink_escape_is_refused` |
| **Symlinked directory pointing outside** | refused | same, plus the audit probe in `docs/INTEROPERABILITY_AUDIT.md` |
| Write outside the root | refused, and no file is created | `tests/test_capabilities.py`, `tests/test_apps.py` |

`path.is_within` (the standard-library helper) is **lexical** and is documented as
such: it does not resolve symlinks and is not a security boundary. The boundary is
the capability check above.

### Interoperability boundary

A provider runs foreign code, so its output is untrusted:

| Check | Rule |
|---|---|
| Message framing | magic, version, kind, length; a bad frame is `protocol.frame` |
| Version mismatch | `protocol.version`, worker stopped |
| Frame size | hard ceiling 8 MiB; `value.size` |
| Value types | JSON scalars, lists and dicts only; `value.type` |
| Integers | signed 64-bit; `value.range` |
| Floats | NaN and Infinity refused; `value.type` |
| Depth and item count | bounded; `value.depth`, `value.size` |
| Reserved keys | `__handle__`, `__bytes__`, `__error__` only in their defined shape |
| Handle id | non-negative integer, never a bool |
| Handle kind | short identifier, so a path or secret cannot ride in it |
| Error messages | coerced, newlines stripped, truncated to 500 characters |
| Deadline | enforced with `select`; a timed-out worker is **terminated**, not reused |
| Crash | `worker.lost`; the pipe is closed and the process reaped |
| Handles | 128-bit random tokens, provider and session ownership, generation counting, explicit release, leak report at shutdown |

Evidence: `tests/test_interop.py` (49 tests), `tests/test_interop_python.py`
(40 tests, including `AdversarialWorkerTests`, which points the provider at a
deliberately hostile worker in `tests/fixtures/evil_worker.py`).

### Randomness

`random.secure_bytes`, `random.secure_int` and `random.secure_token` use the
operating system's CSPRNG through Python's `secrets` module and are never seeded.
`random.float`, `int`, `choice`, `shuffle` and `seed` are a Mersenne Twister and
are documented as **not** suitable for secrets.

Evidence: `tests/test_stdlib_random.py::test_seeding_does_not_determine_secure_output`
(seeding the pseudorandom generator twice does not reproduce `secure_bytes`).

## 4. After execution

* A provider's `close()` returns `{worker_stopped, handles_leaked, python}`, so a
  leaked foreign handle is reported rather than forgotten.
  (`tests/test_interop_python.py::PostExecutionTests`)
* The registry's `close()` releases every handle for the session and closes every
  provider. (`tests/test_interop.py::ShutdownTests`)
* The applications verify their own outputs: the task manager reloads its store and
  the report checks its numbers before claiming success.
  (`tests/test_apps.py`)

## 5. What this does **not** protect against

Stated plainly, because a security document that only lists strengths is useless.

1. **The VM is not a sandbox.** It is Python code running in the user's process
   with the user's privileges. A capability check stops a *Silica program* from
   asking for a file; it does not stop a malicious *engine build*.
2. **The Python worker is not isolated.** It is a child process with the same
   privileges. It can do anything the Python process can do: read any file, open
   sockets, spawn processes. The `interop.python` capability gates *starting* it,
   not what it does. Treat it as running trusted code.
3. **A native library is loaded by path in the speech path.** `silica/voice/espeak.py`
   searches for `libespeak-ng` with `ctypes.util.find_library` and a set of glob
   patterns. The gate is the capability, not the library identity. The planned C
   ABI (`docs/INTEROPERABILITY.md` §11) requires an explicit allowlist; the speech
   path predates that and does not have one.
4. **No memory safety guarantees.** Values are Python objects; there is no unsafe
   code in the engine, and none of the guarantees that a Rust or C implementation
   would need to state.
5. **No resource isolation between programs.** One interpreter, one process: a
   program that loops forever or allocates without limit affects the host. The
   recursion depth is bounded by call frames (`max_frames`), and `time.sleep` is
   capped at one day, but there is no CPU or memory quota.
6. **`interop.python` grants foreign execution.** Granting it is a decision to run
   arbitrary Python. It does not grant filesystem, network or native access *by
   itself*, but the worker already has all of them.
7. **Nothing here has been tested on Termux or any platform other than
   Linux x86_64.** No platform-specific security claim is made.

## 6. Granting a capability

```bash
silica run --allow-fs-read ./data --allow-fs-write ./out program.sc
silica run --capabilities silica.toml program.sc     # [capabilities] table
silica run --deny-fs-write program.sc                # narrow a config file
silica capabilities                                  # print the effective set
```

Deny wins over a grant from a config file, so a caller can always narrow. Nothing
is granted by default, and a library import never grants anything.
