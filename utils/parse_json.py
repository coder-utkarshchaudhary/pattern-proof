"""
JSON parsing utility.

Used to parse the output of the models to extract json from the markdown in the LLM response.
Central extracted used by all the agents.
"""

import json
import re
from typing import Any

def _strip_markdown(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences."""
    text = text.strip()
    # Remove fenced code block
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _find_json_boundary(text: str, opener: str, closer: str) -> str | None:
    """Extract the first balanced {...} or [...] block from text."""
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    # No balanced close found — return everything from opener (truncated JSON)
    return text[start:]


def _repair_truncated(text: str) -> str:
    """
    Best-effort repair of truncated JSON:
    - Remove trailing commas before } or ]
    - Close unclosed brackets/braces
    """
    # Strip trailing incomplete key-value (e.g. `"key": `)
    text = re.sub(r',\s*"[^"]*"\s*:\s*$', "", text)
    # Remove trailing commas before closing brackets
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Count unclosed braces/brackets
    opens = text.count("{") - text.count("}")
    arr_opens = text.count("[") - text.count("]")
    # Close them in reverse order (approximate)
    text = text.rstrip().rstrip(",")
    text += "]" * max(0, arr_opens)
    text += "}" * max(0, opens)
    return text


def extract_json(raw: str, expect_array: bool = False) -> Any:
    """
    Extract and parse a JSON object or array from raw LLM output.

    Strategy:
      1. Strip markdown fences
      2. Try direct parse
      3. Find the first balanced { } or [ ] block
      4. Repair common truncation issues and retry
      5. Return {} or [] as a safe fallback

    Args:
        raw: Raw string output from the LLM
        expect_array: If True, look for [...] first; otherwise {...}
    """
    if not raw:
        return [] if expect_array else {}

    text = _strip_markdown(raw)

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract balanced block
    opener, closer = ("[", "]") if expect_array else ("{", "}")
    block = _find_json_boundary(text, opener, closer)

    if block:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            repaired = _repair_truncated(block)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    # 3. Try the opposite bracket type as a fallback
    fallback_opener, fallback_closer = ("{", "}") if expect_array else ("[", "]")
    block = _find_json_boundary(text, fallback_opener, fallback_closer)
    if block:
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    # 4. Safe fallback
    return [] if expect_array else {}