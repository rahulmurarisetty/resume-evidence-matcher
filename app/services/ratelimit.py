"""In-memory token buckets.

Each limited action ("auth", "analyses", "suggestions", "exports") has a rate such
as 10 per minute. A request is checked against one bucket per key it carries (the
client address, the account, the email tried at login) and is allowed only when
every one of those buckets has a token left; then one token is taken from each.

The buckets live in this process. With several replicas each one counts on its
own, so the real limit is the rate times the number of replicas. A shared store
(Redis, for example) is needed before running more than one.
"""

import math
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

_UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0, "day": 86400.0}
_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*$", re.IGNORECASE)

# Keys a request can be limited by. "ip" uses the rate times the IP multiplier, so
# several people behind one address don't use up each other's allowance.
KeyKind = str
IP = "ip"


@dataclass(frozen=True)
class Rate:
    count: int
    period_seconds: float

    @classmethod
    def parse(cls, text: str) -> "Rate":
        """Read "10/minute", "30/hour", "5/second" or "100/day" (plural units too)."""
        match = _RATE_RE.match(text)
        if match is None:
            raise ValueError(
                f'"{text}" is not a rate. Write it as a count and a unit, such as "10/minute".'
            )
        count = int(match.group(1))
        if count < 1:
            raise ValueError(f'"{text}" allows nothing. Use a count of 1 or more.')
        return cls(count, _UNITS[match.group(2).lower()])

    @property
    def per_second(self) -> float:
        return self.count / self.period_seconds

    def scaled(self, factor: float) -> "Rate":
        return Rate(max(1, math.floor(self.count * factor)), self.period_seconds)


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(
        self,
        rates: Mapping[str, Rate],
        *,
        ip_multiplier: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = 100_000,
    ) -> None:
        self._rates = dict(rates)
        self._ip_multiplier = ip_multiplier
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: dict[tuple[str, KeyKind, str], _Bucket] = {}
        self._lock = threading.Lock()

    def rate(self, action: str, kind: KeyKind) -> Rate:
        rate = self._rates[action]
        return rate.scaled(self._ip_multiplier) if kind == IP else rate

    def hit(self, action: str, keys: Iterable[tuple[KeyKind, str]]) -> float | None:
        """Take a token for `action` from each key's bucket. Returns None when the
        request is allowed, or the seconds to wait when any bucket is empty (then
        no token is taken from any of them)."""
        now = self._clock()
        with self._lock:
            checked: list[tuple[_Bucket, Rate]] = []
            wait = 0.0
            for kind, key in keys:
                rate = self.rate(action, kind)
                bucket = self._refilled((action, kind, key), rate, now)
                checked.append((bucket, rate))
                if bucket.tokens < 1:
                    wait = max(wait, (1 - bucket.tokens) / rate.per_second)
            if wait > 0:
                return wait
            for bucket, _ in checked:
                bucket.tokens -= 1
            if len(self._buckets) > self._max_buckets:
                self._prune(now)
            return None

    def _refilled(self, name: tuple[str, KeyKind, str], rate: Rate, now: float) -> _Bucket:
        bucket = self._buckets.get(name)
        if bucket is None:
            bucket = self._buckets[name] = _Bucket(tokens=float(rate.count), updated=now)
            return bucket
        elapsed = max(0.0, now - bucket.updated)
        bucket.tokens = min(float(rate.count), bucket.tokens + elapsed * rate.per_second)
        bucket.updated = now
        return bucket

    def _prune(self, now: float) -> None:
        """Forget buckets that have filled up again: a new bucket starts full, so
        dropping them changes nothing. If that isn't enough, forget the ones used
        longest ago."""
        for name, bucket in list(self._buckets.items()):
            rate = self.rate(name[0], name[1])
            if bucket.tokens + (now - bucket.updated) * rate.per_second >= rate.count:
                del self._buckets[name]
        excess = len(self._buckets) - self._max_buckets // 2
        if excess > 0:
            oldest = sorted(self._buckets, key=lambda n: self._buckets[n].updated)[:excess]
            for name in oldest:
                del self._buckets[name]

    def __len__(self) -> int:
        return len(self._buckets)


def retry_after_seconds(wait: float) -> int:
    """The Retry-After value: whole seconds, at least 1."""
    return max(1, math.ceil(wait))
