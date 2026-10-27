# Bootstrapping and Self-Hosting Plan

**Silica is not self-hosted.** The compiler in this repository is a Python
reference implementation. Nothing in this document is implemented; it is the
staged plan, and it says what "done" would have to mean before anyone may claim
self-hosting.

## Why a reference implementation first

The point of the first implementation is to pin down semantics: grammar, type
rules, bytecode format, runtime behaviour and error messages. Those are now
fixed and tested (227 tests, `docs/BYTECODE.md` version 1.0). A compiler written
in Silica can be judged against this implementation by running the same test
suite and comparing outputs.

## Stages

1. **Bootstrap in a host language.** *Done in Python; the plan's destination is
   Rust.* Same architecture: lexer → parser → checker → bytecode compiler →
   verifier → VM.
2. **Freeze the interfaces.** Grammar, type rules, runtime interfaces and the
   `.sbc` format must be stable enough that a second implementation can target
   them. Status: `.sbc` v1.0 is specified and verified; the language is still
   `0.x`.
3. **Write the lexer and parser in Silica** (`.sc` sources under a future
   `selfhost/` directory). Requirement: the language needs the features a
   compiler front end needs — at minimum enums/pattern matching, records, and
   first-class functions for clean AST handling. These do not exist yet, so this
   stage cannot start in earnest.
4. **Write semantic analysis and the bytecode compiler in Silica.** Same
   requirement, plus string building at scale and file I/O (`fs` module).
5. **Compile the Silica compiler with the bootstrap compiler.** The host
   implementation emits `.sbc` for the self-hosted compiler.
6. **Rebuild with the self-hosted compiler** and compare the produced `.sbc` with
   the bootstrap output. Identical bytes (or documented, justified differences)
   are the bar.
7. **Conformance suite.** The existing test suite becomes the conformance suite:
   every `.sc` test and every example must produce identical output under both
   compilers, and both must reject the same malformed programs with equivalent
   diagnostics.

## Honest status

| Stage | Status |
|---|---|
| 1. Bootstrap implementation | done (Python reference engine) |
| 2. Stable interfaces | partial — bytecode v1.0 fixed, language `0.x` |
| 3. Lexer/parser in Silica | not started; blocked on language features |
| 4. Checker/compiler in Silica | not started; blocked on language features |
| 5. Bootstrap-compile the Silica compiler | not started |
| 6. Self-rebuild and byte comparison | not started |
| 7. Conformance suite | the suite exists; cross-compiler comparison does not |

## Rules for claiming self-hosting

Do not write "Silica is self-hosted" until:

* the compiler source is Silica, compiled by a documented bootstrap chain, and
* the self-hosted compiler rebuilds itself and produces equivalent output, and
* the conformance suite passes under the self-hosted compiler, and
* the bootstrap compiler remains available and documented as the recovery path.

Until then the accurate statement is: *Silica has a working reference compiler
written in Python, with a bytecode format designed to be re-implementable.*
