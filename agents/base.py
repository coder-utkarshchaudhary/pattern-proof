"""
Base agent configuration.

Manager roles (Claude) → Anthropic API via PydanticAI AnthropicProvider.
Analyzer roles (Gemma 4 31B) → Ollama Cloud via PydanticAI OpenAIProvider
    (OpenAI-compatible endpoint).

Prompt files are loaded from prompts/ at runtime.
Never inline prompt strings in service code.
LLM output is always parsed through utils.parse_json.extract_json.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from backend.config import settings
from backend.utils.logger import get_logger
from backend.utils.parse_json import extract_json

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# ---------------------------------------------------------------------------
# Prompt registry
# ---------------------------------------------------------------------------

PROMPT_FILES: dict[str, str] = {
    "static_analysis_manager": "static_analysis_manager.md",
    "dom_analyzer": "dom_analyzer.md",
    "css_analyzer": "css_analyzer.md",
    "ocr_analyzer": "ocr_analyzer.md",
    "accessibility_analyzer": "accessibility_analyzer.md",
    "visual_analyzer": "visual_analyzer.md",
    "dynamic_analysis_manager": "dynamic_analysis_manager.md",
    "browser_exploration_agent": "browser_exploration_agent.md",
    "trajectory_reasoner": "trajectory_reasoner.md",
    "report_synthesizer": "report_synthesizer.md",
    "privacy_taxonomy_classifier": "privacy_taxonomy_classifier.md",
}


def load_prompt(name: str) -> str:
    """
    Load a system prompt from prompts/.

    Raises KeyError if the name is unknown.
    Raises FileNotFoundError if the file does not exist on disk.
    """
    filename = PROMPT_FILES.get(name)
    if not filename:
        raise KeyError(
            f"Unknown prompt name: {name!r}. Known: {list(PROMPT_FILES)}"
        )
    path = PROMPTS_DIR / filename
    content = path.read_text(encoding="utf-8")
    logger.debug("Prompt loaded", extra={"prompt": name, "chars": len(content)})
    return content


# ---------------------------------------------------------------------------
# Model factories (pydantic-ai 1.x provider API)
# ---------------------------------------------------------------------------


def _claude_model() -> AnthropicModel:
    """Return a Claude model using the Anthropic provider."""
    provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    return AnthropicModel(settings.claude_model, provider=provider)


def _gemma_model() -> OpenAIModel:
    """
    Return a Gemma 4 31B model via Ollama Cloud (OpenAI-compatible endpoint).

    The base_url is the Ollama Cloud URL; the OpenAI provider appends /v1
    internally when the URL doesn't already include it. We normalise it here
    to be explicit.
    """
    base_url = settings.ollama_base_url.rstrip("/") + "/v1"
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=settings.ollama_api_key or "ollama",
    )
    return OpenAIModel(settings.gemma_model, provider=provider)


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------


class BaseAgent:
    """
    Base for all Pattern Proof LLM agents.

    Usage:
        agent = BaseAgent(role="manager", prompt_name="static_analysis_manager")
        result = await agent.run(user_message, expect_array=False)
        # result is already a parsed Python dict/list via extract_json
    """

    MAX_RETRIES = 2

    def __init__(self, role: str, prompt_name: str) -> None:
        """
        Initialise the agent.

        role:        "manager"  → Claude via Anthropic API
                     "analyzer" → Gemma 4 31B via Ollama Cloud
        prompt_name: key in PROMPT_FILES
        """
        self.role = role
        self.prompt_name = prompt_name
        self._system_prompt = load_prompt(prompt_name)
        model = _claude_model() if role == "manager" else _gemma_model()
        self._agent: Agent = Agent(
            model=model,
            system_prompt=self._system_prompt,
        )
        logger.info(
            "Agent initialized",
            extra={"role": role, "prompt": prompt_name},
        )

    async def run(
        self,
        user_message: str,
        expect_array: bool = False,
        audit_id: str | None = None,
        task_id: str | None = None,
    ) -> Any:
        """
        Run the agent and return parsed JSON output (dict or list).

        Retries up to MAX_RETRIES times with a compact repair prompt on
        malformed JSON. Returns an empty container on persistent failure.
        """
        extra = {
            "role": self.role,
            "prompt": self.prompt_name,
            "audit_id": audit_id,
            "task_id": task_id,
        }
        current_message = user_message

        for attempt in range(1, self.MAX_RETRIES + 2):
            try:
                result = await self._agent.run(current_message)
                raw: str = (
                    result.output if hasattr(result, "output") else str(result)
                )
                parsed = extract_json(raw, expect_array=expect_array)
                if parsed or parsed == [] or parsed == {}:
                    logger.debug(
                        "Agent JSON parsed OK",
                        extra={**extra, "attempt": attempt},
                    )
                    return parsed
                raise ValueError("extract_json returned empty/falsy")
            except Exception as exc:
                logger.warning(
                    "Agent JSON parse failed",
                    extra={**extra, "attempt": attempt, "error": str(exc)},
                )
                if attempt <= self.MAX_RETRIES:
                    current_message = (
                        "Your previous response could not be parsed as valid JSON. "
                        "Return ONLY a valid JSON object (or array) with no additional "
                        "text, markdown fences, or commentary.\n\n"
                        "Original request:\n" + user_message
                    )
                else:
                    logger.error("Agent failed after retries", extra=extra)
                    return [] if expect_array else {}

        # Should not be reached, but satisfies type checkers.
        return [] if expect_array else {}


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def make_manager(prompt_name: str) -> BaseAgent:
    """Return a manager-role agent backed by Claude."""
    return BaseAgent(role="manager", prompt_name=prompt_name)


def make_analyzer(prompt_name: str) -> BaseAgent:
    """Return an analyzer-role agent backed by Gemma 4 31B."""
    return BaseAgent(role="analyzer", prompt_name=prompt_name)
