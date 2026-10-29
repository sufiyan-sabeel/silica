use tui

use tui.lib.widgets

use tui.lib.layout

use tui.lib.style

sfn main() {
    let app = tui.app("Settings")
    tui.theme(app, {"accent": "#45C6B0"})
    let header = tui.panel("Preferences")
    tui.add(header, tui.text("up/down move, left/right change, enter activates"))
    let options = tui.panel("General")
    let notifications = tui.checkbox("Enable notifications")
    let telemetry = tui.checkbox("Send anonymous usage data")
    tui.add(options, notifications)
    tui.add(options, telemetry)
    let theme_panel = tui.panel("Theme")
    let choice = tui.radio(["Dark", "Light", "High contrast"])
    tui.add(theme_panel, choice)
    let actions = tui.row()
    let save = tui.button("Save")
    let reset = tui.button("Reset")
    tui.add(actions, save)
    tui.add(actions, reset)
    let feedback = tui.status("no changes yet", "info")
    tui.add(app, header)
    tui.add(app, options)
    tui.add(app, theme_panel)
    tui.add(app, actions)
    tui.add(app, feedback)
    tant oui {
        let key = tui.poll(app)
        si key == "q" {
            tui.close(app)
            halt
        }
        si key == "enter" {
            let action: String = tui.pressed(app)
            si action == "Save" {
                tui.set_text(feedback, "saved theme: " + tui.selected(choice))
            }
            si action == "Reset" {
                tui.select(choice, 0)
                tui.set_text(feedback, "reset to defaults")
            }
        }
    }
}
