sfn main() {
    per n in range(1, 20) {
        si n * n > 50 {
            sprint(n)
            break
        }
    }
    let total: Int = 0
    per n in range(1, 10) {
        si n % 2 == 0 {
            continue
        }
        total = total + n
    }
    sprint(total)
    per row in range(1, 4) {
        per col in range(1, 4) {
            si col == 2 {
                break
            }
            dit(row * 10 + col)
            dit(" ")
        }
    }
    sprint("")
}
