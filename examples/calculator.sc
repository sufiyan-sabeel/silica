sfn apply(a: Float, b: Float, op: String) -> Float {
    si op == "+" {
        ret a + b
    }
    si op == "-" {
        ret a - b
    }
    si op == "*" {
        ret a * b
    }
    si op == "/" {
        si b == 0.0 {
            sprint("cannot divide by zero")
            ret 0.0
        }
        ret a / b
    }
    sprint("unknown operator: " + op)
    ret 0.0
}

sfn main() {
    dit("first number: ")
    let a: Float = float(input(""))
    dit("operator (+ - * /): ")
    let op: String = input("")
    dit("second number: ")
    let b: Float = float(input(""))
    sprint(apply(a, b, op))
}
