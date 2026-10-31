struct Ticket {
    id: Int
    title: String
    open: Bool
}
class Queue {
    tickets: List
    private next_id: Int
    sfn push(title: String) -> Int {
        self.next_id = self.next_id + 1
        push(self.tickets, Ticket(self.next_id, title, oui))
        ret self.next_id
    }
    sfn close(id: Int) {
        per ticket in self.tickets {
            si ticket.id == id {
                ticket.open = nein
            }
        }
    }
    sfn open_count() -> Int {
        let count: Int = 0
        per ticket in self.tickets {
            si ticket.open {
                count = count + 1
            }
        }
        ret count
    }
    static sfn empty() -> Queue {
        ret Queue([], 0)
    }
}

sfn main() {
    let queue: Queue = Queue.empty()
    sprint(queue.push("write the docs"))
    sprint(queue.push("fix the bug"))
    sprint(queue.open_count())
    queue.close(1)
    sprint(queue.open_count())
    let first: Ticket = queue.tickets[0]
    sprint(first.title)
    sprint(first.open)
    sprint(first)
    let copy: Ticket = Ticket(1, "write the docs", nein)
    sprint(first == copy)
    sprint(queue == Queue.empty())
}
