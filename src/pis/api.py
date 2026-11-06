"""The HTTP API the n8n workflows call.

- `POST /ask`: the self-service assistant, for the employee the chat platform says is asking.
- `GET /sync/plan`: payroll change requests derived from the reconciliation, each with an idempotency key,
  routed either to the payroll provider (a clear, mechanical fix) or to the People team (a judgement).
- `POST /sync/ack`: what the workflow did with each request, so a request is never sent twice.

Every call needs the workflow's bearer token. Every read of someone's personal data is audited.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from pis.assistant.core import Assistant
from pis.connectors.hibob import HiBobClient
from pis.privacy import AuditLog
from pis.settings import DATA, policy
from pis.warehouse import mart


class HiBobPeople:
    """The assistant's view of HiBob: one person at a time, through the People service user."""

    def __init__(self, client: HiBobClient, audit: AuditLog):
        self.client, self.audit = client, audit
        self._by_email: dict[str, str] | None = None

    def resolve(self, email: str) -> str | None:
        if self._by_email is None:
            rows = self.client.people(["root.id", "root.email"], include_inactive=False)
            self._by_email = {r["root.email"].lower(): r["root.id"] for r in rows if r.get("root.email")}
        return self._by_email.get(email.lower())

    def profile(self, employee_id: str) -> dict[str, Any] | None:
        body = {"fields": ["root.id", "root.displayName", "work.reportsTo", "internal.status",
                           "payroll.employment.country"], "showInactive": True,
                "filters": [{"fieldPath": "root.id", "operator": "equals", "values": [employee_id]}]}
        rows = self.client._call("POST", "/v1/people/search", json=body)["employees"]
        if not rows:
            return None
        r = {k[1:].replace("/", "."): v["value"] for k, v in rows[0].items() if k.startswith("/")}
        return {"employee_id": r["root.id"], "display_name": r.get("root.displayName"),
                "manager_id": r.get("work.reportsTo"), "status": r.get("internal.status"),
                "country": r.get("payroll.employment.country")}

    def balance(self, employee_id: str) -> dict[str, Any] | None:
        self.audit.append("assistant", "read_timeoff_balance", employee_id, "employee self-service")
        try:
            return self.client.timeoff_balance(employee_id)
        except Exception:  # noqa: BLE001 - no balance is a handoff, not a crash
            return None


class AskIn(BaseModel):
    email: str
    question: str


class AckIn(BaseModel):
    key: str
    outcome: str  # sent | queued | failed
    reference: str | None = None


def sync_plan() -> list[dict[str, Any]]:
    month = policy()["reporting"]["month"]
    r = mart("fct_payroll_recon")
    open_now = r[(r.month == month) & r.status.isin(["salary_mismatch", "hours_mismatch", "joiner_missing"])]
    items = []
    for _, x in open_now.iterrows():
        if x.status == "salary_mismatch":
            action, value = "update_base_monthly", round(float(x.expected_base_monthly), 2)
        elif x.status == "hours_mismatch":
            action, value = "update_weekly_hours", int(x.hibob_hours)
        else:
            action, value = "add_to_payroll", None
        items.append({"employee_id": x.employee_id, "country": x.country, "month": month, "action": action,
                      "value": value, "route": "payroll", "reason": x.status})
    for _, x in r[r.status == "leaver_paid"].iterrows():  # money already paid out: a person decides on recovery
        items.append({"employee_id": x.employee_id, "country": x.country, "month": x.month,
                      "action": "review_overpayment", "value": round(float(x.gross), 2), "route": "people",
                      "reason": "paid after leaving"})
    for _, x in mart("dq_issues").iterrows():
        if x.issue in ("possible_duplicate", "manager_is_leaver", "missing_manager", "comp_not_in_hibob"):
            items.append({"employee_id": x.employee_id, "country": None, "month": month,
                          "action": f"fix_{x.issue}", "value": None, "route": "people", "reason": x.detail})
    for it in items:
        it["key"] = hashlib.sha256(json.dumps([it["employee_id"], it["action"], it["month"], it["value"]])
                                   .encode()).hexdigest()[:20]
    return items


def create_app(people: HiBobPeople, token: str | None = None, acks: Path | None = None) -> FastAPI:
    token = token or os.environ.get("PIS_API_TOKEN", "dev-token")
    acks = acks or DATA / "sync" / "acks.jsonl"
    acks.parent.mkdir(parents=True, exist_ok=True)
    assistant = Assistant(people)
    app = FastAPI(title="people-intelligence-suite")

    def authed(authorization: str | None = Header(None)) -> None:
        if authorization != f"Bearer {token}":
            raise HTTPException(401, "missing or wrong token")

    def done() -> set[str]:
        if not acks.exists():
            return set()
        return {json.loads(line)["key"] for line in acks.read_text().splitlines()
                if json.loads(line)["outcome"] in ("sent", "queued")}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask", dependencies=[Depends(authed)])
    def ask(body: AskIn) -> dict[str, Any]:
        emp = people.resolve(body.email)
        if emp is None:
            return {"kind": "refusal", "text": "I can only help current employees. Please contact the People team.",
                    "citations": [], "reason": "unknown_user"}
        a = assistant.ask(emp, body.question)
        out = {"kind": a.kind, "text": a.text, "citations": a.citations, "tool": a.tool, "reason": a.reason}
        if a.kind == "handoff":
            out["queue"] = policy()["assistant"]["handoff_queue"]
        return out

    @app.get("/sync/plan", dependencies=[Depends(authed)])
    def plan() -> dict[str, Any]:
        sent = done()
        items = [i for i in sync_plan() if i["key"] not in sent]
        return {"items": items, "count": len(items)}

    @app.post("/sync/ack", dependencies=[Depends(authed)])
    def ack(body: AckIn) -> dict[str, str]:
        with acks.open("a") as f:
            f.write(json.dumps(body.model_dump()) + "\n")
        return {"status": "recorded"}

    return app
