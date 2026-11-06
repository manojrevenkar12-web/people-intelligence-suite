"""A local payroll provider and helpdesk, for testing the sync end to end.

The provider honours `Idempotency-Key`: the same key twice creates one change request and answers the
original result, which is what makes a retried or re-run workflow safe.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header


def create_app() -> FastAPI:
    app = FastAPI(title="payroll provider and helpdesk stand-in")
    app.state.requests: dict[str, dict[str, Any]] = {}
    app.state.tickets: list[dict[str, Any]] = []
    app.state.calls = 0

    @app.post("/change-requests")
    def change(body: dict[str, Any], idempotency_key: str | None = Header(None)) -> dict[str, Any]:
        app.state.calls += 1
        if idempotency_key in app.state.requests:
            return app.state.requests[idempotency_key]
        res = {"id": f"CR-{len(app.state.requests) + 1:04d}", "status": "pending_approval", "action": body["action"]}
        app.state.requests[idempotency_key or res["id"]] = res
        return res

    @app.post("/tickets")
    def ticket(body: dict[str, Any]) -> dict[str, Any]:
        t = {"id": f"T-{len(app.state.tickets) + 1:04d}", **body}
        app.state.tickets.append(t)
        return t

    return app
