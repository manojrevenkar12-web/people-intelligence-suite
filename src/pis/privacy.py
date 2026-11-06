"""GDPR controls: pseudonyms for reporting, field access by role, small-group suppression, an audit trail.

- Reporting extracts (Tableau) never carry names, emails or HiBob IDs: a keyed HMAC turns an employee ID
  into a stable pseudonym that cannot be reversed without the key, which lives outside the extract.
- Each role reads only the fields `config/policy.yaml` grants it; everything else is dropped.
- Aggregates over fewer than `pay_gap.min_group` people are suppressed.
- Every read of personal data by a person or a workflow is appended to a hash-chained audit log, so a
  changed or deleted entry is detectable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd

from pis.settings import DATA, policy

DEV_KEY = "local-development-only"


def pseudonym(employee_id: str, key: str | None = None) -> str:
    key = key or os.environ.get(policy()["privacy"]["pseudonym_key_env"], DEV_KEY)
    return "P-" + hmac.new(key.encode(), employee_id.encode(), hashlib.sha256).hexdigest()[:12]


def pseudonymise(
    df: pd.DataFrame,
    columns: tuple[str, ...] = ("employee_id",),
    drop: tuple[str, ...] = ("display_name", "email", "manager_id"),
) -> pd.DataFrame:
    out = df.drop(columns=[c for c in drop if c in df.columns]).copy()
    for c in columns:
        if c in out.columns:
            out[c] = out[c].map(lambda v: pseudonym(str(v)) if pd.notna(v) else v)
    return out


def allowed_fields(role: str) -> set[str]:
    return set(policy()["privacy"]["roles"].get(role, []))


def filter_fields(record: dict[str, Any], role: str) -> dict[str, Any]:
    allowed = allowed_fields(role)
    return {k: v for k, v in record.items() if k in allowed}


def suppress_small(df: pd.DataFrame, count_col: str, min_group: int | None = None) -> pd.DataFrame:
    n = min_group or policy()["pay_gap"]["min_group"]
    out = df.copy()
    small = out[count_col] < n
    for c in out.columns:
        if c != count_col and pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].astype(float).mask(small)
    out[count_col] = out[count_col].mask(small)
    return out


class AuditLog:
    """Append-only JSON lines; each entry carries the hash of the one before it."""

    def __init__(self, path: Path | None = None):
        self.path = path or DATA / "audit" / "access.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "0" * 64
        last = self.path.read_text().strip().splitlines()[-1]
        return json.loads(last)["hash"]

    def append(self, actor: str, action: str, subject: str | None, purpose: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "ts": round(time.time(), 3),
            "actor": actor,
            "action": action,
            "subject": pseudonym(subject) if subject else None,
            "purpose": purpose,
            **extra,
            "prev": self._last_hash(),
        }
        entry["hash"] = hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def verify(self) -> tuple[bool, int | None]:
        prev = "0" * 64
        if not self.path.exists():
            return True, None
        for i, line in enumerate(self.path.read_text().strip().splitlines()):
            e = json.loads(line)
            h = e.pop("hash")
            if e["prev"] != prev or hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest() != h:
                return False, i
            prev = h
        return True, None
