import pytest
import pyzipper

from social_energy import cli, paths
from social_energy.package import PackageError, PackageSpec, build, collect

SPEC = """
archive: demo-data
title: Demo study data
intro: Synthetic.
exclude: ["*.log"]
entries:
  - path: demo/spine
    about: The spine.
  - path: demo/derived/analyses
    exclude: ["*-pre-*"]
    about: Analysis outputs | with a pipe.
  - path: _team/questions.md
    about: Questions.
"""


def _tree(root):
    files = {
        "demo/spine/people.yaml": "- {id: 1}\n",
        "demo/spine/run.log": "noise\n",
        "demo/derived/analyses/outcomes/c1.csv": "a,b\n1,2\n",
        "demo/derived/analyses/outcomes-pre-fix/c1.csv": "old\n",
        "demo/derived/beacons/readouts.csv": "never packed\n",
        "_team/questions.md": "# Q\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


def _spec(tmp_path, text=SPEC):
    path = tmp_path / "package.yaml"
    path.write_text(text, encoding="utf-8")
    return PackageSpec.load(path)


def test_collect_keeps_layout_and_applies_excludes(tmp_path):
    root = tmp_path / "data"
    _tree(root)
    found = collect(root, _spec(tmp_path))
    names = sorted(f.arcname for files in found.values() for f in files)
    assert names == [
        "_team/questions.md",
        "demo/derived/analyses/outcomes/c1.csv",
        "demo/spine/people.yaml",
    ]


def test_build_writes_an_encrypted_checked_archive(tmp_path):
    root = tmp_path / "data"
    _tree(root)
    archive = build(root, _spec(tmp_path), tmp_path / "out", "correct horse battery")
    assert archive.name == "demo-data.zip"
    with pyzipper.AESZipFile(archive) as zf:
        with pytest.raises(RuntimeError):
            zf.read("demo/spine/people.yaml")  # no password, no data
        zf.setpassword(b"correct horse battery")
        assert zf.read("demo/spine/people.yaml") == b"- {id: 1}\n"
        readme = zf.read("README.md").decode()
        sums = zf.read("SHA256SUMS").decode()
    assert "| `demo/derived/analyses` | 1 |" in readme
    assert "with a pipe" in readme and "\\|" in readme
    assert sums.count("\n") == 3 and "demo/spine/people.yaml" in sums
    assert not (tmp_path / "out" / "demo-data.zip.partial").exists()


def test_wrong_password_cannot_read(tmp_path):
    root = tmp_path / "data"
    _tree(root)
    archive = build(root, _spec(tmp_path), tmp_path / "out", "correct horse battery")
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(b"wrong password here")
        with pytest.raises(RuntimeError):
            zf.read("README.md")


def test_missing_entry_and_overlap_are_refused(tmp_path):
    root = tmp_path / "data"
    _tree(root)
    with pytest.raises(PackageError, match="does not exist"):
        collect(root, _spec(tmp_path, SPEC.replace("demo/spine", "demo/nowhere")))
    overlap = SPEC + "  - path: demo/spine/people.yaml\n    about: Again.\n"
    with pytest.raises(PackageError, match="same file"):
        collect(root, _spec(tmp_path, overlap))


def test_short_password_and_output_inside_repo_are_refused(tmp_path):
    root = tmp_path / "data"
    _tree(root)
    with pytest.raises(PackageError, match="12 characters"):
        build(root, _spec(tmp_path), tmp_path / "out", "short")
    with pytest.raises(paths.DataRootError, match="inside the repository"):
        build(root, _spec(tmp_path), paths.REPO_ROOT / "exports", "correct horse battery")


def test_cli_writes_the_password_apart_from_the_archive(tmp_path, monkeypatch):
    root = tmp_path / "data"
    _tree(root)
    study = tmp_path / "studies" / "demo"
    study.mkdir(parents=True)
    (study / "study.yaml").write_text("study_id: demo\ntimezone: Europe/Berlin\n")
    (study / "package.yaml").write_text(SPEC, encoding="utf-8")
    monkeypatch.setenv(paths.ENV_VAR, str(root))
    monkeypatch.delenv("SOCIAL_ENERGY_PACKAGE_PASSWORD", raising=False)
    assert cli.main(["package", str(study / "study.yaml")]) == 0
    exports = root / "demo" / "exports"
    password = (exports / "passwords" / "demo-data.txt").read_text().strip()
    with pyzipper.AESZipFile(exports / "demo-data.zip") as zf:
        zf.setpassword(password.encode())
        assert zf.testzip() is None
