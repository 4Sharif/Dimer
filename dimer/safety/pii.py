"""Basic PII detection and redaction."""

from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CC_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
PROVIDER_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{10,}|AIza[A-Za-z0-9_-]{10,})\b"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Za-z0-9_.-]*(?:api[_-]?key|token|secret|password|credential)[A-Za-z0-9_.-]*"
    r"\s*[:=]\s*)([^\s,;]+)"
)
SENSITIVE_FIELD_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|credential)"
)


def redact_text(text: str) -> str:
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = SSN_RE.sub("[REDACTED_SSN]", text)
    text = CC_RE.sub(_redact_card_number, text)
    return text


def _redact_card_number(match: re.Match[str]) -> str:
    """Redact plausible payment-card numbers without hiding timestamp identifiers."""

    digits = [int(char) for char in match.group(0) if char.isdigit()]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return "[REDACTED_CC]" if checksum % 10 == 0 else match.group(0)


def redact_sensitive_text(text: str) -> str:
    """Best-effort redaction for PII and common credential shapes."""

    redacted = redact_text(text)
    redacted = BEARER_RE.sub("Bearer [REDACTED_SECRET]", redacted)
    redacted = PROVIDER_SECRET_RE.sub("[REDACTED_SECRET]", redacted)
    redacted = SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED_SECRET]", redacted)
    return redacted


def is_sensitive_field_name(name: str) -> bool:
    return bool(SENSITIVE_FIELD_RE.search(name))


def redact_sensitive_data(value: Any) -> Any:
    """Recursively redact strings before durable persistence."""

    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED_SECRET]"
                if SENSITIVE_FIELD_RE.search(str(key)) and item is not None
                else redact_sensitive_data(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def redact_sample_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        redacted = {}
        for k, v in row.items():
            if v is None:
                redacted[k] = None
            elif is_sensitive_field_name(str(k)):
                redacted[k] = "[REDACTED_SECRET]"
            else:
                redacted[k] = redact_sensitive_text(str(v))
        result.append(redacted)
    return result
