use string

sfn main() {
    let line: String = "silica,language,bytecode"
    let parts: List = string.split(line, ",")
    per part in parts {
        sprint(string.upper(part))
    }
    sprint(string.join(parts, " | "))
    sprint(string.replace(line, ",", " "))
    sprint(string.starts_with(line, "silica"))
    sprint(len(line))
    sprint(line[0])
}
