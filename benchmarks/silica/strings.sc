use string

sfn main() {
    let parts: List = []
    let i: Int = 0
    tant i < 20000 {
        push(parts, "item")
        i = i + 1
    }
    let joined: String = string.join(parts, ",")
    let split: List = string.split(joined, ",")
    sprint(len(joined))
    sprint(len(split))
}
