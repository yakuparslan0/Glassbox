"""A wrong value is created early and only blows up three functions later (ZeroDivisionError)."""


def load_count(items):
    return len([x for x in items if x > 100])


def compute_ratio(total, count):
    return total / count


def summarize(items):
    count = load_count(items)
    total = sum(items)
    return compute_ratio(total, count)


def main():
    data = [3, 5, 8, 13]
    print("average of big items:", summarize(data))


main()
