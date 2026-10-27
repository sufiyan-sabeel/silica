use ui

use ui.lib.theme

sfn main() {
    ui.theme("Silica Graphite", {"mode": "system", "colors": {"background": "#0B0D10", "surface": "#15191E", "text_primary": "#F2F4F6", "accent": "#65BFA8"}})
    ui.app("Silica UI") {
        ui.screen({"padding": "24px"}) {
            ui.card({"padding": "20px", "radius": "12px", "elevation": 2}) {
                ui.text("Hello from Silica UI", {"size": "xl", "weight": "600"})
                ui.text("Rendered to build/ui_hello.html", {"color": "text_secondary"})
            }
        }
    }
    ui.render({"target": "web", "out": "build/ui_hello.html"})
}
