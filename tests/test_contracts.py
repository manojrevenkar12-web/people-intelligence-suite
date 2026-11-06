"""Contracts at the door: a file in cents is quarantined whole, with the reason."""

import pandas as pd

from pis.ingest import check_payroll


def frame(gross, file="cloudpay_it_2026-03.csv"):
    return pd.DataFrame(
        {
            "month": "2026-03",
            "employee_id": [str(i) for i in range(len(gross))],
            "country": "IT",
            "cost_centre": "Engineering",
            "department": "Engineering",
            "weekly_hours": 40,
            "base_monthly": gross,
            "gross": gross,
            "employer_cost": gross,
            "vendor": "cloudpay",
            "source_file": file,
        }
    )


def test_file_in_cents_is_quarantined_as_a_file():
    kept, bad, files = check_payroll(frame([450000.0, 380000.0, 512000.0]))
    assert kept.empty and files == [{"source_file": "cloudpay_it_2026-03.csv", "country": "IT", "month": "2026-03"}]
    assert bad[0]["reason"] == "file_amounts_out_of_range"


def test_one_bad_row_is_quarantined_alone():
    kept, bad, files = check_payroll(frame([4500.0, 3800.0, 5120.0, 99999.0]))
    assert len(kept) == 3 and not files and bad[0]["reason"] == "gross_out_of_range"


def test_duplicate_person_month_is_quarantined():
    df = frame([4500.0, 3800.0])
    df.loc[1, "employee_id"] = "0"
    kept, bad, _ = check_payroll(df)
    assert len(kept) == 1 and bad[0]["reason"] == "duplicate_row"
