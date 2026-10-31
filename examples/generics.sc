struct Pair<K, V> {
    key: K
    value: V
}
class Bag<T> {
    items: List<T>
    sfn add(item: T) {
        push(self.items, item)
    }
    sfn count() -> Int {
        ret len(self.items)
    }
    sfn at(index: Int) -> T {
        ret self.items[index]
    }
}

sfn repeat<T>(value: T, times: Int) -> List<T> {
    let out: List<T> = []
    let i: Int = 0
    tant i < times {
        push(out, value)
        i = i + 1
    }
    ret out
}

sfn largest<T: Orderable>(items: List<T>) -> T {
    let best: T = items[0]
    per item in items {
        si item > best {
            best = item
        }
    }
    ret best
}

sfn main() {
    let words: Bag<String> = Bag([])
    words.add("alpha")
    words.add("beta")
    sprint(words.count())
    sprint(words.at(1))
    let numbers: List<Int> = repeat(7, 3)
    sprint(numbers)
    sprint(largest(numbers))
    sprint(largest(["pear", "apple"]))
    sprint(largest([2.5, 1.5, 9.0]))
    let pair: Pair<String, Int> = Pair("age", 42)
    sprint(pair.key)
    sprint(pair.value)
    let nested: List<Bag<Int>> = [Bag([1, 2]), Bag([3])]
    sprint(len(nested))
    sprint(nested[0].count())
}
