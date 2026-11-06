"""GDPR controls: pseudonyms, field access, small-group suppression, a tamper-evident audit trail."""

import pandas as pd

from pis.privacy import AuditLog, filter_fields, pseudonym, pseudonymise, suppress_small
from pis.tableau import extract_tables


def test_pseudonym_is_stable_keyed_and_not_the_id():
    a, b = pseudonym("123", key="k1"), pseudonym("123", key="k2")
    assert a == pseudonym("123", key="k1") and a != b and "123" not in a


def test_pseudonymise_drops_direct_identifiers():
    df = pd.DataFrame({"employee_id": ["1"], "display_name": ["Lena"], "email": ["l@x"], "manager_id": ["2"]})
    out = pseudonymise(df)
    assert list(out.columns) == ["employee_id"] and out.employee_id[0].startswith("P-")


def test_roles_see_only_their_fields():
    rec = {"root.id": "1", "salary": 70000, "work.department": "Sales", "internal.status": "Active"}
    assert "salary" not in filter_fields(rec, "employee_self")
    assert "salary" in filter_fields(rec, "people_partner")
    assert filter_fields(rec, "leadership") == {}


def test_small_groups_are_suppressed():
    df = pd.DataFrame({"department": ["A", "B"], "people": [12, 3], "adjusted_gap": [0.02, 0.2]})
    out = suppress_small(df, "people", 5)
    assert out.adjusted_gap.isna().tolist() == [False, True] and pd.isna(out.people[1])


def test_audit_log_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(3):
        log.append("assistant", "read_timeoff_balance", str(i), "self-service")
    assert log.verify() == (True, None)
    lines = log.path.read_text().splitlines()
    lines[1] = lines[1].replace("self-service", "curiosity")
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify() == (False, 1)


def test_reporting_extract_has_no_names_or_emails(built):
    for name, df in extract_tables().items():
        assert not {"display_name", "email", "manager_id"} & set(df.columns), name
        if "employee_id" in df.columns:
            assert df.employee_id.str.startswith("P-").all(), name
