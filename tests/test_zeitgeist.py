"""zeitgeist-platform export: which rows are kept, what is written where.

All rows are invented. User and interview IDs are short strings, not real UUIDs.
"""

import hashlib
import json
from pathlib import Path

import yaml

from social_energy import cli, zeitgeist

AGENT = {"id": "agent-1", "agent_name": "wave_pre", "system_prompt": "PROMPT"}

# Users:
#   u-real      two real calls + survey            -> kept (2 interviews, survey)
#   u-real-ns   one real call, no survey           -> kept (1 interview)
#   u-survey    no calls, survey                   -> kept (survey only)
#   u-tester    one test call + survey             -> dropped (test-only)
#   u-mixed     one test call + one real call      -> kept, test call dropped
#   u-empty     nothing                            -> dropped (empty)
USERS = [
    {"id": "u-real", "custom_info": {"q": "A"}, "post_interview_info": {"ST004": 1},
     "surveys_resolved": [{"question_id": "ST004"}], "surveys_resolved_at": "t"},
    {"id": "u-real-ns", "custom_info": {"q": "B"}, "post_interview_info": None,
     "surveys_resolved": None, "surveys_resolved_at": None},
    {"id": "u-survey", "custom_info": {}, "post_interview_info": {"ST004": 2},
     "surveys_resolved": [], "surveys_resolved_at": "t"},
    {"id": "u-tester", "custom_info": {"q": "T"}, "post_interview_info": {"ST004": 3},
     "surveys_resolved": [], "surveys_resolved_at": "t"},
    {"id": "u-mixed", "custom_info": {"q": "M"}, "post_interview_info": {},
     "surveys_resolved": None, "surveys_resolved_at": None},
    {"id": "u-empty", "custom_info": None, "post_interview_info": {},
     "surveys_resolved": None, "surveys_resolved_at": None},
]  # fmt: skip
INTERVIEWS = [
    {"id": "i1", "user_id": "u-real", "is_test_call": False, "transcript": "x"},
    {"id": "i2", "user_id": "u-real", "is_test_call": False, "transcript": "x"},
    {"id": "i3", "user_id": "u-real-ns", "is_test_call": False, "transcript": "x"},
    {"id": "i4", "user_id": "u-tester", "is_test_call": True, "transcript": "x"},
    {"id": "i5", "user_id": "u-mixed", "is_test_call": True, "transcript": "x"},
    {"id": "i6", "user_id": "u-mixed", "is_test_call": False, "transcript": "x"},
    {"id": "i7", "user_id": "u-ghost", "is_test_call": False, "transcript": "x"},  # no user row
    {"id": "i8", "user_id": "u-ghost", "is_test_call": None, "transcript": "x"},  # null = real
]
SUMMARIES = [{"interview_id": i} for i in ("i1", "i4", "i6")]
QA_PAIRS = [{"interview_id": i, "turn_number": 1} for i in ("i1", "i1", "i4", "i5", "i7")]


def _select():
    return zeitgeist.select(AGENT, INTERVIEWS, SUMMARIES, QA_PAIRS, USERS, deleted_interviews=2)


def test_select_drops_test_calls_and_their_derived_rows():
    export = _select()
    assert [i["id"] for i in export.interviews] == ["i1", "i2", "i3", "i6", "i7", "i8"]
    assert [s["interview_id"] for s in export.summaries] == ["i1", "i6"]
    assert [q["interview_id"] for q in export.qa_pairs] == ["i1", "i1", "i7"]


def test_select_keeps_real_and_survey_only_users_but_not_testers_or_empty():
    export = _select()
    assert [p["user_id"] for p in export.participants] == [
        "u-real", "u-real-ns", "u-survey", "u-mixed",
    ]  # fmt: skip
    by_id = {p["user_id"]: p for p in export.participants}
    assert by_id["u-real"]["n_interviews"] == 2
    assert by_id["u-survey"] == {
        "user_id": "u-survey", "pre_interview_answers": {}, "n_interviews": 0, "has_survey": True,
    }  # fmt: skip
    assert [s["user_id"] for s in export.survey] == ["u-real", "u-survey"]
    assert export.survey[0]["responses"] == {"ST004": 1}


def test_select_never_exports_identity_columns():
    users = [{**USERS[0], "name": "N", "email": "E", "age": 1, "gender": "G"}]
    export = zeitgeist.select(AGENT, INTERVIEWS[:1], [], [], users, deleted_interviews=0)
    rows = json.dumps([export.participants, export.survey])
    assert '"N"' not in rows and '"E"' not in rows and "email" not in rows


def test_select_qa_accounts_for_every_input_row():
    qa = _select().qa
    assert qa == {
        "interviews_in": 8, "interviews_test_dropped": 2, "interviews_out": 6,
        "interviews_without_user_row": 2, "interviews_deleted_on_platform": 2,
        "summaries_in": 3, "summaries_out": 2, "qa_pairs_in": 5, "qa_pairs_out": 3,
        "users_in": 6, "users_test_only_dropped": 1, "users_empty_dropped": 1, "users_out": 4,
        "survey_out": 2,
    }  # fmt: skip
    assert qa["interviews_in"] == qa["interviews_test_dropped"] + qa["interviews_out"]
    assert qa["users_in"] == (
        qa["users_test_only_dropped"] + qa["users_empty_dropped"] + qa["users_out"]
    )


