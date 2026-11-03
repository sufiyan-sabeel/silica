# Float division by zero is a runtime error, not inf.
sfn main() {
    let a: Float = 1.0
    let b: Float = 0.0
    sprint(a / b)
}
