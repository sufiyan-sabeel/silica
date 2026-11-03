# Division truncates toward zero; % keeps the dividend's sign (C-style, not Python's).
sfn main() {
    sprint(-7 / 2)
    sprint(7 / -2)
    sprint(-7 % 2)
    sprint(7 % -2)
    sprint(7 / 2)
}
