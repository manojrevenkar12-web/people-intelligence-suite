"""Workforce analytics on top of the warehouse: pay equity, explanations for GL breaks, trends.

Pay equity reads gender through a separate HiBob service user that may read the personal category.
Gender is joined in memory, used for aggregates only, and never written to the warehouse; any group
smaller than `pay_gap.min_group` is suppressed before anything leaves this module.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from pis.connectors.hibob import HiBobClient
from pis.settings import policy
from pis.warehouse import mart


def pay_gap(gender_client: HiBobClient) -> dict[str, Any]:
    cfg = policy()["pay_gap"]
    comp = mart("fct_comp_position")
    g = pd.DataFrame(gender_client.people(["root.id", "personal.gender"], include_inactive=False))
    if "personal.gender" not in g:
        return {"available": False, "reason": "the pay-equity service user cannot read personal.gender"}
    df = comp.merge(g.rename(columns={"root.id": "employee_id", "personal.gender": "gender"}), on="employee_id")
    df["fte_base"] = df["annual_base"] * 40 / df["weekly_hours"]  # compare full-time equivalents
    mf = df[df["gender"].isin(["female", "male"])].copy()
    mf["female"] = (mf["gender"] == "female").astype(float)
    # unexplained gap: log pay on level, country and department, plus the female indicator
    X = pd.get_dummies(mf[["level", "country", "department"]], drop_first=True).astype(float)
    X.insert(0, "female", mf["female"].values)
    X.insert(0, "const", 1.0)
    y = np.log(mf["fte_base"].values)
    beta, *_ = np.linalg.lstsq(X.values, y, rcond=None)
    resid = y - X.values @ beta
    sigma2 = resid @ resid / (len(y) - X.shape[1])
    se = float(np.sqrt(sigma2 * np.linalg.inv(X.values.T @ X.values)[1, 1]))
    overall = {
        "adjusted_gap": round(float(1 - np.exp(beta[1])), 4),
        "se": round(se, 4),
        "raw_gap": round(
            float(1 - mf.loc[mf.female == 1, "fte_base"].median() / mf.loc[mf.female == 0, "fte_base"].median()), 4
        ),
        "people": int(len(mf)),
    }
    rows = []
    for (dept, level), grp in mf.groupby(["department", "level"]):
        nf, nm = int((grp.female == 1).sum()), int((grp.female == 0).sum())
        if nf < cfg["min_group"] or nm < cfg["min_group"]:
            rows.append({"department": dept, "level": level, "suppressed": True})
            continue
        # within one category, adjust for country by comparing to each country's male median
        male_median = grp[grp.female == 0].groupby("country").fte_base.median()
        ratio = grp.fte_base / grp.country.map(male_median)
        gap = float(1 - ratio[grp.female == 1].median())
        rows.append(
            {
                "department": dept,
                "level": level,
                "suppressed": False,
                "women": nf,
                "men": nm,
                "gap": round(gap, 4),
                "flag": gap >= cfg["threshold"],
            }
        )
    by_dept = []
    for dept, grp in mf.groupby("department"):
        Xd = pd.get_dummies(grp[["level", "country"]], drop_first=True).astype(float)
        Xd.insert(0, "female", grp["female"].values)
        Xd.insert(0, "const", 1.0)
        nf, nm = int((grp.female == 1).sum()), int((grp.female == 0).sum())
        if nf < cfg["min_group"] or nm < cfg["min_group"]:
            by_dept.append({"department": dept, "suppressed": True})
            continue
        yd = np.log(grp["fte_base"].values)
        b, *_ = np.linalg.lstsq(Xd.values, yd, rcond=None)
        res = yd - Xd.values @ b
        dof = max(len(yd) - Xd.shape[1], 1)
        se_d = float(np.sqrt(res @ res / dof * np.linalg.pinv(Xd.values.T @ Xd.values)[1, 1]))
        gap = float(1 - np.exp(b[1]))
        low = float(1 - np.exp(b[1] + 1.645 * se_d))  # 90% interval on the gap
        high = float(1 - np.exp(b[1] - 1.645 * se_d))
        by_dept.append(
            {
                "department": dept,
                "suppressed": False,
                "women": nf,
                "men": nm,
                "adjusted_gap": round(gap, 4),
                "interval": [round(low, 4), round(high, 4)],
                "over_threshold": gap >= cfg["threshold"],
                "evidence": low > 0,
            }
        )
    return {
        "available": True,
        "overall": overall,
        "by_department": by_dept,
        "categories": rows,
        "threshold": cfg["threshold"],
        "min_group": cfg["min_group"],
        "non_binary_reported_separately": "suppressed below the minimum group size",
    }


def explain_gl_breaks() -> list[dict[str, Any]]:
    """Pair GL breaks that cancel out within a month and entity, and name the transfer that explains them."""
    gl = mart("fct_gl_recon")
    flagged = gl[gl.flagged & ~gl.payroll_quarantined]
    recon = mart("fct_payroll_recon")
    work = mart("stg_work_history").sort_values(["employee_id", "effective_date"])
    moves = []
    for emp, w in work.groupby("employee_id"):
        prev = None
        for _, r in w.iterrows():
            if prev is not None and r.department != prev:
                moves.append({"employee_id": emp, "from": prev, "to": r.department, "month": str(r.effective_date)[:7]})
            prev = r.department
    out = []
    for (month, country), f in flagged.groupby(["month", "country"]):
        over, under = f[f.difference > 0], f[f.difference < 0]
        for _, u in under.iterrows():
            for _, o in over.iterrows():
                if abs(u.difference + o.difference) > 1:
                    continue
                # Finance booked cost to o.department that HiBob places in u.department: someone who moved u <- o
                cands = [
                    m for m in moves if m["from"] == o.department and m["to"] == u.department and m["month"] <= month
                ]
                cost = recon[(recon.month == month) & (recon.country == country) & recon.paid]
                hit = [
                    m
                    for m in cands
                    if abs(float(cost[cost.employee_id == m["employee_id"]].employer_cost.sum()) + u.difference) <= 1
                ]
                out.append(
                    {
                        "month": month,
                        "country": country,
                        "booked_to": o.department,
                        "belongs_to": u.department,
                        "amount": round(float(o.difference), 2),
                        "explained_by": [m["employee_id"] for m in hit],
                    }
                )
    return out


def workforce_summary() -> dict[str, Any]:
    p = policy()["reporting"]
    hc = mart("fct_headcount_monthly")
    months = sorted(hc.month.unique())
    last = p["month"]
    window = months[-p["attrition_window_months"] :]
    w = hc[hc.month.isin(window)]
    avg_head = w.groupby("month").headcount.sum().mean()
    by_dept = []
    for dept, g in w.groupby("department"):
        avg = g.groupby("month").headcount.sum().mean()
        by_dept.append(
            {
                "department": dept,
                "headcount": int(hc[(hc.month == last) & (hc.department == dept)].headcount.sum()),
                "leavers_12m": int(g.leavers.sum()),
                "voluntary_12m": int(g.voluntary_leavers.sum()),
                "attrition_12m": round(float(g.leavers.sum() / avg), 3) if avg else None,
            }
        )
    trend = hc.groupby("month")[["headcount", "hires", "leavers"]].sum().reset_index()
    return {
        "month": last,
        "headcount": int(hc[hc.month == last].headcount.sum()),
        "fte": float(hc[hc.month == last].fte.sum()),
        "attrition_12m": round(float(w.leavers.sum() / avg_head), 3),
        "voluntary_attrition_12m": round(float(w.voluntary_leavers.sum() / avg_head), 3),
        "by_department": by_dept,
        "trend": trend.to_dict("records"),
        "by_country": hc[hc.month == last].groupby("country").headcount.sum().to_dict(),
    }
