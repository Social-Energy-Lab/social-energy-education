"""Survey ingest (zeitgeist-platform export) on a hand-written golden fixture and synth.

Golden fixture ``fixtures/survey/zeitgeist_responses.jsonl`` (all values invented):

u-1, version 18, 2026-08-05 10:00 +00:00
    q_pre "7" (the study-ID item) · ST004 "2"/3 · B1 "4"/4 · B4A "ZGL_B4_01" (code, "don't know")
    · ST016 "8" (number) · ZGL_A1_1 free text                                   -> 6 rows, all ok
u-2, version 16, 2026-08-06 09:30 +02:00 (= 07:30 UTC)
    q_pre "12" · B1 "5" with scale_max 4 (out of range) · SYMBOL_3 code
    · GRADIENT_variable_C21 "3" only in the flat view (old form version)         -> 4 rows, 1 not ok
u-3, version 17, 2026-08-07 12:00 +00:00
    q_pre "" (empty) · ST004 "" in the resolved view but "1" in the flat view (mismatch, empty)
                                                                                 -> 2 rows, 2 not ok
Rows: 6 + 4 + 2 = 12. Resolved items 6 + 3 + 2 = 11, flat-only 1, so 11 + 1 = 12.
Flat items (without __survey_version): 5 + 3 + 1 = 9, all of which also appear in rows.
"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from social_energy import cli
from social_energy.survey import SurveyConfig, ingest_zeitgeist
from social_energy.synth.survey import generate_survey

FIXTURE = Path(__file__).parent / "fixtures" / "survey" / "zeitgeist_responses.jsonl"
CONFIG = SurveyConfig(study_id_item="q_pre")


def _row(items: pl.DataFrame, respondent: str, item: str) -> dict:
    rows = items.filter((pl.col("respondent") == respondent) & (pl.col("item") == item))
    assert rows.height == 1, (respondent, item, rows.height)
    return rows.row(0, named=True)


def test_one_row_per_respondent_and_answered_item():
    items = ingest_zeitgeist([FIXTURE], CONFIG).items
    assert items.height == 12
    assert items.group_by("respondent").len().sort("respondent").rows() == [
        ("u-1", 6), ("u-2", 4), ("u-3", 2),
    ]  # fmt: skip
    # Unanswered items are absent in the export and stay absent (u-2 has no ST004).
    assert items.filter((pl.col("respondent") == "u-2") & (pl.col("item") == "ST004")).is_empty()


def test_numbers_codes_and_text_are_separated():
    items = ingest_zeitgeist([FIXTURE], CONFIG).items
    st004 = _row(items, "u-1", "ST004")
    assert (st004["value_numeric"], st004["value_code"], st004["scale_max"]) == (2, None, 3)
    assert st004["block"] is None and st004["type"] == "single_choice"
    dont_know = _row(items, "u-1", "B4A_SC173.SC173Q01")
    assert (dont_know["value_numeric"], dont_know["value_code"]) == (None, "ZGL_B4_01")
    assert dont_know["block"] == "B4A_SC173" and dont_know["ok"]
    text = _row(items, "u-1", "ZGL_A1_1")
    assert text["free_text"] and text["value_numeric"] is None and text["value_code"] is None
    assert _row(items, "u-1", "ST016")["value_numeric"] == 8
    assert _row(items, "u-2", "SYMBOL_3")["value_code"] == "SYMBOL_3_1"


def test_flat_only_items_from_older_versions_are_kept_and_flagged():
    items = ingest_zeitgeist([FIXTURE], CONFIG).items
    old = _row(items, "u-2", "GRADIENT_variable_C21")
    assert old["flat_only"] and old["ok"]
    assert (old["value_raw"], old["value_numeric"], old["type"], old["scale_max"]) == (
        "3", 3, None, None,
    )  # fmt: skip
    assert items["flat_only"].sum() == 1


def test_flags_and_ok():
    items = ingest_zeitgeist([FIXTURE], CONFIG).items
    assert _row(items, "u-2", "B1_ST034.ST034Q01TA")["out_of_range"]
    st004 = _row(items, "u-3", "ST004")
    # The resolved view wins; the disagreement with the flat view is flagged.
    assert st004["value_raw"] == "" and st004["empty"] and st004["mismatch"]
    assert _row(items, "u-3", "q_pre")["empty"]
    not_ok = items.filter(~pl.col("ok")).select("respondent", "item").sort("respondent", "item")
    assert not_ok.rows() == [
        ("u-2", "B1_ST034.ST034Q01TA"), ("u-3", "ST004"), ("u-3", "q_pre"),
    ]  # fmt: skip


def test_respondents_table_carries_version_time_and_typed_study_id():
    tables = ingest_zeitgeist([FIXTURE], CONFIG)
    resp = tables.respondents.sort("respondent")
    assert resp["respondent"].to_list() == ["u-1", "u-2", "u-3"]
    assert resp["survey_version"].to_list() == [18, 16, 17]
    assert resp["submitted_at"].to_list() == [
        datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
        datetime(2026, 8, 6, 7, 30, tzinfo=UTC),
        datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
    ]
    assert resp["study_id_raw"].to_list() == ["7", "12", None]
    assert resp["n_items"].to_list() == [6, 4, 2]
    assert resp["n_ok"].to_list() == [6, 3, 0]
    assert resp["line_no"].to_list() == [1, 2, 3]
    # Every item row carries its respondent's version and time.
    assert _row(tables.items, "u-2", "SYMBOL_3")["survey_version"] == 16


def test_qa_accounts_for_every_input_record():
    qa = ingest_zeitgeist([FIXTURE], CONFIG).qa
    assert qa == {
        "files": 1, "respondents": 3, "survey_versions": {"16": 1, "17": 1, "18": 1},
        "resolved_items_in": 11, "flat_items_in": 9, "rows_out": 12,
        "flat_only": 1, "mismatch": 1, "empty": 2, "out_of_range": 1, "free_text": 1,
        "not_ok": 3,
    }  # fmt: skip
    assert qa["resolved_items_in"] + qa["flat_only"] == qa["rows_out"]


def test_without_study_id_item_the_column_is_null():
    resp = ingest_zeitgeist([FIXTURE], SurveyConfig()).respondents
    assert resp["study_id_raw"].null_count() == 3


def test_synthetic_export_round_trips(tmp_path):
    """Oracle: every generated answer comes back exactly, and nothing else does."""
    truth = generate_survey(tmp_path / "responses.jsonl", n_respondents=25, seed=3)
    tables = ingest_zeitgeist([tmp_path / "responses.jsonl"], SurveyConfig("q_id"))
    got = {
        (r["respondent"], r["item"]): r["value_numeric"]
        for r in tables.items.filter(pl.col("value_numeric").is_not_null()).iter_rows(named=True)
    }
    assert got == truth.numeric
    assert dict(tables.respondents.select("respondent", "study_id_raw").iter_rows()) == (
        truth.study_ids
    )
    assert tables.qa["not_ok"] == truth.n_out_of_range
    assert tables.qa["flat_only"] == truth.n_flat_only


def test_ingest_survey_cli_writes_parquet_and_qa(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "synthetic-camp" / "raw" / "survey" / "zeitgeist" / "agent_x"
    raw.mkdir(parents=True)
    (raw / "responses.jsonl").write_bytes(FIXTURE.read_bytes())
    monkeypatch.setenv("SOCIAL_ENERGY_DATA", str(tmp_path / "data"))
    study = tmp_path / "study.yaml"
    study.write_text("study_id: synthetic-camp\ntimezone: UTC\n")
    (tmp_path / "data" / "synthetic-camp" / "local.yaml").write_text(
        "survey:\n  zeitgeist:\n    study_id_item: q_pre\n"
    )
    assert cli.main(["ingest-survey", str(study)]) == 0
    out = tmp_path / "data" / "synthetic-camp" / "derived" / "survey"
    assert pl.read_parquet(out / "items.parquet").height == 12
    assert pl.read_parquet(out / "respondents.parquet")["study_id_raw"].to_list() == [
        "7", "12", None,
    ]  # fmt: skip
    assert (out / "qa.json").exists()
