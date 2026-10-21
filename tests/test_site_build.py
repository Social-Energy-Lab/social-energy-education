"""The site builder: synthetic camp or public data dir, validated before it counts as built."""

import json
from pathlib import Path

import pytest

from social_energy import cli
from social_energy.paths import REPO_ROOT, DataRootError
from social_energy.site import SiteDataError
from social_energy.site.build import build_site, synthetic_site_data
from social_energy.study import ExplorerConfig, StudyConfig

TZ = "Europe/Berlin"
STUDY = REPO_ROOT / "studies" / "dsa-2026" / "study.yaml"


def _config() -> ExplorerConfig:
    return StudyConfig.load(STUDY).explorer_config()


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site")
    return build_site(out, None, config=_config(), timezone=TZ)


def test_build_synthetic_site(built):
    for name in ("index.html", "vendor/d3.min.js", "model.js", "data/meta.json"):
        assert (built / name).is_file(), name
    meta = json.loads((built / "data" / "meta.json").read_text())
    assert meta["synthetic"] is True
    assert len(meta["nodes"]) >= 30
    assert {n["course"] for n in meta["nodes"]} - {-1}
    assert meta["special_days"]
    json.loads((built / "data" / "aggregates.json").read_text())


def test_synthetic_needs_config_and_timezone(tmp_path):
    with pytest.raises(ValueError):
        build_site(tmp_path / "o", None)


def test_synthetic_site_data_returns_data_dir(tmp_path):
    data = synthetic_site_data(tmp_path / "d", _config(), timezone=TZ, seed=1)
    assert (data / "meta.json").is_file() and (data / "aggregates.json").is_file()


def test_build_with_data_dir_copies_and_validates(tmp_path, built):
    out = build_site(tmp_path / "again", built / "data")
    assert (out / "data" / "meta.json").is_file()
    bad = tmp_path / "bad"
    bad.mkdir()
    for f in (built / "data").iterdir():
        (bad / f.name).write_bytes(f.read_bytes())
    meta = json.loads((bad / "meta.json").read_text())
    meta["mode"] = "team"
    (bad / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(SiteDataError):
        build_site(tmp_path / "refused", bad)


def test_build_refuses_out_inside_repo():
    with pytest.raises(DataRootError):
        build_site(REPO_ROOT / "site-out", None, config=_config(), timezone=TZ)


def test_cli_site_build_without_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("SOCIAL_ENERGY_DATA", raising=False)
    out = tmp_path / "site"
    assert cli.main(["site-build", str(STUDY), "--out", str(out)]) == 0
    assert (out / "data" / "meta.json").is_file()


def test_cli_site_build_requires_out(tmp_path):
    assert cli.main(["site-build", str(STUDY)]) == 2


def _copy_data(built: Path, dest: Path) -> Path:
    dest.mkdir(parents=True)
    for f in (built / "data").iterdir():
        (dest / f.name).write_bytes(f.read_bytes())
    return dest


def test_build_refuses_stray_file_in_data_dir(tmp_path, built):
    data = _copy_data(built, tmp_path / "data")
    (data / "notes.txt").write_text("names")
    with pytest.raises(SiteDataError, match=r"notes\.txt"):
        build_site(tmp_path / "o", data)
    assert not (tmp_path / "o" / "data" / "notes.txt").exists()


def test_build_refuses_data_dir_inside_out(tmp_path, built):
    out = tmp_path / "o"
    _copy_data(built, out / "data")
    with pytest.raises(ValueError, match="inside the output"):
        build_site(out, out / "data")
    assert (out / "data" / "meta.json").is_file()


def test_build_uses_one_min_group(tmp_path, built, monkeypatch):
    from social_energy.site import build as mod

    seen = []
    monkeypatch.setattr(
        mod, "validate_site_data", lambda d, min_group=5: seen.append(min_group) or {}
    )
    build_site(tmp_path / "o", built / "data", config=ExplorerConfig(min_group=7))
    assert seen == [7, 7]


def test_build_refuses_missing_listed_table(tmp_path, built):
    data = _copy_data(built, tmp_path / "data")
    (data / "pairs.bin").unlink()
    with pytest.raises(SiteDataError, match=r"pairs\.bin"):
        build_site(tmp_path / "o", data)
    assert not (tmp_path / "o" / "data").exists()


def test_build_refuses_symlink_in_data_dir(tmp_path, built):
    data = _copy_data(built, tmp_path / "data")
    secret = tmp_path / "secret.bin"
    secret.write_bytes((data / "seen.bin").read_bytes())
    (data / "seen.bin").unlink()
    (data / "seen.bin").symlink_to(secret)
    with pytest.raises(SiteDataError, match=r"seen\.bin"):
        build_site(tmp_path / "o", data)


def test_synthetic_camp_has_course_structure(built):
    # Ties stay mostly inside courses, and cross courses more on the synthetic special day.
    import numpy as np

    meta = json.loads((built / "data" / "meta.json").read_text())
    n = meta["files"]["pairs"]["count"]
    cols = np.frombuffer((built / "data" / "pairs.bin").read_bytes(), "<u2").reshape(3, n)
    k, a, b = cols
    course = np.array([node["course"] for node in meta["nodes"]])
    cross = course[a] != course[b]
    special = meta["special_days"][0]
    on = (k >= special["start_bin"]) & (k < special["end_bin"])
    assert cross[~on].mean() < 0.3
    assert cross[on].mean() > cross[~on].mean() + 0.15
    assert n < 150_000


def test_synthetic_numbers_match_the_synthetic_camp(built):
    meta = json.loads((built / "data" / "meta.json").read_text())
    agg = json.loads((built / "data" / "aggregates.json").read_text())
    n = agg["numbers"]
    assert n["n_participants"] == len(meta["nodes"])
    assert n["n_presses"] == meta["files"]["presses"]["count"]
    assert n["n_confirmatory"] <= n["n_participants"]
    people = [r["people"] for s, rows in agg.items() if s != "numbers" for r in rows]
    assert max(people) <= n["n_participants"]
