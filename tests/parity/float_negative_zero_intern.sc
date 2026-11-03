# xfail: the Python optimizer interns float constants by ==, and 0.0 == -0.0,
# so the first-seen sign is applied to both. Expected IEEE output: -0.0 then 0.0.
sfn main() {
    sprint(-0.0)
    sprint(0.0 - 0.0)
}
