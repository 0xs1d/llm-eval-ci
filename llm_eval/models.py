from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AssertionSpec:
    type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    id: str
    prompt: str
    provider: str
    assertions: tuple[AssertionSpec, ...]
    params: dict[str, Any] = field(default_factory=dict)
    flaky_retries: int = 0


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    raw: Any = None
    latency_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssertionResult:
    type: str
    passed: bool
    message: str
    score: float = 1.0


@dataclass
class EvalResult:
    case_id: str
    provider: str
    status: str
    score: float
    attempts: int
    seed: int | None
    assertion_results: list[AssertionResult] = field(default_factory=list)
    response: str | None = None
    error: str | None = None
    flaky: bool = False
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "provider": self.provider,
            "status": self.status, "score": self.score,
            "attempts": self.attempts, "seed": self.seed,
            "assertions": [a.__dict__ for a in self.assertion_results],
            "response": self.response, "error": self.error,
            "flaky": self.flaky, "duration_ms": round(self.duration_ms, 3),
        }


@dataclass
class EvalReport:
    run_id: str
    suite: str
    started_at: str
    results: list[EvalResult]
    previous_run_id: str | None = None
    score_delta: float | None = None
    pass_rate_delta: float | None = None

    @property
    def score(self) -> float:
        return sum(r.score for r in self.results) / len(self.results) if self.results else 0.0

    @property
    def passed(self) -> int:
        return sum(r.status in ("passed", "flaky") for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "suite": self.suite, "started_at": self.started_at,
            "summary": {"total": len(self.results), "passed": self.passed,
                         "failed": len(self.results) - self.passed,
                         "pass_rate": self.passed / len(self.results) if self.results else 0.0,
                         "score": self.score, "score_delta": self.score_delta,
                         "pass_rate_delta": self.pass_rate_delta},
            "previous_run_id": self.previous_run_id,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def new(cls, run_id: str, suite: str, results: list[EvalResult]) -> "EvalReport":
        return cls(run_id, suite, datetime.now(timezone.utc).isoformat(), results)
