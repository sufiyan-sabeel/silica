# Float constants are keyed by bit pattern, so -0.0 and 0.0 are distinct
# values with distinct output. Regression guard for the constant-pool defect.
sfn main() {
    sprint(-0.0)
    sprint(0.0 - 0.0)
}
