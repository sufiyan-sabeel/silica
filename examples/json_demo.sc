use json

sfn main() {
    let document: String = "{\"project\": \"silica\", \"version\": 1, \"stable\": false, \"tags\": [\"compiler\", \"bytecode\"], \"extra\": null}"
    let parsed = json.parse(document)
    sprint(type_of(parsed))
    sprint(json.stringify(parsed))
    sprint(json.stringify(parsed, 2))
    let text: String = json.stringify(parsed)
    sprint(json.stringify(json.parse(text)) == text)
    let settings: Map = {"width": 80, "ratio": 1.5, "wrap": oui, "tags": ["a", "b"]}
    sprint(json.stringify(settings))
    sprint(json.parse("[1, 2, 3]"))
}
