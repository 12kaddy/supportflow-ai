"""Conservative prompt-attack screening and common PII redaction; no classifier claim."""

import re
from dataclasses import dataclass

ATTACKS = [
    r"(?:ignore|override|disregard|forget)\b.{0,50}\b(?:instructions?|system|rules?|policy)",
    r"(?:reveal|print|show|leak)\b.{0,35}\b(?:system prompt|api key|password|secret)",
    r"(?:bypass|skip)\b.{0,35}\b(?:approval|review|authorization|authentication)",
    r"(?:act as|you are now|pretend to be)\b.{0,25}\b(?:admin|reviewer|system)",
    r"(?:approve|execute|issue)\b.{0,40}\brefund\b.{0,30}\bwithout\b.{0,20}\b(?:review|approval)",
    r"(?:निर्देश|नियम).{0,30}(?:अनदेखा|भूल जाओ)",
]
PII = [
    ("email", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ("aadhaar", r"(?<!\w)\d{4}[ -]\d{4}[ -]\d{4}(?!\w)"),
    ("card", r"(?<![\w-])(?:\d[ -]?){15,19}(?!\w)"),
    ("phone", r"(?<![\w-])(?:\+91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\w)"),
    ("pan", r"\b[A-Z]{5}\d{4}[A-Z]\b"),
]


@dataclass
class InputVerdict:
    text: str
    blocked: bool
    redactions: list[str]


def redact(text):
    kinds = []
    for name, pattern in PII:
        text, count = re.subn(pattern, f"[REDACTED_{name.upper()}]", text, flags=re.I)
        if count:
            kinds.append(name)
    return text, kinds


def inspect_input(text):
    protected, kinds = redact(text)
    return InputVerdict(protected, any(re.search(p, text, re.I | re.S) for p in ATTACKS), kinds)
