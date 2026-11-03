# An integer literal outside 64-bit range is a compile error, not a wrap.
sfn main() {
    sprint(9223372036854775808)
}
