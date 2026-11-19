"""Tool-use loop against Claude on AWS Bedrock."""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from . import data
from .evidence import EvidenceCollector, check_citations
from .models import AskResponse
from .tools import TOOLS, tool_definitions

log = logging.getLogger("spend_assistant")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system.md"


class LLMError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


class FinalAnswer(BaseModel):
    """Structured final output. The LLM writes prose and names policy sections; code builds the evidence."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "declined"]
    answer: str
    policy_sections: list[str]


def model_id() -> str:
    return os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5-5")


def llm_label() -> str:
    return f"bedrock:{model_id()}"


@lru_cache
def system_prompt() -> str:
    return PROMPT_PATH.read_text().replace("{{POLICY}}", data.policy_text().strip())


@lru_cache
def bedrock_client() -> anthropic.AnthropicBedrock:
    # The SDK reads AWS_BEARER_TOKEN_BEDROCK, ANTHROPIC_BEDROCK_BASE_URL and AWS_REGION itself.
    # An empty value copied from .env.example would be used as-is (empty bearer token, empty URL), so drop it.
    for var in ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_BEDROCK_BASE_URL"):
        if os.environ.get(var, None) == "":
            del os.environ[var]
    return anthropic.AnthropicBedrock(
        timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "90")),
        max_retries=1,
    )


def _run_tool(name: str, raw_args: dict, collector: EvidenceCollector) -> tuple[str, bool]:
    """Validate LLM-sent arguments, run the tool, record evidence. Returns (content, is_error)."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"Unknown tool '{name}'. Available tools: {', '.join(TOOLS)}.", True
    try:
        args = tool.args_model.model_validate(raw_args)
    except ValidationError as e:
        log.info("tool %s rejected args %s: %s", name, raw_args, e.errors(include_url=False))
        return f"Invalid arguments for {name}. Fix them and call again:\n{e}", True
    result = tool.fn(args)
    collector.record(name, args.model_dump(mode="json", exclude_none=True), result)
    log.info("tool %s args=%s", name, args.model_dump_json(exclude_none=True))
    return json.dumps(result, default=str), False


def _build_response(final: FinalAnswer, collector: EvidenceCollector) -> AskResponse:
    policy_evidence, citation_warnings = check_citations(final.policy_sections)
    route = (["policy"] if policy_evidence else []) + (["data"] if collector.items else [])
    return AskResponse(
        status=final.status,
        answer=final.answer,
        route=route,
        policy_evidence=policy_evidence,
        data_evidence=collector.items,
        warnings=list(dict.fromkeys(collector.warnings)) + citation_warnings,
        llm=llm_label(),
    )


def ask(question: str) -> AskResponse:
    question = question.strip()
    if not question:
        raise LLMError("empty_question", "Question is empty.", 422)
    return _ask_bedrock(question)


def _ask_bedrock(question: str) -> AskResponse:
    client = bedrock_client()
    collector = EvidenceCollector()
    messages: list[dict] = [{"role": "user", "content": question}]
    max_iterations = int(os.environ.get("LLM_MAX_ITERATIONS", "6"))

    for _ in range(max_iterations):
        try:
            # No temperature: Claude Sonnet 5.5 rejects sampling parameters. Determinism comes from fixed tools and the output schema.
            resp = client.messages.create(
                model=model_id(),
                max_tokens=16000,
                system=system_prompt(),
                tools=tool_definitions(),
                messages=messages,
                output_config={
                    "effort": os.environ.get("LLM_EFFORT", "low"),
                    "format": {"type": "json_schema", "schema": FinalAnswer.model_json_schema()},
                },
            )
        except anthropic.APITimeoutError as e:
            raise LLMError("llm_timeout", "The language model did not respond in time. Please retry.", 504) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("llm_unreachable", f"Could not reach the language model: {e}", 502) from e
        except anthropic.APIStatusError as e:
            raise LLMError("llm_error", f"Language model returned HTTP {e.status_code}.", 502) from e
        except RuntimeError as e:
            # Raised by the Bedrock client before sending when it finds no bearer token and no AWS credentials.
            raise LLMError(
                "llm_auth",
                "No Bedrock credentials found. Set AWS_BEARER_TOKEN_BEDROCK or AWS credentials (see .env.example).",
                502,
            ) from e

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    content, is_error = _run_tool(block.name, block.input, collector)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
            continue

        if resp.stop_reason == "refusal":
            raise LLMError("llm_refused", "The language model declined to process this request.")
        if resp.stop_reason == "max_tokens":
            raise LLMError("llm_truncated", "The language model's answer was cut off. Please retry.")

        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            final = FinalAnswer.model_validate_json(text)
        except ValidationError as e:
            log.warning("unparseable final output: %r", text[:500])
            raise LLMError("llm_bad_output", "The language model returned an answer in an unexpected format.") from e
        log.info("answer status=%s sections=%s tools=%d", final.status, final.policy_sections, len(collector.items))
        return _build_response(final, collector)

    raise LLMError("iteration_cap", f"The assistant needed more than {max_iterations} steps. Try a narrower question.")

