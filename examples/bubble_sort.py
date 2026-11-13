"""Bubble sort: O(n^2) comparisons (Big-O laboratory subject)."""


def bubble_sort(values):
    items = list(values)
    n = len(items)
    for i in range(n):
        for j in range(n - i - 1):
            if items[j] > items[j + 1]:
                items[j], items[j + 1] = items[j + 1], items[j]
    return items


if __name__ == "__main__":
    data = [5, 2, 9, 1, 7, 3, 8, 6, 4, 0]
    print(bubble_sort(data))
