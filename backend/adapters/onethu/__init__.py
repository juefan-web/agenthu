"""OneTHU adapter (M0 research stub).

OneTHU is a *reference for capabilities and data acquisition*, not a runtime
dependency. The product must work without the user opening OneTHU. See
``RESEARCH.md`` in this package for the research status and open questions.

No credential handling, login flow or network access is implemented yet: doing
so requires confirming the technical and authorization boundaries first.
"""

from backend.adapters.onethu.adapter import OneTHUAdapter

__all__ = ["OneTHUAdapter"]
