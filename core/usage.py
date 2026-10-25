"""Token accounting and session metrics.

Unknown fields stay None — never invent usage or cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ui.measure import format_count, format_duration


@dataclass
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None

    def add(self, other: "Usage") -> None:
        self.input_tokens = _sum(self.input_tokens, other.input_tokens)
        self.output_tokens = _sum(self.output_tokens, other.output_tokens)
        self.cached_tokens = _sum(self.cached_tokens, other.cached_tokens)
        self.reasoning_tokens = _sum(self.reasoning_tokens, other.reasoning_tokens)
        self.total_tokens = _sum(self.total_tokens, other.total_tokens)
        if self.total_tokens is None:
            parts = [self.input_tokens, self.output_tokens]
            if any(p is not None for p in parts):
                self.total_tokens = (self.input_tokens or 0) + (self.output_tokens or 0)


def parse_usage(raw: Mapping[str, Any] | None) -> Usage:
    if not raw:
        return Usage()
    prompt = _int(raw.get("prompt_tokens") or raw.get("input_tokens"))
    completion = _int(raw.get("completion_tokens") or raw.get("output_tokens"))
    cached = _int(raw.get("cached_tokens"))
    details = raw.get("prompt_tokens_details")
    if cached is None and isinstance(details, dict):
        cached = _int(details.get("cached_tokens"))
    reasoning = None
    cdetails = raw.get("completion_tokens_details")
    if isinstance(cdetails, dict):
        reasoning = _int(cdetails.get("reasoning_tokens"))
    total = _int(raw.get("total_tokens"))
    return Usage(
        input_tokens=prompt,
        output_tokens=completion,
        cached_tokens=cached,
        reasoning_tokens=reasoning,
        total_tokens=total,
    )


@dataclass
class Metrics:
    requests: int = 0
    tool_calls: int = 0
    files_read: int = 0
    files_modified: int = 0
    commands_executed: int = 0
    usage: Usage = field(default_factory=Usage)
    started: float = 0.0
    context_used: int | None = None
    context_window: int | None = None

    def summary_lines(self, elapsed: float) -> list[str]:
        u = self.usage
        lines = [
            f"Input tokens       {format_count(u.input_tokens)}",
            f"Output tokens      {format_count(u.output_tokens)}",
            f"Total tokens       {format_count(u.total_tokens)}",
            "",
            f"Requests                 {self.requests}",
            f"Tool calls              {self.tool_calls}",
            "",
            f"Session time          {format_duration(elapsed)}",
            "",
            "Estimated cost        Cost unavailable",
        ]
        return lines

    def context_label(self) -> str:
        used = self.context_used or self.usage.total_tokens
        window = self.context_window
        if used is None:
            return "Context —"
        if window:
            pct = int(100 * used / window) if window else 0
            return f"Context {format_count(used)} / {format_count(window)} · {pct}%"
        return f"Context {format_count(used)}"


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum(a: int | None, b: int | None) -> int | None:
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)
