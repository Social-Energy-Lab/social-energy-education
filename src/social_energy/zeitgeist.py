"""Export AI interviews and the post-interview survey from zeitgeist-platform.

zeitgeist-platform runs voice interviews with an "agent" and stores, per agent, the
calls (transcripts), its own summaries and question/answer segments, and per user
the answers to the survey delivered after the call. This module copies one agent's
rows, read-only, into ``$SOCIAL_ENERGY_DATA/<study>/raw/``.

Unlike an ingest, the export *drops* rows, because these are rows that never
belonged to the study:

* test calls (``is_test_call``) and everything derived from them;
* users whose only calls were tests (pilot testers, including their survey);
* users with neither a real call nor survey answers.

Calls deleted on the platform are never fetched; only their count is recorded.
Identity columns (name, email, age, gender) are never selected. Every dropped row
is counted in ``qa`` and in the ``EXPORT.md`` written next to the files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DSN_ENV_VAR = "ZEITGEIST_DATABASE_URL"

Row = dict[str, Any]


@dataclass(frozen=True)
class Export:
    agent: Row
    interviews: list[Row]
    summaries: list[Row]
    qa_pairs: list[Row]
    participants: list[Row]
    survey: list[Row]
    qa: dict[str, int]


def _filled(value: Any) -> bool:
    return value not in (None, {}, [], "")


def select(
    agent: Row,
    interviews: list[Row],
    summaries: list[Row],
    qa_pairs: list[Row],
    users: list[Row],
    deleted_interviews: int,
) -> Export:
    real = [i for i in interviews if not i.get("is_test_call")]
    kept_ids = {i["id"] for i in real}
    real_calls: dict[str, int] = {}
    test_calls: dict[str, int] = {}
    for i in interviews:
        counter = test_calls if i.get("is_test_call") else real_calls
        counter[i["user_id"]] = counter.get(i["user_id"], 0) + 1

    kept_users, test_only, empty = [], 0, 0
    for u in users:
        n_real, n_test = real_calls.get(u["id"], 0), test_calls.get(u["id"], 0)
        if n_real:
            kept_users.append(u)
        elif n_test:
            test_only += 1
        elif _filled(u.get("post_interview_info")):
            kept_users.append(u)
        else:
            empty += 1

    user_ids = {u["id"] for u in users}
    participants = [
        {
            "user_id": u["id"],
            "pre_interview_answers": u.get("custom_info"),
            "n_interviews": real_calls.get(u["id"], 0),
            "has_survey": _filled(u.get("post_interview_info")),
        }
        for u in kept_users
    ]
    survey = [
        {
            "user_id": u["id"],
            "surveys_resolved_at": u.get("surveys_resolved_at"),
            "responses": u["post_interview_info"],
            "surveys_resolved": u.get("surveys_resolved"),
        }
        for u in kept_users
        if _filled(u.get("post_interview_info"))
    ]
    kept_summaries = [s for s in summaries if s["interview_id"] in kept_ids]
    kept_qa = [q for q in qa_pairs if q["interview_id"] in kept_ids]
    qa = {
        "interviews_in": len(interviews),
        "interviews_test_dropped": len(interviews) - len(real),
        "interviews_out": len(real),
        "interviews_without_user_row": sum(1 for i in real if i["user_id"] not in user_ids),
        "interviews_deleted_on_platform": deleted_interviews,
        "summaries_in": len(summaries),
        "summaries_out": len(kept_summaries),
        "qa_pairs_in": len(qa_pairs),
        "qa_pairs_out": len(kept_qa),
        "users_in": len(users),
        "users_test_only_dropped": test_only,
        "users_empty_dropped": empty,
        "users_out": len(kept_users),
        "survey_out": len(survey),
    }
    return Export(agent, real, kept_summaries, kept_qa, participants, survey, qa)


def _write_jsonl(path: Path, rows: list[Row]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(export: Export, raw_dir: Path, exported_at: str) -> dict[str, Path]:
    """Write one agent's export under ``raw_dir``; returns the two folders written."""
    name = export.agent["agent_name"]
    interviews_dir = raw_dir / "ai-interviews" / "zeitgeist" / name
    survey_dir = raw_dir / "survey" / "zeitgeist" / name
    for d in (interviews_dir, survey_dir):
        d.mkdir(parents=True, exist_ok=True)

    agent = {k: v for k, v in export.agent.items() if k != "system_prompt"}
    (interviews_dir / "agent.json").write_text(
        json.dumps(agent, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (interviews_dir / "system_prompt.md").write_text(
        export.agent.get("system_prompt") or "", encoding="utf-8"
    )
    files = {
        interviews_dir / "interviews.jsonl": export.interviews,
        interviews_dir / "summaries.jsonl": export.summaries,
        interviews_dir / "qa_pairs.jsonl": export.qa_pairs,
        interviews_dir / "participants.jsonl": export.participants,
        survey_dir / "responses.jsonl": export.survey,
    }
    for path, rows in files.items():
        _write_jsonl(path, rows)

    provenance = "\n".join(
        [
            "# zeitgeist-platform export (LOCAL ONLY, never commit)",
            "",
            f"- Exported: {exported_at}, read-only, by `social-energy fetch-zeitgeist`.",
            f"- Agent: `{export.agent['id']}` (`{name}`).",
            f"- Interviews: `raw/ai-interviews/zeitgeist/{name}/`."
            f" Survey: `raw/survey/zeitgeist/{name}/`.",
            "- Dropped: test calls and their summaries/segments, users whose only calls were"
            " tests, users with no call and no survey. Calls deleted on the platform are not"
            " fetched. Identity columns (name, email, age, gender) are never selected.",
            "- Join key: the platform user UUID (`user_id`). Linking it to a study ID happens"
            " only in the local spine.",
            "- Integrity: `sha256sum -c SHA256SUMS` in each folder.",
            "",
            "## Counts",
            "",
            "| Count | Rows |",
            "|---|---|",
            *(f"| `{k}` | {v} |" for k, v in export.qa.items()),
            "",
        ]
    )
    for d in (interviews_dir, survey_dir):
        (d / "EXPORT.md").write_text(provenance, encoding="utf-8")
        sums = [f"{_sha256(f)}  {f.name}" for f in sorted(d.iterdir()) if f.name != "SHA256SUMS"]
        (d / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return {"interviews": interviews_dir, "survey": survey_dir}


_AGENT_SQL = """
select id, agent_name, institution, status, target_group, conversation_goal, hypothesis,
       questions, knowledge_base, things_to_avoid, languages, anonymized, gdpr_mode,
       recording_enabled, collect_info, transcriber_provider, transcriber_model,
       transcriber_language, voice_provider, personality, system_prompt, first_messages,
       summary_prompt, post_interview_config, processing_llm, created_at, updated_at
from agents_v2 where id = %(agent)s
"""
_INTERVIEWS_SQL = """
select id, user_id, is_test_call, vapi_call_id, started_at, ended_at, duration, status,
       interview_mode, channel, transcript, cleaned_transcript, cleaned_at, summary,
       structured_data, success_evaluation, raw_data, quality_flagged, quality_severity,
       quality_summary, quality_signals, created_at
from interviews where agent_id = %(agent)s order by started_at, id
"""
_SUMMARIES_SQL = """
select s.interview_id, s.language, s.source_language, s.summary_text, s.key_threads,
       s.generated_model, s.created_at
from interview_summaries s join interviews i on i.id = s.interview_id
where i.agent_id = %(agent)s order by s.interview_id, s.language
"""
_QA_PAIRS_SQL = """
select id, transcript_id as interview_id, turn_number, question, answer, description, reason,
       content_category, qa_status, sentiment, salience, processing_language, source_language,
       extraction_model, extraction_at
from qa_pairs where agent_id = %(agent)s order by transcript_id, turn_number, id
"""
_USERS_SQL = """
select id, custom_info, post_interview_info, surveys_resolved, surveys_resolved_at
from users where agent_id = %(agent)s order by created_at, id
"""
_DELETED_SQL = "select count(*) as n from deleted_interviews where agent_id = %(agent)s"


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def fetch(dsn: str, agent_id: str) -> Export:
    """Read one agent's rows from the platform database (read-only session)."""
    import psycopg  # optional dependency: uv sync --extra zeitgeist
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.read_only = True
        params = {"agent": agent_id}

        def rows(sql: str) -> list[Row]:
            return conn.execute(sql, params).fetchall()

        agents = rows(_AGENT_SQL)
        if not agents:
            raise LookupError(f"no agent {agent_id} on the platform")
        return select(
            agents[0],
            [
                {**r, "id": str(r["id"]), "user_id": _str(r["user_id"])}
                for r in rows(_INTERVIEWS_SQL)
            ],
            [{**r, "interview_id": str(r["interview_id"])} for r in rows(_SUMMARIES_SQL)],
            [{**r, "interview_id": str(r["interview_id"])} for r in rows(_QA_PAIRS_SQL)],
            [{**r, "id": str(r["id"])} for r in rows(_USERS_SQL)],
            deleted_interviews=rows(_DELETED_SQL)[0]["n"],
        )
