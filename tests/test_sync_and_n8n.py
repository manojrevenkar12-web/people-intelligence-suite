"""The payroll sync is safe to retry and re-run; the n8n workflows are well formed and hold no secrets."""

import json
import re

from fastapi.testclient import TestClient

from pis.api import HiBobPeople, create_app
from pis.n8n_build import build
from pis.pipeline import hibob_client
from pis.privacy import AuditLog
from pis.sim.payroll_stub import create_app as provider_app


def test_second_run_sends_nothing_and_retries_create_nothing(built, tmp_path):
    api = TestClient(
        create_app(HiBobPeople(hibob_client(), AuditLog(tmp_path / "a.jsonl")), token="t", acks=tmp_path / "acks.jsonl")
    )
    prov = TestClient(provider_app())
    h = {"Authorization": "Bearer t"}
    first = api.get("/sync/plan", headers=h).json()["items"]
    assert first and {i["route"] for i in first} == {"payroll", "people"}
    for it in first:
        for _ in range(2):  # every call retried once
            prov.post("/change-requests", json=it, headers={"Idempotency-Key": it["key"]})
        api.post("/sync/ack", json={"key": it["key"], "outcome": "sent"}, headers=h)
    assert len(prov.app.state.requests) == len(first)
    assert api.get("/sync/plan", headers=h).json()["items"] == []
    assert api.get("/sync/plan").status_code == 401


def test_overpayments_go_to_a_person_not_to_payroll(built, tmp_path):
    api = TestClient(
        create_app(HiBobPeople(hibob_client(), AuditLog(tmp_path / "a.jsonl")), token="t", acks=tmp_path / "acks.jsonl")
    )
    items = api.get("/sync/plan", headers={"Authorization": "Bearer t"}).json()["items"]
    assert all(i["route"] == "people" for i in items if i["action"] == "review_overpayment")


def test_workflows_are_well_formed(tmp_path):
    for path in build(tmp_path):
        wf = json.loads(path.read_text())
        names = [n["name"] for n in wf["nodes"]]
        assert len(names) == len(set(names))
        for src, outs in wf["connections"].items():
            assert src in names
            for branch in outs["main"]:
                for c in branch:
                    assert c["node"] in names
        text = path.read_text()
        assert not re.search(r"(Bearer [A-Za-z0-9]|sk-ant|password)", text)
        for n in wf["nodes"]:
            if n["type"] == "n8n-nodes-base.httpRequest":
                assert n["parameters"]["url"].startswith("={{ $env.")


def test_payroll_calls_carry_the_idempotency_key(tmp_path):
    wf = json.loads([p for p in build(tmp_path) if "payroll" in p.name][0].read_text())
    send = next(n for n in wf["nodes"] if n["name"] == "Send to payroll provider")
    headers = send["parameters"]["headerParameters"]["parameters"]
    assert {"name": "Idempotency-Key", "value": "={{ $json.key }}"} in headers


def test_chat_webhook_requires_a_secret(tmp_path):
    wf = json.loads([p for p in build(tmp_path) if "SelfService" in p.name][0].read_text())
    hook = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert hook["parameters"]["authentication"] == "headerAuth" and hook["credentials"]
