use ui

use ui.lib.widgets

use ui.lib.theme

sfn main() {
    ui.theme("Silica Graphite", {"mode": "system", "colors": {"background": "#0B0D10", "surface": "#15191E", "surface_variant": "#20252C", "text_primary": "#F2F4F6", "text_secondary": "#A6AFB9", "accent": "#65BFA8", "border": "#303741", "error": "#D96B6B"}, "motion": {"enabled": oui, "respect_reduced_motion": oui}})
    let tasks: List = ["Design tokens", "Responsive layout", "Scroll container"]
    ui.app("Tasks") {
        ui.screen({"padding": {"sm": "12px", "md": "24px"}}) {
            ui.row({"gap": "12px", "align": "center"}) {
                ui.text("Tasks", {"size": "xl", "weight": "600"})
                ui.spacer()
                ui.button("Toggle theme", {"id": "theme-toggle"}) {
                    ui.on("click") {
                        ui.state.toggle("dark")
                        ui.state.set("status", "theme changed")
                    }
                }
            }
            ui.text("Status: ", {"id": "status", "bind_text": "status"})
            ui.lib.widgets.scroll({"direction": "vertical", "snap": "none"}) {
                ui.lib.widgets.list(tasks) {
                    ui.lib.widgets.list_item() {
                        ui.card({"padding": "12px", "background": "surface_variant"}) {
                            ui.text(item, {"color": "text_primary"})
                            ui.text("pending", {"color": "text_secondary", "size": "sm"})
                        }
                    }
                }
            }
        }
    }
    ui.render({"target": "web", "out": "build/ui_tasks.html"})
}
