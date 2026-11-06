"""Bring every source into the landing zone, through a contract.

A row that breaks its contract goes to quarantine with the reason, never silently into the numbers.
A whole payroll file is quarantined when most of its rows break the same rule, because that is a
file problem (an export in cents, a wrong month) rather than a person problem.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from pis.connectors.hibob import HiBobClient
from pis.settings import DATA, canonical_department, policy


@dataclass
class IngestResult:
    landed: dict[str, int] = field(default_factory=dict)
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    hibob_requests: int = 0
    hibob_retries: int = 0
    missing_fields: dict[str, int] = field(default_factory=dict)


def _num(x: str) -> float:
    return float(x.replace(".", "").replace(",", ".")) if "," in x else float(x)


def read_payroll_file(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    if path.name.startswith("datev"):
        rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
        df = pd.DataFrame(
            {
                "month": [r["Monat"] for r in rows],
                "employee_id": [r["Mitarbeiter-ID"] for r in rows],
                "country": "DE",
                "cost_centre": [r["Kostenstelle"] for r in rows],
                "weekly_hours": [int(r["Wochenstunden"]) for r in rows],
                "base_monthly": [_num(r["Grundgehalt"]) for r in rows],
                "gross": [_num(r["Brutto"]) for r in rows],
                "employer_cost": [_num(r["Arbeitgeberkosten"]) for r in rows],
                "vendor": "datev",
            }
        )
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
        df = pd.DataFrame(
            {
                "month": [r["pay_period"] for r in rows],
                "employee_id": [r["employee_ref"] for r in rows],
                "country": [r["country"] for r in rows],
                "cost_centre": [r["cost_centre"] for r in rows],
                "weekly_hours": [int(r["weekly_hours"]) for r in rows],
                "base_monthly": [float(r["base_monthly"]) for r in rows],
                "gross": [float(r["gross_pay"]) for r in rows],
                "employer_cost": [float(r["employer_cost"]) for r in rows],
                "vendor": "cloudpay",
            }
        )
    df["department"] = df["cost_centre"].map(canonical_department)
    df["source_file"] = path.name
    return df


def check_payroll(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    c = policy()["contracts"]
    bad: list[dict[str, Any]] = []
    files_out: list[dict[str, Any]] = []
    keep = []
    for name, f in df.groupby("source_file", sort=True):
        too_big = f["gross"] > c["monthly_gross_max_eur"]
        if too_big.mean() > 0.5:
            files_out.append({"source_file": name, "country": f["country"].iloc[0], "month": f["month"].iloc[0]})
            bad.append(
                {
                    "source": "payroll",
                    "key": name,
                    "reason": "file_amounts_out_of_range",
                    "detail": f"{too_big.sum()} of {len(f)} rows above {c['monthly_gross_max_eur']} EUR gross;"
                    f" median {f['gross'].median():,.0f} EUR. Looks like an export in cents.",
                }
            )
            continue
        for _, r in f[too_big].iterrows():
            bad.append(
                {
                    "source": "payroll",
                    "key": f"{name}:{r['employee_id']}",
                    "reason": "gross_out_of_range",
                    "detail": f"gross {r['gross']:,.2f} EUR",
                }
            )
        f = f[~too_big]
        dup = f.duplicated(["month", "employee_id"], keep="first")
        for _, r in f[dup].iterrows():
            bad.append(
                {
                    "source": "payroll",
                    "key": f"{name}:{r['employee_id']}",
                    "reason": "duplicate_row",
                    "detail": "the same person twice in one month",
                }
            )
        keep.append(f[~dup])
    return (pd.concat(keep, ignore_index=True) if keep else df.iloc[0:0]), bad, files_out


def check_people(people: pd.DataFrame, salaries: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    c = policy()["contracts"]
    bad: list[dict[str, Any]] = []
    wrong = (
        (salaries["base"] < c["salary_min_eur"])
        | (salaries["base"] > c["salary_max_eur"])
        | (salaries["currency"] != "EUR")
    )
    for _, r in salaries[wrong].iterrows():
        bad.append(
            {
                "source": "hibob.salaries",
                "key": f"{r['employee_id']}:{r['effective_date']}",
                "reason": "salary_out_of_range",
                "detail": f"{r['base']} {r['currency']}",
            }
        )
    order = people["termination_date"].notna() & (people["termination_date"] < people["start_date"])
    for _, r in people[order].iterrows():
        bad.append(
            {
                "source": "hibob.people",
                "key": r["employee_id"],
                "reason": "ends_before_start",
                "detail": f"{r['start_date']} to {r['termination_date']}",
            }
        )
    return people[~order], salaries[~wrong], bad


def ingest(client: HiBobClient, sources: Path | None = None, landing: Path | None = None) -> IngestResult:
    sources = sources or DATA / "sources"
    landing = landing or DATA / "landing"
    landing.mkdir(parents=True, exist_ok=True)
    res = IngestResult()

    raw = pd.DataFrame(client.people())
    people = pd.DataFrame(
        {
            "employee_id": raw["root.id"],
            "display_name": raw["root.displayName"],
            "email": raw["root.email"],
            "department": raw["work.department"].map(canonical_department),
            "title": raw["work.title"],
            "site": raw["work.site"],
            "start_date": pd.to_datetime(raw["work.startDate"]).dt.date,
            "manager_id": raw["work.reportsTo"],
            "level": raw["work.customColumns.level"],
            "status": raw["internal.status"],
            "termination_date": pd.to_datetime(raw["internal.terminationDate"]).dt.date,
            "termination_reason": raw["internal.terminationReason"],
            "employment_type": raw["payroll.employment.type"],
            "weekly_hours": raw["payroll.employment.weeklyHours"].astype(int),
            "country": raw["payroll.employment.country"],
        }
    )
    sal = pd.DataFrame(
        [
            {
                "employee_id": s["employeeId"],
                "effective_date": s["effectiveDate"],
                "base": float(s["base"]["value"]),
                "currency": s["base"]["currency"],
            }
            for s in client.table("salaries")
        ]
    )
    sal["effective_date"] = pd.to_datetime(sal["effective_date"]).dt.date
    work = pd.DataFrame(
        [
            {
                "employee_id": w["employeeId"],
                "effective_date": w["effectiveDate"],
                "department": canonical_department(w["department"]),
                "title": w["title"],
                "level": w["customColumns"]["level"],
            }
            for w in client.table("work")
        ]
    )
    work["effective_date"] = pd.to_datetime(work["effective_date"]).dt.date
    people, sal, bad = check_people(people, sal)
    res.quarantined += bad
    res.hibob_requests, res.hibob_retries = client.report.requests, client.report.retries
    res.missing_fields = dict(client.report.missing_fields)

    payroll = pd.concat([read_payroll_file(p) for p in sorted((sources / "payroll").glob("*.csv"))], ignore_index=True)
    payroll, bad, files_out = check_payroll(payroll)
    res.quarantined += bad
    pd.DataFrame(files_out, columns=["source_file", "country", "month"]).to_parquet(
        landing / "quarantined_files.parquet", index=False
    )
    gl = pd.read_csv(sources / "finance" / "gl_personnel.csv", dtype={"period": str})
    gl["cost_center"] = gl["cost_center"].map(canonical_department)
    gl["country"] = gl["entity"].str[:2]
    comp = pd.read_csv(sources / "comp" / "cycle.csv", dtype={"employee_id": str, "cycle": str})

    for name, df in {
        "people": people,
        "salaries": sal,
        "work_history": work,
        "payroll": payroll,
        "gl": gl,
        "comp_cycle": comp,
    }.items():
        df.to_parquet(landing / f"{name}.parquet", index=False)
        res.landed[name] = len(df)
    pd.DataFrame(res.quarantined, columns=["source", "key", "reason", "detail"]).to_parquet(
        landing / "quarantine.parquet", index=False
    )
    return res
