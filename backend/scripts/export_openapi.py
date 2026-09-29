"""Export the OpenAPI contract to a JSON file.

Used by CI to freeze the Backend <-> React/Tauri client contract (D-009)::

    python -m backend.scripts.export_openapi --output openapi.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.main import app


def build_schema() -> dict[str, object]:
    return app.openapi()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the AgentHU OpenAPI schema.")
    parser.add_argument("--output", default="openapi.json", help="Output file path")
    args = parser.parse_args()

    schema = build_schema()
    paths = schema.get("paths")
    path_count = len(paths) if isinstance(paths, dict) else 0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI schema with {path_count} paths to {output}")


if __name__ == "__main__":
    main()
