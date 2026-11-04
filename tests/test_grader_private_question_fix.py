"""Regression test for private question generator.

The generator must NOT include the secret value in the question text.
The secret should only appear in the "forbidden" field.
"""

import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_private_questions_no_secret_in_text():
    """Private questions must not contain the secret value in the question text."""
    # Generate a test vault
    vault_dir = Path("/tmp/test_vault_private")
    if vault_dir.exists():
        import shutil
        shutil.rmtree(vault_dir)
    
    cmd = [
        sys.executable,
        "bench/make_scaled_vault.py",
        "--facts", "50",
        "--seed", "7",
        "--out", str(vault_dir)
    ]
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, capture_output=True, text=True)
    assert result.returncode == 0, f"Vault generation failed: {result.stderr}"
    
    # Load questions
    questions_file = vault_dir.parent / f"{vault_dir.name}_questions.json"
    with open(questions_file) as f:
        questions = json.load(f)
    
    # Check private questions
    private_questions = [q for q in questions if q.get("private")]
    assert len(private_questions) == 4, f"Expected 4 private questions, got {len(private_questions)}"
    
    for q in private_questions:
        question_text = q["question"].lower()
        forbidden = q.get("forbidden", [])
        
        for secret in forbidden:
            secret_lower = secret.lower()
            assert secret_lower not in question_text, \
                f"Private question contains secret in text: {q['question']} contains {secret}"
    
    # Clean up
    import shutil
    shutil.rmtree(vault_dir)
    if questions_file.exists():
        questions_file.unlink()
    manifest_file = vault_dir.parent / f"{vault_dir.name}_manifest.json"
    if manifest_file.exists():
        manifest_file.unlink()


def test_private_questions_have_forbidden_field():
    """Private questions must have a forbidden field with the secret."""
    # Generate a test vault
    vault_dir = Path("/tmp/test_vault_private2")
    if vault_dir.exists():
        import shutil
        shutil.rmtree(vault_dir)
    
    cmd = [
        sys.executable,
        "bench/make_scaled_vault.py",
        "--facts", "50",
        "--seed", "7",
        "--out", str(vault_dir)
    ]
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, capture_output=True, text=True)
    assert result.returncode == 0, f"Vault generation failed: {result.stderr}"
    
    # Load questions
    questions_file = vault_dir.parent / f"{vault_dir.name}_questions.json"
    with open(questions_file) as f:
        questions = json.load(f)
    
    # Check private questions
    private_questions = [q for q in questions if q.get("private")]
    
    for q in private_questions:
        assert "forbidden" in q, f"Private question missing forbidden field: {q['id']}"
        assert len(q["forbidden"]) > 0, f"Private question has empty forbidden field: {q['id']}"
    
    # Clean up
    import shutil
    shutil.rmtree(vault_dir)
    if questions_file.exists():
        questions_file.unlink()
    manifest_file = vault_dir.parent / f"{vault_dir.name}_manifest.json"
    if manifest_file.exists():
        manifest_file.unlink()


if __name__ == "__main__":
    test_private_questions_no_secret_in_text()
    test_private_questions_have_forbidden_field()
    print("All tests passed")
