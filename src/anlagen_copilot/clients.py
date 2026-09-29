"""API clients built from the settings, one function per provider.

Only entry points call these: the CLI and the eval scripts build the clients
once and pass them on. The functions that do the work take a client as an
argument instead, so a test can hand them a fake.
"""

from anthropic import Anthropic
from openai import OpenAI

from anlagen_copilot.settings import get_settings


def get_openai_client() -> OpenAI:
    """Build an OpenAI client with the key from the settings."""
    return OpenAI(api_key=get_settings().openai_api_key.get_secret_value())


def get_anthropic_client() -> Anthropic:
    """Build an Anthropic client with the key from the settings."""
    return Anthropic(api_key=get_settings().anthropic_api_key.get_secret_value())
