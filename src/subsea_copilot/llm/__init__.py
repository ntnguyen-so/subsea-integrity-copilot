"""Application-owned, tool-disabled model transport.

Export the CLI chat adapter and sanitized provider errors. Application tool calls
are structured requests for the runtime gateway, never executable CLI authority.
"""

from .copilot_cli import CopilotCLIChatModel, ProviderError

__all__ = ["CopilotCLIChatModel", "ProviderError"]
