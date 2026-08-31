#!/usr/bin/env python3
"""No-cost smoke test of the pinned Deep Agents SDK and bounded tool surface."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import socket
import tempfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = PACKAGE_ROOT / "scripts" / "deepagents_worker.py"
ARTIFACTS = PACKAGE_ROOT / "artifacts"


def _load_worker() -> Any:
    spec = importlib.util.spec_from_file_location("deepagents_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Deep Agents worker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scripted_model(
    *, forbidden_tool: str | None = None, command_target: Path | None = None
) -> Any:
    """Create the fake model lazily so importing this script needs no SDK extras."""
    from collections.abc import Callable, Iterator, Sequence  # noqa: PLC0415

    from langchain_core.language_models import LanguageModelInput  # noqa: PLC0415
    from langchain_core.language_models.chat_models import BaseChatModel  # noqa: PLC0415
    from langchain_core.messages import AIMessage, BaseMessage  # noqa: PLC0415
    from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: PLC0415
    from langchain_core.runnables import Runnable  # noqa: PLC0415
    from langchain_core.tools import BaseTool  # noqa: PLC0415
    from pydantic import Field  # noqa: PLC0415

    class ScriptedChatModel(BaseChatModel):
        messages: Iterator[AIMessage] = Field(exclude=True)
        observed_tools: list[str] = Field(default_factory=list)

        @property
        def _llm_type(self) -> str:
            return "openai"

        def _get_ls_params(self, **_: Any) -> dict[str, str]:
            return {"ls_provider": "openai", "ls_model_name": "gpt-5.2-codex"}

        def bind_tools(
            self,
            tools: Sequence[dict[str, Any] | type | Callable | BaseTool],
            **_: Any,
        ) -> Runnable[LanguageModelInput, AIMessage]:
            self.observed_tools = [
                tool.name
                if isinstance(tool, BaseTool)
                else str(tool.get("function", {}).get("name", ""))
                if isinstance(tool, dict)
                else getattr(tool, "__name__", str(tool))
                for tool in tools
            ]
            return self

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            del messages, stop, run_manager, kwargs
            return ChatResult(generations=[ChatGeneration(message=next(self.messages))])

    if forbidden_tool is not None:
        forbidden_arguments: dict[str, dict[str, Any]] = {
            "delete": {"file_path": "/app/delete-canary.txt"},
            "execute": {
                "command": f"touch {shlex.quote(str(command_target))}"
                if command_target is not None
                else "exit 0"
            },
            "task": {"description": "forbidden synthetic subagent dispatch"},
            "write_todos": {"todos": []},
        }
        if forbidden_tool not in forbidden_arguments:
            raise ValueError(f"unsupported forbidden tool probe: {forbidden_tool}")
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": forbidden_tool,
                        "args": forbidden_arguments[forbidden_tool],
                        "id": f"forbidden-{forbidden_tool}-dispatch",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="A forbidden dispatch unexpectedly returned."),
        ]
    else:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/tests/forbidden.txt",
                            "content": "must-not-exist\n",
                        },
                        "id": "write-forbidden-smoke",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {
                            "file_path": "/../escape-write.txt",
                            "content": "must-not-escape\n",
                        },
                        "id": "write-traversal-smoke",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/../outside-secret.txt"},
                        "id": "read-traversal-smoke",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {"file_path": "/app/value.txt"},
                        "id": "read-smoke",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "edit_file",
                        "args": {
                            "file_path": "/app/value.txt",
                            "old_string": "before\n",
                            "new_string": "after\n",
                        },
                        "id": "edit-smoke",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Candidate edit prepared; controller verification required."),
        ]
    scripted = ScriptedChatModel(messages=iter(messages))
    return scripted


def _error_contains(error: BaseException, expected: str) -> bool:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if expected in str(current):
            return True
        nested = getattr(current, "exceptions", ())
        if isinstance(nested, (list, tuple)):
            pending.extend(item for item in nested if isinstance(item, BaseException))
        for item in (current.__cause__, current.__context__):
            if isinstance(item, BaseException):
                pending.append(item)
    return False


def _assert_forbidden_dispatch_rejected(
    *, worker: Any, workspace: Path, packet: dict[str, Any]
) -> bool:
    delete_canary = workspace / "app" / "delete-canary.txt"
    execute_canary = workspace / "app" / "execute-canary.txt"
    delete_canary.write_text("must-remain\n", encoding="utf-8")
    for tool_name in ("execute", "delete", "task", "write_todos"):
        model = _scripted_model(forbidden_tool=tool_name, command_target=execute_canary)
        agent = worker.build_bounded_agent(
            model=model,
            profile_key="openai",
            workspace=workspace,
            packet=packet,
        )
        try:
            agent.invoke(
                {"messages": [{"role": "user", "content": "Run the synthetic probe."}]},
                config={"recursion_limit": 8},
            )
        except BaseException as exc:
            if not _error_contains(exc, f"forbidden tool call: {tool_name}"):
                raise AssertionError(
                    f"{tool_name} was not rejected by the controller dispatch boundary"
                ) from exc
        else:
            raise AssertionError(f"forbidden tool call unexpectedly completed: {tool_name}")
    if execute_canary.exists() or delete_canary.read_text(encoding="utf-8") != "must-remain\n":
        raise AssertionError("a forbidden tool dispatch changed the workspace")
    return True


def _smoke_passed(
    *,
    workspace_edit_succeeded: bool,
    out_of_scope_write_denied: bool,
    traversal_write_denied: bool,
    traversal_read_denied: bool,
    tool_names: list[str],
    expected_tools: list[str],
    network_attempts: list[str],
    forbidden_tool_calls_rejected: bool,
) -> bool:
    return (
        workspace_edit_succeeded
        and out_of_scope_write_denied
        and traversal_write_denied
        and traversal_read_denied
        and tool_names == expected_tools
        and {"delete", "execute", "task", "write_todos"}.isdisjoint(tool_names)
        and forbidden_tool_calls_rejected
        and not network_attempts
    )


def _assert_os_network_disabled() -> None:
    errors: list[str] = []
    try:
        socket.getaddrinfo("docs.langchain.com", 443)
    except OSError:
        pass
    else:
        errors.append("DNS resolution unexpectedly succeeded")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        probe.connect(("1.1.1.1", 443))
    except OSError:
        pass
    else:
        errors.append("external socket connection unexpectedly succeeded")
    finally:
        probe.close()
    if errors:
        raise RuntimeError("; ".join(errors))


def run_smoke(
    *, output: Path | None = None, assert_os_network_disabled: bool = False
) -> dict[str, Any]:
    if assert_os_network_disabled:
        _assert_os_network_disabled()
    packet = {
        "schema_version": 1,
        "policy": {
            "controller_is_sole_acceptor": True,
            "allowed_paths": ["app/"],
        },
    }
    network_attempts: list[str] = []

    def deny_network(*args: Any, **kwargs: Any) -> Any:
        del kwargs
        network_attempts.append(repr(args[:2]))
        raise RuntimeError("network access is disabled during the SDK smoke")

    disabled_environment = {
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "DEEPAGENTS_CODE_OFFLINE": "1",
        "DEEPAGENTS_CODE_NO_UPDATE_CHECK": "1",
    }
    with (
        tempfile.TemporaryDirectory(prefix="daiw-sdk-smoke-") as temporary,
        mock.patch.dict(os.environ, disabled_environment, clear=False),
        mock.patch("socket.create_connection", side_effect=deny_network),
        mock.patch("socket.getaddrinfo", side_effect=deny_network),
        mock.patch.object(socket.socket, "connect", side_effect=deny_network),
    ):
        worker = _load_worker()
        actual_version = version("deepagents")
        if actual_version != worker.EXPECTED_DEEPAGENTS_VERSION:
            raise RuntimeError(
                f"deepagents=={worker.EXPECTED_DEEPAGENTS_VERSION} is required; "
                f"found {actual_version}"
            )
        scripted = _scripted_model()
        workspace = Path(temporary) / "workspace"
        target = workspace / "app" / "value.txt"
        forbidden_target = workspace / "tests" / "forbidden.txt"
        escaped_write_target = Path(temporary) / "escape-write.txt"
        outside_secret = Path(temporary) / "outside-secret.txt"
        outside_canary = "DAIW_OUTSIDE_READ_CANARY"
        target.parent.mkdir(parents=True)
        target.write_text("before\n", encoding="utf-8")
        outside_secret.write_text(outside_canary + "\n", encoding="utf-8")
        forbidden_tool_calls_rejected = _assert_forbidden_dispatch_rejected(
            worker=worker,
            workspace=workspace,
            packet=packet,
        )
        agent = worker.build_bounded_agent(
            model=scripted,
            profile_key="openai",
            workspace=workspace,
            packet=packet,
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "Apply the scripted edit."}]},
            config={"recursion_limit": 18},
        )
        final_content = worker._final_content(result)
        tool_results = {
            getattr(message, "tool_call_id", None): str(getattr(message, "content", ""))
            for message in result.get("messages", [])
            if getattr(message, "tool_call_id", None)
        }
        traversal_write_output = tool_results.get("write-traversal-smoke", "").lower()
        traversal_read_output = tool_results.get("read-traversal-smoke", "")
        traversal_write_denied = not escaped_write_target.exists() and any(
            marker in traversal_write_output for marker in ("denied", "not allowed", "error")
        )
        traversal_read_denied = outside_canary not in traversal_read_output and any(
            marker in traversal_read_output.lower() for marker in ("denied", "not allowed", "error")
        )
        tool_names = sorted(scripted.observed_tools)
        expected_tools = sorted(worker.ALLOWED_TOOLS)
        workspace_edit_succeeded = target.read_text(encoding="utf-8") == "after\n"
        out_of_scope_write_denied = not forbidden_target.exists()
        passed = _smoke_passed(
            workspace_edit_succeeded=workspace_edit_succeeded,
            out_of_scope_write_denied=out_of_scope_write_denied,
            traversal_write_denied=traversal_write_denied,
            traversal_read_denied=traversal_read_denied,
            tool_names=tool_names,
            expected_tools=expected_tools,
            network_attempts=network_attempts,
            forbidden_tool_calls_rejected=forbidden_tool_calls_rejected,
        )
        record = {
            "schema_version": 1,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runtime": "deepagents",
            "runtime_version": actual_version,
            "network_request_made": bool(network_attempts),
            "network_attempts": len(network_attempts),
            "model": "openai:gpt-5.2-codex (scripted, no transport)",
            "profile_provider": "openai",
            "observed_tools": tool_names,
            "forbidden_tools_absent": all(
                item not in tool_names for item in ("delete", "execute", "task", "write_todos")
            ),
            "forbidden_tool_calls_rejected": forbidden_tool_calls_rejected,
            "workspace_edit_succeeded": workspace_edit_succeeded,
            "out_of_scope_write_denied": out_of_scope_write_denied,
            "traversal_write_denied": traversal_write_denied,
            "traversal_read_denied": traversal_read_denied,
            "final_response_present": bool(final_content),
            "passed": passed,
        }
    output = output or ARTIFACTS / "deepagents-sdk-smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"artifact": str(output), **record}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert-os-network-disabled", action="store_true")
    args = parser.parse_args()
    result = run_smoke(
        output=args.output,
        assert_os_network_disabled=args.assert_os_network_disabled,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
