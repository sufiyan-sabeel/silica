sfn sign(n: Int) -> String {
    si n > 0 {
        ret "positive"
    } sino {
        si n < 0 {
            ret "negative"
        }
    }
    ret "zero"
}

sfn main() {
    assert(sign(5) == "positive")
    assert(sign(-5) == "negative")
    assert(sign(0) == "zero")
    let total: Int = 0
    per i in range(1, 5) {
        total = total + i
    }
    assert(total == 10)
    let countdown: Int = 3
    let seen: Int = 0
    tant countdown > 0 {
        seen = seen + 1
        countdown = countdown - 1
    }
    assert(seen == 3)
    let letters: String = ""
    per ch in "abc" {
        letters = letters + ch
    }
    assert(letters == "abc")
    let sum: Int = 0
    per key in {"x": 1, "y": 2} {
        sum = sum + 1
    }
    assert(sum == 2)
    assert((oui und nein) == nein)
    assert((oui ou nein) == oui)
    assert(non nein == oui)
    sprint("control flow ok")
}
