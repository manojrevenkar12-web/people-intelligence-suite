"""A local stand-in for the HiBob public API, serving the simulated company.

Behaves the way the real API is documented to behave where it matters to a client:
- `POST /v1/people/search` takes dot-notation field IDs and answers with slash keys (`/root/id`) plus
  nested category objects; fields the service user may not read are silently left out (200, not 403);
  `showInactive` defaults to false; a `root.id` filter takes at most 200 values.
- Bulk employee tables (`/v1/bulk/people/salaries`, `/v1/bulk/people/work`) are paginated with a cursor.
- Time-off balances per employee.
- Basic auth with a service user; every Nth request answers 429 with Retry-After.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

DEFAULT_PERMS = {"root", "work", "internal", "payroll"}  # no "personal": the People service user cannot read it
FIELD_GETTERS = {
    "root.id": lambda p: p["id"],
    "root.firstName": lambda p: p["firstName"],
    "root.surname": lambda p: p["surname"],
    "root.displayName": lambda p: p["displayName"],
    "root.email": lambda p: p["email"],
    "work.department": lambda p: p["work"]["department"],
    "work.title": lambda p: p["work"]["title"],
    "work.site": lambda p: p["work"]["site"],
    "work.startDate": lambda p: p["work"]["startDate"],
    "work.reportsTo": lambda p: (p["work"]["reportsTo"] or {}).get("id"),
    "work.customColumns.level": lambda p: p["work"]["customColumns"]["level"],
    "internal.status": lambda p: p["internal"]["status"],
    "internal.lifecycleStatus": lambda p: p["internal"]["lifecycleStatus"],
    "internal.terminationDate": lambda p: p["internal"]["terminationDate"],
    "internal.terminationReason": lambda p: p["internal"]["terminationReason"],
    "payroll.employment.type": lambda p: p["payroll"]["employment"]["type"],
    "payroll.employment.weeklyHours": lambda p: p["payroll"]["employment"]["weeklyHours"],
    "payroll.employment.country": lambda p: p["payroll"]["employment"]["country"],
    "personal.gender": lambda p: p["personal"]["gender"],
    "personal.birthDate": lambda p: p["personal"]["birthDate"],
}


def create_app(data_dir: Path, user: str = "SERVICE-PIS", token: str = "test-token",
               categories: set[str] | None = None, throttle_every: int = 0) -> FastAPI:
    hibob = data_dir / "sources" / "hibob"
    people = json.loads((hibob / "people.json").read_text())
    tables = {"salaries": json.loads((hibob / "salaries.json").read_text()),
              "work": json.loads((hibob / "work.json").read_text())}
    timeoff = {t["employeeId"]: t for t in json.loads((hibob / "timeoff.json").read_text())}
    perms = categories or DEFAULT_PERMS
    expected = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()
    app = FastAPI(title="HiBob stand-in")
    state = {"n": 0}

    @app.middleware("http")
    async def auth_and_throttle(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("authorization") != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        state["n"] += 1
        if throttle_every and state["n"] % throttle_every == 0:
            return JSONResponse({"error": "rate limited"}, status_code=429, headers={"Retry-After": "1"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/people/search")
    def search(body: dict[str, Any]) -> dict[str, Any]:
        fields = body.get("fields") or ["root.id", "root.displayName", "work.department", "work.title"]
        rows = people if body.get("showInactive") else [p for p in people if p["internal"]["status"] == "Active"]
        for f in body.get("filters") or []:
            if f.get("fieldPath") != "root.id" or f.get("operator") != "equals":
                raise HTTPException(400, "only root.id equals filters are supported here")
            if len(f["values"]) > 200:
                raise HTTPException(400, "too many values in filter (max 200)")
            wanted = set(f["values"])
            rows = [p for p in rows if p["id"] in wanted]
        out = []
        for p in rows:
            e: dict[str, Any] = {}
            for fid in fields:
                if fid not in FIELD_GETTERS or fid.split(".")[0] not in perms:
                    continue  # silently omitted, as the real API does
                val = FIELD_GETTERS[fid](p)
                e["/" + fid.replace(".", "/")] = {"value": val}
                cat, *rest = fid.split(".")
                node = e.setdefault(cat, {})
                for k in rest[:-1]:
                    node = node.setdefault(k, {})
                node[rest[-1]] = val
            out.append(e)
        return {"employees": out}

    @app.get("/v1/bulk/people/{table}")
    def bulk(table: str, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
        if table not in tables:
            raise HTTPException(404, "unknown table")
        if table == "salaries" and "payroll" not in perms:
            return {"results": [], "response_metadata": {"next_cursor": None}}
        start = int(cursor or 0)
        page = tables[table][start:start + limit]
        nxt = start + limit if start + limit < len(tables[table]) else None
        return {"results": page, "response_metadata": {"next_cursor": str(nxt) if nxt is not None else None}}

    @app.get("/v1/timeoff/employees/{employee_id}/balance")
    def balance(employee_id: str, policyType: str = "Holiday", authorization: str | None = Header(None)) -> dict:
        t = timeoff.get(employee_id)
        if not t or t["policyType"] != policyType:
            raise HTTPException(404, "no balance")
        return t

    return app
