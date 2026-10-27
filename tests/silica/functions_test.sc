sfn add(a: Int, b: Int) -> Int {
    ret a + b
}

sfn fib(n: Int) -> Int {
    si n < 2 {
        ret n
    }
    ret fib(n - 1) + fib(n - 2)
}

sfn greet(name: String) {
    sprint("hello " + name)
}

sfn main() {
    assert(add(2, 3) == 5)
    assert(fib(10) == 55)
    greet("silica")
    assert(type_of(add(0, 0)) == "Int")
    sprint("functions ok")
}
