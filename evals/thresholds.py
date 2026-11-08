"""Thresholds for --check, read from evals/thresholds.json.

"floors" are minimums and "ceilings" are maximums. Each key is a dotted path into
the "metrics" part of latest.json, such as "pairs.exact.overall.status_accuracy".
A path that leads to a rate uses its "rate" value.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Thresholds:
    floors: dict[str, float]
    ceilings: dict[str, float]


def load_thresholds(path: Path) -> Thresholds:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Thresholds(
        floors={k: float(v) for k, v in data.get("floors", {}).items()},
        ceilings={k: float(v) for k, v in data.get("ceilings", {}).items()},
    )


def lookup(metrics: dict[str, Any], path: str) -> float | None:
    node: Any = metrics
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if isinstance(node, dict):
        node = node.get("rate")
    if isinstance(node, bool) or not isinstance(node, int | float):
        return None
    return float(node)


def check_thresholds(metrics: dict[str, Any], thresholds: Thresholds) -> list[str]:
    """One message per metric that is missing or past its threshold."""
    failures: list[str] = []
    for path, floor in thresholds.floors.items():
        value = lookup(metrics, path)
        if value is None:
            failures.append(f"{path}: not measured in this run (floor {floor:g})")
        elif value < floor - 1e-9:
            failures.append(f"{path}: {value:.4f} is below the floor {floor:g}")
    for path, ceiling in thresholds.ceilings.items():
        value = lookup(metrics, path)
        if value is None:
            failures.append(f"{path}: not measured in this run (ceiling {ceiling:g})")
        elif value > ceiling + 1e-9:
            failures.append(f"{path}: {value:.4f} is above the ceiling {ceiling:g}")
    return failures
