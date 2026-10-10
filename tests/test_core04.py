"""Tests for tools/core04.py and tools/build.py.

Every rule the corrected corpus depends on is driven here from both sides:
the case it must change and the cases it must leave alone.
"""

import copy
import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import build  # noqa: E402
import core04  # noqa: E402

SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schema" / "vcon.schema.json"


TEXT_DIALOG = {"type": "text", "start": "2026-03-28T03:34:54+00:00", "parties": [0],
               "body": "x", "encoding": "none", "mediatype": "text/plain"}


def container(**extra):
    """A minimal core-04-valid container, plus whatever the test adds."""
    doc = {
        "vcon": "0.4.0",
        "uuid": "019d3282-5162-8f9d-9dd8-dd37220d739c",
        "created_at": "2026-03-28T03:34:54+00:00",
        "parties": [{"name": "A"}],
        "dialog": [TEXT_DIALOG],
        "attachments": [],
    }
    doc.update(extra)
    return doc


def attachment(**fields):
    base = {"purpose": "tags", "start": "2026-03-28T03:34:54+00:00", "party": 0, "dialog": 0}
    base.update(fields)
    return base


# ---- attachment-mediatype ----

def test_json_body_gets_application_json():
    doc = container(attachments=[attachment(encoding="json", body='{"a": 1}')])
    result = core04.correct(doc)
    assert doc["attachments"][0]["mediatype"] == "application/json"
    assert result.applied == [core04.Change("attachment-mediatype", "/attachments/0")]
    assert result.unresolved == []


def test_existing_mediatype_is_left_alone():
    doc = container(attachments=[attachment(encoding="json", body="{}", mediatype="text/x-odd")])
    result = core04.correct(doc)
    assert doc["attachments"][0]["mediatype"] == "text/x-odd"
    assert result.applied == [] and result.unresolved == []


def test_url_attachment_is_not_inline_and_is_left_alone():
    doc = container(attachments=[attachment(url="https://example.com/a", content_hash="sha512-x")])
    result = core04.correct(doc)
    assert "mediatype" not in doc["attachments"][0]
    assert result.applied == [] and result.unresolved == []


def test_json_encoding_with_unparsable_body_is_unresolved_not_guessed():
    doc = container(attachments=[attachment(encoding="json", body="{not json")])
    result = core04.correct(doc)
    assert "mediatype" not in doc["attachments"][0]
    assert result.unresolved == [core04.Change("attachment-mediatype", "/attachments/0")]


@pytest.mark.parametrize("encoding", ["none", "base64url", None])
@pytest.mark.parametrize("body", ["hello", '{"a": 1}'])
def test_non_json_encoding_is_unresolved_not_guessed(encoding, body):
    # A JSON-looking body under another encoding is still not settled by the data.
    fields = {"body": body}
    if encoding is not None:
        fields["encoding"] = encoding
    doc = container(attachments=[attachment(**fields)])
    result = core04.correct(doc)
    assert "mediatype" not in doc["attachments"][0]
    assert result.unresolved == [core04.Change("attachment-mediatype", "/attachments/0")]


def test_correction_never_touches_other_fields():
    doc = container(attachments=[attachment(encoding="json", body='{"a": 1}')])
    before = copy.deepcopy(doc)
    core04.correct(doc)
    del doc["attachments"][0]["mediatype"]
    assert doc == before


# ---- the additive invariant ----

def test_additive_accepts_added_keys():
    core04.assert_additive({"a": [{"b": 1}]}, {"a": [{"b": 1, "c": 2}]})


@pytest.mark.parametrize("after", [
    {"a": [{"b": 2}]},          # value changed
    {"a": [{}]},                # key removed
    {"a": []},                  # list item removed
    {"a": [{"b": 1}, {"x": 1}]},  # list item added
    {"a": {"b": 1}},            # type changed
])
def test_additive_rejects_anything_but_an_added_key(after):
    with pytest.raises(core04.NotAdditive):
        core04.assert_additive({"a": [{"b": 1}]}, after)


