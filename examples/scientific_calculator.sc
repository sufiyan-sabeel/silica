use ui

use ui.lib.widgets

use colors

use fs

use string

const OUT: String = "build/calculator.html"

const BASE: String = "#0B0B0C"

const AMBER: String = "#FF9F0A"

const RED: String = "#FF453A"

sfn shade(base: String, amount: Float) -> String {
    si amount >= 0.0 {
        ret colors.hex(colors.lighten(base, amount))
    }
    ret colors.hex(colors.darken(base, 0.0 - amount))
}

sfn ensure_contrast(fg: String, bg: String, minimum: Float) -> String {
    let out: String = fg
    let tries: Int = 0
    tant colors.contrast(out, bg) < minimum und tries < 40 {
        si colors.luminance(bg) > 0.5 {
            out = colors.hex(colors.darken(out, 0.02))
        } sino {
            out = colors.hex(colors.lighten(out, 0.02))
        }
        tries = tries + 1
    }
    ret out
}

sfn build_theme() -> Map {
    let background: String = BASE
    let surface: String = shade(BASE, 0.06)
    let variant: String = shade(BASE, 0.14)
    let text: String = ensure_contrast(colors.best_foreground(background)["hex"], background, 7.0)
    let secondary: String = ensure_contrast(colors.hex(colors.mix(text, background, 0.45)), background, 4.5)
    let accent: String = AMBER
    let accent_text: String = ensure_contrast(colors.best_foreground(accent)["hex"], accent, 4.5)
    let error: String = ensure_contrast(RED, background, 4.5)
    ret {"background": background, "surface": surface, "surface_variant": variant, "text_primary": text, "text_secondary": secondary, "accent": accent, "accent_text": accent_text, "border": shade(BASE, 0.18), "error": error}
}

sfn key(theme: Map, label: String, id: String, kind: String) {
    let background: String = theme["surface_variant"]
    let colour: String = theme["text_primary"]
    si kind == "op" {
        background = theme["accent"]
        colour = theme["accent_text"]
    }
    si kind == "util" {
        background = theme["surface"]
        colour = theme["accent"]
    }
    si kind == "eq" {
        background = theme["accent"]
        colour = theme["accent_text"]
    }
    ui.button(label, {"id": id, "background": background, "color": colour, "radius": "14px", "size": "lg", "weight": "500", "height": "56px", "width": "100%"})
}

sfn keypad(theme: Map) {
    ui.column({"gap": "8px", "width": "100%"}) {
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "AC", "key-ac", "util")
            key(theme, "+/−", "key-neg", "util")
            key(theme, "%", "key-pct", "util")
            key(theme, "⌫", "key-back", "util")
            key(theme, "÷", "key-div", "op")
        }
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "7", "key-7", "num")
            key(theme, "8", "key-8", "num")
            key(theme, "9", "key-9", "num")
            key(theme, "√", "key-sqrt", "util")
            key(theme, "×", "key-mul", "op")
        }
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "4", "key-4", "num")
            key(theme, "5", "key-5", "num")
            key(theme, "6", "key-6", "num")
            key(theme, "x²", "key-sq", "util")
            key(theme, "−", "key-sub", "op")
        }
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "1", "key-1", "num")
            key(theme, "2", "key-2", "num")
            key(theme, "3", "key-3", "num")
            key(theme, "1/x", "key-inv", "util")
            key(theme, "+", "key-add", "op")
        }
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "0", "key-0", "num")
            key(theme, ".", "key-dot", "num")
            key(theme, "π", "key-pi", "util")
            key(theme, "e", "key-e", "util")
            key(theme, "=", "key-eq", "eq")
        }
        ui.row({"gap": "8px", "width": "100%"}) {
            key(theme, "xʸ", "key-pow", "util")
            key(theme, "log", "key-log", "util")
            key(theme, "ln", "key-ln", "util")
            key(theme, "Ans", "key-ans", "util")
            key(theme, "CLR", "key-clrhist", "util")
        }
    }
}

