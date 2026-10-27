use string

sfn main() {
    let s: String = "Silica Language"
    assert(len(s) == 15)
    assert(s[0] == "S")
    assert(string.contains(s, "Lang"))
    assert(string.starts_with(s, "Sil"))
    assert(string.ends_with(s, "guage"))
    assert(string.upper(s) == "SILICA LANGUAGE")
    assert(string.lower(s) == "silica language")
    assert(string.trim("  pad  ") == "pad")
    assert(string.replace(s, " ", "-") == "Silica-Language")
    assert(string.join(["a", "b"], "+") == "a+b")
    assert(len(string.split("a,b,c", ",")) == 3)
    assert("con" + "cat" == "concat")
    sprint("strings ok")
}
