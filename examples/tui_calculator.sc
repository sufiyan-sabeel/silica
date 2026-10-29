use tui

use tui.lib.widgets

use tui.lib.layout

use tui.lib.style

use string

sfn compute(left: String, right: String, op: String) -> String {
    let a: Float = float(left)
    let b: Float = float(right)
    si op == "ADD" {
        ret str(a + b)
    }
    si op == "SUBTRACT" {
        ret str(a - b)
    }
    si op == "MULTIPLY" {
        ret str(a * b)
    }
    si op == "DIVIDE" {
        si b == 0.0 {
            ret "cannot divide by zero"
        }
        ret str(a / b)
    }
    ret "unknown operation"
}

sfn is_number(text: String) -> Bool {
    let trimmed: String = string.trim(text)
    si len(trimmed) == 0 {
        ret nein
    }
    let dot: Bool = string.contains(trimmed, ".")
    let digits: Int = len(string.replace(string.replace(trimmed, ".", ""), "-", ""))
    si digits == 0 {
        ret nein
    }
    si string.contains(trimmed, " ") {
        ret nein
    }
    ret oui
}

sfn main() {
    let app = tui.app("Silica Calculator")
    tui.theme(app, {"accent": "#45C6B0", "error": "#F87171"})
    let title = tui.panel("Calculator")
    tui.add(title, tui.text("Tab or arrows move focus. Type to edit. Enter runs."))
    let inputs = tui.row()
    let left = tui.field("0")
    let right = tui.field("0")
    tui.add(inputs, left)
    tui.add(inputs, right)
    let operations = tui.row()
    let add = tui.button("ADD")
    let sub = tui.button("SUBTRACT")
    let mul = tui.button("MULTIPLY")
    let div = tui.button("DIVIDE")
    tui.add(operations, add)
    tui.add(operations, sub)
    tui.add(operations, mul)
    tui.add(operations, div)
    let result_panel = tui.panel("Result")
    let result = tui.text("press Enter to calculate")
    tui.add(result_panel, result)
    tui.add(app, title)
    tui.add(app, inputs)
    tui.add(app, operations)
    tui.add(app, result_panel)
    tui.add(app, tui.text("q quits, Escape clears"))
    tui.set_text(left, "12")
    tui.set_text(right, "4")
    tant oui {
        let key = tui.poll(app)
        si key == "q" {
            tui.close(app)
            halt
        }
        si key == "enter" {
            let chosen: String = tui.pressed(app)
            si len(chosen) > 0 {
                let a: String = tui.value(left)
                let b: String = tui.value(right)
                si non is_number(a) {
                    tui.set_text(result, "first value is not a number")
                } sino {
                    si non is_number(b) {
                        tui.set_text(result, "second value is not a number")
                    } sino {
                        tui.set_text(result, compute(a, b, chosen))
                    }
                }
            }
        }
        si key == "escape" {
            tui.set_text(left, "")
            tui.set_text(right, "")
            tui.set_text(result, "cleared")
        }
    }
}
