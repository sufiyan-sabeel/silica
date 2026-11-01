# Interoperability architecture

How Silica will call into other ecosystems — Python, C and C++, Rust,
JavaScript, the JVM, WebAssembly/WASI, and external worker processes — through one
Silica-facing shape, without weakening the security model the VM already has.

Companion to `docs/INTEROPERABILITY_AUDIT.md`, which records what the current
implementation does. This document is the design; §14 states exactly which part of
it exists today.

**Design constraints inherited from the audit** (see its §9): the native registry
is immutable at runtime (F1), `CALL_NATIVE` is verified against that registry (F2),
`authorize_call` in the VM is the single authorization point (F3), capability kinds
are a closed set (F4), there is no foreign value type (F5), and the bytecode format
is 1.0 with no demonstrated need to change (F9).

---

## 1. Principles

1. **One Silica-facing shape.** A Silica program must not be able to tell whether
   a call went to Python, a C library, a worker or WASM. Ecosystem differences
   live below the provider interface.
2. **Deny by default.** Nothing is callable, no provider is loaded, and no
   capability is held unless it was explicitly granted.
3. **One authorization point.** Every privileged external operation is authorised
   by the same function that authorises natives today
   (`CapabilitySet.authorize_call`). Providers never check capabilities
   themselves and never receive an already-resolved path they could re-interpret.
4. **No raw addresses.** Silica never sees a pointer, an address, a file
   descriptor or a native handle integer. It sees an opaque, typed, owned token.
5. **Explicit lifetime.** Every foreign resource has an owner, a release path and
   a defined behaviour after release.
6. **Nothing is claimed that is not tested.** Each layer states its evidence.

---

## 2. Common foreign value representation

A single `ForeignValue` crosses every boundary. It is a tagged union, not a
wrapper around arbitrary Python objects, so a provider cannot smuggle an
arbitrary object into the VM.

| Tag | Payload | Silica type | Notes |
|---|---|---|---|
| `NONE` | — | `Unit` | |
| `BOOL` | `bool` | `Bool` | |
| `INT` | 64-bit signed | `Int` | Out of range is an error, never a wrap |
| `FLOAT` | 64-bit IEEE-754 | `Float` | NaN/Inf allowed; documented per provider |
| `STRING` | UTF-8 `str` | `String` | Invalid UTF-8 from a foreign side is an error |
| `BYTES` | `bytes` | *new* | Only via an explicit conversion; not a Silica type today |
| `LIST` | `list[ForeignValue]` | `List` | Homogeneous by construction where the signature says so |
| `MAP` | `dict[str, ForeignValue]` | `Map` | Keys are strings only, matching Silica's `Map` |
| `HANDLE` | `ForeignHandle` | opaque | §3 |
| `ERROR` | `InteropError` | — | Never a value; see §5 |

Rules:

- **Conversion is explicit and total.** `to_foreign(value)` and
  `from_foreign(fv, expected_type)` either succeed or raise a structured error.
  No implicit coercion, no "best effort" mapping.
- **Depth and size are bounded** on both conversion directions (§9).
- **No cycles.** A `LIST`/`MAP` that would contain itself is rejected at
  conversion, not at use.
- **`BYTES` is deliberately not a Silica type.** Introducing one is a language
  change and is out of scope; the tag exists so a provider can hand bytes to a
  future conversion layer without a format change here.

---

## 3. Opaque handles and lifecycle

A foreign object that cannot be copied by value (a file object, a JDBC
connection, a JS object, a Rust `Box<T>`) is represented by a handle.

```text
ForeignHandle
  id           opaque token, unique within a session   (never an address)
  provider     the provider that created it
  kind         a provider-declared type name, e.g. "java.sql.Connection"
  generation   incremented on release; a stale token is refused
  released     bool
```

Lifecycle:

| Event | Behaviour |
|---|---|
| Create | Only inside a provider invocation; the registry records the owning session |
| Use | `HandleRegistry.use(token, provider, session)` validates ownership, generation and liveness **before** the provider sees it |
| Release | `HandleRegistry.release(token)` marks it released, increments the generation, and calls the provider's `release` exactly once |
| Use after release | Structured `InteropError` with code `handle.released` — never a crash, never a silent null |
| Wrong owner | `handle.owner` error: a handle from another provider or session cannot be used |
| Session end | All handles for that session are released; a provider that fails to release is reported, not ignored |
| Program exit | The runtime closes every provider, releasing remaining handles; leaks are reported in the closing summary |

