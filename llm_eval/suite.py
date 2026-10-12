from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AssertionSpec, TestCase


def load_suite(path: str | Path) -> tuple[str, int, list[TestCase], dict[str, dict[str, Any]]]:
    source = Path(path)
    data = yaml.safe_load(source.read_text()) or {}
    cases = []
    seen: set[str] = set()
    for raw in data.get("tests", []):
        case_id = raw["id"]
        if case_id in seen: raise ValueError(f"duplicate test id: {case_id}")
        seen.add(case_id)
        assertions = tuple(AssertionSpec(a["type"], {k: v for k, v in a.items() if k != "type"}) for a in raw["assertions"])
        cases.append(TestCase(case_id, raw["prompt"], raw.get("provider", "default"), assertions,
                              raw.get("params", {}), int(raw.get("flaky_retries", 0))))
    if not cases: raise ValueError("suite must contain at least one test")
    return data.get("name", source.stem), int(data.get("seed", 0)), cases, data.get("providers", {})
