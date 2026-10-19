from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SOURCE = PROJECT_ROOT / "frontend" / "src"


def test_frontend_does_not_persist_conversation_memory_bodies() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(FRONTEND_SOURCE.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".jsx"}
    )

    assert "localStorage" not in source
    assert "indexedDB" not in source
    assert "memory_revision" not in source
    assert "relevant_older_turns" not in source
    assert source.count("sessionStorage.setItem") == 2
    assert "sessionStorage.setItem(RESUME_TOKEN_KEY, token)" in source
    assert 'sessionStorage.setItem(ACTIVE_SESSION_KEY, "true")' in source
