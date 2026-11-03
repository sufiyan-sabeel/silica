# Silica — R1 Environment Handoff

**Status:** phase closed — waiting for confirmation of a Rust-capable machine
**Document version:** 1.0 · 2026-11-03
**Scope:** what is frozen on `main`, what the build machine must provide, and the exact
commands to prove it. No Rust code has been written.

---

## 1. What is on `main`, and stays there

| Artefact | Path | State |
|---|---|---|
| Benchmark report | `docs/design/SILICA_R1_BENCHMARK_READINESS.md` | approved, frozen |
| Gate harness | `benchmarks/gate.py` | approved, frozen |
| Gate benchmark source | `benchmarks/silica/gate_bench.sc` | frozen — prints `1499997500000` |
| Implementation readiness | `docs/design/SILICA_R1_IMPLEMENTATION_READINESS.md` | decisions recorded |
| Parity contract | `tests/parity/` (29 files, 14 cases) + `tests/test_parity_contract.py` | frozen, no xfail cases |
| NOP regression | `tests/test_nop.py` | merged (PR #8) |
| Reference VM | `silica/` | unchanged since PR #8; 1,364 tests green on the stabilization branch (1,352 on `main`, one stale-skip-list failure — see the readiness report §2.8) |

The harness is only reproducible because its program is committed: the `.sbc` is
produced from `benchmarks/silica/gate_bench.sc` by the Python compiler, never
hand-edited, and the pinned stdout hash proves the run is the right run.

---

## 2. M1 toolchain requirements

M1 is **pure `std` Rust with zero crate dependencies**, so it builds fully offline.
That is deliberate: it removes crates.io, vendoring and lockfile questions from the
first gate.

| Requirement | Detail |
|---|---|
| `rustc` + `cargo` | stable channel, **≥ 1.85**. M1's own code would build on 1.70, but the workspace pins one MSRV and M2's PyO3 requires 1.85 — meet 1.85 once |
| Linker | `cc` or `gcc` present — the `x86_64-unknown-linux-gnu` target links through it |
| Host target installed | `rustup target list --installed` shows the host triple |
| Crate registry | **not needed for M1** (no dependencies) |
| Python | 3.9+ to run the reference side of the gate and compile the `.sbc` |

**The floor rises at M2.** PyO3 0.30.1 requires **Rust ≥ 1.85**, so the workspace MSRV
should be set to 1.85 from the start even though M1 alone needs less — otherwise M2
forces a toolchain upgrade mid-spike.

---

## 3. M2 requirements — Python headers and PyO3

| Requirement | Detail |
|---|---|
| PyO3 | 0.30.x (current: 0.30.1), feature `abi3-py39` |
| Rust | **≥ 1.85** (PyO3's MSRV, not ours) |
| CPython | **≥ 3.9** — matches Silica's declared floor; `abi3-py39` produces one wheel per OS/arch for every Python ≥ 3.9 |
| Python headers | `Python.h` for the build interpreter: `python3-dev` (Debian/Ubuntu), `python3-devel` (Fedora/RHEL), included in the official Windows installer, `xcode-select --install` + a framework build on macOS |
| C toolchain | a compiler **and** linker — PyO3 builds C glue and links against libpython |
| Wheel builder | `maturin` (current release) for `abi3` wheels; `setuptools-rust` is the alternative |
| Interpreter selection | `PYO3_PYTHON=/path/to/python3` when several are installed |

`abi3` note: the plain `abi3` feature needs a host interpreter present and cannot
cross-compile; `abi3-py39` can be used without one, which is what makes
cross-compiled wheels possible later.

---

## 4. Exact commands to run on the build machine

### 4.1 Prove the toolchain works

```bash
rustc --version            # expect >= 1.85 (the workspace MSRV)
cargo --version
rustup target list --installed
cc --version || gcc --version
python3 --version          # expect >= 3.9
```

A version is not proof that linking works, so build something and run it:

```bash
cd "$(mktemp -d)" && cargo new --quiet linkcheck && cd linkcheck
cargo run --quiet          # must print: Hello, world!
```

If that prints, the toolchain can compile **and link** — which is the property the
gate depends on. If it fails at the link step, the toolchain is incomplete and M1
cannot start.

### 4.2 Run the reference side of the gate

From the repository root, with the Python VM installed (`pip install -e .` or on
`PYTHONPATH`):

```bash
mkdir -p build
python3 -m silica compile benchmarks/silica/gate_bench.sc -o build/gate_bench.sbc
python3 benchmarks/gate.py --sbc build/gate_bench.sbc
```

Expected: `stdout_matches_reference True`, `stdout_sha256` beginning `2c20dd17`,
`exit 0`, and a median around 7.1–7.3 s on x86_64 (the exact value is machine-specific
and is recomputed at run time — never hardcoded).

Note: `silica compile` has no `--help`; its usage is
`silica compile <file.sc> [-o out.sbc]`.

### 4.3 Run the gate once the Rust VM exists

```bash
cargo build --release
python3 benchmarks/gate.py --sbc build/gate_bench.sbc \
    --compare target/release/silica --json
```

Pass condition: `"passes_gate": true`, i.e. the interleaved ratio is **≥ 3.0**, with
`stdout_matches_reference` true.

---

## 5. Android/Termux versus a full build environment

| Work | Termux (ARM64 Android) | Linux / macOS / Windows |
|---|---|---|
| Python side: gate harness, parity corpus, docs | **yes** — ordinary Python 3 | yes |
| M1 Rust source (pure `std`, no deps) | **possible but unverified** — Termux ships `rust` targeting `aarch64-linux-android`; whether its version and linker are sufficient is untested | yes |
| M1 gate measurement | **valid only if both VMs run on the same device** — the harness compares them in one session, so an ARM reference against an ARM Rust run is a fair ratio; an ARM reference against an x86 Rust run is not | yes, preferred |
| M2 / PyO3 | **do not plan on it** — needs CPython headers for the Android ABI plus the NDK; unverified and fragile | yes |
| `abi3` wheels for distribution | no | **yes** — one build per OS/arch |
| Windows build | no | **yes** — needs the MSVC build tools, not just rustup |
| macOS build (x86_64 + arm64 or universal2) | no | **yes** — needs Xcode CLT |

**Practical split:** develop and review M1 anywhere, including Termux, but measure the
gate on one machine with both VMs present, and build M2 and any wheels on a desktop OS.
The Android "no Python on the device" story does not exist at M2 either — PyO3 embeds
CPython — so Android is not a target for this spike.

---

## 6. Frozen, and not to be changed

| Contract | Where | Rule |
|---|---|---|
| Gate | §3 of the benchmark report | ≥3× execution-only, interleaved, median of 5 after 1 warm-up, target derived at run time |
| Benchmark program and output | `benchmarks/silica/gate_bench.sc` | `1499997500000\n`, SHA-256 `2c20dd17…` |
| Parity corpus | `tests/parity/` | 14 cases, stdout/stderr/exit-code exact, no xfail |
| `.sbc` format | `silica/bytecode.py` | magic `SILICABC`, format 1.0, 17-byte header |
| Opcode contract | `OPS` | 43 opcodes, all implemented (NOP since PR #8) |
| Default VM | `silica/cli.py` | stays Python; Rust is opt-in |

Nothing in this handoff changes the Python reference VM, the default VM, or `.sbc`.

---

## 7. Waiting for

Confirmation that a machine has a working Rust toolchain (§4.1 prints
`Hello, world!` from `cargo run`), and the recorded output of those commands. On
receipt, M1 begins as specified in §14 of the implementation-readiness document. No
M2, no R2, and no changes to the reference VM until then.
