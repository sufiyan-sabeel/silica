struct Point {
    x: Int
    y: Int
}
struct Rect {
    origin: Point
    width: Int
    height: Int
}

sfn area(r: Rect) -> Int {
    ret r.width * r.height
}

sfn moved(r: Rect, dx: Int) -> Rect {
    ret Rect(origin: Point(x: r.origin.x + dx, y: r.origin.y), width: r.width, height: r.height)
}

sfn main() {
    let p = Point(x: 3, y: 4)
    sprint("point: " + str(p))
    sprint("x = " + str(p.x))
    let q = Point(10, 20)
    sprint("positional: " + str(q))
    let box = Rect(origin: p, width: 6, height: 5)
    sprint("nested: " + str(box))
    sprint("area: " + str(area(box)))
    box.width = 8
    sprint("after resize: " + str(area(box)))
    let shifted = moved(box, 100)
    sprint("shifted: " + str(shifted.origin.x))
    sprint("original: " + str(box.origin.x))
    sprint("equal points: " + str(p == Point(3, 4)))
    sprint("different points: " + str(p == q))
    let boxes = [box, shifted]
    per b in boxes {
        sprint("  " + str(b.origin.x) + " " + str(area(b)))
    }
}
