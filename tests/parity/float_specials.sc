# inf and NaN are reachable only through float(String); arithmetic never produces them.
sfn main() {
    sprint(float("inf"))
    sprint(float("-inf"))
    sprint(float("nan"))
    let i: Float = float("inf")
    sprint(i + 1.0)
    sprint(i - i)
}
