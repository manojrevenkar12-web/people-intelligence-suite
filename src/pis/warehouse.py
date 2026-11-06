"""Build the People warehouse with dbt (DuckDB locally; the same models run on PostgreSQL)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from pis.settings import DATA, ROOT, policy

WAREHOUSE = ROOT / "warehouse"


def dbt_vars(landing: Path) -> dict[str, Any]:
    p = policy()
    return {
        "landing": str(landing),
        "reporting_month": p["reporting"]["month"],
        "tolerance_abs": p["reconciliation"]["tolerance_abs_eur"],
        "tolerance_rel": p["reconciliation"]["tolerance_rel"],
        "gl_tolerance": p["reconciliation"]["gl_tolerance_abs_eur"],
        "pay_bands": p["pay_bands"],
        "org_root_titles": p["org"]["root_titles"],
        "span_of_control_max": p["reporting"]["span_of_control_max"],
    }


def dbt_build(landing: Path | None = None, db: Path | None = None) -> dict[str, Any]:
    from dbt.cli.main import dbtRunner

    landing = (landing or DATA / "landing").resolve()
    db = (db or DATA / "warehouse.duckdb").resolve()
    os.environ["PIS_WAREHOUSE"] = str(db)
    res = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(WAREHOUSE),
            "--profiles-dir",
            str(WAREHOUSE),
            "--vars",
            json.dumps(dbt_vars(landing)),
            "--quiet",
        ]
    )
    nodes = res.result.results if res.result is not None else []
    failed = [r.node.name for r in nodes if str(r.status) not in ("success", "pass")]
    if not res.success or failed:
        raise RuntimeError(f"dbt build failed: {failed or res.exception}")
    return {"nodes": len(nodes), "db": str(db)}


def mart(name: str, db: Path | None = None) -> pd.DataFrame:
    with duckdb.connect(str(db or DATA / "warehouse.duckdb")) as con:
        return con.execute(f"select * from {name}").df()
