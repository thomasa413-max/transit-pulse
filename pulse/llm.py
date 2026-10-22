"""Thin wrapper around the Claude API: one call, its usage and its cost.

Set PULSE_FAKE_LLM=1 to run the whole pipeline offline (tests, local preview):
the fake model returns deterministic answers built from the input.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

from . import config


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    fake: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        p_in, p_out = config.PRICES.get(self.model, (0.0, 0.0))
        if self.input_tokens > 100_000 and self.model == "claude-haiku-5-5":
            p_in, p_out = 0.50, 2.50
        return round((self.input_tokens * p_in + self.output_tokens * p_out) / 1_000_000, 6)

    def usage(self) -> dict:
        return {
            "model": self.model, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "cost_usd": self.cost_usd,
            "seconds": self.seconds, "fake": self.fake,
        }


def fake_mode() -> bool:
    return os.environ.get("PULSE_FAKE_LLM") == "1"


def call(system: str, user: str, *, model: str = config.MODEL_DAILY,
         max_tokens: int = 1500, fake_responder=None, schema: dict | None = None) -> LLMResult:
    """One model call. With `schema`, the answer is forced into a tool call whose
    input must match the JSON schema, so the result is always parseable JSON."""
    start = time.monotonic()
    if fake_mode():
        text = fake_responder(user) if fake_responder else "{}"
        return LLMResult(text=text, model=model, input_tokens=len(system + user) // 4,
                         output_tokens=len(text) // 4, seconds=round(time.monotonic() - start, 2),
                         fake=True)

    import anthropic  # imported lazily so tests run without the package

    client = anthropic.Anthropic(max_retries=3)
    kwargs = {}
    if schema:
        kwargs["tools"] = [{"name": "answer", "description": "Return the answer.", "input_schema": schema}]
        kwargs["tool_choice"] = {"type": "tool", "name": "answer"}
    def send(**extra):
        return client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                      messages=[{"role": "user", "content": user}], **extra)

    try:
        msg = send(**kwargs)
    except anthropic.BadRequestError as exc:
        # Some models refuse a forced tool choice: offer the tool without forcing it.
        if schema and "tool_choice" in str(exc):
            kwargs["tool_choice"] = {"type": "auto"}
            msg = send(**kwargs)
        else:
            raise
    tool_inputs = [b.input for b in msg.content if getattr(b, "type", "") == "tool_use"]
    if tool_inputs:
        text = json.dumps(tool_inputs[0], ensure_ascii=False)
    else:
        text = "".join(getattr(b, "text", "") for b in msg.content)
    return LLMResult(
        text=text, model=model,
        input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
        seconds=round(time.monotonic() - start, 2),
        extra={"stop_reason": msg.stop_reason},
    )


def parse_json(text: str) -> dict:
    """Read the first JSON object in a model answer (tolerates code fences)."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise
