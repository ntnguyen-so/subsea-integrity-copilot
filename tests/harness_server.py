"""Isolated HTTP/worker fixture; deliberately injects failures, never used by production."""

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from subsea_copilot import api
from subsea_copilot.config import Settings
from subsea_copilot.llm.copilot_cli import render_prompt
from subsea_copilot.runtime.scripted import ScriptedChatModel


class HarnessProbe(ScriptedChatModel):
    max_prompt_chars: int = 144000

    def _generate(self, messages, **kwargs):
        context = json.loads(next(
            message.content.split("\nBOUND_CONTEXT\n", 1)[1]
            for message in messages
            if isinstance(message, SystemMessage) and "\nBOUND_CONTEXT\n" in message.content
        ))
        repairing = any(
            isinstance(message, HumanMessage)
            and message.additional_kwargs.get("validation_repair")
            for message in messages
        )
        response = super()._generate(messages, **kwargs)
        message = response.generations[0].message
        if context["phase"] == "plan" and not repairing:
            plan = json.loads(message.content)
            plan["schema_version"] = 999
            message.content = json.dumps(plan)
        elif context["phase"] == "answer" and "denial control" in context["question"]:
            message.content = ""
            message.tool_calls = [{
                "id": "controlled-denial", "name": "unauthorized.write",
                "args": context["scope"],
            }]
        elif self.role == "event_diagnosis" and context["phase"] == "answer":
            requests = [
                call for item in messages if isinstance(item, AIMessage)
                for call in item.tool_calls
            ]
            if not any(call["args"].get("receipt_id") for call in requests):
                archives = [
                    item for item in messages if isinstance(item, HumanMessage)
                    and isinstance(item.content, str) and '"archived_receipts":' in item.content
                ]
                if archives:
                    receipt = json.loads(archives[-1].content)["archived_receipts"][0]
                    message.content = ""
                    message.tool_calls = [{
                        "id": "controlled-rehydrate", "name": "evidence.get",
                        "args": {
                            **context["scope"], "ids": [], "receipt_id": receipt["receipt_id"],
                        },
                    }]
            if not message.tool_calls and not repairing:
                candidate = json.loads(message.content)
                candidate["limitations"].append("controlled_unknown_limitation")
                message.content = json.dumps(candidate)
        wire = render_prompt(messages, self.bound_schemas)
        if len(wire) > self.max_prompt_chars:
            raise AssertionError("The provider received an oversized model view.")
        message.response_metadata["test_prompt_sha256"] = hashlib.sha256(wire.encode()).hexdigest()
        return response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = replace(
        Settings.from_env(), port=args.port, tenant_id=args.tenant, runtime_dir=args.runtime_dir,
    )

    def probe(**kwargs: Any) -> HarnessProbe:
        return HarnessProbe(
            **kwargs, max_prompt_chars=110000 if kwargs["role"] == "event_diagnosis" else 144000,
        )

    api.ScriptedChatModel = probe
    uvicorn.run(api.create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
