#!/usr/bin/env python3
"""No-cost smoke test of the pinned Deep Agents SDK and bounded tool surface."""

from __future__ import annotations

import importlib.util
import json
import os
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


def _scripted_model() -> Any:
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

    scripted = ScriptedChatModel(
        messages=iter(
            [
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
        )
    )
    return scripted


def _smoke_passed(
    *,
    workspace_edit_succeeded: bool,
    out_of_scope_write_denied: bool,
    traversal_write_denied: bool,
    traversal_read_denied: bool,
    tool_names: list[str],
    expected_tools: list[str],
    network_attempts: list[str],
) -> bool:
    return (
        workspace_edit_succeeded
        and out_of_scope_write_denied
        and traversal_write_denied
        and traversal_read_denied
        and tool_names == expected_tools
        and {"delete", "execute", "task", "write_todos"}.isdisjoint(tool_names)
        and not network_attempts
    )


def run_smoke() -> dict[str, Any]:
    worker = _load_worker()
    actual_version = version("deepagents")
    if actual_version != worker.EXPECTED_DEEPAGENTS_VERSION:
        raise RuntimeError(
            f"deepagents=={worker.EXPECTED_DEEPAGENTS_VERSION} is required; found {actual_version}"
        )
    packet = {
        "schema_version": 1,
        "policy": {
            "controller_is_sole_acceptor": True,
            "allowed_paths": ["app/"],
        },
    }
    scripted = _scripted_model()
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
        workspace = Path(temporary) / "workspace"
        target = workspace / "app" / "value.txt"
        forbidden_target = workspace / "tests" / "forbidden.txt"
        escaped_write_target = Path(temporary) / "escape-write.txt"
        outside_secret = Path(temporary) / "outside-secret.txt"
        outside_canary = "DAIW_OUTSIDE_READ_CANARY"
        target.parent.mkdir(parents=True)
        target.write_text("before\n", encoding="utf-8")
        outside_secret.write_text(outside_canary + "\n", encoding="utf-8")
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
            "workspace_edit_succeeded": workspace_edit_succeeded,
            "out_of_scope_write_denied": out_of_scope_write_denied,
            "traversal_write_denied": traversal_write_denied,
            "traversal_read_denied": traversal_read_denied,
            "final_response_present": bool(final_content),
            "passed": passed,
        }
    ARTIFACTS.mkdir(exist_ok=True)
    output = ARTIFACTS / "deepagents-sdk-smoke.json"
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"artifact": str(output), **record}


def main() -> int:
    result = run_smoke()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
