# Changes

Every change this repository makes to the upstream containers, the core-04
requirement behind it, and every problem it found and did not change.
Counts are in [REPORT.md](REPORT.md), which `tools/build.py` measures on each
build; this file states rules and reasons, not numbers that could go stale.

Section references are to
[draft-ietf-vcon-vcon-core-04](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04)
(core-04).

## Applied

### `attachment-mediatype`: `mediatype` on inline attachments

[Core-04 section 4.4.5](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04#section-4.4.5)
requires `mediatype` on an inline Attachment Object, one that carries its
content in `body`, and the schema lists it as required. Every inline
attachment in the three datasets has `"encoding": "json"` and a `body` that
parses as JSON, and none has `mediatype`.

The rule: when an inline attachment has no `mediatype`, its `encoding` is
`json` and its `body` parses as JSON, add `"mediatype": "application/json"`.
An inline attachment without `mediatype` that does not meet both conditions
is counted as unresolved in REPORT.md and left unchanged. None of the three
datasets has one.

Applies to all three datasets. It is the only finding in the Supreme Court
dataset, so every container there passes the schema after it.

### `dialog-content-hash`: `content_hash` on recordings, from the fetched bytes

[Core-04 section 2.4](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04#section-2.4)
requires `content_hash` beside `url`. A hash can only come from the bytes the
URL serves, so this correction reads it from a table:
[`hashes/ietf-audio.tsv`](hashes/ietf-audio.tsv), one row per URL with the
file's size and its `content_hash` (section 2.2: `sha512-` and the base64url
digest). The table was made on 2026-10-11 by `tools/fetch_ietf_audio.py`,
which downloaded every IETF 86 and 90-94 audio recording with a signed-in
IETF Datatracker session; see README.md.

The rule: when a dialog has a `url`, no `content_hash`, and its URL is in a
hash table, add that table's `content_hash`. A dialog with a `url` that is in
no table is counted as unresolved in REPORT.md and left unchanged.

Applies to the IETF dataset's audio recordings. Checking these hashes needs
an IETF login, since the URLs redirect to it; the upstream README leaves them
unhashed for that reason.

## Open

These are recorded and not changed. Each would need a value the data does
not contain.

### Recordings with `url` and no `content_hash`

[Core-04 section 2.4](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04#section-2.4)
requires `content_hash` beside `url` on externally referenced content. A
hash describes the bytes the URL serves, so it can only come from fetching
them. REPORT.md counts these dialogs by host.

* **IETF, YouTube recordings.** A YouTube watch URL serves an HTML page, not
  the media, so no hash of it can describe the recording. The upstream README
  ("Media references") states this and writes no hash for these by design.
* **Newport, Granicus recordings.** Each `cityofnewport.granicus.com/
  DownloadFile.php` URL redirects to `archive-video.granicus.com`, which
  answered HTTP 403 "Request blocked" from CloudFront on 2026-10-09, with and
  without the player page as referrer.

No access control was worked around. If the recordings become publicly
retrievable, a hash table built from them could be added as a correction
input; until then the containers stay as published.

### IETF: attachments that reference a dialog in a container with no dialog

These containers have no `dialog` and no `analysis`, and every attachment
says `"dialog": 0`. They pass the schema, since the schema cannot check that
an index points at something. Core-04's schema requires `dialog` on every
attachment, so removing the reference would make them fail it, and a dialog
cannot be made up. Upstream would need either to add the session's dialog or
to say how core-04 expects an attachment of a session without a recording to
be referenced.

### IETF: one recording labeled `audio/mpeg` that is Ogg Vorbis

`https://www.ietf.org/audio/ietf93/ietf93-congresshalli-20150720-0900.mp3`,
referenced by `ietf93/ietf93_icnrg_23899.vcon.json` with
`"mediatype": "audio/mpeg"`, serves Ogg Vorbis audio (mono, 16 kHz) under an
`.mp3` name. Correcting the value would change an original value, which this
repository does not do; its `content_hash` is applied, since it describes the
bytes served.

### IETF: dialogs that name parties that do not exist

These dialogs list party indexes past the end of the container's `parties`
array, by one to five. Dropping the extra indexes, or adding parties rebuilt
from the transcript's speakers, are both judgment calls about the meeting.
Neither is applied.

## Not in this repository

Two findings appear only in `fake-vcons` and `tadhack-2025`, which are not
included (see README.md):

* attachments without `start`
  ([core-04 section 4.4.2](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04#section-4.4.2));
  the data does not say when each attachment was made;
* text dialogs with a `body` and no `encoding`
  ([core-04 section 2.3.2](https://datatracker.ietf.org/doc/html/draft-ietf-vcon-vcon-core-04#section-2.3.2)).