def test_write_lays_out_files_per_agent(tmp_path):
    raw = tmp_path / "raw"
    written = zeitgeist.write(_select(), raw, exported_at="2000-01-01T00:00:00+00:00")
    interviews_dir = raw / "ai-interviews" / "zeitgeist" / "wave_pre"
    survey_dir = raw / "survey" / "zeitgeist" / "wave_pre"
    assert written == {"interviews": interviews_dir, "survey": survey_dir}
    assert sorted(p.name for p in interviews_dir.iterdir()) == [
        "EXPORT.md", "SHA256SUMS", "agent.json", "interviews.jsonl", "participants.jsonl",
        "qa_pairs.jsonl", "summaries.jsonl", "system_prompt.md",
    ]  # fmt: skip
    assert sorted(p.name for p in survey_dir.iterdir()) == [
        "EXPORT.md", "SHA256SUMS", "responses.jsonl",
    ]  # fmt: skip
    lines = (interviews_dir / "interviews.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in lines] == ["i1", "i2", "i3", "i6", "i7", "i8"]
    assert (interviews_dir / "system_prompt.md").read_text() == "PROMPT"
    provenance = (interviews_dir / "EXPORT.md").read_text()
    assert "2000-01-01T00:00:00+00:00" in provenance
    assert "| `interviews_test_dropped` | 2 |" in provenance
    # SHA256SUMS covers every other file in the folder, in `sha256sum -c` format.
    sums = (survey_dir / "SHA256SUMS").read_text().splitlines()
    assert [line.split("  ")[1] for line in sums] == ["EXPORT.md", "responses.jsonl"]
    digest = hashlib.sha256((survey_dir / "responses.jsonl").read_bytes()).hexdigest()
    assert f"{digest}  responses.jsonl" in sums


def _study_yaml(tmp_path: Path, agents) -> Path:
    """Public study.yaml in the repo; the agents live in the private local.yaml beside the data."""
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump({"study_id": "synthetic-camp", "timezone": "UTC"}))
    local = tmp_path / "data" / "synthetic-camp"
    local.mkdir(parents=True, exist_ok=True)
    (local / "local.yaml").write_text(
        yaml.safe_dump({"ai_interviews": {"zeitgeist": {"agents": agents}}})
    )
    return path


def test_cli_needs_the_database_url(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    monkeypatch.delenv(zeitgeist.DSN_ENV_VAR, raising=False)
    study = _study_yaml(tmp_path, [{"id": "agent-1", "wave": "pre"}])
    assert cli.main(["fetch-zeitgeist", str(study)]) == 2
    assert zeitgeist.DSN_ENV_VAR in capsys.readouterr().out


def test_cli_fetches_every_configured_agent_into_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    monkeypatch.setenv(zeitgeist.DSN_ENV_VAR, "postgresql://fake")
    calls = []

    def fake_fetch(dsn, agent_id):
        calls.append((dsn, agent_id))
        agent = {**AGENT, "id": agent_id, "agent_name": f"name-{agent_id}"}
        return zeitgeist.select(agent, INTERVIEWS, SUMMARIES, QA_PAIRS, USERS, 0)

    monkeypatch.setattr(zeitgeist, "fetch", fake_fetch)
    study = _study_yaml(tmp_path, [{"id": "a", "wave": "pre"}, {"id": "b", "wave": "post"}])
    assert cli.main(["fetch-zeitgeist", str(study)]) == 0
    assert calls == [("postgresql://fake", "a"), ("postgresql://fake", "b")]
    raw = tmp_path / "data" / "synthetic-camp" / "raw"
    for name in ("name-a", "name-b"):
        assert (raw / "ai-interviews" / "zeitgeist" / name / "interviews.jsonl").exists()
        assert (raw / "survey" / "zeitgeist" / name / "responses.jsonl").exists()


def test_cli_without_configured_agents_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    monkeypatch.setenv(zeitgeist.DSN_ENV_VAR, "postgresql://fake")
    study = tmp_path / "study.yaml"
    study.write_text(yaml.safe_dump({"study_id": "x", "timezone": "UTC"}))
    assert cli.main(["fetch-zeitgeist", str(study)]) == 1
    assert "ai_interviews" in capsys.readouterr().out


def test_fetch_is_read_only():
    # fetch() is the only code that touches the platform database.
    import inspect

    assert "read_only = True" in inspect.getsource(zeitgeist.fetch)
    queries = {k: v for k, v in vars(zeitgeist).items() if k.endswith("_SQL")}
    assert len(queries) == 6
    for name, sql in queries.items():
        assert sql.strip().lower().startswith("select"), name


def test_identity_columns_are_never_queried():
    import re

    users_sql = zeitgeist._USERS_SQL.lower()
    for column in ("name", "email", "age", "gender", "post_name", "post_email"):
        assert not re.search(rf"\b{column}\b", users_sql), column
