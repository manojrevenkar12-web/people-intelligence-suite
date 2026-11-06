"""Score everything against the simulated truth: `q2s`-style, the evaluation may read data/truth, nothing else may.

- Reconciliation and data-quality checks against the planted defects (precision and recall).
- GL breaks: is the right transfer named?
- Pay equity: is the planted gap found, and what else is flagged?
- The assistant on the dev questions and the blind held-out questions (first run recorded once).
- The payroll sync, run twice against the provider stand-in: nothing sent twice.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from pis.analytics import explain_gl_breaks, pay_gap, workforce_summary
from pis.api import HiBobPeople, create_app
from pis.pipeline import hibob_client, run
from pis.privacy import AuditLog
from pis.settings import DATA, ROOT
from pis.warehouse import mart

REPORTS = ROOT / "reports"


def _pr(found: set[str], truth: set[str]) -> dict[str, Any]:
    tp = len(found & truth)
    return {"found": len(found), "planted": len(truth), "true_positives": tp,
            "precision": round(tp / len(found), 3) if found else None,
            "recall": round(tp / len(truth), 3) if truth else None}


def score_data(truth: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    r = mart("fct_payroll_recon")
    ids = lambda k: {x["employee_id"] for x in truth[k]}  # noqa: E731
    out: dict[str, Any] = {}
    mapping = {"leaver_paid": "leaver_paid", "joiner_missing": "joiner_missing",
               "raise_not_in_payroll": "salary_mismatch", "fte_mismatch": "hours_mismatch"}
    for planted, status in mapping.items():
        out[planted] = _pr(set(r[r.status == status].employee_id), ids(planted))
    exceptions = r[~r.status.isin(["matched", "source_quarantined"])]
    planted_all = set().union(*[ids(k) for k in mapping])
    out["payroll_exceptions_total"] = {"rows": int(len(exceptions)), "people": int(exceptions.employee_id.nunique()),
                                       "people_not_planted": int(len(set(exceptions.employee_id) - planted_all))}
    out["rows_checked"] = int(len(r))
    dq = mart("dq_issues")
    for planted, issue in {"manager_is_leaver": "manager_is_leaver", "missing_manager": "missing_manager",
                           "duplicate_rehire": "possible_duplicate", "comp_not_in_hibob": "comp_not_in_hibob"}.items():
        out[planted] = _pr(set(dq[dq.issue == issue].employee_id), ids(planted))
    q = mart("stg_quarantine")
    want = {f"cloudpay_{x['country'].lower()}_{x['month']}.csv" for x in truth["vendor_cents_month"]}
    out["vendor_cents_month"] = _pr(set(q[q.reason == "file_amounts_out_of_range"].key), want)
    gl = explain_gl_breaks()
    named = {e for g in gl for e in g["explained_by"]}
    out["gl_old_cost_center"] = {**_pr(named, ids("gl_old_cost_center")), "breaks": len(gl),
                                 "breaks_explained": sum(1 for g in gl if g["explained_by"])}
    return out


def score_pay_gap(truth: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    planted = {x["department"] for x in truth["pay_gap"]}
    evidence = {d["department"] for d in gap["by_department"] if not d["suppressed"] and d.get("evidence")}
    over = {d["department"] for d in gap["by_department"] if not d["suppressed"] and d.get("over_threshold")}
    return {"planted": sorted(planted), "over_threshold": sorted(over), "with_evidence": sorted(evidence),
            "planted_found": planted <= evidence, "overall": gap["overall"]}


def _employees() -> dict[str, dict[str, Any]]:
    p = mart("stg_people")
    act = p[(p.status == "Active") & p.manager_id.notna()]
    mgr_ok = set(p[p.status == "Active"].employee_id)
    act = act[act.manager_id.isin(mgr_ok)].sort_values("employee_id")
    return {c: g.iloc[0].to_dict() for c, g in act.groupby("country")}


def run_questions(path: Path, client: TestClient, token: str) -> dict[str, Any]:
    staff = _employees()
    rows = []
    for line in path.read_text().splitlines():
        q = json.loads(line)
        emp = staff[q["country"]]
        res = client.post("/ask", json={"email": emp["email"], "question": q["question"]},
                          headers={"Authorization": f"Bearer {token}"}).json()
        kind_ok = res["kind"] == q["expect"]
        cite_ok = (q.get("citation") is None) or (q["citation"] in res.get("citations", []))
        tool_ok = (q.get("tool") is None) or (res.get("tool") == q["tool"])
        rows.append({"id": q["id"], "country": q["country"], "question": q["question"], "expect": q["expect"],
                     "got": res["kind"], "citation": q.get("citation"), "got_citations": res.get("citations"),
                     "tool": q.get("tool"), "got_tool": res.get("tool"), "reason": res.get("reason"),
                     "correct": bool(kind_ok and cite_ok and tool_ok), "kind_ok": kind_ok})
    n = len(rows)
    unsafe = [r for r in rows if r["expect"] in ("refusal", "handoff") and r["got"] == "answer"]
    cautious = [r for r in rows if r["expect"] == "answer" and r["got"] != "answer"]
    wrong_cite = [r for r in rows if r["expect"] == "answer" and r["got"] == "answer" and not r["correct"]]
    return {"questions": n, "correct": sum(r["correct"] for r in rows),
            "answered_when_it_should_not": len(unsafe), "handed_over_when_it_could_answer": len(cautious),
            "answered_from_the_wrong_section": len(wrong_cite),
            "refusals_kept": sum(1 for r in rows if r["expect"] == "refusal" and r["got"] == "refusal"),
            "refusals_expected": sum(1 for r in rows if r["expect"] == "refusal"), "rows": rows}


def score_sync(client: TestClient, token: str) -> dict[str, Any]:
    from pis.sim.payroll_stub import create_app as provider_app

    prov = TestClient(provider_app())
    h = {"Authorization": f"Bearer {token}"}
    runs = []
    for attempt in range(2):
        items = client.get("/sync/plan", headers=h).json()["items"]
        for it in items:
            if it["route"] == "payroll":
                res = prov.post("/change-requests", json=it, headers={"Idempotency-Key": it["key"]}).json()
                if attempt == 0 and it is items[0]:  # a retried call: same key, must not create a second request
                    prov.post("/change-requests", json=it, headers={"Idempotency-Key": it["key"]})
                outcome = "sent"
            else:
                res = prov.post("/tickets", json={"queue": "people-ops", **it}).json()
                outcome = "queued"
            client.post("/sync/ack", json={"key": it["key"], "outcome": outcome, "reference": res["id"]}, headers=h)
        runs.append(len(items))
    app = prov.app
    return {"first_run_items": runs[0], "second_run_items": runs[1],
            "change_requests": len(app.state.requests), "provider_calls": app.state.calls,
            "people_tickets": len(app.state.tickets),
            "by_action": _count([r["action"] for r in app.state.requests.values()])}


def _count(xs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def evaluate(record_heldout: bool = True) -> dict[str, Any]:
    pipeline = run()
    truth = json.loads((DATA / "truth" / "defects.json").read_text())
    gap = pay_gap(hibob_client(pay_equity=True))
    results: dict[str, Any] = {"pipeline": pipeline, "data": score_data(truth),
                               "pay_gap": score_pay_gap(truth, gap), "pay_gap_detail": gap,
                               "workforce": workforce_summary(), "gl_breaks": explain_gl_breaks()}
    token = "eval-token"
    sync_dir = DATA / "sync"
    acks = sync_dir / "acks.jsonl"
    if acks.exists():
        acks.unlink()
    audit = AuditLog(DATA / "audit" / "eval.jsonl")
    if audit.path.exists():
        audit.path.unlink()
    api = TestClient(create_app(HiBobPeople(hibob_client(), audit), token=token, acks=acks))
    results["assistant_dev"] = run_questions(ROOT / "eval" / "dev" / "questions.jsonl", api, token)
    results["sync"] = score_sync(api, token)
    ok, bad_line = audit.verify()
    results["audit"] = {"entries": len(audit.path.read_text().splitlines()) if audit.path.exists() else 0,
                        "chain_intact": ok}
    heldout = {}
    for folder in sorted((ROOT / "eval" / "heldout").glob("v*/")):
        res = run_questions(folder / "questions.jsonl", api, token)
        status = (folder / "STATUS").read_text().strip()
        heldout[folder.name] = {"status": status, "latest": {k: v for k, v in res.items() if k != "rows"}}
        first = REPORTS / "heldout" / folder.name / "first_run.json"
        if record_heldout and not first.exists():
            first.parent.mkdir(parents=True, exist_ok=True)
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                    text=True).stdout.strip()
            first.write_text(json.dumps({"set": folder.name, "commit": commit, "results": res}, indent=2))
            (first.parent / "first_run.sha256").write_text(
                hashlib.sha256(first.read_bytes()).hexdigest() + "  first_run.json\n")
    results["assistant_heldout"] = heldout
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "results.json").write_text(json.dumps(results, indent=2, default=str))
    return results
