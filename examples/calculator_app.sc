use string

sfn is_digits(s: String) -> Bool {
    si len(s) == 0 {
        ret nein
    }
    per ch in s {
        si ch < "0" {
            ret nein
        }
        si ch > "9" {
            ret nein
        }
    }
    ret oui
}

sfn is_number(s: String) -> Bool {
    let body: String = s
    si string.starts_with(body, "-") {
        body = string.replace(body, "-", "")
    }
    si len(body) == 0 {
        ret nein
    }
    let parts: List = string.split(body, ".")
    si len(parts) == 1 {
        ret is_digits(parts[0])
    }
    si len(parts) != 2 {
        ret nein
    }
    si len(parts[0]) == 0 {
        ret nein
    }
    ret is_digits(parts[0]) und is_digits(parts[1])
}

sfn words(line: String) -> List {
    let out: List = []
    per part in string.split(line, " ") {
        si len(part) > 0 {
            push(out, part)
        }
    }
    ret out
}

sfn apply(left: Float, op: String, right: Float) -> Bool {
    si op == "+" {
        sprint(left + right)
        ret oui
    }
    si op == "-" {
        sprint(left - right)
        ret oui
    }
    si op == "*" {
        sprint(left * right)
        ret oui
    }
    si op == "/" {
        si right == 0.0 {
            sprint("error: cannot divide by zero")
            ret nein
        }
        sprint(left / right)
        ret oui
    }
    sprint("error: unknown operator '" + op + "' (use + - * /)")
    ret nein
}

sfn main() {
    sprint("Silica calculator")
    sprint("type an expression such as '12 * 4', or 'quit' to leave")
    let running: Bool = oui
    tant running {
        let line: String = string.trim(input("calc> "))
        si line == "quit" {
            sprint("bye")
            running = nein
        } sino {
            si len(line) == 0 {
                sprint("error: empty input")
            } sino {
                let parts: List = words(line)
                si len(parts) != 3 {
                    sprint("error: expected three parts, like '12 * 4'")
                } sino {
                    si is_number(parts[0]) == nein {
                        sprint("error: '" + parts[0] + "' is not a number")
                    } sino {
                        si is_number(parts[2]) == nein {
                            sprint("error: '" + parts[2] + "' is not a number")
                        } sino {
                            let left: Float = float(parts[0])
                            let right: Float = float(parts[2])
                            let ok: Bool = apply(left, parts[1], right)
                        }
                    }
                }
            }
        }
    }
}
