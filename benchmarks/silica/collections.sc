use collections

sfn main() {
    let xs: List = []
    let i: Int = 0
    tant i < 200000 {
        push(xs, i)
        i = i + 1
    }
    let total: Int = 0
    per x in xs {
        total = total + x
    }
    sprint(total)
    sprint(len(collections.sort(collections.reverse(xs))))
}
