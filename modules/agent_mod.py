import os
import time
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from typing import Any, Literal, Optional

from modules import get_logger
from modules.agent_utils import create_llm
from modules.generics import current_date_ist
from modules.prompt import SYSTEM_PROMPT

load_dotenv()

logger = get_logger("[agent]", show_time=False)

# Transient LLM failures (503 overloaded, rate limits, timeouts) — retry with backoff
_LLM_RETRY_COUNT = int(os.getenv("RETRY_COUNT", 3))
_LLM_RETRY_DELAY = int(os.getenv("RETRY_DELAY", 60))

_TRANSIENT_MARKERS = (
    "503",
    "502",
    "429",
    "overloaded",
    "service unavailable",
    "rate limit",
    "too many requests",
    "timeout",
    "timed out",
    "temporarily",
    "connection reset",
    "connection refused",
    "connection error",
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    """Return True for temporary provider outages that are worth retrying."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


class AgentModule:
    def __init__(self):
        self.llm = None

    def init(
        self,
        model_provider: Literal["openai", "google", "openrouter", "nvidia", "ollama"] | None = None,
        model_temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        provider = model_provider or os.getenv("MODEL_PROVIDER", "nvidia")
        temperature = model_temperature if model_temperature is not None else float(os.getenv("MODEL_TEMPERATURE", 0.4))
        tokens = max_tokens or int(os.getenv("MAX_TOKENS", 1500))

        env_mode = os.getenv("ENV_MODE", "dev").upper()
        logger.info(f"Initializing LLM: {provider} (temp: {temperature}, tokens: {tokens}) | ENV_MODE: {env_mode}")
        self.llm = create_llm(
            model_provider=provider,
            model_temperature=temperature,
            max_tokens=tokens,
        )

    def hot_switch_model(self, model_provider: Literal["openai", "google", "openrouter", "nvidia", "ollama"] | None = None, model_name: str | None = None, temperature: float | None = None) -> None:
        provider = model_provider or os.getenv("MODEL_PROVIDER", "nvidia")
        temp = temperature if temperature is not None else float(os.getenv("MODEL_TEMPERATURE", 0.4))
        logger.info(f"Hot-switching model: {provider} / {model_name or 'default'} (temp: {temp})")
        self.llm = create_llm(
            model_provider=provider,
            model_name=model_name,
            model_temperature=temp,
        )

    def summarize_emails(self, emails: list[dict[str, Any]], prompt: Optional[str] = None, user_name: Optional[str] = None, calendar_events: Optional[list[dict[str, Any]]] = None) -> str:
        """Summarize emails (and optionally calendar events) using LLM.

        Retries on transient provider errors (503 overloaded, 429 rate limit, timeouts)
        using RETRY_COUNT / RETRY_DELAY from .env — same knobs as Gmail fetch retries.
        """
        if self.llm is None:
            self.init()

        email_json = str(emails)
        if not prompt:
            prompt = SYSTEM_PROMPT
        if user_name:
            prompt = prompt.replace("{USER_NAME}", user_name)
        prompt = prompt.replace("{CURRENT_DATE}", current_date_ist())

        user_message = f"{prompt}\n\nHere are the emails to summarize:\n\n{email_json}"

        if calendar_events:
            cal_json = str(calendar_events)
            user_message += f"\n\nHere are the upcoming calendar events to include in the summary:\n\n{cal_json}"

        logger.info(f"Summarizing {len(emails)} emails" + (f" + {len(calendar_events)} calendar events" if calendar_events else "") + "...")

        last_error: BaseException | None = None
        for attempt in range(_LLM_RETRY_COUNT):
            try:
                response = self.llm.invoke([HumanMessage(content=user_message)])
                if attempt > 0:
                    logger.success(f"LLM summarize succeeded on attempt {attempt + 1}/{_LLM_RETRY_COUNT}")
                return response.content
            except Exception as e:
                last_error = e
                is_last = attempt >= _LLM_RETRY_COUNT - 1
                if not _is_transient_llm_error(e) or is_last:
                    if is_last and _is_transient_llm_error(e):
                        logger.error(
                            f"LLM still unavailable after {_LLM_RETRY_COUNT} attempts: {e}"
                        )
                    raise

                # Linear backoff: delay, 2*delay, 3*delay — gives overloaded providers time to recover
                wait = _LLM_RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"LLM temporarily unavailable (attempt {attempt + 1}/{_LLM_RETRY_COUNT}): {e}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)

        # Unreachable, but keeps type-checkers happy
        raise last_error  # type: ignore[misc]