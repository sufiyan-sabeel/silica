use path

use time

use random

sfn describe(p: String) -> String {
    ret path.stem(p) + path.ext(p)
}

sfn main() {
    let file: String = path.join(["reports", "2026", "summary.txt"])
    sprint(file)
    sprint(describe(file))
    sprint(path.normalise("reports/./2026/../2026/summary.txt"))
    sprint(path.is_within(file, "reports"))
    sprint(path.is_within("../etc/passwd", "reports"))
    sprint(path.sep)
    sprint(time.iso(1000000000))
    sprint(time.parse_iso("2001-09-09T01:46:40Z"))
    sprint(time.year(1000000000))
    sprint(time.now() > 1600000000)
    let start: Float = time.monotonic()
    sprint(time.monotonic() >= start)
    random.seed(2026)
    let a: Int = random.int(1, 100)
    random.seed(2026)
    let b: Int = random.int(1, 100)
    sprint(a == b)
    sprint(len(random.secure_bytes(8)))
    let pick: Int = random.secure_int(1, 7)
    sprint(pick >= 1)
    sprint(pick < 7)
    let hand: List = ["rock", "paper", "scissors"]
    sprint(len(random.shuffle(hand)))
}
