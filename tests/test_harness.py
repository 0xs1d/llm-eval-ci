import unittest
import json
import tempfile
from pathlib import Path
from urllib.error import HTTPError

from llm_eval.assertions import AssertionRegistry
from llm_eval.errors import PermanentProviderError, ProviderConfigurationError, TransientProviderError
from llm_eval.models import AssertionSpec, ProviderResponse, TestCase
from llm_eval.providers import CallableProvider, OpenAICompatibleProvider
from llm_eval.reporting import JsonReportStore
from llm_eval.runner import EvalRunner
from llm_eval.suite import load_suite


class HarnessTests(unittest.TestCase):
    def test_builtin_assertions(self):
        registry = AssertionRegistry.builtins()
        self.assertTrue(registry.evaluate("regex", "Hello 30 days", {"pattern": r"30 days"}).passed)
        self.assertTrue(registry.evaluate("rule", '{"score": 8}', {
            "operation": "gte", "path": "$.score", "value": 7}).passed)
        self.assertTrue(registry.evaluate("json_schema", '{"ok":true}', {
            "schema": {"type": "object", "required": ["ok"]}}).passed)

    def test_parallel_runner_and_deterministic_seed(self):
        seeds = []
        def answer(prompt, params, seed):
            seeds.append(seed)
            return ProviderResponse("yes")
        case = TestCase("one", "question", "fake", (AssertionSpec("regex", {"pattern": "yes"}),))
        runner = EvalRunner({"fake": CallableProvider(answer)}, max_workers=2)
        report = runner.run("suite", [case], suite_seed=10)
        self.assertEqual(report.passed, 1)
        self.assertEqual(seeds[0], runner._seed(10, "one"))

    def test_transient_error_is_retried(self):
        calls = 0
        def answer(prompt, params, seed):
            nonlocal calls
            calls += 1
            if calls == 1: raise TransientProviderError("busy")
            return "ok"
        case = TestCase("retry", "q", "fake", (AssertionSpec("rule", {"operation": "equals", "value": "ok"}),))
        result = EvalRunner({"fake": CallableProvider(answer)}, backoff_seconds=0).run("s", [case]).results[0]
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.attempts, 2)

    def test_flaky_case_is_marked_but_passes(self):
        calls = 0
        def answer(prompt, params, seed):
            nonlocal calls
            calls += 1
            return "bad" if calls == 1 else "good"
        case = TestCase("flaky", "q", "fake", (AssertionSpec("rule", {"operation": "equals", "value": "good"}),), flaky_retries=1)
        report = EvalRunner({"fake": CallableProvider(answer)}).run("s", [case])
        self.assertEqual(report.passed, 1)
        self.assertTrue(report.results[0].flaky)

    def test_suite_loader_and_report_store(self):
        with tempfile.TemporaryDirectory() as directory:
            suite_path = Path(directory) / "suite.yaml"
            suite_path.write_text("""name: loaded\nseed: 9\ntests:\n  - id: one\n    prompt: hi\n    assertions:\n      - type: regex\n        pattern: ok\n""")
            name, seed, cases, providers = load_suite(suite_path)
            self.assertEqual((name, seed, cases[0].id), ("loaded", 9, "one"))
            report = EvalRunner({"default": CallableProvider(lambda *_: "ok")}).run(name, cases, seed, "r1")
            store = JsonReportStore(Path(directory) / "history")
            saved = store.save(report)
            self.assertEqual(json.loads(saved.read_text())["run_id"], "r1")
            self.assertEqual(store.load("r1")["summary"]["passed"], 1)
            self.assertEqual(store.latest()["run_id"], "r1")

    def test_openai_compatible_adapter_is_injectable_and_forwards_seed(self):
        captured = {}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return json.dumps({"choices": [{"message": {"content": "hello"}}], "usage": {"total_tokens": 3}}).encode()

        def transport(request, timeout):
            captured.update({"body": json.loads(request.data), "auth": request.headers.get("Authorization"), "timeout": timeout})
            return Response()

        result = OpenAICompatibleProvider("https://demo.invalid/chat", api_key="demo-secret",
                                          model="demo", timeout_seconds=2, transport=transport).complete("hi", {}, 7)
        self.assertEqual(result.text, "hello")
        self.assertEqual(captured["body"]["seed"], 7)
        self.assertEqual(captured["body"]["model"], "demo")
        self.assertEqual(captured["auth"], "Bearer demo-secret")
        self.assertEqual(result.usage["total_tokens"], 3)

    def test_openai_compatible_adapter_classifies_errors(self):
        def timeout_transport(request, timeout): raise TimeoutError("slow")
        with self.assertRaises(TransientProviderError):
            OpenAICompatibleProvider("https://demo.invalid", transport=timeout_transport).complete("hi", {})

        def unauthorized_transport(request, timeout):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)
        with self.assertRaises(PermanentProviderError):
            OpenAICompatibleProvider("https://demo.invalid", transport=unauthorized_transport).complete("hi", {})
        with self.assertRaises(ProviderConfigurationError): OpenAICompatibleProvider("")


if __name__ == "__main__": unittest.main()
