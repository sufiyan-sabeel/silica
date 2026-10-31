use colors

sfn main() {
    let brand = colors.oklch(0.65, 0.18, 190)
    sprint("brand      " + colors.hex(brand))
    let detail = colors.describe(brand)
    sprint("oklch      L " + str(detail["oklch"][0]) + "  C " + str(detail["oklch"][1]) + "  h " + str(detail["oklch"][2]))
    sprint("")
    sprint("shade scale")
    let shades = colors.palette(brand)
    per step in ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"] {
        sprint("  " + step + "  " + colors.hex(shades[step]))
    }
    sprint("")
    sprint("theme")
    let theme = colors.theme(brand)
    per name in ["background", "surface", "text", "muted", "accent", "success", "warning", "error"] {
        sprint("  " + name + "  " + colors.hex(theme[name]))
    }
    sprint("")
    sprint("accessibility")
    let report = colors.audit(theme)
    per check in report["checks"] {
        let verdict = "FAIL"
        si check["passes"] {
            verdict = "pass"
        }
        sprint("  " + check["pair"] + "  " + str(check["ratio"]) + "  " + verdict)
    }
    sprint("")
    sprint("readable ink on the accent: " + colors.best_foreground(theme["accent"])["hex"])
    sprint("")
    sprint("perceptual mixing")
    let red = colors.parse("#ff0000")
    let blue = colors.parse("#0000ff")
    sprint("  red + blue in OKLab: " + colors.hex(colors.mix(red, blue, 0.5)))
    sprint("  gradient: " + str(len(colors.gradient(red, blue, 5))) + " steps")
    sprint("")
    sprint("css")
    sprint(colors.css_theme(theme))
}
