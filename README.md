# vcon-datasets-core04

A corrected copy of three public vCon datasets published by the
[vcon-dev](https://github.com/vcon-dev) community, changed only where
[draft-ietf-vcon-vcon-core-04](https://datatracker.ietf.org/doc/draft-ietf-vcon-vcon-core/04/)
(core-04) states a requirement and the data itself settles the missing value.
A vCon is a JSON container for one conversation: its parties, its recordings
or messages (dialogs), its attachments and its analysis.

On 2026-10-09 no container in these datasets passed the core-04 JSON schema.
The corrections add two fields: `mediatype` on inline attachments, and
`content_hash` on recordings whose bytes were fetched and hashed. Every
Supreme Court container passes after them.
The IETF and Newport datasets carry problems the data cannot settle; those
are listed in [CHANGES.md](CHANGES.md) and left as they are.

[REPORT.md](REPORT.md) holds every count: containers per dataset, how many
were corrected, how many pass the schema before and after, and what remains.
`tools/build.py` writes it; nothing in it is typed by hand.

## Contents

| Path | What it is |
|---|---|
| `datasets/<name>/` | The corrected containers, at the same relative paths as upstream, and the dataset's `LICENSE` |
| `PINS.tsv` | The upstream repository and commit each dataset is built from |
| `hashes/*.tsv` | Content hashes of fetched recordings, one row per URL, applied by the `dialog-content-hash` correction |
| `CHANGES.md` | The change list: each correction with the core-04 section behind it, and each open item |
| `REPORT.md`, `report.json` | The measured counts, and the tree digest each dataset is checked against |
| `tools/core04.py` | The correction rule, the validator and the index checks |
| `tools/build.py` | Regenerates `datasets/` from the pinned upstreams, or checks it offline |
| `schema/vcon.schema.json` | The core-04 JSON schema the corpus is judged against |
| `tests/` | Tests for every rule above |

Only the `*.vcon.json` containers and each `LICENSE` are copied. Upstream
generator scripts, READMEs and manifests stay in the upstream repositories.

## Datasets

| Dataset | Upstream | Pinned commit | License | Copyright |
|---|---|---|---|---|
| vcon-supreme-court-arguments | [vcon-dev/vcon-supreme-court-arguments](https://github.com/vcon-dev/vcon-supreme-court-arguments) | `061d5a87976fc4246d360e27f67326995d5f0128` | MIT | Copyright (c) 2026 vcon-dev contributors |
| ietf-meeting-vcons | [vcon-dev/ietf-meeting-vcons](https://github.com/vcon-dev/ietf-meeting-vcons) | `b919f24dd29c0419f356c4b1133220c18de3a9ef` | BSD-3-Clause, with a note on the IETF Trust Legal Provisions | Copyright (c) 2025, vCon Development Community |
| vcon-dataset-city-of-newport-ri | [vcon-dev/vcon-dataset-city-of-newport-ri](https://github.com/vcon-dev/vcon-dataset-city-of-newport-ri) | `1a999e1de306f9b565e4832a5de356395beb8aed` | BSD-3-Clause, with the same note | Copyright (c) 2025, vCon Development Community |

Two other vcon-dev datasets, `fake-vcons` and `tadhack-2025`, are not
included. Every container in both names its parties with gmail.com addresses
and +1 phone numbers, and the TADHack README states that they "were not
checked against real subscribers". Republishing them could reach real people.
Including them with reserved values (`example.invalid` addresses, 555-01xx
numbers) in their place would be a separate decision.

fake-vcons is corrected upstream instead. `tools/fake_vcons.py` applies the
core-04 corrections to a fake-vcons checkout in place, adding keys only:
`start` on each attachment (from the container's `created_at`), `mediatype:
application/json` on each JSON attachment body, and `encoding: none` on each
text dialog. It reports, and does not change, attachments whose object body
is declared `encoding: none`. Run it as `python tools/fake_vcons.py <checkout>`.

## What a correction may do

A correction adds a key to an object. It never changes or removes a value,
never adds or removes an array element, and never reorders anything.
`tools/build.py` checks every container against that rule
(`core04.assert_additive`) and stops if one breaks it. Each corrected file is
written in the same JSON layout as its upstream file, so its diff shows only
the added lines and the comma JSON requires before them.

## Licenses and the IETF Trust Legal Provisions

Each dataset directory keeps its upstream `LICENSE` file unchanged, and the
table above repeats its copyright line. The Supreme Court dataset is MIT
licensed. The IETF and Newport datasets are BSD-3-Clause licensed, and both
LICENSE files add a note that the underlying IETF meeting content is subject
to the [IETF Trust Legal Provisions](https://trustee.ietf.org/documents/trust-legal-provisions/)
(TLP) and the [IETF Note Well](https://www.ietf.org/about/note-well/).

The current TLP is version 5.0, effective 25 March 2015. Read on 2026-10-09,
it says:

* Section 3.c grants anyone the right "to copy, publish, display and
  distribute IETF Contributions and IETF Documents in full and without
  modification", and to distribute unmodified portions, provided each portion
  is attributed to the IETF and identifies the document it comes from.
* Section 3.d.i grants no license to modify IETF Contributions or IETF
  Documents outside the IETF Standards Process.
* Section 2.c places content contributed before the effective date under the
  provisions in force when it was contributed. This repository did not review
  those earlier versions.

The IETF content in these containers is the meeting agendas, minutes, slides
and documents carried in attachment `body` strings, and the transcripts
carried in or referenced from `analysis` objects. Each container also keeps
its `meeting_metadata` attachment, which names the meeting and working group
the content comes from.

Conclusion: redistributing the IETF dataset under these terms is allowed
because the corrections never modify IETF content. Every `body`, transcript
and URL is carried byte for byte; the only changes are keys added beside the
content (`mediatype` on an attachment, `content_hash` on a recording), and the
build fails if any original value changes. The attribution each container already carries is kept. The Newport
dataset carries the same note in its LICENSE, although its README describes
the recordings as public records of the City of Newport, RI; the same
additive rule meets the note either way. This is the maintainer's reading of
the published terms, not legal advice.

Personal data in the IETF set: 6,169 of the 8,181 IETF containers (counted
2026-10-10 at the pinned commit) name parties by email address, the working
group chairs and session participants as the IETF publishes them. They are
carried as upstream publishes them. Removing or replacing them would modify
IETF content, which the provisions above do not allow outside the IETF
Standards Process, and the repository's rule allows only added keys.

The vendored schema, `schema/vcon.schema.json`, is `vcon_json_schema.json`
from the IETF vCon working group's
[draft-ietf-vcon-vcon-core](https://github.com/ietf-wg-vcon/draft-ietf-vcon-vcon-core)
repository, commit `99589dd0b474d95c2feed52165fc2c95b1191d3d` (tag
draft-ietf-vcon-vcon-core-04, 2026-09-07), unmodified, SHA-256
`b3c1ae28041dea304c978a0e9e04da18253fa58517ad3472a6adf1167c01a8d9`. That
repository's CONTRIBUTING.md places contributions under BCP 78 and 79, the
TLP, and the TLP rules for code components, which make a code component
available under the Revised BSD License (TLP section 4.c).

## Checking the corpus

The check needs no network and no upstream checkout. It runs the unit tests,
then judges every committed container again and compares the result, and a
digest of every file, with `report.json`:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python tools/build.py check
```

CI runs the same two commands, and so does `.githooks/pre-commit` once
`git config core.hooksPath .githooks` is set.

## Regenerating it

```sh
.venv/bin/python tools/build.py build --cache ~/vcon-datasets
```

`build` clones each upstream into the cache directory (or reuses a clean
checkout already there), checks out the pinned commit, refuses a checkout
that is not at its pin or has local changes, and rewrites `datasets/`,
`report.json` and `REPORT.md`. Only git touches an upstream repository, with
hooks, symbolic links, submodules and LFS turned off. Nothing in a dataset is
executed. The fetched datasets take about 2.3 GB.

Two builds from the same pins produce the same `report.json`, byte for byte.

## Hashing the login-gated IETF audio

The IETF 86 and 90-94 audio recordings redirect to the IETF login, so their
`content_hash` cannot be computed anonymously. `tools/fetch_ietf_audio.py`
downloads them with your own signed-in session and records each file's
core-04 `content_hash` in a `manifest.tsv`:

```sh
.venv/bin/python tools/fetch_ietf_audio.py download \
    --urls ietf-audio-urls.txt --cookies cookies.txt --out ~/ietf-audio
```

`--urls` is a file with one URL per line. `--cookies` is a Netscape-format
`cookies.txt` holding the `sessionid` cookie of `auth.ietf.org`, from a
browser signed in to the IETF Datatracker. With it, each request follows the
single sign-on redirects (`get.ietf.org/oidc`, the `auth.ietf.org` authorize
endpoint, the callback) to the file; the script stops before it would load
the sign-in page. The file holds a live login, so keep it private and delete
it after the run. The
script sends only those cookies, one download at a time, two seconds apart.
It stops, with a message saying why, on a login redirect, a web page in place
of audio, a Cloudflare challenge, a short download, or less than 2 GiB of free
disk; a second run verifies what is already saved and continues. For files
downloaded in a browser instead, `hash-local --urls FILE --dir DIR` hashes
them, matched to URLs by file name.

The manifest of the 2026-10-11 run is committed as `hashes/ietf-audio.tsv`
and applied by the `dialog-content-hash` correction (CHANGES.md). Anyone
checking these hashes needs an IETF login too, which is why the upstream
dataset does not carry them.

## Validation

Containers are judged with the Python `jsonschema` package as a draft-07
validator, with every `format` the schema uses asserted: `date-time`, `uri`
and `uuid`. `jsonschema` skips a format check whose helper package is not
installed and does not say so. `tools/core04.py` refuses to run in that case,
and a test checks it.

The schema cannot see a reference to a dialog or party that does not exist,
so the build also checks every index a container uses and reports the broken
ones separately.

## Upstream

The corrections are offered back to each upstream repository as a pull
request with the output of `tools/build.py`. This repository stays the pinned
copy that [sipnab](https://github.com/NormB/sipnab)'s vCon corpus test reads.
