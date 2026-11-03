# The R1 dispatch gate benchmark. Prints exactly one line: 1499997500000
#
# Verified three ways: closed form 3*n*(n-1)/2 - n with n = 1000000, an
# independent loop, and this VM. Uses 12 opcodes, all inside the 30-opcode M1
# set, and calls no native -- so a Rust VM can run it with no Python involved.
#
# Measured by benchmarks/gate.py; see docs/design/SILICA_R1_BENCHMARK_READINESS.md.
sfn main() {
    let total: Int = 0
    let i: Int = 0
    tant i < 1000000 {
        total = total + i * 3 - 1
        i = i + 1
    }
    sprint(total)
}
