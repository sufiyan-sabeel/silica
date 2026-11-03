# Int is signed 64-bit and wraps on overflow.
sfn main() {
    let max: Int = 9223372036854775807
    sprint(max + 1)
    sprint(max * 2)
}
