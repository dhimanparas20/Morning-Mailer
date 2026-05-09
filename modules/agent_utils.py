import importlib
import os
from dataclasses import dataclass
from typing import Optional, Literal

from modules.logger import get_logger

logger = get_logger("Agent Utils")


@dataclass(frozen=True)
class ModelConfig:
    module_name: str
    class_name: str
    model_env: str
    api_key_env: str
    base_url_env: str = ""


MODEL_REGISTRY: dict[str, ModelConfig] = {
    "openai": ModelConfig(
        module_name="langchain_openai",
        class_name="ChatOpenAI",
        model_env="OPENAI_MODEL",
        api_key_env="OPENAI_API_KEY",
    ),
    "google": ModelConfig(
        module_name="langchain_google_genai",
        class_name="ChatGoogleGenerativeAI",
        model_env="GOOGLE_MODEL",
        api_key_env="GOOGLE_API_KEY",
    ),
    "openrouter": ModelConfig(
        module_name="langchain_openrouter",
        class_name="ChatOpenRouter",
        model_env="OPEN_ROUTER_CHAT_MODEL",
        api_key_env="OPEN_ROUTER_API_KEY",
    ),
    "nvidia": ModelConfig(
        module_name="langchain_nvidia_ai_endpoints",
        class_name="ChatNVIDIA",
        model_env="NVIDIA_MODEL",
        api_key_env="NVIDIA_API_KEY",
    ),
}


def create_llm(
    model_name: str | None = None,
    api_key: Optional[str] = None,
    model_provider: Literal["openai", "google", "openrouter", "nvidia"] = "openai",
    model_temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
):
    """
    Factory function to create a LangChain chat model instance.

    Args:
        model_name: The model identifier (e.g., "gpt-4o").
        api_key: Optional API key override. Falls back to env var.
        model_provider: The LLM provider to use.
        model_temperature: Optional temperature override. Falls back to MODEL_TEMPERATURE env var.
        max_tokens: Optional max tokens override. Falls back to MODEL_MAX_TOKENS env var.

    Returns:
        A LangChain chat model instance.

    Raises:
        ValueError: If the model provider is unknown.
        ImportError: If the required LangChain integration package is not installed.
    """
    config = MODEL_REGISTRY.get(model_provider)
    if not config:
        raise ValueError(
            f"Unknown model provider: '{model_provider}'. " f"Supported providers: {list(MODEL_REGISTRY.keys())}"
        )

    # Use `is None` so that 0.0 is respected as a valid temperature
    temperature = model_temperature if model_temperature is not None else float(os.getenv("MODEL_TEMPERATURE", "0.5"))

    resolved_model = model_name if model_name else os.getenv(config.model_env)
    resolved_api_key = api_key or os.getenv(config.api_key_env)

    if not resolved_model:
        raise ValueError(f"No model name provided and env var '{config.model_env}' is not set.")
    if not resolved_api_key:
        raise ValueError(f"No API key provided and env var '{config.api_key_env}' is not set.")

    logger.info(
        f"🤖 Loading {model_provider} model: {resolved_model} || temp: {temperature}",
    )

    try:
        module = importlib.import_module(config.module_name)
        ModelClass = getattr(module, config.class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(
            f"Could not load '{config.class_name}' from '{config.module_name}'. "
            f"Is the package installed? Error: {e}"
        ) from e

    # Build kwargs dynamically to avoid passing unsupported params
    model_kwargs = {
        "model": resolved_model,
        "api_key": resolved_api_key,
        "temperature": temperature,
        "max_tokens": max_tokens or int(os.getenv("MAX_TOKENS", 1500)),
    }

    if config.base_url_env:
        base_url = os.getenv(config.base_url_env)
        if base_url:
            model_kwargs["base_url"] = base_url

    return ModelClass(**model_kwargs)