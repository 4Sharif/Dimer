"""Anthropic provider."""

from dimer.providers.base import create_provider

def get_anthropic_provider(config=None):
    return create_provider("anthropic", config)
