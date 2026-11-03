# Maps preserve insertion order in printing, keys() and iteration.
sfn main() {
    let m: Map = {"zebra": 1, "apple": 2, "mango": 3}
    sprint(m)
    sprint(keys(m))
    per k in m {
        dit(k)
        dit(" ")
    }
    sprint("")
}
