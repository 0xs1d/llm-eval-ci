from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .assertions import AssertionRegistry
from .errors import TransientProviderError
from .models import EvalReport, EvalResult, TestCase
from .providers import Provider


class RateLimiter:
    def __init__(self, requests_per_second: float):
        self.interval = 1 / requests_per_second if requests_per_second > 0 else 0
        self.lock, self.next_at = threading.Lock(), 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic(); delay = max(0, self.next_at - now); self.next_at = max(now, self.next_at) + self.interval
        if delay: time.sleep(delay)


class EvalRunner:
    def __init__(self, providers: dict[str, Provider], *, registry: AssertionRegistry | None = None,
                 max_workers: int = 8, provider_limits: dict[str, float] | None = None,
                 max_retries: int = 2, backoff_seconds: float = 0.1):
        self.providers, self.registry = providers, registry or AssertionRegistry.builtins()
        self.max_workers, self.max_retries, self.backoff_seconds = max_workers, max_retries, backoff_seconds
        self.limiters = {name: RateLimiter(rate) for name, rate in (provider_limits or {}).items()}

    def _seed(self, suite_seed: int, case_id: str) -> int:
        digest = hashlib.sha256(f"{suite_seed}:{case_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    def _one(self, case: TestCase, suite_seed: int) -> EvalResult:
        provider = self.providers[case.provider]; seed = self._seed(suite_seed, case.id)
        started = time.perf_counter(); total_attempts = 0; first_result = None; last_error = None
        max_runs = 1 + case.flaky_retries
        for flaky_attempt in range(max_runs):
            response = None
            for retry in range(self.max_retries + 1):
                total_attempts += 1
                try:
                    if case.provider in self.limiters: self.limiters[case.provider].wait()
                    response = provider.complete(case.prompt, case.params, seed)
                    break
                except TransientProviderError as exc:
                    last_error = str(exc)
                    if retry < self.max_retries: time.sleep(self.backoff_seconds * (2 ** retry))
                except Exception as exc:
                    last_error = str(exc); break
            if response is None: continue
            assertions = [self.registry.evaluate(a.type, response.text, a.config) for a in case.assertions]
            passed = all(a.passed for a in assertions)
            result = EvalResult(case.id, case.provider, "passed" if passed else "failed",
                                sum(a.passed for a in assertions) / len(assertions) if assertions else 1.0,
                                total_attempts, seed, assertions, response.text, duration_ms=(time.perf_counter()-started)*1000)
            if first_result is None: first_result = result
            if passed:
                result.flaky = flaky_attempt > 0 or (first_result is not None and first_result.status == "failed")
                result.status = "flaky" if result.flaky else "passed"
                return result
        if first_result:
            first_result.attempts = total_attempts; first_result.duration_ms = (time.perf_counter()-started)*1000
            first_result.flaky = case.flaky_retries > 0
            return first_result
        return EvalResult(case.id, case.provider, "error", 0.0, total_attempts, seed, error=last_error,
                          duration_ms=(time.perf_counter()-started)*1000)

    def run(self, suite: str, cases: list[TestCase], suite_seed: int = 0, run_id: str = "local") -> EvalReport:
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = [pool.submit(self._one, case, suite_seed) for case in cases]
            results = [future.result() for future in futures]
        return EvalReport.new(run_id, suite, results)


def add_delta(report: EvalReport, previous_path: str | Path | None) -> EvalReport:
    if not previous_path or not Path(previous_path).exists(): return report
    old = json.loads(Path(previous_path).read_text()); summary = old.get("summary", {})
    report.previous_run_id = old.get("run_id")
    report.score_delta = report.score - summary.get("score", 0.0)
    rate = report.passed / len(report.results) if report.results else 0.0
    report.pass_rate_delta = rate - summary.get("pass_rate", 0.0)
    return report
