import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_speculative_generation_decision_remains_safely_deferred(
    tmp_path: Path,
) -> None:
    output = tmp_path / "speculative-decision.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "evaluate_speculative_decision.py"),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["decision"] == "defer_speculative_answer_generation"
    assert result["production_speculative_generation_implemented"] is False
    assert result["experimental_feature_flag_added"] is False
    assert result["checks"]["no_speculation_entered_answer_history"] is True
    assert result["checks"]["one_active_generation_maximum"] is True

