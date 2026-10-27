sfn fib(n: Int) -> Int {
    si n < 2 {
        ret n
    }
    ret fib(n - 1) + fib(n - 2)
}

sfn main() {
    sprint(fib(24))
}
