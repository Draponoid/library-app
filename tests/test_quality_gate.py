"""The gate must reject attempts to weaken checks."""

from pathlib import Path

import pytest

from scripts import checks


@pytest.fixture
def quality_project(tmp_path, monkeypatch):
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'scripts').mkdir()
    for name in ('app.py', 'database.py', 'setup_local.py'):
        (tmp_path / name).write_text('', encoding='utf-8')
    (tmp_path / 'pyproject.toml').write_text(Path('pyproject.toml').read_text(encoding='utf-8'), encoding='utf-8')
    monkeypatch.setattr(checks, 'ROOT', tmp_path)
    return tmp_path


def test_policy_rejects_lower_coverage_threshold(quality_project):
    path = quality_project / 'pyproject.toml'
    path.write_text(path.read_text(encoding='utf-8').replace('fail_under = 80', 'fail_under = 40'), encoding='utf-8')
    with pytest.raises(ValueError, match='threshold'):
        checks.policy()


def test_policy_rejects_skipped_tests(quality_project):
    (quality_project / 'tests/test_bad.py').write_text(
        'import pytest\n@pytest.mark.skip\ndef test_bad(): pass\n', encoding='utf-8'
    )
    with pytest.raises(ValueError, match='exclusion'):
        checks.policy()


def test_policy_requires_explanation_for_suppression(quality_project):
    checks.policy()
    (quality_project / 'app.py').write_text('import subprocess  # nosec B404\n', encoding='utf-8')
    with pytest.raises(ValueError, match='suppression'):
        checks.policy()
