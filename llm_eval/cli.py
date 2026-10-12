from __future__ import annotations

import argparse
import json
from pathlib import Path

from .providers import FixtureProvider
from .runner import EvalRunner, add_delta
from .suite import load_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm-eval")
    parser.add_argument("suite")
    parser.add_argument("--output", default="eval-report.json")
    parser.add_argument("--previous")
    parser.add_argument("--run-id", default="local")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    name, seed, cases, provider_data = load_suite(args.suite)
    providers = {n: FixtureProvider(v.get("responses", {})) for n, v in provider_data.items()}
    if "default" not in providers: providers["default"] = FixtureProvider({c.prompt: "" for c in cases})
    report = add_delta(EvalRunner(providers, max_workers=args.workers).run(name, cases, seed, args.run_id), args.previous)
    Path(args.output).write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    print(f"{report.passed}/{len(report.results)} passed; score={report.score:.3f}; report={args.output}")
    return 0 if report.passed == len(report.results) else 1


if __name__ == "__main__": raise SystemExit(main())
