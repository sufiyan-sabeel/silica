# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

Silica is pre-1.0; security fixes land on the current `0.1.x` line.

## Reporting a vulnerability

Report privately to the maintainer (see `LICENSE` for the copyright holder).
Please do not open a public issue for:

* a bytecode verifier bypass — any `.sbc` that executes despite failing the
  documented rules in `docs/BYTECODE.md`;
* a crash, hang or unbounded resource use caused by a hostile `.sc` or `.sbc`
  file;
* a way to read or write a file that the granted capabilities do not cover —
  escaping a root through `..`, a symlink, or an absolute path;
* any network, process, environment or arbitrary host-execution capability
  (none exists, so any path that provides one is a bug);
* a way for a program to grant itself a capability, or for a callee to end up
  with more authority than its caller.

Include the file, the command, and the observed behaviour. You will get an
acknowledgement, an assessment, and credit if you want it.

## Threat model in v0.8.0

A Silica program starts with **no capabilities**. It can compute, print and read
stdin. It cannot open a file until the host grants `fs.read`, `fs.write` or
`fs.list` for a specific root path.

The capability model, in the order the guarantees are enforced:

1. **Built before the VM starts.** The set comes from the command line or a TOML
   file. Nothing in Silica source can name, read or mutate it, so a program
   cannot escalate.
2. **Scoped to roots.** A grant is a capability plus a root path. A requested
   path is resolved (`realpath`, so symlinks and `..` are collapsed) and then
   tested for containment. A symlink inside a granted root that points outside
   it is refused, because resolution happens before the check.
3. **Checked at dispatch, not in the function.** Privileged natives declare
   `requires=<capability>` in the registry; the VM authorises at `CALL_NATIVE`
   before the body runs and hands the native the path that was authorised. A
   filesystem function therefore cannot be reached unguarded, and there is no
   second resolution step that could disagree with the check.
4. **Narrowing only.** `derive()` produces a strictly smaller set and refuses to
   add a root, add an ungarnted capability, or revive a denied one. Deny always
   beats grant.

What is still true and still matters:

* **The verifier.** Untrusted bytecode must be rejected before execution:
  opcode and operand bounds, jump targets, call arities, native existence,
  stack discipline and resource limits. Deliberately corrupted chunks are in
  the test suite.
* **Resource limits.** Constant/function counts, code size, locals, stack depth
  and call frames are bounded.
* **The engine process.** The reference engine is Python code, not an OS
  sandbox. A granted `fs.write` root is enforced by path checking, not by an
  operating-system jail: if the process can write the path, so can a program
  that was granted it. Do not grant a root you would not hand to the program
  directly.

## What is explicitly out of scope

* Denial of service through a legitimately large but well-formed program.
* Bugs in Python itself or in the host interpreter.
* A program doing something unpleasant *within* a capability it was granted —
  for example writing garbage into a directory you allowed it to write. Grant
  the narrowest root that works.
