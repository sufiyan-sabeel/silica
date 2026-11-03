sfn main() {
    let total: Int = 0
    let i: Int = 0
    tant i < 1000000 {
        total = total + i * 3 - 1
        i = i + 1
    }
    sprint(total)
}
