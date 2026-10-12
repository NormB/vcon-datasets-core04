"""Tests for tools/fake_vcons.py: the core-04 corrections proposed upstream
to vcon-dev/fake-vcons.

Each rule is driven from the case it must change and the cases it must
leave alone, and the shapes fake-vcons actually holds are checked against
the core-04 schema after correction.
"""

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import core04  # noqa: E402
import fake_vcons  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schema" / "vcon.schema.json"

CREATED = "2025-02-26T20:02:41.706860+00:00"

LAWFUL_BASIS = {
    "purpose": "lawful_basis",
    "encoding": "json",
    "party": 0,
    "dialog": 0,
    "body": json.dumps({"lawful_basis": "legitimate_interests"}),
}

BRIA = {
    "body": {"state": "ANSWERED", "received_at": "2025-02-26T20:02:41.707140"},
    "encoding": "none",
    "purpose": "bria_call_ended",
    "party": 0,
    "dialog": 0,
}

TEXT_NO_ENCODING = {
    "type": "text",
    "start": "2025-02-26T20:02:41.706620+00:00",
    "parties": [0],
    "originator": 0,
    "body": "Hello, thank you for calling.",
    "mediatype": "text/plain",
}


def container(dialog=None, attachments=None):
    """A container shaped like a fake-vcons file at 7e91cbe."""
    return {
        "vcon": "0.4.0",
        "uuid": "02105744-f8f8-4eb3-882b-d78eced80c78",
        "created_at": CREATED,
        "parties": [{"name": "A", "validation": "synthetic"}],
        "dialog": [copy.deepcopy(TEXT_NO_ENCODING)] if dialog is None else dialog,
        "attachments": attachments if attachments is not None else [],
    }


def rules(changes):
    return sorted(c.rule for c in changes)


def test_an_attachment_without_start_takes_the_containers_created_at():
    doc = container(attachments=[copy.deepcopy(LAWFUL_BASIS)])
    result = fake_vcons.correct(doc)
    assert doc["attachments"][0]["start"] == CREATED
    assert "attachment-start" in rules(result.applied)


def test_an_attachment_that_has_a_start_keeps_it():
    attachment = dict(copy.deepcopy(LAWFUL_BASIS), start="2020-01-01T00:00:00+00:00")
    doc = container(attachments=[attachment])
    result = fake_vcons.correct(doc)
    assert doc["attachments"][0]["start"] == "2020-01-01T00:00:00+00:00"
    assert "attachment-start" not in rules(result.applied)


def test_a_json_string_body_and_a_json_object_body_both_take_application_json():
    doc = container(attachments=[copy.deepcopy(LAWFUL_BASIS), copy.deepcopy(BRIA)])
    fake_vcons.correct(doc)
    assert [a["mediatype"] for a in doc["attachments"]] == ["application/json"] * 2


def test_a_string_body_that_is_not_json_gets_no_mediatype_and_is_reported():
    attachment = {"purpose": "note", "encoding": "none", "party": 0, "dialog": 0, "body": "plain words"}
    doc = container(attachments=[attachment])
    result = fake_vcons.correct(doc)
    assert "mediatype" not in doc["attachments"][0]
    assert "attachment-mediatype" in rules(result.unresolved)


def test_a_text_dialog_with_a_string_body_takes_encoding_none():
    doc = container()
    result = fake_vcons.correct(doc)
    assert doc["dialog"][0]["encoding"] == "none"
    assert "dialog-encoding" in rules(result.applied)


def test_a_dialog_that_has_an_encoding_keeps_it():
    dialog = dict(copy.deepcopy(TEXT_NO_ENCODING), encoding="base64url")
    doc = container(dialog=[dialog])
    result = fake_vcons.correct(doc)
    assert doc["dialog"][0]["encoding"] == "base64url"
    assert "dialog-encoding" not in rules(result.applied)


def test_a_dialog_with_a_non_string_body_and_no_encoding_is_reported_not_guessed():
    dialog = dict(copy.deepcopy(TEXT_NO_ENCODING), body={"k": 1})
    doc = container(dialog=[dialog])
    result = fake_vcons.correct(doc)
    assert "encoding" not in doc["dialog"][0]
    assert "dialog-encoding" in rules(result.unresolved)


def test_an_object_body_under_encoding_none_is_reported_and_left_unchanged():
    # Section 2.3 defines "none" as a JSON string; an object body needs
    # "json". Changing it would change a value, so it is only reported.
    doc = container(attachments=[copy.deepcopy(BRIA)])
    result = fake_vcons.correct(doc)
    assert doc["attachments"][0]["encoding"] == "none"
    assert "attachment-encoding-mismatch" in rules(result.unresolved)


def test_every_change_only_adds_keys():
    before = container(attachments=[copy.deepcopy(LAWFUL_BASIS), copy.deepcopy(BRIA)])
    after = copy.deepcopy(before)
    fake_vcons.correct(after)
    core04.assert_additive(before, after)


def test_the_fake_vcons_shapes_validate_against_core04_after_correction():
    v = core04.validator(SCHEMA)
    doc = container(attachments=[copy.deepcopy(LAWFUL_BASIS), copy.deepcopy(BRIA)])
    assert core04.findings(doc, v), "premise: the uncorrected shapes are invalid"
    fake_vcons.correct(doc)
    assert core04.findings(doc, v) == []
