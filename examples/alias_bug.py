"""Two classic aliasing bugs: a mutable default argument and a list shared between two names."""


def add_item(item, bucket=[]):
    bucket.append(item)
    return bucket


first = add_item("apple")
second = add_item("pear")
print(first, second)

original = [1, 2, 3]
copy = original
copy.append(4)
print(original, copy)
