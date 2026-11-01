use fs

use json

use string

const FACTS: String = "build/packaging/facts.json"

const SUMS: String = "dist/SHA256SUMS.txt"

sfn main() {
    si fs.exists(FACTS) == nein {
        sprint("write-sums: " + FACTS + " not found; run tools/package/facts.py first")
        halt(1)
    }
    let facts: Any = json.parse(fs.read_text(FACTS))
    let wheel: Any = facts["wheel"]
    let sdist: Any = facts["sdist"]
    let lines: List = []
    push(lines, wheel["sha256"] + "  " + wheel["name"])
    push(lines, sdist["sha256"] + "  " + sdist["name"])
    fs.write_text(SUMS, string.join(lines, "\n") + "\n")
    sprint("write-sums: wrote " + SUMS)
    sprint("  " + wheel["name"])
    sprint("  " + sdist["name"])
}
