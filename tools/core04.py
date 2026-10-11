"""The corrections, and the checks that judge them.

One rule in one place: build.py applies these, the tests drive them, and
report.py judges the committed corpus with the same validator.

What is corrected (draft-ietf-vcon-vcon-core-04):

* ``attachment-mediatype`` -- an inline Attachment Object (one with a
  ``body``) must carry ``mediatype`` (section 4.4.5). It is added only when the
  data settles the value: ``encoding`` is ``json`` and the body parses as
  JSON, so the media type is ``application/json``. Any other inline
  attachment without ``mediatype`` is reported as unresolved and left as it
  is.
* ``dialog-content-hash`` -- a Dialog Object with ``url`` must carry
  ``content_hash`` (section 2.4). It is added only from a table of hashes
  computed from the bytes the URL served (``read_hashes``); a dialog whose URL
  is not in a table is reported as unresolved.

Every correction adds a key. None changes or removes a value: the IETF Trust
Legal Provisions allow IETF content to be redistributed in full and without
modification, and a correction that only adds keys beside the content keeps
every original value byte for byte. ``assert_additive`` holds the build to
that.
"""

import json
import pathlib
import re
import urllib.parse
from typing import NamedTuple

import jsonschema


class Change(NamedTuple):
    """One rule at one place in a container (a JSON Pointer)."""

    rule: str
    pointer: str


class Correction(NamedTuple):
    """What ``correct`` did, and what it found and could not settle."""

    applied: list
    unresolved: list


class Pin(NamedTuple):
    """One upstream dataset at one commit."""

    name: str
    url: str
    commit: str
    license: str


class NotAdditive(Exception):
    """A corrected container changed or removed an original value."""


class UnknownStyle(Exception):
    """No known serialization reproduces a file's bytes."""


# ---- corrections ----

def _parses_as_json(text):
    try:
        json.loads(text)
    except (TypeError, ValueError):
        return False
    return True


def correct(doc, hashes=None):
    """Apply every correction to ``doc`` in place.

    ``hashes`` maps a URL to the content_hash of the bytes it served.
    """
    applied, unresolved = [], []
    hashes = hashes or {}
    for i, d in enumerate(doc.get("dialog") or []):
        if not isinstance(d, dict) or not isinstance(d.get("url"), str) or "content_hash" in d:
            continue
        where = Change("dialog-content-hash", f"/dialog/{i}")
        if d["url"] in hashes:
            d["content_hash"] = hashes[d["url"]]
            applied.append(where)
        else:
            unresolved.append(where)
    for i, a in enumerate(doc.get("attachments") or []):
        if not isinstance(a, dict) or "body" not in a or "mediatype" in a:
            continue
        where = Change("attachment-mediatype", f"/attachments/{i}")
        if a.get("encoding") == "json" and isinstance(a["body"], str) and _parses_as_json(a["body"]):
            a["mediatype"] = "application/json"
            applied.append(where)
        else:
            unresolved.append(where)
    return Correction(applied, unresolved)


def assert_additive(before, after, path=""):
    """Raise unless ``after`` is ``before`` with object keys added and nothing else."""
    if isinstance(before, dict):
        if not isinstance(after, dict):
            raise NotAdditive(f"{path or '/'}: object became {type(after).__name__}")
        for key, value in before.items():
            if key not in after:
                raise NotAdditive(f"{path}/{key}: removed")
            assert_additive(value, after[key], f"{path}/{key}")
    elif isinstance(before, list):
        if not isinstance(after, list) or len(after) != len(before):
            raise NotAdditive(f"{path or '/'}: array changed length or type")
        for i, (b, a) in enumerate(zip(before, after)):
            assert_additive(b, a, f"{path}/{i}")
    elif type(before) is not type(after) or before != after:
        raise NotAdditive(f"{path or '/'}: value changed")


# ---- serialization ----

# Each upstream file was written by one of these; reusing the file's own
# style keeps a corrected file's diff to the lines that were added.
_STYLE_ARGS = {
    "i2": ({"indent": 2}, ""),
    "i2a": ({"indent": 2, "ensure_ascii": False}, ""),
    "i2nl": ({"indent": 2}, "\n"),
    "i2anl": ({"indent": 2, "ensure_ascii": False}, "\n"),
    "c": ({}, ""),
    "ca": ({"ensure_ascii": False}, ""),
}
STYLES = list(_STYLE_ARGS)


def dump(doc, style):
    kwargs, tail = _STYLE_ARGS[style]
    return (json.dumps(doc, **kwargs) + tail).encode("utf-8")


