use gui

use gui.lib.widgets

use gui.lib.layout

sfn handle_click() {
    sprint("Button clicked")
}

sfn main() {
    let app = gui.app("Silica GUI")
    let window = gui.window(app, "Hello Silica", 640, 420)
    gui.add(window, gui.heading("Hello from Silica"))
    gui.add(window, gui.text("A real window, drawn by tkinter."))
    gui.add(window, gui.field("type here"))
    gui.add(window, gui.checkbox("Remember me"))
    let button = gui.button("Click me")
    gui.add(window, button)
    gui.on_click(button, "handle_click")
    gui.show(window)
    gui.run(app, 20)
    gui.close(window)
}
