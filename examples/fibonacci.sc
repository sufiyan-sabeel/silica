sfn fib(n: Int) -> Int {
    si n < 2 {
        ret n
    }
    ret fib(n - 1) + fib(n - 2)
}

sfn main() {
    per i in range(0, 11) {
        dit(fib(i))
        dit(" ")
    }
    sprint("")
}