# ---- serialization ----

@pytest.mark.parametrize("style", core04.STYLES)
def test_every_style_round_trips(style):
    doc = {"s": "café", "n": [1, {"k": None}]}
    raw = core04.dump(doc, style)
    assert core04.detect_style(raw, json.loads(raw)) == style
    assert core04.dump(json.loads(raw), style) == raw


def test_detect_style_refuses_bytes_it_cannot_reproduce():
    raw = b'{"a":1}'  # compact without spaces: none of the styles
    with pytest.raises(core04.UnknownStyle):
        core04.detect_style(raw, json.loads(raw))


def test_added_key_is_appended_after_existing_keys():
    doc = container(attachments=[attachment(encoding="json", body="{}")])
    core04.correct(doc)
    assert list(doc["attachments"][0])[-1] == "mediatype"


# ---- validation ----

def test_validator_asserts_every_format_the_schema_uses():
    validator = core04.validator(SCHEMA)
    formats = core04.schema_formats(json.loads(SCHEMA.read_text()))
    assert formats == {"date-time", "uri", "uuid"}
    for fmt in formats:
        assert fmt in validator.format_checker.checkers, fmt


@pytest.mark.parametrize("field,value", [
    ("created_at", "not a date"),
    ("uuid", "not-a-uuid"),
])
def test_validator_reports_bad_formats(field, value):
    doc = container(**{field: value})
    keys = core04.findings(doc, core04.validator(SCHEMA))
    assert any(k.startswith(f"/{field} format") for k in keys), keys


def test_bad_uri_is_reported():
    doc = container(dialog=[{
        "type": "recording", "start": "2026-03-28T03:34:54+00:00", "parties": [0],
        "url": "not a uri", "content_hash": "sha512-" + "A" * 86, "mediatype": "audio/mpeg",
    }])
    keys = core04.findings(doc, core04.validator(SCHEMA))
    assert "/dialog/*/url format: not a uri" in keys, keys


def test_minimal_container_is_valid():
    assert core04.findings(container(), core04.validator(SCHEMA)) == []


def test_missing_mediatype_finding_key_names_the_property():
    doc = container(attachments=[attachment(encoding="json", body="{}")])
    keys = core04.findings(doc, core04.validator(SCHEMA))
    assert keys == ["/attachments/* required: 'mediatype' is a required property"]


def test_corrected_attachment_validates():
    doc = container(attachments=[attachment(encoding="json", body="{}")])
    core04.correct(doc)
    assert core04.findings(doc, core04.validator(SCHEMA)) == []


# ---- index errors ----

def test_attachment_dialog_index_past_the_end():
    doc = container(attachments=[attachment(encoding="json", body="{}", dialog=1)])
    assert core04.index_errors(doc) == {"attachment-dialog-index"}


def test_dialog_party_index_past_the_end():
    doc = container(dialog=[{"type": "text", "start": "2026-03-28T03:34:54+00:00",
                             "parties": [0, 1], "body": "x", "encoding": "none",
                             "mediatype": "text/plain"}])
    assert core04.index_errors(doc) == {"dialog-party-index"}


def test_analysis_dialog_index_past_the_end():
    doc = container(analysis=[{"type": "summary", "dialog": 1, "vendor": "v",
                               "body": "x", "encoding": "none"}])
    assert core04.index_errors(doc) == {"analysis-dialog-index"}


def test_indexes_in_range_are_not_errors():
    doc = container(
        dialog=[{"type": "text", "start": "2026-03-28T03:34:54+00:00", "parties": [0],
                 "body": "x", "encoding": "none", "mediatype": "text/plain"}],
        attachments=[attachment(encoding="json", body="{}", dialog=0)],
        analysis=[{"type": "summary", "dialog": [0], "vendor": "v"}],
    )
    assert core04.index_errors(doc) == set()


