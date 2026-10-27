use ui

use ui.lib.widgets

use ui.lib.animation

sfn main() {
    let fade: Map = ui.lib.animation.transition("transform", "300ms", "ease-out")
    ui.app("Motion") {
        ui.lib.widgets.animate(fade) {
            ui.card({"padding": "16px", "radius": "12px"}) {
                ui.text("Fades and lifts in")
            }
        }
    }
    ui.render({"target": "web", "out": "build/ui_animate.html"})
}
