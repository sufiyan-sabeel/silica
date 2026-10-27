use collections

use string

sfn main() {
    let nums: List = [5, 3, 9, 1]
    sprint(collections.sort(nums))
    sprint(collections.reverse(nums))
    sprint(collections.sum(nums))
    sprint(collections.index_of(nums, 9))
    let ages: Map = {"anita": 31, "rahul": 27}
    sprint(ages["anita"])
    sprint(has(ages, "rahul"))
    per name in ages {
        sprint(name)
    }
    sprint(keys(ages))
    let bag: List = []
    push(bag, "apple")
    push(bag, "pear")
    sprint(bag)
}
