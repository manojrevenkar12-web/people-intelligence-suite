"""The whole pipeline: HiBob and the files into landing, through contracts, into the warehouse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pis.connectors.hibob import HiBobClient
from pis.ingest import ingest
from pis.settings import DATA
from pis.warehouse import dbt_build


def hibob_client(throttle_every: int = 0, pay_equity: bool = False) -> HiBobClient:
    """The real HiBob when HIBOB_BASE_URL is set; otherwise the local stand-in on the simulated company."""
    if os.environ.get("HIBOB_BASE_URL"):
        user = "HIBOB_PAY_EQUITY_USER" if pay_equity else "HIBOB_SERVICE_USER"
        token = "HIBOB_PAY_EQUITY_TOKEN" if pay_equity else "HIBOB_TOKEN"
        return HiBobClient(os.environ["HIBOB_BASE_URL"], os.environ[user], os.environ[token])
    from fastapi.testclient import TestClient

    from pis.sim.hibob_stub import create_app  # the stand-in is part of the simulation, not the pipeline logic

    cats = {"root", "personal"} if pay_equity else None  # pay equity may read gender, nothing about pay
    app = create_app(DATA, throttle_every=throttle_every, categories=cats)
    return HiBobClient("http://hibob.local", "SERVICE-PIS", "test-token", http=TestClient(app), sleep=lambda s: None)


def run(data: Path | None = None, throttle_every: int = 7) -> dict[str, Any]:
    data = data or DATA
    res = ingest(hibob_client(throttle_every), data / "sources", data / "landing")
    built = dbt_build(data / "landing", data / "warehouse.duckdb")
    return {
        "landed": res.landed,
        "quarantined": len(res.quarantined),
        "hibob_requests": res.hibob_requests,
        "hibob_retries": res.hibob_retries,
        "missing_fields": res.missing_fields,
        "dbt_nodes": built["nodes"],
    }
