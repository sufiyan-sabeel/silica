use tui

use tui.lib.widgets

use tui.lib.layout

use tui.lib.style

sfn main() {
    let app = tui.app("Silica Terminal")
    let panel = tui.panel("Welcome to Silica")
    tui.add(panel, tui.heading("Silica TUI"))
    tui.add(panel, tui.text("Arrow keys move the focus. Enter and q are read by the program."))
    tui.add(app, panel)
    tui.add(app, tui.spacer(1))
    tui.add(app, tui.divider())
    tui.add(app, tui.button("Continue"))
    tui.add(app, tui.field("type here"))
    tui.add(app, tui.list(["alpha", "beta", "gamma"]))
    tui.add(app, tui.table([["name", "value"], ["speed", "fast"], ["cost", "none"]]))
    tui.theme(app, {"accent": "magenta"})
    tant oui {
        let key = tui.poll(app)
        si key == "q" {
            tui.close(app)
            halt
        }
        si key == "enter" {
            sprint("selected: " + tui.selected(app))
        }
        si key == "resize" {
            sprint(tui.size(app))
        }
    }
}