The token is a random 128-bit value, not a table index, so it leaks no
information and cannot be guessed into another session.

---

## 4. Provider interface and registration

A provider is one object with a narrow contract:

```python
class Provider:                       # silica/interop/provider.py
    name: str                         # unique, e.g. "python"
    version: str                      # provider's own version
    abi: int                          # interface version it implements
    capabilities: tuple[str, ...]     # kinds it needs, from the known set

    def operations(self) -> dict[str, Signature]      # metadata, no execution
    def invoke(self, operation, args, ctx) -> ForeignValue
    def release(self, handle, ctx) -> None
    def close(self) -> None
```

Rules:

- **Metadata before execution.** `operations()` is callable without starting
  anything, so the checker can type a call and the user can see what a provider
  offers.
- **Registration is explicit and separate.** `ProviderRegistry.register(provider)`
  refuses duplicate names, unknown capability kinds (F4) and an `abi` it does not
  implement. The registry is **not** `natives.MODULES` (F1): provider operations
  never appear in the standard-library namespace, and no provider can shadow or
  extend `core`, `fs`, `math` or any other module.
- **No implicit discovery.** Nothing is imported, scanned or started unless a host
  program registers it. There is no entry-point scan, no environment variable, no
  directory walk.
- **Deny by default.** A registered provider is inert until a capability it needs
  is granted *and* an invocation is authorised at the VM boundary (§7).

---

## 5. Module resolution and signature metadata

Provider operations are namespaced and typed like natives, but resolved from the
provider registry rather than the native registry:

```text
<provider>.<operation>          python.call
                                c.malloc
                                wasm.invoke
```

A `Signature` carries everything needed to type a call without running it:

| Field | Meaning |
|---|---|
| `name` | operation name within the provider |
| `params` | list of `(name, ForeignType)` |
| `ret` | `ForeignType` |
| `min_args`, `max_args` | arity, as natives do today |
| `errors` | the error codes the operation may raise |
| `blocking` | whether it may block (drives §9) |
| `releases` | whether it consumes the handle argument |

`ForeignType` is the tag set from §2 plus `HANDLE(kind)` and `ANY`.

**Conversion rules** are declared, not guessed: `from_foreign` is driven by the
declared parameter type, so a provider returning the wrong tag is an
`interop.conversion` error naming the operation and position — not a crash later.

**Structured errors.** Every interop failure is an `InteropError` with:

```text
code       stable machine-readable string   ("handle.released", "capability.denied")
provider   which provider
operation  which operation
message    one sentence, no host secrets
hint       optional, actionable
```

Codes are a closed, documented set. A message never contains a filesystem path the
program was not granted, an environment variable value, or a provider-internal
detail such as a stack trace or a native address (audit §7 shows why: the
existing speech path prints the resolved library path in diagnostics).

---

## 6. Worker protocol

For ecosystems that cannot be embedded (JS, JVM, a Python version the host cannot
load), the provider is a process.

- **Transport:** length-prefixed frames over stdin/stdout. A frame is
  `magic | version | kind | request-id | length | payload`, with a hard maximum
  (§9). Nothing else is written to those streams; diagnostics go to stderr.
- **Kinds:** `hello`, `describe`, `invoke`, `result`, `error`, `release`, `close`.
- **Handshake:** the host sends `hello` with its protocol version and the session
  id; the worker replies with its provider name, version, ABI and its operation
  list. A version mismatch closes the worker with `protocol.version`.
- **Correlation:** every request carries an id; a response with an unknown id is a
  protocol error, not a result for something else.
- **No ambient authority:** the worker inherits nothing but its own stdin/stdout/
  stderr. It is started with an explicit argument vector, no shell, and a working
  directory chosen by the host.
- **Backpressure:** at most one in-flight request per worker in the first version.
- **Death:** a worker that exits, hangs past its deadline, or writes a malformed
  frame is killed and every handle it owned is released; the failure surfaces as
  `interop.worker_lost`.

The existing speech code (subprocess with a 300 s timeout, audit §7) is the
precedent for *starting* a process, not for the protocol: it has no framing, no
correlation and no handshake, and it must not be treated as a template.

---

## 7. Runtime lifecycle

