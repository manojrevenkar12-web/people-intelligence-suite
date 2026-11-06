"""The pipeline, the analytics and the assistant never see the simulated truth."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "pis"
ALLOWED = {"evaluate.py", "cli.py"}  # the evaluation compares with the truth; the CLI starts the simulation


def test_only_the_evaluation_reads_the_truth():
    for path in SRC.rglob("*.py"):
        if "sim" in path.parts or path.name in ALLOWED:
            continue
        text = path.read_text()
        assert not re.search(r"[\"']truth[\"']|truth/defects|defects\.json", text), path
        assert "company.yaml" not in text, path
        assert not re.search(r"from pis\.sim\.company|import pis\.sim\.company", text), path


def test_stand_ins_are_only_used_when_no_real_endpoint_is_configured():
    text = (SRC / "pipeline.py").read_text()
    assert "HIBOB_BASE_URL" in text and "from pis.sim.hibob_stub import create_app" in text
