"""The core-04 corrections proposed upstream to vcon-dev/fake-vcons.

fake-vcons is not part of this corpus (see README). These rules produce the
change offered to its maintainers as a pull request, from the commit named on
the command line, so the change can be regenerated and reviewed.

What is corrected (draft-ietf-vcon-vcon-core-04 and its JSON schema):

* ``attachment-start`` -- the schema requires ``start`` on every Attachment
  Object. No attachment in fake-vcons has one, and nothing in their bodies
  states when they were exchanged in a stated timezone, so ``start`` is set
  to the container's ``created_at``.
* ``attachment-mediatype`` -- an inline attachment must carry ``mediatype``
  (section 4.4.5). It is ``application/json`` when the body is a JSON object
  or array, or a string that parses as JSON under ``encoding: json``.
  Any other body is reported as unresolved.
* ``dialog-encoding`` -- a Dialog Object with a body must carry ``encoding``.
  A string body takes ``none``, which section 2.3 defines as a JSON string
  carried without modification. Any other body is reported as unresolved.

Reported, not changed:

* ``attachment-encoding-mismatch`` -- an attachment whose body is not a
  string under ``encoding: none``. Section 2.3 calls for ``json`` there;
  correcting it would change an existing value.

Every correction adds a key; ``core04.assert_additive`` holds the run to it.
"""

import argparse
import json
import pathlib
import sys

import core04


def _json_mediatype_settled(attachment):
    body = attachment["body"]
    if isinstance(body, (dict, list)):
        return True
    return (
        attachment.get("encoding") == "json"
        and isinstance(body, str)
        and core04._parses_as_json(body)
    )


def correct(doc):
    """Apply every correction to ``doc`` in place."""
    applied, unresolved = [], []
    for i, d in enumerate(doc.get("dialog") or []):
        if not isinstance(d, dict) or "body" not in d or "encoding" in d:
            continue
        where = core04.Change("dialog-encoding", f"/dialog/{i}")
        if isinstance(d["body"], str):
            d["encoding"] = "none"
            applied.append(where)
        else:
            unresolved.append(where)
    for i, a in enumerate(doc.get("attachments") or []):
        if not isinstance(a, dict):
            continue
        pointer = f"/attachments/{i}"
        if "start" not in a and isinstance(doc.get("created_at"), str):
            a["start"] = doc["created_at"]
            applied.append(core04.Change("attachment-start", pointer))
        if "body" in a and "mediatype" not in a:
            where = core04.Change("attachment-mediatype", pointer)
            if _json_mediatype_settled(a):
                a["mediatype"] = "application/json"
                applied.append(where)
            else:
                unresolved.append(where)
        if "body" in a and a.get("encoding") == "none" and not isinstance(a["body"], str):
            unresolved.append(core04.Change("attachment-encoding-mismatch", pointer))
    return core04.Correction(applied, unresolved)


def apply_tree(tree):
    """Correct every container under ``tree`` in place, keeping each file's
    own JSON layout. Returns per-rule counts of applied and unresolved."""
    counts = {"applied": {}, "unresolved": {}, "files": 0}
    for path in sorted(pathlib.Path(tree).rglob("*.vcon.json")):
        raw = path.read_bytes()
        before = json.loads(raw)
        style = core04.detect_style(raw, before)
        after = json.loads(raw)
        result = correct(after)
        core04.assert_additive(before, after)
        for kind, changes in (("applied", result.applied), ("unresolved", result.unresolved)):
            for c in changes:
                counts[kind][c.rule] = counts[kind].get(c.rule, 0) + 1
        if result.applied:
            path.write_bytes(core04.dump(after, style))
        counts["files"] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tree", help="a fake-vcons checkout to correct in place")
    args = parser.parse_args(argv)
    json.dump(apply_tree(args.tree), sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
