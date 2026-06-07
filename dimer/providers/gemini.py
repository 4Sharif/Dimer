"""Gemini provider."""

from dimer.providers.base import create_provider

def get_gemini_provider(config=None):
    return create_provider("gemini", config)
