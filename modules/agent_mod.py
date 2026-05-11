import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from typing import Any, Literal, Optional

from modules import get_logger
from modules.agent_utils import create_llm
from modules.prompt import SYSTEM_PROMPT

load_dotenv()

logger = get_logger("[agent]", show_time=False)


class AgentModule:
    def __init__(self):
        self.llm = None

    def init(
        self,
        model_provider: Literal["openai", "google", "openrouter", "nvidia"] | None = None,
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

    def summarize_emails(self, emails: list[dict[str, Any]], prompt: Optional[str] = None) -> str:
        """Summarize emails using LLM"""
        if self.llm is None:
            self.init()

        email_json = str(emails)
        if not prompt:
            prompt = SYSTEM_PROMPT
        user_message = f"{prompt}\n\nHere are the emails to summarize:\n\n{email_json}"

        logger.info(f"Summarizing {len(emails)} emails...")

        response = self.llm.invoke([HumanMessage(content=user_message)])
        return response.content