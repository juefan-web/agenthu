"""One-off generator for tests/fixtures/deletion-recover-digest.json.

Not imported by the suite; kept so the fixture bytes can be reproduced. The
algorithm line and sample digests are pinned by test_data_recovery.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(body: dict) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


SAMPLES = [
    {
        "description": "standard confirm body (UUID strings, boolean true)",
        "body": {
            "preview_id": "c47ac1b7-4d5a-4b8e-8f2a-3d1c9e7b5a11",
            "preview_digest": "a" * 64,
            "client_request_id": "recover-sample-0001",
            "confirmed": True,
        },
    },
    {
        "description": "non-ASCII client_request_id stays real UTF-8 (no ascii escaping)",
        "body": {
            "preview_id": "0f9e8d7c-6b5a-4c3d-2e1f-0a9b8c7d6e5f",
            "preview_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "client_request_id": "回执-恢复-样本-0002",
            "confirmed": True,
        },
    },
]


def build() -> dict:
    samples = []
    for sample in SAMPLES:
        entry = dict(sample)
        entry["canonical"] = canonical(sample["body"])
        entry["sha256"] = digest(sample["body"])
        samples.append(entry)
    algorithm = (
        "sha256(utf8(json.dumps(body, sort_keys=True, separators=(',',':'), ensure_ascii=False)))"
    )
    pinned_by = (
        "tests/integration/test_data_recovery.py; the desktop client mirrors this file (D-036 §8-2)"
    )
    return {
        "algorithm": algorithm,
        "pinned_by": pinned_by,
        "samples": samples,
    }


if __name__ == "__main__":
    target = Path(__file__).with_name("deletion-recover-digest.json")
    target.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("written", target)