# ---- pins ----

def test_parse_pins_skips_comments_and_header():
    text = ("# comment\n#\n# name\turl\tcommit\tlicense\n"
            "ds\thttps://example.com/ds\t" + "a" * 40 + "\tMIT\n")
    assert core04.parse_pins(text) == [core04.Pin("ds", "https://example.com/ds", "a" * 40, "MIT")]


@pytest.mark.parametrize("row", [
    "ds\thttps://example.com/ds\tabc\tMIT",        # short commit
    "ds\thttps://example.com/ds\t" + "a" * 40,     # missing license
    "../x\thttps://example.com/ds\t" + "a" * 40 + "\tMIT",  # name escapes
])
def test_parse_pins_rejects_bad_rows(row):
    with pytest.raises(ValueError):
        core04.parse_pins(row + "\n")


# ---- the build, end to end, from a local pinned repository ----

def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1"})


def upstream(tmp_path, files):
    repo = tmp_path / "upstream"
    for rel, data in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    repo.mkdir(exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x")
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    return repo, head


def test_build_corrects_copies_license_and_reports(tmp_path):
    bad = container(attachments=[attachment(encoding="json", body="{}")])
    good = container()
    raw_bad = core04.dump(bad, core04.STYLES[0])
    raw_good = core04.dump(good, core04.STYLES[2])
    repo, head = upstream(tmp_path, {
        "LICENSE": b"MIT License\n",
        "a/one.vcon.json": raw_bad,
        "b/two.vcon.json": raw_good,
        "notes.json": b"{}",
    })
    pin = core04.Pin("ds", str(repo), head, "MIT")
    out = tmp_path / "out"
    report = build.build([pin], tmp_path / "cache", out, SCHEMA)

    fixed = json.loads((out / "ds/a/one.vcon.json").read_bytes())
    assert fixed["attachments"][0]["mediatype"] == "application/json"
    assert (out / "ds/b/two.vcon.json").read_bytes() == raw_good
    assert (out / "ds/LICENSE").read_bytes() == b"MIT License\n"
    assert not (out / "ds/notes.json").exists()

    ds = report["datasets"]["ds"]
    assert ds["commit"] == head
    assert ds["containers"] == 2
    assert ds["changed_containers"] == 1
    assert ds["applied"] == {"attachment-mediatype": 1}
    assert ds["valid_before"] == 1 and ds["valid_after"] == 2
    assert ds["findings_after"] == {}


def test_build_refuses_a_checkout_off_its_pin(tmp_path):
    repo, head = upstream(tmp_path, {"LICENSE": b"x", "a.vcon.json": core04.dump(container(), core04.STYLES[0])})
    pin = core04.Pin("ds", str(repo), "b" * 40, "MIT")
    with pytest.raises(build.BuildError):
        build.build([pin], tmp_path / "cache", tmp_path / "out", SCHEMA)


def test_build_refuses_an_output_that_is_not_additive(tmp_path, monkeypatch):
    repo, head = upstream(tmp_path, {"LICENSE": b"x", "a.vcon.json": core04.dump(
        container(attachments=[attachment(encoding="json", body="{}")]), core04.STYLES[0])})

    def mangle(doc):
        doc["uuid"] = "changed"
        return core04.Correction([], [])
    monkeypatch.setattr(core04, "correct", mangle)
    with pytest.raises(core04.NotAdditive):
        build.build([core04.Pin("ds", str(repo), head, "MIT")], tmp_path / "cache", tmp_path / "out", SCHEMA)


# ---- verify: the committed corpus against its committed report ----

def built(tmp_path):
    repo, head = upstream(tmp_path, {
        "LICENSE": b"MIT License\n",
        "a.vcon.json": core04.dump(container(attachments=[attachment(encoding="json", body="{}")]),
                                   core04.STYLES[0]),
        "b.vcon.json": core04.dump(container(attachments=[attachment(body="plain")]), core04.STYLES[0]),
    })
    out = tmp_path / "out"
    report = build.build([core04.Pin("ds", str(repo), head, "MIT")], tmp_path / "cache", out, SCHEMA)
    return out, report


def test_verify_accepts_a_fresh_build(tmp_path):
    out, report = built(tmp_path)
    assert build.verify(out, report, SCHEMA) == []


def test_verify_names_a_dataset_whose_files_changed(tmp_path):
    out, report = built(tmp_path)
    (out / "ds/a.vcon.json").write_bytes(core04.dump(
        container(attachments=[attachment(encoding="json", body="{}")]), core04.STYLES[0]))
    problems = build.verify(out, report, SCHEMA)
    assert problems and all(p.startswith("ds:") for p in problems), problems


def test_verify_names_a_missing_dataset(tmp_path):
    out, report = built(tmp_path)
    report["datasets"]["other"] = dict(report["datasets"]["ds"])
    assert any(p.startswith("other:") for p in build.verify(out, report, SCHEMA))


def test_unresolved_is_counted(tmp_path):
    _, report = built(tmp_path)
    assert report["datasets"]["ds"]["unresolved"] == {"attachment-mediatype": 1}
    assert report["datasets"]["ds"]["valid_after"] == 1


def test_report_markdown_states_the_measured_numbers(tmp_path):
    _, report = built(tmp_path)
    text = build.render(report)
    assert "| ds | 2 | 1 | 0 | 1 |" in text
    assert "/attachments/* required: 'mediatype' is a required property" in text


def test_render_is_the_same_after_report_json_round_trip():
    # report.json is written with sorted keys; REPORT.md must not depend on order.
    d = {"url": "u", "commit": "c", "license": "MIT", "containers": 1, "changed_containers": 0,
         "applied": {}, "unresolved": {}, "valid_before": 1, "valid_after": 1,
         "findings_before": {}, "findings_after": {}, "index_errors": {}, "tree_sha256": "t",
         "valid_with_index_errors": 0, "unhashed_url_hosts": {}}
    report = {"schema_sha256": "s", "datasets": {"zeta": d, "alpha": d}}
    again = json.loads(json.dumps(report, sort_keys=True))
    assert build.render(report) == build.render(again)


# ---- what the open items are made of ----

def recording(url, **extra):
    d = {"type": "recording", "start": "2026-03-28T03:34:54+00:00", "parties": [0],
         "url": url, "mediatype": "video/mp4"}
    d.update(extra)
    return d


def test_unhashed_recording_hosts_counts_by_host():
    doc = container(dialog=[recording("https://www.youtube.com/watch?v=x"),
                            recording("https://www.youtube.com/watch?v=y"),
                            recording("https://www.ietf.org/a.mp3", content_hash="sha512-x")])
    assert core04.unhashed_url_hosts(doc) == {"www.youtube.com": 2}


def test_build_reports_hosts_and_valid_with_index_errors(tmp_path):
    no_dialog = container(dialog=[], attachments=[attachment(encoding="json", body="{}")])
    unhashed = container(dialog=[recording("https://youtu.be/x")])
    repo, head = upstream(tmp_path, {
        "LICENSE": b"x",
        "a.vcon.json": core04.dump(no_dialog, core04.STYLES[0]),
        "b.vcon.json": core04.dump(unhashed, core04.STYLES[0]),
    })
    report = build.build([core04.Pin("ds", str(repo), head, "MIT")], tmp_path / "cache",
                         tmp_path / "out", SCHEMA)
    ds = report["datasets"]["ds"]
    assert ds["unhashed_url_hosts"] == {"youtu.be": 1}
    assert ds["valid_with_index_errors"] == 1
    assert build.verify(tmp_path / "out", report, SCHEMA) == []
    text = build.render(report)
    assert "| Host | Dialogs |" in text and "| `youtu.be` | 1 |" in text
    assert "1 of the valid containers carry an index error" in text
