use collections

sfn main() {
    let xs: List = [3, 1, 2]
    assert(len(xs) == 3)
    assert(xs[0] == 3)
    assert(collections.sum(xs) == 6)
    assert(collections.sort(xs) == [1, 2, 3])
    assert(collections.reverse(xs) == [2, 1, 3])
    assert(collections.index_of(xs, 2) == 2)
    assert(collections.index_of(xs, 99) == -1)
    assert(has(xs, 1))
    assert(non has(xs, 99))
    let bag: List = []
    push(bag, 1)
    push(bag, 2)
    assert(len(bag) == 2)
    assert(bag == [1, 2])
    let m: Map = {"a": 1, "b": 2}
    assert(len(m) == 2)
    assert(m["a"] == 1)
    assert(has(m, "b"))
    assert(len(keys(m)) == 2)
    assert(len(values(m)) == 2)
    assert(type_of(m) == "Map")
    sprint("collections ok")
}
