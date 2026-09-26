"""External data source adapters.

Business logic never binds to OneTHU, WeChat, email or any specific provider.
External sources are converted into unified Events by adapters and only then
enter the domain:

    External Source -> Adapter -> Normalized Event -> Backend -> Agent
"""

from backend.adapters.base import (
    AdapterCredentials,
    NormalizedEvent,
    SourceAdapter,
    normalize_to_event_create,
)

__all__ = [
    "AdapterCredentials",
    "NormalizedEvent",
    "SourceAdapter",
    "normalize_to_event_create",
]
