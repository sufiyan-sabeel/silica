use fs

use json

use time

use string

const STORE: String = "tasks.json"

sfn is_digits(s: String) -> Bool {
    si len(s) == 0 {
        ret nein
    }
    per ch in s {
        si ch < "0" {
            ret nein
        }
        si ch > "9" {
            ret nein
        }
    }
    ret oui
}

sfn words(line: String) -> List {
    let out: List = []
    per part in string.split(line, " ") {
        si len(part) > 0 {
            push(out, part)
        }
    }
    ret out
}

sfn load() -> List {
    si fs.exists(STORE) == nein {
        ret []
    }
    let text: String = string.trim(fs.read_text(STORE))
    si len(text) == 0 {
        ret []
    }
    let data: Any = json.parse(text)
    si type_of(data) != "List" {
        sprint("warning: " + STORE + " does not hold a list; starting empty")
        ret []
    }
    let valid: List = []
    per task in data {
        si type_of(task) != "Map" {
            sprint("warning: " + STORE + " holds an entry that is not a task; starting empty")
            ret []
        }
        si has(task, "id") == nein ou has(task, "title") == nein ou has(task, "done") == nein {
            sprint("warning: " + STORE + " holds a task without id, title or done; starting empty")
            ret []
        }
        push(valid, task)
    }
    ret valid
}

sfn save(tasks: List) {
    fs.write_text(STORE, json.stringify(tasks, 2))
}

sfn next_id(tasks: List) -> Int {
    let highest: Int = 0
    per task in tasks {
        si task["id"] > highest {
            highest = task["id"]
        }
    }
    ret highest + 1
}

sfn find(tasks: List, id: Int) -> Int {
    let index: Int = 0
    per task in tasks {
        si task["id"] == id {
            ret index
        }
        index = index + 1
    }
    ret -1
}

sfn show(tasks: List) {
    si len(tasks) == 0 {
        sprint("no tasks yet")
        ret
    }
    per task in tasks {
        let mark: String = "[ ]"
        si task["done"] == oui {
            mark = "[x]"
        }
        sprint(mark + " " + str(task["id"]) + ". " + task["title"])
    }
    let open: Int = 0
    per task in tasks {
        si task["done"] == nein {
            open = open + 1
        }
    }
    sprint(str(len(tasks)) + " task(s), " + str(open) + " still open")
}

sfn with_done(tasks: List, id: Int, flag: Bool) -> List {
    let out: List = []
    per task in tasks {
        si task["id"] == id {
            push(out, {"id": task["id"], "title": task["title"], "done": flag, "created": task["created"]})
        } sino {
            push(out, task)
        }
    }
    ret out
}

sfn without(tasks: List, id: Int) -> List {
    let out: List = []
    per task in tasks {
        si task["id"] != id {
            push(out, task)
        }
    }
    ret out
}

sfn main() {
    let tasks: List = load()
    sprint("Silica task manager - " + str(len(tasks)) + " task(s) in " + STORE)
    sprint("commands: add <title> | list | done <id> | remove <id> | quit")
    let running: Bool = oui
    tant running {
        let line: String = string.trim(input("task> "))
        let parts: List = words(line)
        si len(parts) == 0 {
            sprint("error: no command given")
        } sino {
            let verb: String = parts[0]
            si verb == "quit" {
                running = nein
                sprint("bye")
            } sino {
                si verb == "list" {
                    show(tasks)
                } sino {
                    si verb == "add" {
                        si len(parts) < 2 {
                            sprint("error: add needs a title")
                        } sino {
                            let title: String = string.join(parts, " ")
                            title = string.replace(title, "add ", "")
                            si len(title) == 0 {
                                sprint("error: the title cannot be empty")
                            } sino {
                                let task: Map = {"id": next_id(tasks), "title": title, "done": nein, "created": time.now()}
                                push(tasks, task)
                                save(tasks)
                                sprint("added #" + str(task["id"]) + ": " + title)
                            }
                        }
                    } sino {
                        si verb == "done" ou verb == "remove" {
                            si len(parts) != 2 {
                                sprint("error: " + verb + " needs one id")
                            } sino {
                                si is_digits(parts[1]) == nein {
                                    sprint("error: '" + parts[1] + "' is not an id")
                                } sino {
                                    let id: Int = int(parts[1])
                                    si find(tasks, id) < 0 {
                                        sprint("error: no task with id " + str(id))
                                    } sino {
                                        si verb == "done" {
                                            tasks = with_done(tasks, id, oui)
                                            save(tasks)
                                            sprint("task " + str(id) + " is done")
                                        } sino {
                                            tasks = without(tasks, id)
                                            save(tasks)
                                            sprint("removed task " + str(id))
                                        }
                                    }
                                }
                            }
                        } sino {
                            sprint("error: unknown command '" + verb + "'")
                        }
                    }
                }
            }
        }
    }
}
