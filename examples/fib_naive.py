"""Naive recursive Fibonacci: the same sub-problems are recomputed again and again (memoization candidate)."""


def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


if __name__ == "__main__":
    result = fib(15)
    print("fib(15) =", result)
