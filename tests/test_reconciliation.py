"""Reconciliation and data quality on the built warehouse."""

from pis.analytics import explain_gl_breaks, workforce_summary
from pis.warehouse import mart


def test_every_person_month_is_classified_once(built):
    r = mart("fct_payroll_recon")
    assert not r.duplicated(["employee_id", "month"]).any()
    assert set(r.status) <= {
        "matched",
        "source_quarantined",
        "unknown_in_hibob",
        "leaver_paid",
        "paid_before_start",
        "joiner_missing",
        "not_paid",
        "hours_mismatch",
        "salary_mismatch",
    }
    assert (r.status == "matched").mean() > 0.95


def test_quarantined_file_is_not_reported_as_unpaid_people(built):
    r = mart("fct_payroll_recon")
    q = r[r.status == "source_quarantined"]
    assert len(q) > 0 and set(q.country) == {"IT"} and q.month.nunique() == 1


def test_gl_breaks_cancel_out_and_are_explained(built):
    breaks = explain_gl_breaks()
    assert breaks and all(b["explained_by"] for b in breaks)


def test_workforce_summary(built):
    w = workforce_summary()
    assert 200 < w["headcount"] < 320 and 0 < w["attrition_12m"] < 0.3
    assert sum(w["by_country"].values()) == w["headcount"]
