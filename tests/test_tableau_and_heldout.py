"""The Tableau extract reads back what was written; the held-out questions and their first run stay pinned."""

import hashlib
from pathlib import Path

from tableauhyperapi import Connection, HyperProcess, Telemetry

from pis.tableau import extract_tables, write_hyper

ROOT = Path(__file__).resolve().parents[1]


def test_hyper_extract_round_trip(built, tmp_path):
    tables = extract_tables()
    counts = write_hyper(tables, tmp_path / "t.hyper")
    assert counts == {k: len(v) for k, v in tables.items()}
    with (
        HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as h,
        Connection(h.endpoint, str(tmp_path / "t.hyper")) as c,
    ):
        names = {t.name.unescaped for t in c.catalog.get_table_names("Extract")}
    assert names == set(tables)


def test_heldout_questions_and_first_run_are_pinned():
    for pin in (ROOT / "eval" / "heldout").glob("*.sha256"):
        digest, rel = pin.read_text().split()
        assert hashlib.sha256((pin.parent / rel).read_bytes()).hexdigest() == digest
    for first in (ROOT / "reports" / "heldout").glob("*/first_run.sha256"):
        digest, rel = first.read_text().split()
        assert hashlib.sha256((first.parent / rel).read_bytes()).hexdigest() == digest
