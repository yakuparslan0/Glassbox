"""A zoo of dead, cold and duplicated code for the Mark & Sweep report."""
import json
import os
import sys

UNUSED_CONSTANT = 42


def used(x):
    unused_local = x * 2
    return x + 1


def never_called(a, b):
    return a - b


def after_return(x):
    return x
    print("this line can never run")


def constant_branch(x):
    if False:
        print("dead branch")
    return x


def block_one(items):
    total = 0
    for item in items:
        if item > 0:
            total += item * 2
        else:
            total -= 1
    return total


def block_two(values):
    acc = 0
    for value in values:
        if value > 0:
            acc += value * 2
        else:
            acc -= 1
    return acc


def rarely_used(flag):
    if flag:
        return "rare path"
    return "common path"


if __name__ == "__main__":
    print(used(1))
    print(block_one([1, -2, 3]))
    print(block_two([4, -5, 6]))
    print(after_return(7))
    print(constant_branch(8))
    print(rarely_used(False))
    print(sys.version_info.major)
