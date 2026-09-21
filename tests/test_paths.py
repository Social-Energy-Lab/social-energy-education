from pathlib import Path

import pytest

from social_energy import paths


def test_data_root_comes_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.data_root() == tmp_path.resolve()


def test_missing_environment_variable_is_a_clear_error(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    with pytest.raises(paths.DataRootError, match=paths.ENV_VAR):
        paths.data_root()


def test_data_root_inside_the_repository_is_refused(monkeypatch):
    inside = Path(__file__).resolve().parents[1] / "data"
    monkeypatch.setenv(paths.ENV_VAR, str(inside))
    with pytest.raises(paths.DataRootError, match="inside the repository"):
        paths.data_root()


def test_study_layout(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    layout = paths.study("dsa-2026")
    assert layout.raw == tmp_path.resolve() / "dsa-2026" / "raw"
    assert layout.spine == tmp_path.resolve() / "dsa-2026" / "spine"
    assert layout.derived == tmp_path.resolve() / "dsa-2026" / "derived"