sfn style_block(theme: Map) -> String {
    let lines: List = []
    push(lines, "<style>")
    push(lines, "  .si-calc-display { text-align: right; font-variant-numeric: tabular-nums; word-break: break-all; }")
    push(lines, "  .si-calc-expr { text-align: right; min-height: 1.2em; color: " + theme["text_secondary"] + "; }")
    push(lines, "  .si-calc-tape { max-height: 132px; overflow-y: auto; }")
    push(lines, "  .si-calc-tape button { all: unset; display: block; width: 100%; text-align: right; cursor: pointer; padding: 4px 0; color: " + theme["text_secondary"] + "; font-variant-numeric: tabular-nums; }")
    push(lines, "  .si-calc-tape button:hover { color: " + theme["text_primary"] + "; }")
    push(lines, "  .si-calc-error { color: " + theme["error"] + "; }")
    push(lines, "  @media (max-width: 380px) { .si-calc-display { font-size: 2.6rem; } }")
    push(lines, "  :focus-visible { outline: 3px solid " + theme["accent"] + "; outline-offset: 2px; }")
    push(lines, "</style>")
    ret string.join(lines, "\n")
}

sfn engine() -> String {
    let lines: List = []
    push(lines, "<script>")
    push(lines, "/* silica-scientific-calculator: generated by Silica.")
    push(lines, " * The page structure, theme, palette and CSS come from Silica source.")
    push(lines, " * The arithmetic below is JavaScript: Silica does not run in the browser.")
    push(lines, " * No eval, no new Function — a hand-written evaluator over a token array. */")
    push(lines, "(function () {")
    push(lines, "  'use strict';")
    push(lines, "  var tokens = [], entry = '0', fresh = true, errored = false;")
    push(lines, "  var history = [];")
    push(lines, "  var display = document.getElementById('calc-display');")
    push(lines, "  var exprLine = document.getElementById('calc-expr');")
    push(lines, "  var tape = document.getElementById('calc-tape');")
    push(lines, "")
    push(lines, "  function format(v) {")
    push(lines, "    if (!isFinite(v)) return 'Error';")
    push(lines, "    if (v === 0) return '0';")
    push(lines, "    var a = Math.abs(v);")
    push(lines, "    if (a >= 1e12 || a < 1e-9) {")
    push(lines, "      return v.toExponential(9).replace(/(\\.\\d*?)0+e/, '$1e').replace(/\\.e/, 'e').replace('e+', 'e');")
    push(lines, "    }")
    push(lines, "    var s = v.toPrecision(12);")
    push(lines, "    if (s.indexOf('e') >= 0) return s;")
    push(lines, "    if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\\.$/, '');")
    push(lines, "    return s;")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function toNumber(text) {")
    push(lines, "    if (text === '' || text === 'Error') return 0;")
    push(lines, "    var n = Number(text);")
    push(lines, "    return isFinite(n) ? n : 0;")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function precedence(op) { return (op === '*' || op === '/' || op === '^') ? 2 : 1; }")
    push(lines, "")
    push(lines, "  function apply(a, op, b) {")
    push(lines, "    if (op === '+') return a + b;")
    push(lines, "    if (op === '-') return a - b;")
    push(lines, "    if (op === '*') return a * b;")
    push(lines, "    if (op === '/') return b === 0 ? NaN : a / b;")
    push(lines, "    if (op === '^') return Math.pow(a, b);")
    push(lines, "    return b;")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function evaluate(list) {")
    push(lines, "    var values = [], ops = [];")
    push(lines, "    function fold() {")
    push(lines, "      var op = ops.pop(), b = values.pop(), a = values.pop();")
    push(lines, "      if (a === undefined || b === undefined) { values.push(NaN); return; }")
    push(lines, "      values.push(apply(a, op, b));")
    push(lines, "    }")
    push(lines, "    for (var i = 0; i < list.length; i++) {")
    push(lines, "      var t = list[i];")
    push(lines, "      if (typeof t === 'number') { values.push(t); continue; }")
    push(lines, "      while (ops.length && precedence(ops[ops.length - 1]) >= precedence(t)) fold();")
    push(lines, "      ops.push(t);")
    push(lines, "    }")
    push(lines, "    while (ops.length) fold();")
    push(lines, "    return values.length === 1 ? values[0] : NaN;")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function exprText() {")
    push(lines, "    var parts = [];")
    push(lines, "    for (var i = 0; i < tokens.length; i++) {")
    push(lines, "      parts.push(typeof tokens[i] === 'number' ? format(tokens[i]) : tokens[i]);")
    push(lines, "    }")
    push(lines, "    if (!fresh || tokens.length === 0) parts.push(entry);")
    push(lines, "    return parts.join(' ');")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function render() {")
    push(lines, "    if (display) {")
    push(lines, "      display.textContent = entry;")
    push(lines, "      display.className = 'si-calc-display' + (errored ? ' si-calc-error' : '');")
    push(lines, "    }")
    push(lines, "    if (exprLine) exprLine.textContent = tokens.length ? exprText() : '';")
    push(lines, "    if (!tape) return;")
    push(lines, "    tape.innerHTML = '';")
    push(lines, "    for (var i = 0; i < history.length; i++) {")
    push(lines, "      (function (row) {")
    push(lines, "        var b = document.createElement('button');")
    push(lines, "        b.type = 'button';")
    push(lines, "        b.textContent = row.expr + ' = ' + row.result;")
    push(lines, "        b.setAttribute('data-history', row.result);")
    push(lines, "        b.addEventListener('click', function () {")
    push(lines, "          entry = row.result; tokens = []; fresh = true; errored = false; render();")
    push(lines, "        });")
    push(lines, "        tape.appendChild(b);")
    push(lines, "      })(history[i]);")
    push(lines, "    }")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function digit(d) {")
    push(lines, "    if (errored) { entry = '0'; errored = false; fresh = true; }")
    push(lines, "    if (fresh) { entry = d; fresh = false; }")
    push(lines, "    else if (entry === '0') { entry = d; }")
    push(lines, "    else if (entry.length < 16) { entry = entry + d; }")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function dot() {")
    push(lines, "    if (errored) { entry = '0'; errored = false; fresh = true; }")
    push(lines, "    if (fresh) { entry = '0.'; fresh = false; }")
    push(lines, "    else if (entry.indexOf('.') < 0) { entry = entry + '.'; }")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function operator(op) {")
    push(lines, "    if (errored) return;")
    push(lines, "    if (fresh) {")
    push(lines, "      if (tokens.length === 0) { tokens.push(toNumber(entry)); tokens.push(op); }")
    push(lines, "      else if (typeof tokens[tokens.length - 1] === 'string') { tokens[tokens.length - 1] = op; }")
    push(lines, "      else { tokens.push(op); }")
    push(lines, "    } else {")
    push(lines, "      tokens.push(toNumber(entry));")
    push(lines, "      tokens.push(op);")
    push(lines, "    }")
    push(lines, "    fresh = true;")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function equals() {")
    push(lines, "    if (errored) return;")
    push(lines, "    var list = tokens.slice();")
    push(lines, "    if (!fresh) list.push(toNumber(entry));")
    push(lines, "    if (!list.length) return;")
    push(lines, "    var expr = exprText();")
    push(lines, "    var r = evaluate(list);")
    push(lines, "    if (!isFinite(r)) {")
    push(lines, "      errored = true; entry = 'Error'; tokens = []; fresh = true; render(); return;")
    push(lines, "    }")
    push(lines, "    history.unshift({ expr: expr, result: format(r) });")
    push(lines, "    if (history.length > 20) history.pop();")
    push(lines, "    entry = format(r); tokens = []; fresh = true;")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function unary(kind) {")
    push(lines, "    if (errored && kind !== 'neg') return;")
    push(lines, "    var v = toNumber(entry);")
    push(lines, "    var out = v;")
    push(lines, "    if (kind === 'sqrt') out = v < 0 ? NaN : Math.sqrt(v);")
    push(lines, "    if (kind === 'sq') out = v * v;")
    push(lines, "    if (kind === 'inv') out = v === 0 ? NaN : 1 / v;")
    push(lines, "    if (kind === 'log') out = v <= 0 ? NaN : Math.log10(v);")
    push(lines, "    if (kind === 'ln') out = v <= 0 ? NaN : Math.log(v);")
    push(lines, "    if (kind === 'neg') out = 0 - v;")
    push(lines, "    if (kind === 'pct') out = v / 100;")
    push(lines, "    if (!isFinite(out)) { errored = true; entry = 'Error'; tokens = []; fresh = true; render(); return; }")
    push(lines, "    entry = format(out);")
    push(lines, "    fresh = true;")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function back() {")
    push(lines, "    if (errored) { entry = '0'; errored = false; fresh = true; render(); return; }")
    push(lines, "    if (fresh) return;")
    push(lines, "    entry = entry.slice(0, -1);")
    push(lines, "    if (entry === '' || entry === '-') { entry = '0'; fresh = true; }")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function clearAll() {")
    push(lines, "    tokens = []; entry = '0'; fresh = true; errored = false;")
    push(lines, "    render();")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  function press(key) {")
    push(lines, "    if (/^[0-9]$/.test(key)) { digit(key); return; }")
    push(lines, "    if (key === '.') { dot(); return; }")
    push(lines, "    if (key === '+' || key === '-' || key === '*' || key === '/' || key === '^') { operator(key); return; }")
    push(lines, "    if (key === '=') { equals(); return; }")
    push(lines, "    if (key === 'ac') { clearAll(); return; }")
    push(lines, "    if (key === 'back') { back(); return; }")
    push(lines, "    if (key === 'pi') { entry = format(Math.PI); fresh = true; errored = false; render(); return; }")
    push(lines, "    if (key === 'e') { entry = format(Math.E); fresh = true; errored = false; render(); return; }")
    push(lines, "    if (key === 'ans') { if (history.length) { entry = history[0].result; fresh = true; errored = false; } render(); return; }")
    push(lines, "    if (key === 'clrhist') { history = []; render(); return; }")
    push(lines, "    unary(key);")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  var keymap = { Enter: '=', '=': '=', Escape: 'ac', Backspace: 'back', Delete: 'ac', '+': '+', '-': '-', '*': '*', '/': '/', '^': '^', '.': '.', '%': 'pct' };")
    push(lines, "  document.addEventListener('keydown', function (evt) {")
    push(lines, "    if (evt.ctrlKey || evt.metaKey || evt.altKey) return;")
    push(lines, "    if (/^[0-9]$/.test(evt.key)) { press(evt.key); evt.preventDefault(); return; }")
    push(lines, "    var mapped = keymap[evt.key];")
    push(lines, "    if (mapped) { press(mapped); evt.preventDefault(); }")
    push(lines, "  });")
    push(lines, "")
    push(lines, "  var ids = ['ac','neg','pct','back','div','7','8','9','sqrt','mul','4','5','6','sq','sub','1','2','3','inv','add','0','dot','pi','e','eq','pow','log','ln','ans','clrhist'];")
    push(lines, "  var map = { ac:'ac', neg:'neg', pct:'pct', back:'back', div:'/', mul:'*', sub:'-', add:'+', eq:'=', sqrt:'sqrt', sq:'sq', inv:'inv', pow:'^', log:'log', ln:'ln', pi:'pi', e:'e', ans:'ans', clrhist:'clrhist', dot:'.' };")
    push(lines, "  for (var i = 0; i < ids.length; i++) {")
    push(lines, "    (function (name) {")
    push(lines, "      var node = document.getElementById('key-' + name);")
    push(lines, "      if (!node) return;")
    push(lines, "      var action = map[name] || name;")
    push(lines, "      node.addEventListener('click', function () { press(action); });")
    push(lines, "    })(ids[i]);")
    push(lines, "  }")
    push(lines, "")
    push(lines, "  window.silicaCalculator = { press: press, format: format, state: function () { return { entry: entry, history: history }; } };")
    push(lines, "  render();")
    push(lines, "})();")
    push(lines, "</script>")
    ret string.join(lines, "\n")
}

sfn inline_assets(path: String) {
    let css_path: String = "build/theme.css"
    let js_path: String = "build/silica-ui-runtime.js"
    si fs.exists(css_path) == nein ou fs.exists(js_path) == nein {
        sprint("error: the renderer's assets are missing next to " + path)
        halt(1)
    }
    let page: String = fs.read_text(path)
    let css: String = fs.read_text(css_path)
    let js: String = fs.read_text(js_path)
    let link: String = "<link rel=\"stylesheet\" href=\"theme.css\">"
    let script: String = "<script src=\"silica-ui-runtime.js\"></script>"
    si string.contains(page, link) == nein ou string.contains(page, script) == nein {
        sprint("error: " + path + " does not reference the renderer assets as expected")
        sprint("hint: the page would not be self-contained; failing instead of shipping it")
        halt(1)
    }
    page = string.replace(page, link, "<style>\n" + css + "\n</style>")
    page = string.replace(page, script, "<script>\n" + js + "\n</script>")
    fs.write_text(path, page)
    sprint("inlined theme.css and silica-ui-runtime.js: " + path + " is one file")
}

sfn inject(path: String, block: String) {
    si fs.exists(path) == nein {
        sprint("error: " + path + " was not written by ui.render")
        halt(1)
    }
    let page: String = fs.read_text(path)
    si string.contains(page, "silica-scientific-calculator") {
        sprint("error: " + path + " already carries the engine; remove it and re-run")
        halt(1)
    }
    si string.contains(page, "</body>") == nein {
        sprint("error: cannot inject into " + path + ": no </body> marker found")
        sprint("hint: the UI renderer changed its output shape; the page would be")
        sprint("      silently inert, so this fails instead of writing it")
        halt(1)
    }
    let injected: String = string.replace(page, "</body>", block + "\n</body>")
    fs.write_text(path, injected)
}

sfn main() {
    let theme: Map = build_theme()
    ui.theme("Silica Calculator", {"mode": "dark", "colors": theme})
    ui.app("Calculator") {
        ui.screen({"padding": "16px"}) {
            ui.column({"gap": "12px", "width": "100%"}) {
                ui.card({"padding": "16px", "radius": "16px", "background": theme["surface"]}) {
                    ui.column({"gap": "6px", "width": "100%"}) {
                        ui.text("", {"id": "calc-expr", "size": "sm", "color": theme["text_secondary"]})
                        ui.text("0", {"id": "calc-display", "size": "xl", "weight": "600", "color": theme["text_primary"]})
                    }
                }
                keypad(theme)
                ui.card({"padding": "12px", "radius": "16px", "background": theme["surface"]}) {
                    ui.column({"gap": "4px", "width": "100%"}) {
                        ui.text("history", {"size": "sm", "color": theme["text_secondary"]})
                        ui.lib.widgets.scroll({"direction": "vertical", "snap": "none"}) {
                            ui.text("", {"id": "calc-tape"})
                        }
                    }
                }
            }
        }
    }
    ui.render({"target": "web", "out": OUT})
    inline_assets(OUT)
    inject(OUT, style_block(theme) + "\n" + engine())
    sprint("wrote " + OUT)
    sprint("  contrast text/background: " + str(colors.contrast(theme["text_primary"], theme["background"])))
    sprint("  contrast accent_text/accent: " + str(colors.contrast(theme["accent_text"], theme["accent"])))
    sprint("  open it in a browser; it needs no network")
}
