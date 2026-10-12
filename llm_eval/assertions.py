from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from jsonschema import ValidationError, validate

from .models import AssertionResult


class Assertion(ABC):
    type: str

    @abstractmethod
    def evaluate(self, response: str, config: dict[str, Any]) -> AssertionResult:
        raise NotImplementedError


class RegexAssertion(Assertion):
    type = "regex"

    def evaluate(self, response: str, config: dict[str, Any]) -> AssertionResult:
        pattern = config["pattern"]
        flags = re.IGNORECASE if config.get("ignore_case") else 0
        passed = re.search(pattern, response, flags) is not None
        return AssertionResult(self.type, passed, f"pattern {'matched' if passed else 'did not match'}")


class JsonSchemaAssertion(Assertion):
    type = "json_schema"

    def evaluate(self, response: str, config: dict[str, Any]) -> AssertionResult:
        try:
            validate(json.loads(response), config["schema"])
        except (ValueError, ValidationError) as exc:
            return AssertionResult(self.type, False, f"invalid JSON/schema: {exc.message if hasattr(exc, 'message') else exc}")
        return AssertionResult(self.type, True, "JSON matches schema")


def _json_path(value: Any, path: str) -> Any:
    current = value
    for part in path.lstrip("$.").split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


class RuleAssertion(Assertion):
    type = "rule"

    def evaluate(self, response: str, config: dict[str, Any]) -> AssertionResult:
        operation = config["operation"]
        actual: Any = response
        if "path" in config:
            try:
                actual = _json_path(json.loads(response), config["path"])
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                return AssertionResult(self.type, False, f"path lookup failed: {exc}")
        expected = config.get("value")
        if operation == "equals": passed = actual == expected
        elif operation == "contains": passed = expected in actual
        elif operation == "regex": passed = re.search(str(expected), str(actual)) is not None
        elif operation == "gte": passed = actual >= expected
        elif operation == "lte": passed = actual <= expected
        else: raise ValueError(f"unsupported rule operation: {operation}")
        return AssertionResult(self.type, passed, f"{actual!r} {'satisfied' if passed else 'did not satisfy'} {operation}")


class AssertionRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Assertion] = {}

    def register(self, plugin: Assertion) -> None:
        if plugin.type in self._plugins: raise ValueError(f"assertion already registered: {plugin.type}")
        self._plugins[plugin.type] = plugin

    def evaluate(self, assertion_type: str, response: str, config: dict[str, Any]) -> AssertionResult:
        try: plugin = self._plugins[assertion_type]
        except KeyError as exc: raise ValueError(f"unknown assertion type: {assertion_type}") from exc
        return plugin.evaluate(response, config)

    @classmethod
    def builtins(cls) -> "AssertionRegistry":
        registry = cls()
        for plugin in (RegexAssertion(), JsonSchemaAssertion(), RuleAssertion()): registry.register(plugin)
        return registry
