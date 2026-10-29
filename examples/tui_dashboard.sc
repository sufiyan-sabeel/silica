use tui

use tui.lib.widgets

use tui.lib.layout

use tui.lib.style

sfn stage_label(step: Int) -> String {
    si step == 0 {
        ret "waiting to start"
    }
    si step == 1 {
        ret "compiling"
    }
    si step == 2 {
        ret "running tests"
    }
    si step == 3 {
        ret "packaging"
    }
    ret "complete"
}

sfn stage_level(step: Int) -> String {
    si step == 4 {
        ret "success"
    }
    ret "info"
}

sfn main() {
    let app = tui.app("Dashboard")
    tui.theme(app, {"accent": "#45C6B0", "success": "#4ADE80"})
    let title = tui.panel("Build dashboard")
    tui.add(title, tui.table([["stage", "status"], ["compile", "ok"], ["tests", "671 passed"], ["package", "wheel"]]))
    tui.add(app, title)
    let progress_panel = tui.panel("Progress")
    let bar = tui.progress(0, 4)
    let spinner = tui.spinner("idle")
    tui.add(progress_panel, bar)
    tui.add(progress_panel, spinner)
    tui.add(app, progress_panel)
    let actions = tui.row()
    let advance = tui.button("Advance")
    let reset = tui.button("Reset")
    tui.add(actions, advance)
    tui.add(actions, reset)
    tui.add(app, actions)
    let message = tui.status("waiting to start", "info")
    tui.add(app, message)
    let step: Int = 0
    tant oui {
        let key = tui.poll(app)
        si key == "q" {
            tui.close(app)
            halt
        }
        si key == "r" {
            step = 0
            tui.set_progress(bar, 0)
            tui.set_text(spinner, "idle")
            tui.set_text(message, "waiting to start")
        }
        si key == "enter" {
            let action: String = tui.pressed(app)
            si action == "Advance" {
                si step < 4 {
                    step = step + 1
                }
                tui.set_progress(bar, step)
                tui.set_text(spinner, stage_label(step))
                tui.set_text(message, "step " + str(step) + ": " + stage_label(step))
            }
        }
    }
}
