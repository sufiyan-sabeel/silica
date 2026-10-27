sfn main() {
    let n: Int = 0
    let total: Int = 0
    tant n < 1000000 {
        total = total + n * 2 - 1
        n = n + 1
    }
    sprint(total)
}
