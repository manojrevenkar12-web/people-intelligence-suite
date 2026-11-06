from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


@lru_cache
def policy() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "policy.yaml").read_text())


def canonical_department(name: str) -> str:
    return policy()["department_aliases"].get(name, name)