```text
host program
  ├── creates a CapabilitySet (unchanged; docs/LANGUAGE_SPEC.md)
  ├── registers providers explicitly          registry.register(...)
  ├── opens a session                         session = registry.open_session()
  │     ├── provider.start() if it needs starting
  │     └── handles are owned by this session
  ├── runs Silica chunks, or calls provider operations through the host API
  │     └── every privileged call passes authorize_call  ◄── the one gate
  └── session.close()
        ├── every handle released (or reported)
        ├── provider.close() / worker terminated
        └── leaks reported in the closing summary
```

**Where the gate sits.** Today the VM authorises natives at
`silica/vm.py:293` before calling `native.fn`. Interop keeps exactly one such
point: a provider operation is authorised by the same
`CapabilitySet.authorize_call` call, with a synthetic record carrying
`requires` (the provider capability) and `path_arg` where applicable. A provider
therefore cannot be invoked through a path that skips the gate, and adding a
provider does not add a second place to audit.

**Ordering guarantees.** Registration before use; `describe` before the first
`invoke`; release before close; no invocation after close. Violations raise, they
do not warn.

---

## 8. Capability model

- **Kinds.** The existing 8 kinds stay as they are. A provider declares the kinds
  it needs; in the first version those are existing kinds only (for example a
  provider that reads files needs `fs.read`). New kinds (`interop.python`,
  `interop.worker`, …) are an **explicit decision** requiring an entry in
  `KNOWN` in `silica/capabilities.py` — the registry refuses unknown kinds rather
  than inventing one (F4).
- **Granularity.** A grant is per kind and, for the filesystem kinds, per
  directory root — the same model as today.
- **Who holds it.** The host, never the provider and never the Silica program. A
  provider receives only the arguments it was authorised to receive.
- **Path arguments.** Where an operation takes a path, the provider declares
  `path_arg`; the authorisation step resolves it against the granted root and
  substitutes the resolved path, exactly as `authorize_call` does today. The
  provider never resolves a path itself.
- **Refusal is total.** A denied call performs no I/O, starts no worker, loads no
  library, and allocates no handle.

---

## 9. Timeout and resource limits

| Limit | Scope | Default |
|---|---|---|
| Deadline | per invocation, carried in `ctx.deadline` | set by the host; no invocation runs unbounded |
| Message size | per frame, both directions | 1 MiB, configurable down |
| Result size | per invocation | 16 MiB |
| Handle count | per session | 1024 |
| Worker memory | advisory, enforced by the host process limit | provider-specific |
| Blocking | `Signature.blocking` decides whether a call may run on the main thread | non-blocking default |

A call that exceeds its deadline is aborted and reported as
`interop.timeout`, with the handle state left consistent (the operation is
treated as failed, not partially applied; providers that cannot guarantee this
must declare `blocking` and are refused a deadline shorter than their declared
minimum).

---

## 10. Package and environment isolation

- A provider declares the ecosystem package it depends on (`onnxruntime`,
  `libfoo.so.3`, `node`, `java`), and the host checks availability **before**
  registration completes, so a missing dependency is a startup error rather than a
  runtime surprise.
- **Library loading is allowlisted** (§11). A provider may load only the exact
  libraries it declared, by name and version, from a directory the host allows —
  stricter than the current `espeak.py` behaviour, which globs system paths.
- A worker runs in its own working directory, with its own environment, and with
  no inherited handles beyond its standard streams.
- Nothing in this layer reads or writes the Silica project's own files unless the
  `fs.*` capabilities were granted for those paths.

---

## 11. C ABI ownership and versioning

For C, C++, Rust and anything else exposing a stable ABI:

- **Silica owns the calling convention.** The boundary is a small C ABI defined by
  Silica (`silica_interop_*`), not each library's native API. A provider adapts
  the library to that ABI; the VM never calls an arbitrary symbol.
- **Explicit allowlist.** The host passes a list of permitted libraries and
  symbols; anything else is refused before `dlopen`/`CDLL`. No globbing, no
  `find_library` fallback in the provider path.
- **Ownership is declared, not inferred.** Each parameter and return value states
  who frees it: caller, callee, or a handle. A value whose ownership is not
  declared is refused at registration.
- **No pointers in Silica.** A pointer becomes a `HANDLE` with a kind, or it does
  not cross the boundary. There is no `Any`-typed pointer and no arithmetic.
- **Versioning.** The ABI carries a major/minor version; the host refuses a major
  mismatch and accepts a higher minor, ignoring operations it does not know.
  Every symbol is versioned or length-prefixed so an older library cannot be
  misread by a newer host.
