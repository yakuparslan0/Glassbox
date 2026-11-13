"""Both tracer backends must produce the same event sequence (time fields excluded)."""

from __future__ import annotations

import pytest
from helpers import EXAMPLES, example_source, run, strip_time

EXAMPLE_FILES = sorted(p.name for p in EXAMPLES.glob("*.py"))

SAMPLES = {
    "classes_and_closures": """
class Counter:
    def __init__(self, start):
        self.value = start

    def bump(self, by=1):
        self.value += by
        return self.value


def make_adder(n):
    def add(x):
        return x + n
    return add


c = Counter(3)
c.bump()
c.bump(by=5)
add2 = make_adder(2)
print([add2(i) for i in range(3)], c.value)
""",
    "exceptions": """
def inner(x):
    return 10 // x


def middle(x):
    try:
        return inner(x)
    finally:
        print("middle cleanup")


def outer():
    try:
        middle(0)
    except ZeroDivisionError as exc:
        print("caught", exc)
    try:
        try:
            raise ValueError("first")
        except ValueError:
            raise KeyError("second")
    except KeyError:
        print("rewrapped")
    return "done"


print(outer())
""",
    "uncaught": """
def boom():
    raise RuntimeError("kaboom")


def caller():
    boom()


caller()
""",
    "generators": """
def count_to(n):
    for i in range(n):
        yield i * i


def first_two(gen):
    return next(gen), next(gen)


total = 0
for v in count_to(4):
    total += v
pair = first_two(count_to(10))
abandoned = count_to(5)
next(abandoned)
del abandoned
print(total, pair)
""",
    "library_calls": """
import json
import math
import time

def key_fn(item):
    return -item

data = {"b": [1, 2], "a": {"x": 1}}
text = json.dumps(data, sort_keys=True)
loaded = json.loads(text)
ordered = sorted([3, 1, 2], key=key_fn)
root = math.sqrt(16)
time.sleep(0)
print(text, loaded, ordered, root)
""",
    "stdin_and_globals": """
counter = 0

def bump():
    global counter
    counter += 1

name = input("name? ")
for _ in range(3):
    bump()
print(name, counter)
""",
}


def _compare(source: str, **kwargs) -> None:
    monitoring = strip_time(run(source, tracer="monitoring", **kwargs))
    settrace = strip_time(run(source, tracer="settrace", **kwargs))
    for a, b in zip(monitoring, settrace, strict=False):
        assert a == b, f"first divergence:\nmonitoring: {a}\nsettrace:   {b}"
    assert len(monitoring) == len(settrace)


@pytest.mark.parametrize("name", EXAMPLE_FILES)
def test_examples_have_identical_event_sequences(name: str) -> None:
    _compare(example_source(name), limits={"max_steps": 600}, keyframe_interval=50)


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_samples_have_identical_event_sequences(name: str) -> None:
    _compare(SAMPLES[name], stdin="Ada\n", keyframe_interval=25, filter="boundaries_verbose")
