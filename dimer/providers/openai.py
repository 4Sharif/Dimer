"""OpenAI provider."""

from dimer.providers.base import create_provider

def get_openai_provider(config=None):
    return create_provider("openai", config)
