#!/usr/bin/env python3
"""Evaluate a deliberately small pure-function subset without executing candidate code."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 2
MAX_CALLS = 256
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
TRUSTED_VERIFIER_COMPLETION = "DAIW_TRUSTED_VERIFIER_COMPLETED:v1"
_MODULE_PATTERN = re.compile(r"app(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_CALLABLE_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_ALLOWED_IMPORTS = {
    ("__future__", ("annotations",)),
    ("app.events", ("RecordEvent",)),
}
_ALLOWED_STRING_METHODS = {"casefold", "join", "lower", "split", "strip", "upper"}


class CandidateProbeError(RuntimeError):
    """Candidate source is outside the verifier subset or failed its calls."""


def _validate_target(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"module", "callable"}:
        raise ValueError(f"{label} must contain only module and callable")
    module = value["module"]
    callable_name = value["callable"]
    if not isinstance(module, str) or _MODULE_PATTERN.fullmatch(module) is None:
        raise ValueError(f"{label} module is invalid")
    if not isinstance(callable_name, str) or _CALLABLE_PATTERN.fullmatch(callable_name) is None:
        raise ValueError(f"{label} callable is invalid")
    return {"module": module, "callable": callable_name}


def _validate_calls(calls: Any) -> list[dict[str, Any]]:
    if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_CALLS:
        raise ValueError(f"calls must contain between 1 and {MAX_CALLS} operations")
    validated: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise ValueError(f"call {index} must be an object")
        allowed = {"module", "callable", "argument", "factory"}
        if set(call) not in ({"module", "callable", "argument"}, allowed):
            raise ValueError(f"call {index} fields are invalid")
        target = _validate_target(
            {"module": call["module"], "callable": call["callable"]},
            f"call {index}",
        )
        record: dict[str, Any] = {**target, "argument": call["argument"]}
        if "factory" in call:
            record["factory"] = _validate_target(call["factory"], f"call {index} factory")
            if not isinstance(call["argument"], dict):
                raise ValueError(f"call {index} factory argument must be an object")
        validated.append(record)
    serialized = json.dumps(validated, separators=(",", ":"), sort_keys=True)
    if len(serialized.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("candidate request exceeds the trusted size limit")
    return validated


def _module_path(repository: Path, module: str) -> Path:
    relative = Path(*module.split(".")).with_suffix(".py")
    path = (repository / relative).resolve()
    try:
        path.relative_to(repository)
    except ValueError as exc:
        raise CandidateProbeError("candidate module escapes the repository") from exc
    if not path.is_file() or path.is_symlink():
        raise CandidateProbeError("candidate module must be a regular file")
    return path


def _single_pure_function(repository: Path, module: str, callable_name: str) -> ast.FunctionDef:
    if "." in callable_name:
        raise CandidateProbeError("candidate callable must be a top-level function")
    path = _module_path(repository, module)
    try:
        source = path.read_bytes()
        if len(source) > MAX_REQUEST_BYTES:
            raise CandidateProbeError("candidate module exceeds the trusted size limit")
        tree = ast.parse(source, filename=path.name)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise CandidateProbeError("candidate module cannot be parsed") from exc

    functions: list[ast.FunctionDef] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        if isinstance(node, ast.ImportFrom):
            imported = (node.module or "", tuple(alias.name for alias in node.names))
            if imported in _ALLOWED_IMPORTS and all(alias.asname is None for alias in node.names):
                continue
        if isinstance(node, ast.FunctionDef):
            functions.append(node)
            continue
        raise CandidateProbeError("candidate module contains executable or unsupported code")

    if len(functions) != 1 or functions[0].name != callable_name:
        raise CandidateProbeError("candidate callable is missing or ambiguous")
    function = functions[0]
    annotations = [argument.annotation for argument in function.args.args]
    annotations.append(function.returns)
    allowed_annotation_names = {"bool", "float", "int", "RecordEvent", "str"}
    if any(
        annotation is not None
        and (not isinstance(annotation, ast.Name) or annotation.id not in allowed_annotation_names)
        for annotation in annotations
    ):
        raise CandidateProbeError("candidate callable annotation is outside the pure subset")
    if function.type_comment is not None or getattr(function, "type_params", []):
        raise CandidateProbeError("candidate callable type metadata is outside the pure subset")
    if (
        function.decorator_list
        or function.args.posonlyargs
        or len(function.args.args) != 1
        or function.args.vararg is not None
        or function.args.kwonlyargs
        or function.args.kwarg is not None
        or function.args.defaults
        or function.args.kw_defaults
    ):
        raise CandidateProbeError("candidate callable signature is outside the pure subset")
    statements = list(function.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if len(statements) != 1 or not isinstance(statements[0], ast.Return):
        raise CandidateProbeError("candidate callable must contain one pure return expression")
    if statements[0].value is None:
        raise CandidateProbeError("candidate callable must return a value")
    return function


def _evaluate(node: ast.AST, environment: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            return node.value
    elif isinstance(node, ast.Name):
        if node.id in environment:
            return environment[node.id]
    elif isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise CandidateProbeError("private candidate attributes are forbidden")
        owner = _evaluate(node.value, environment)
        if isinstance(owner, dict) and node.attr in owner:
            return owner[node.attr]
    elif isinstance(node, ast.Subscript):
        owner = _evaluate(node.value, environment)
        key = _evaluate(node.slice, environment)
        if isinstance(owner, (dict, list, tuple)) and isinstance(key, (str, int)):
            try:
                return owner[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise CandidateProbeError("candidate subscript failed") from exc
    elif isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and value.conversion == -1:
                if value.format_spec is not None:
                    raise CandidateProbeError("candidate format specifications are forbidden")
                parts.append(str(_evaluate(value.value, environment)))
            else:
                raise CandidateProbeError("candidate formatted value is unsupported")
        return "".join(parts)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _evaluate(node.left, environment) + _evaluate(node.right, environment)
    elif isinstance(node, (ast.List, ast.Tuple)):
        values = [_evaluate(value, environment) for value in node.elts]
        return values if isinstance(node, ast.List) else tuple(values)
    elif isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise CandidateProbeError("candidate dictionary unpacking is forbidden")
        return {
            _evaluate(key, environment): _evaluate(value, environment)
            for key, value in zip(node.keys, node.values, strict=True)
        }
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.keywords or node.func.attr not in _ALLOWED_STRING_METHODS:
            raise CandidateProbeError("candidate call is outside the pure string subset")
        owner = _evaluate(node.func.value, environment)
        if not isinstance(owner, str):
            raise CandidateProbeError("candidate method receiver must be a string")
        arguments = [_evaluate(argument, environment) for argument in node.args]
        try:
            return getattr(owner, node.func.attr)(*arguments)
        except (AttributeError, TypeError, ValueError) as exc:
            raise CandidateProbeError("candidate string operation failed") from exc
    raise CandidateProbeError(f"candidate expression {type(node).__name__} is forbidden")


def run_candidate_calls(
    repository: Path,
    calls: list[dict[str, Any]],
) -> list[Any]:
    """Evaluate controller-selected pure expressions; never import candidate modules."""
    repository = repository.resolve(strict=True)
    if not repository.is_dir() or not (repository / "app").is_dir():
        raise ValueError("candidate repository must contain an app package")
    validated_calls = _validate_calls(calls)
    function_cache: dict[tuple[str, str], ast.FunctionDef] = {}
    results: list[Any] = []
    for call in validated_calls:
        key = (call["module"], call["callable"])
        if key not in function_cache:
            function_cache[key] = _single_pure_function(
                repository,
                call["module"],
                call["callable"],
            )
        function = function_cache[key]
        parameter = function.args.args[0].arg
        value = _evaluate(function.body[-1].value, {parameter: call["argument"]})
        try:
            encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CandidateProbeError("candidate result is not JSON-safe") from exc
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise CandidateProbeError("candidate result exceeds the trusted size limit")
        results.append(value)
    if len(json.dumps(results).encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise CandidateProbeError("candidate results exceed the trusted size limit")
    return results
