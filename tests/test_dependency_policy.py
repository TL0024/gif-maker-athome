from __future__ import annotations

from pathlib import Path

from scripts.check_dependency_policy import dependency_policy_errors


def test_dependency_policy_accepts_current_pillow_floor(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("Pillow>=12.3,<13\n", encoding="utf-8")

    assert dependency_policy_errors(requirements, {"pillow": "12.3.0"}) == []


def test_dependency_policy_rejects_pillow_below_version_12(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("Pillow>=10,<12\n", encoding="utf-8")

    errors = dependency_policy_errors(requirements, {"pillow": "11.3.0"})

    assert any("must require version 12.3 or newer" in error for error in errors)
    assert any("below the required security floor 12.3" in error for error in errors)
