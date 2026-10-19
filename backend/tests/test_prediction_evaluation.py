import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_deterministic_prediction_evaluation_passes(tmp_path: Path) -> None:
    output = tmp_path / "prediction-evaluation.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "evaluate_prediction.py"),
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
    assert result["all_checks_passed"] is True
    assert result["corpus_case_count"] >= 10
    assert result["quality"]["unnecessary_prediction_case_rate"] == 0
    assert result["stale_race"]["stale_discard_count"] >= 1
    assert result["calls"]["max_calls_for_one_turn"] <= 2
    assert result["context"]["maximum_selected_chars"] <= 3_200

