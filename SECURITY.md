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
* a way to read or write files, network, or environment variables from a Silica
  program (v0.1.0 exposes no such capability, so any path that does is a bug).

Include the file, the command, and the observed behaviour. You will get an
acknowledgement, an assessment, and credit if you want it.

## Threat model in v0.1.0

Silica programs can read stdin and write stdout/stderr. They cannot touch the
filesystem, the network, the environment, or other processes. That means the
interesting attack surface is:

1. **The verifier.** Untrusted bytecode must be rejected before execution:
   opcode and operand bounds, jump targets, call arities, native existence,
   stack discipline and resource limits are all checked. The test suite includes
   deliberately corrupted and hand-crafted invalid chunks.
2. **Resource limits.** Constant/function counts, code size, locals, stack depth
   and call frames are bounded, so a hostile file cannot allocate without limit
   inside the engine's own structures.
3. **The engine process.** The reference engine is Python code, not a sandbox.
   Running an untrusted Silica program is as safe as running a Python program in
   the same process — which is to say, only run code you trust until a sandboxed
   host exists.

## What is explicitly out of scope

* Denial of service through a legitimately large but well-formed program.
* Bugs in Python itself or in the host interpreter.
