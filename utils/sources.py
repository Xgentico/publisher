# publisher_agent/utils/sources.py
from __future__ import annotations
import re
from typing import Any, Dict, Iterable

TAG_PATTERN = re.compile(r"\[(S\d+)\]")               # [S1]
LINKED_PATTERN = re.compile(r"\[S\d+\]\([^)]+\)")     # [S1](https://...)
PLAIN_TAG_PATTERN = re.compile(r"\[S\d+\]")           # [S1]

def link_sources_in_text(text: str, mapping: Dict[str, str]) -> str:
    """Replace [S1] with [S1](URL) if URL exists; leave tag if not mapped."""
    if not mapping:
        return text
    def repl(m):
        tag = m.group(1)
        url = mapping.get(tag)
        return f"[{tag}]({url})" if url else f"[{tag}]"
    return TAG_PATTERN.sub(repl, text)

def strip_sources_in_text(text: str) -> str:
    """Remove [S1](url) and bare [S1] from text (for Word export)."""
    text = LINKED_PATTERN.sub("", text)
    text = PLAIN_TAG_PATTERN.sub("", text)
    return " ".join(text.split())  # collapse leftover doublespaces/newlines

def _transform_any(obj: Any, fn) -> Any:
    """Recursively apply fn to all strings in nested dict/list/tuple."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: _transform_any(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_transform_any(v, fn) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_transform_any(v, fn) for v in obj)
    return obj

def link_sources(obj: Any, mapping: Dict[str, str]) -> Any:
    """Recursively link tags in any nested structure (dict/list/str)."""
    return _transform_any(obj, lambda s: link_sources_in_text(s, mapping))

def strip_sources(obj: Any) -> Any:
    """Recursively strip tags in any nested structure (dict/list/str)."""
    return _transform_any(obj, strip_sources_in_text)
