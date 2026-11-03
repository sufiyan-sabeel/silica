# Strings are sequences of Unicode code points, not bytes and not graphemes.
sfn main() {
    let s: String = "héllo"
    sprint(len(s))
    sprint(s[1])
    let emoji: String = "😀"
    sprint(len(emoji))
    sprint(emoji[0])
    let combining: String = "e" + "́"
    sprint(len(combining))
    sprint(combining[0])
    sprint(combining[1])
}
