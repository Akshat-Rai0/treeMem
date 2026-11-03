"""Tests for repository hygiene and .gitignore configuration."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_gitignore_exists_and_contains_required_patterns():
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore does not exist"

    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

    required_patterns = [
        ".env",
        "__pycache__/",
        "*.pyc",
        ".DS_Store",
        "__MACOSX/",
        "*.egg-info/",
        "memory/",
        "my_memory/",
        "demo/",
        ".placements.jsonl",
        ".dashboard_url",
        ".locks/",
        ".events/",
        ".pytest_cache/",
        "dist/",
        "build/",
    ]

    for pattern in required_patterns:
        assert pattern in lines, f"Required pattern {pattern!r} missing from .gitignore"
