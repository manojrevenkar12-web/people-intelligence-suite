"""The HiBob client: batching, pagination, 429 retries, and silent field omission reported."""

from fastapi.testclient import TestClient

from pis.connectors.hibob import HiBobClient
from pis.settings import DATA
from pis.sim.hibob_stub import create_app


def client(**kw):
    return HiBobClient(
        "http://hibob",
        "SERVICE-PIS",
        "test-token",
        http=TestClient(create_app(DATA, **kw)),
        sleep=lambda s: None,
        batch=50,
    )


def test_reads_everyone_including_leavers_in_batches():
    c = client()
    rows = c.people()
    ids = c.employee_ids()
    assert len(rows) == len(ids) and {r["root.id"] for r in rows} == set(ids)
    assert {r["internal.status"] for r in rows} == {"Active", "Inactive"}
    assert c.report.requests == 1 + 1 + -(-len(ids) // 50)


def test_retries_after_429():
    c = client(throttle_every=3)
    rows = c.people()
    assert rows and c.report.retries >= 1


def test_paginates_effective_dated_tables():
    c = client()
    sal = list(c.table("salaries", limit=37))
    assert len(sal) == len({(s["employeeId"], s["effectiveDate"]) for s in sal}) > 37


def test_missing_permission_is_reported_not_ignored():
    c = client(categories={"root", "work"})
    c.people(["root.id", "work.department", "internal.status"])
    assert c.report.missing_fields.get("internal.status") == len(c.employee_ids())


def test_wrong_token_is_refused():
    c = HiBobClient("http://hibob", "SERVICE-PIS", "wrong", http=TestClient(create_app(DATA)))
    try:
        c.employee_ids()
    except Exception as e:  # noqa: BLE001
        assert "401" in str(e)
    else:
        raise AssertionError("expected 401")