def detect_style(raw, doc):
    """The style that reproduces ``raw`` from ``doc`` exactly."""
    for style in STYLES:
        if dump(doc, style) == raw:
            return style
    raise UnknownStyle("no known serialization reproduces these bytes")


# ---- validation ----

def schema_formats(schema):
    """Every ``format`` value the schema uses."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("format"), str):
                found.add(node["format"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schema)
    return found


def validator(schema_path):
    """A draft-07 validator over the vendored schema, with formats asserted.

    jsonschema skips a format whose checker package is not installed, without
    saying so. Refuse to build a validator that would skip one.
    """
    schema = json.loads(pathlib.Path(schema_path).read_text())
    # Every format jsonschema knows, not only draft-07's list: core-04 marks
    # identifiers `format: uuid`, a format draft-07 does not define.
    checker = jsonschema.FormatChecker()
    missing = schema_formats(schema) - set(checker.checkers)
    if missing:
        raise RuntimeError(f"format checks not installed: {sorted(missing)}; "
                           "install requirements.txt")
    return jsonschema.Draft7Validator(schema, format_checker=checker)


def _finding_key(error):
    path = "".join("/*" if isinstance(p, int) else f"/{p}" for p in error.absolute_path)
    if error.validator == "required":
        detail = error.message
    elif error.validator == "format":
        detail = f"not a {error.validator_value}"
    else:
        detail = f"{error.validator} {json.dumps(error.validator_value)}"[:200]
    return f"{path or '/'} {error.validator}: {detail}"


def findings(doc, v):
    """The schema findings for ``doc``, one key per kind and place, sorted."""
    return sorted({_finding_key(e) for e in v.iter_errors(doc)})


def _indexes(value):
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _indexes(v)


def index_errors(doc):
    """References to dialogs or parties that do not exist. The schema cannot see these."""
    dialogs = len(doc.get("dialog") or [])
    parties = len(doc.get("parties") or [])
    errors = set()
    for d in doc.get("dialog") or []:
        if isinstance(d, dict) and any(i >= parties for i in _indexes(d.get("parties"))):
            errors.add("dialog-party-index")
    for a in doc.get("attachments") or []:
        if isinstance(a, dict) and any(i >= dialogs for i in _indexes(a.get("dialog"))):
            errors.add("attachment-dialog-index")
    for a in doc.get("analysis") or []:
        if isinstance(a, dict) and any(i >= dialogs for i in _indexes(a.get("dialog"))):
            errors.add("analysis-dialog-index")
    return errors


def unhashed_url_hosts(doc):
    """Dialogs with a ``url`` and no ``content_hash`` (section 2.4), counted by host."""
    hosts = {}
    for d in doc.get("dialog") or []:
        if isinstance(d, dict) and isinstance(d.get("url"), str) and "content_hash" not in d:
            host = urllib.parse.urlsplit(d["url"]).netloc
            hosts[host] = hosts.get(host, 0) + 1
    return hosts


# ---- hash tables ----

# Section 2.2: "sha512", a hyphen, and the base64url SHA-512 digest. 64 bytes
# encode to 86 characters without padding.
_SHA512_TOKEN = re.compile(r"^sha512-[A-Za-z0-9_-]{86}$")


def read_hashes(path):
    """URL -> content_hash, from a fetch manifest (url, filename, size, content_hash)."""
    lines = pathlib.Path(path).read_text().splitlines()
    if not lines or lines[0].split("\t") != ["url", "filename", "size", "content_hash"]:
        raise ValueError(f"{path}: not a fetch manifest")
    table = {}
    for n, line in enumerate(lines[1:], 2):
        url, _name, _size, token = line.split("\t")
        if not _SHA512_TOKEN.match(token):
            raise ValueError(f"{path}:{n}: {token!r} is not a sha512 content_hash")
        if url in table:
            raise ValueError(f"{path}:{n}: {url} is listed twice")
        table[url] = token
    return table


# ---- pins ----

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def parse_pins(text):
    pins = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) != 4:
            raise ValueError(f"pins line {n}: expected 4 tab-separated columns")
        pin = Pin(*cols)
        if not _NAME.match(pin.name) or ".." in pin.name:
            raise ValueError(f"pins line {n}: bad name {pin.name!r}")
        if not _COMMIT.match(pin.commit):
            raise ValueError(f"pins line {n}: commit must be 40 hex digits")
        pins.append(pin)
    return pins
