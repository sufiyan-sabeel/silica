use fs

use json

use string

use collections

const SOURCE: String = "sales.csv"

const REPORT: String = "report.json"

sfn is_digits(s: String) -> Bool {
    si len(s) == 0 {
        ret nein
    }
    per ch in s {
        si ch < "0" {
            ret nein
        }
        si ch > "9" {
            ret nein
        }
    }
    ret oui
}

sfn is_number(s: String) -> Bool {
    let body: String = s
    si string.starts_with(body, "-") {
        body = string.replace(body, "-", "")
    }
    let parts: List = string.split(body, ".")
    si len(parts) == 1 {
        ret is_digits(parts[0])
    }
    si len(parts) != 2 {
        ret nein
    }
    si len(parts[0]) == 0 {
        ret nein
    }
    ret is_digits(parts[0]) und is_digits(parts[1])
}

sfn pad(text: String, width: Int) -> String {
    let out: String = text
    tant len(out) < width {
        out = out + " "
    }
    ret out
}

sfn money(value: Float) -> String {
    let rounded: Int = int(value * 100.0 + 0.5)
    let whole: Int = rounded / 100
    let cents: Int = rounded % 100
    let tail: String = str(cents)
    si cents < 10 {
        tail = "0" + tail
    }
    ret str(whole) + "." + tail
}

sfn main() {
    si fs.exists(SOURCE) == nein {
        sprint("error: " + SOURCE + " not found in this directory")
        sprint("copy examples/data/" + SOURCE + " here and run again")
        halt(1)
    }
    let text: String = string.trim(fs.read_text(SOURCE))
    let lines: List = string.split(text, "\n")
    si len(lines) < 2 {
        sprint("error: " + SOURCE + " needs a header and at least one row")
        halt(1)
    }
    sprint("reading " + str(len(lines) - 1) + " row(s) from " + SOURCE)
    let regions: List = []
    let totals: List = []
    let revenue: Float = 0.0
    let units: Int = 0
    let bad: Int = 0
    let line_number: Int = 1
    per line in lines {
        line_number = line_number + 1
        si line_number > 2 {
            let cells: List = string.split(string.trim(line), ",")
            si len(cells) != 3 {
                sprint("warning: line " + str(line_number) + " does not have three fields")
                bad = bad + 1
            } sino {
                si is_number(cells[1]) == nein ou is_number(cells[2]) == nein {
                    sprint("warning: line " + str(line_number) + " has a non-numeric value")
                    bad = bad + 1
                } sino {
                    let count: Int = int(cells[1])
                    let price: Float = float(cells[2])
                    let amount: Float = float(count) * price
                    let at: Int = collections.index_of(regions, cells[0])
                    si at < 0 {
                        push(regions, cells[0])
                        push(totals, amount)
                    } sino {
                        let rebuilt: List = []
                        let slot: Int = 0
                        per value in totals {
                            si slot == at {
                                push(rebuilt, value + amount)
                            } sino {
                                push(rebuilt, value)
                            }
                            slot = slot + 1
                        }
                        totals = rebuilt
                    }
                    revenue = revenue + amount
                    units = units + count
                }
            }
        }
    }
    si len(regions) == 0 {
        sprint("error: no usable rows in " + SOURCE)
        halt(1)
    }
    sprint("")
    sprint(pad("region", 12) + "revenue")
    sprint("-------------------")
    let best: String = regions[0]
    let best_total: Float = totals[0]
    let index: Int = 0
    per name in regions {
        sprint(pad(name, 12) + money(totals[index]))
        si totals[index] > best_total {
            best_total = totals[index]
            best = name
        }
        index = index + 1
    }
    sprint("-------------------")
    sprint(pad("total", 12) + money(revenue))
    sprint(pad("units", 12) + str(units))
    sprint(pad("best", 12) + best)
    si bad > 0 {
        sprint("skipped     " + str(bad) + " bad row(s)")
    }
    let rows: List = []
    let at: Int = 0
    per name in regions {
        push(rows, {"region": name, "revenue": totals[at]})
        at = at + 1
    }
    let report: Map = {"source": SOURCE, "rows": len(lines) - 1, "units": units, "revenue": revenue, "best": best, "skipped": bad, "regions": rows}
    fs.write_text(REPORT, json.stringify(report, 2))
    sprint("wrote " + REPORT)
}
