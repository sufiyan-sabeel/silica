use fs

use string

sfn main() {
    let path: String = "examples/hello.sc"
    si fs.exists(path) {
        let source: String = fs.read_text(path)
        sprint(len(source) > 0)
        let lines: List = string.split(source, "\n")
        sprint(lines[0])
    } sino {
        sprint("missing")
    }
    let entries: List = fs.list_dir("examples")
    sprint(len(entries) > 0)
    sprint(fs.exists("examples/nope.sc"))
}