- **Unwind and longjmp are forbidden** across the boundary; a provider must
  convert failure into an `InteropError` code.

---

## 12. WebAssembly / WASI strategy

- The VM is written in Python, so "Silica in the browser" means a WASM build of
  the *host*, which is a separate project (noted in `docs/ROADMAP.md`).
- For **calling** WASM, a WASI provider runs a module in a sandboxed instance:
  linear memory only, no filesystem unless the instance is given a preopened
  directory mapped from a granted `fs.*` root, no network unless a future
  capability grants it.
- Values cross as `ForeignValue` serialised into linear memory with an explicit
  layout (little-endian, length-prefixed strings), never as host pointers.
- Fuel metering or an instruction budget enforces §9's deadline; a module that
  exhausts it is terminated, and its handles are released.
- A WASM provider must declare the imports it needs; an undeclared import fails at
  instantiation.

---

## 13. Compatibility and migration policy

- **The bytecode format does not change for this work** (F9). The foundation is
  Python-side. If a future phase needs a new opcode, it must demonstrate why a
  host-side call cannot do the job, and it must keep 1.0 files loadable.
- **No Silica syntax is added** in the foundation. There is no `use python`, no
  `foreign` block, and no new keyword. A program that compiled before compiles
  now, with identical behaviour — pinned by the existing suite.
- **The standard library is untouched.** No placeholder natives, no
  `interop`-named module in `MODULES`, no reserved keyword. Reserved *planned*
  module names keep failing loudly.
- **Additive only.** The interop package is importable from Python hosts; it adds
  no symbol to `silica.natives` and changes no existing signature.
- **Versioning of this interface.** `Provider.abi` starts at 1. A breaking change
  to the provider interface increments it; the registry refuses providers built
  against a major version it does not implement.
- **Migration.** When an ecosystem becomes usable, the change is a new provider
  plus (if needed) a new capability kind — both additive. Deprecation of a
  provider is its `close()` and removal from the registry; nothing in the language
  changes.

---

## 14. What exists today, and what does not

Implemented in this phase — `silica/interop/`, Python-side only, with fake-provider
tests:

| Piece | File |
|---|---|
| Foreign value tags and total conversion | `silica/interop/values.py` |
| Opaque handles, ownership, generation, release | `silica/interop/handles.py` |
| Provider interface and signature metadata | `silica/interop/provider.py` |
| Provider registry, separate from `natives.MODULES` | `silica/interop/registry.py` |
| Structured interop errors with a closed code set | `silica/interop/errors.py` |
| Invocation context: deadline, size bounds, capability check | `silica/interop/context.py` |

Deliberately **not** implemented, and not claimed:

| Not done | Why |
|---|---|
| Executing Python, C, Rust, JS, JVM or WASM | Out of scope for this phase |
| Starting any process or worker | Out of scope; §6 is the protocol to implement next |
| Loading any native library | §11 requires an allowlist that does not exist yet |
| New opcodes, new keywords, new stdlib natives | Compatibility policy, §13 |
| New capability kinds | Requires an explicit decision on the `KNOWN` tuple (F4) |
| Typing a provider call from Silica source | Needs `CALL_NATIVE` to reach a second registry (F2); blocked by design |

## 15. Unresolved decisions and risks

1. **How a provider call becomes reachable from Silica source.** Options: a
   dedicated opcode (format change, F2), a host-registered native shim per
   operation (keeps format 1.0, adds natives — conflicts with "no placeholder
   APIs"), or host-only invocation for now. **Recommendation:** host-only until a
   concrete need justifies one of the others.
2. **Capability granularity for interop.** One kind per provider, or per
   operation family? A single `interop.<provider>` kind is coarse but simple; the
   filesystem kinds show the scoped model works.
3. **Worker protocol stability.** Length-prefixed frames are easy to implement in
   five ecosystems, but a JS worker needs a stream adapter. Not yet proven.
4. **Async.** Silica has no async and no first-class functions, so a long call
   blocks the VM. A blocking provider plus a deadline is the honest first answer.
5. **Handle garbage collection.** Explicit release is specified; whether to add a
   best-effort collector for handles a program forgets is open. Explicit-only is
   predictable and testable, so it is the default.
6. **Termux/ARM64.** The `espeak` search paths exist for it, but nothing here has
   been run on Termux; no support is claimed.
7. **Performance.** Every crossing allocates and converts. Not measured, and not
   claimed to be cheap.
