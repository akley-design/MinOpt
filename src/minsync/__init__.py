"""MinSync - isolated Docker command executor / MCP server."""

from .app import MinSyncApp, VERSION

__all__ = ["MinSyncApp", "VERSION"]
__version__ = VERSION
