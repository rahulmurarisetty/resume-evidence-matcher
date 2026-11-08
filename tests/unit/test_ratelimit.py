import pytest

from app.services.ratelimit import IP, Rate, RateLimiter, retry_after_seconds


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("text", "count", "period"),
    [
        ("10/minute", 10, 60),
        ("30/hour", 30, 3600),
        (" 5 / seconds ", 5, 1),
        ("100/Day", 100, 86400),
    ],
)
def test_parse(text: str, count: int, period: float) -> None:
    assert Rate.parse(text) == Rate(count, period)


@pytest.mark.parametrize("text", ["10", "ten/minute", "10/week", "0/minute", "-1/hour", ""])
def test_parse_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        Rate.parse(text)


def test_bucket_empties_and_refills() -> None:
    clock = Clock()
    limiter = RateLimiter({"auth": Rate(3, 60)}, clock=clock)
    keys = [("email", "a")]
    assert [limiter.hit("auth", keys) for _ in range(3)] == [None, None, None]
    wait = limiter.hit("auth", keys)
    assert wait == pytest.approx(20.0)  # one token comes back every 20 seconds
    clock.now += 19
    assert limiter.hit("auth", keys) == pytest.approx(1.0)
    clock.now += 1
    assert limiter.hit("auth", keys) is None
    assert limiter.hit("auth", keys) is not None
    clock.now += 3600  # refills to the cap, no further
    assert [limiter.hit("auth", keys) for _ in range(4)][-1] is not None


def test_keys_and_actions_are_separate() -> None:
    limiter = RateLimiter({"auth": Rate(1, 60), "exports": Rate(1, 60)}, clock=Clock())
    assert limiter.hit("auth", [("email", "a")]) is None
    assert limiter.hit("auth", [("email", "b")]) is None
    assert limiter.hit("exports", [("email", "a")]) is None
    assert limiter.hit("auth", [("email", "a")]) is not None


def test_a_request_takes_a_token_only_when_every_key_allows_it() -> None:
    limiter = RateLimiter({"analyses": Rate(2, 60)}, clock=Clock())
    assert limiter.hit("analyses", [("user", "u1")]) is None
    assert limiter.hit("analyses", [("user", "u1")]) is None
    # u1 is out, so the shared address loses nothing for this refused request.
    assert limiter.hit("analyses", [(IP, "10.0.0.1"), ("user", "u1")]) is not None
    assert limiter.hit("analyses", [(IP, "10.0.0.1"), ("user", "u2")]) is None
    assert limiter.hit("analyses", [(IP, "10.0.0.1"), ("user", "u3")]) is None


def test_ip_buckets_use_the_multiplier() -> None:
    limiter = RateLimiter({"auth": Rate(2, 60)}, ip_multiplier=3, clock=Clock())
    assert limiter.rate("auth", IP) == Rate(6, 60)
    assert limiter.rate("auth", "email") == Rate(2, 60)
    results = [limiter.hit("auth", [(IP, "1.2.3.4")]) for _ in range(7)]
    assert results[:6] == [None] * 6 and results[6] is not None


def test_memory_stays_bounded() -> None:
    clock = Clock()
    limiter = RateLimiter({"auth": Rate(1, 1)}, clock=clock, max_buckets=10)
    for i in range(10):
        limiter.hit("auth", [("email", str(i))])
    clock.now += 5  # every bucket has refilled
    limiter.hit("auth", [("email", "new")])
    assert len(limiter) == 1
    for i in range(30):  # none refills in between: the oldest are forgotten
        limiter.hit("auth", [("email", f"busy{i}")])
    assert len(limiter) <= 10


def test_scaled_and_retry_after() -> None:
    assert Rate(5, 60).scaled(0.1) == Rate(1, 60)
    assert Rate(5, 60).scaled(2.5) == Rate(12, 60)
    assert retry_after_seconds(0.01) == 1
    assert retry_after_seconds(20.2) == 21
