"""Provider subsystem — OpenAI-compatible backends + routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.errors import ConfigError

if TYPE_CHECKING:  # pragma: no cover
    from providers.base import BaseProvider

from core.models import ProviderInfo


def _classes() -> dict[str, type]:
    from providers.openrouter import OpenRouterProvider
    from providers.omnirouter import OmniRouterProvider
    from providers.nine_router import NineRouterProvider
    from providers.openai_provider import OpenAIProvider
    from providers.anthropic_provider import AnthropicProvider
    from providers.groq import GroqProvider
    from providers.deepseek import DeepSeekProvider
    from providers.ollama import OllamaProvider
    from providers.together import TogetherProvider
    from providers.mistral import MistralProvider
    from providers.fireworks import FireworksProvider
    from providers.gemini import GeminiProvider
    from providers.lmstudio import LMStudioProvider

    return {
        "openrouter": OpenRouterProvider,
        "omnirouter": OmniRouterProvider,
        "9router": NineRouterProvider,
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "groq": GroqProvider,
        "deepseek": DeepSeekProvider,
        "ollama": OllamaProvider,
        "together": TogetherProvider,
        "mistral": MistralProvider,
        "fireworks": FireworksProvider,
        "gemini": GeminiProvider,
        "lmstudio": LMStudioProvider,
    }


def provider_info_registry() -> dict[str, ProviderInfo]:
    return {pid: cls().info() for pid, cls in _classes().items()}


def available_providers() -> list[str]:
    return list(_classes().keys())


def create_provider(provider_id: str | None = None) -> "BaseProvider":
    from config import store as cfg

    provider_id = (provider_id or cfg.get("provider", "openrouter")).lower()
    classes = _classes()
    try:
        return classes[provider_id]()
    except KeyError:
        raise ConfigError(
            f"Unknown provider '{provider_id}'.",
            hint=f"Known providers: {', '.join(sorted(classes))}",
        ) from None


__all__ = [
    "available_providers",
    "create_provider",
    "provider_info_registry",
]
