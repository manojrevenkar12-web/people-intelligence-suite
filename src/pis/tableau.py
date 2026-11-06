"""Tableau extracts (.hyper) for the leadership reporting suite.

One extract file with one table per reporting subject, pseudonymised, read back after writing to prove
the row counts. Point a Tableau workbook (or a published data source) at `reports/tableau/people.hyper`;
the field list and meaning of each table is in `docs/tableau-data-model.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter, SqlType, TableDefinition,
                             TableName, Telemetry)

from pis.privacy import pseudonymise, suppress_small
from pis.settings import ROOT
from pis.warehouse import mart

OUT = ROOT / "reports" / "tableau" / "people.hyper"


def _sql_type(s: pd.Series) -> SqlType:
    if pd.api.types.is_bool_dtype(s):
        return SqlType.bool()
    if pd.api.types.is_integer_dtype(s):
        return SqlType.big_int()
    if pd.api.types.is_float_dtype(s):
        return SqlType.double()
    return SqlType.text()


def extract_tables(pay_gap: dict[str, Any] | None = None) -> dict[str, pd.DataFrame]:
    hc = mart("fct_headcount_monthly")
    comp = pseudonymise(mart("fct_comp_position"))
    recon = mart("fct_payroll_recon")
    recon = pseudonymise(recon[recon.status != "matched"][["employee_id", "month", "country", "hibob_department",
                                                            "status", "expected_base_monthly",
                                                            "payroll_base_monthly", "hibob_hours", "payroll_hours"]])
    dq = pseudonymise(mart("dq_issues"))
    dq["detail"] = dq["issue"]  # free-text detail names people; the extract keeps the category only
    gl = mart("fct_gl_recon")
    tables = {"headcount_monthly": hc, "comp_position": comp, "payroll_exceptions": recon,
              "data_quality_issues": dq, "gl_reconciliation": gl}
    if pay_gap and pay_gap.get("available"):
        d = pd.DataFrame([x for x in pay_gap["by_department"] if not x["suppressed"]])
        d["people"] = d["women"] + d["men"]
        tables["pay_equity_by_department"] = suppress_small(
            d[["department", "people", "women", "men", "adjusted_gap"]], "people")
    return tables


def write_hyper(tables: dict[str, pd.DataFrame], path: Path = OUT) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(hyper.endpoint, str(path), CreateMode.CREATE_AND_REPLACE) as con:
            con.catalog.create_schema_if_not_exists("Extract")
            for name, df in tables.items():
                df = df.copy()
                for c in df.columns:
                    if not (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c])):
                        df[c] = df[c].astype(str)
                table = TableDefinition(TableName("Extract", name),
                                        [TableDefinition.Column(c, _sql_type(df[c])) for c in df.columns])
                con.catalog.create_table(table)
                df = df.astype(object).where(df.notna(), None)
                rows = [[v.item() if hasattr(v, "item") else v for v in r] for r in df.itertuples(index=False)]
                with Inserter(con, table) as ins:
                    ins.add_rows(rows)
                    ins.execute()
            for name in tables:  # read back
                counts[name] = con.execute_scalar_query(f'SELECT COUNT(*) FROM "Extract"."{name}"')
    return counts
