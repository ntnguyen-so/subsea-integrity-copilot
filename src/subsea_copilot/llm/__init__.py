"""Application-owned, tool-disabled model transport."""

from .copilot_cli import CopilotCLIChatModel, ProviderError

__all__ = ["CopilotCLIChatModel", "ProviderError"]
