#!/usr/bin/env python3
"""Download the login-gated IETF audio with your own session, and hash it.

The IETF 86 and 90-94 audio recordings that ietf-meeting-vcons references
redirect to the IETF login. This script fetches them with the session
cookies of a browser you are signed in with, and records each file's
core-04 content_hash (section 2.2: "sha512-" and the base64url SHA-512
digest of the body served at the URL, no padding).

It sends only your cookies. It does not imitate a browser and does not work
around bot protection: a login redirect, an HTML page in place of audio, or
a Cloudflare challenge stops the run with a message saying which.

    fetch_ietf_audio.py download --urls URLS --cookies cookies.txt --out DIR
        Download every URL in URLS (one per line) into DIR, one at a time,
        and append a row to DIR/manifest.tsv after each file. A second run
        verifies the files already in the manifest and continues.

    fetch_ietf_audio.py hash-local --urls URLS --dir DIR
        Hash files already downloaded by hand into DIR, matched to URLS by
        file name, and write DIR/manifest.tsv.

The cookies file is the Netscape cookies.txt format that browser cookie
export extensions write; it needs the sessionid cookie of auth.ietf.org,
which lets the single sign-on redirects complete. It holds a live login:
keep it private and delete it when the run is done.

Exit codes: 0 done, 1 stopped (login, challenge, mismatch, disk, HTTP error),
2 bad arguments.
"""

import argparse
import base64
import hashlib
import http.cookiejar
import pathlib
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

USER_AGENT = "vcon-datasets-core04-fetch/1 (+https://github.com/NormB/vcon-datasets-core04)"
# Space left free on the output disk after a download.
MIN_FREE = 2 * 1024**3
CHUNK = 1 << 20
MANIFEST = "manifest.tsv"
HEADER = "url\tfilename\tsize\tcontent_hash"


class Row(NamedTuple):
    url: str
    filename: str
    size: int
    content_hash: str


class FetchStopped(Exception):
    """The run stopped; the message says why and what to do."""


class NeedsLogin(FetchStopped):
    pass


class Challenged(FetchStopped):
    pass


class Mismatch(FetchStopped):
    pass


class NoSpace(FetchStopped):
    pass


class HttpFailed(FetchStopped):
    pass


def content_hash(digest):
    """The core-04 ContentHash token for a finished hashlib.sha512 object."""
    return "sha512-" + base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")


def filename(url):
    return pathlib.PurePosixPath(urllib.parse.urlsplit(url).path).name


def read_urls(path):
    urls, names = [], {}
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = filename(line)
        if not name or name in names:
            raise ValueError(f"{line}: file name {name!r} is empty or also used by {names.get(name)}")
        names[name] = line
        urls.append(line)
    return urls


# ---- the manifest ----

def read_manifest(out):
    path = pathlib.Path(out) / MANIFEST
    rows = {}
    if path.exists():
        for line in path.read_text().splitlines()[1:]:
            url, name, size, h = line.split("\t")
            rows[url] = Row(url, name, int(size), h)
    return rows


def _append(out, row):
    path = pathlib.Path(out) / MANIFEST
    new = not path.exists()
    with open(path, "a") as f:
        if new:
            f.write(HEADER + "\n")
        f.write("\t".join(map(str, row)) + "\n")


def write_manifest(out, rows):
    path = pathlib.Path(out) / MANIFEST
    path.write_text(HEADER + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows))


# ---- hashing ----

def _looks_like_html(head):
    return head.lstrip()[:1] == b"<"


def hash_file(path):
    """(size, content_hash, first bytes) of a file."""
    h = hashlib.sha512()
    size = 0
    head = b""
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            if not head:
                head = chunk[:64]
            h.update(chunk)
            size += len(chunk)
    return size, content_hash(h), head


def hash_local(urls, src):
    """Rows for files in ``src`` named like a URL; also URLs with no usable file, and stray files."""
    by_name = {filename(u): u for u in urls}
    rows, missing = [], []
    present = {p.name for p in pathlib.Path(src).iterdir() if p.is_file()}
    for url in urls:
        name = filename(url)
        if name not in present:
            missing.append(url)
            continue
        size, h, head = hash_file(pathlib.Path(src) / name)
        if _looks_like_html(head):
            missing.append(url)
            continue
        rows.append(Row(url, name, size, h))
    unknown = sorted(n for n in present if n not in by_name and n != MANIFEST)
    return rows, missing, unknown


# ---- downloading ----

class _StopAtLogin(urllib.request.HTTPRedirectHandler):
    """Follow the single sign-on redirects; stop before the sign-in page.

    get.ietf.org sends an unsigned request through /oidc to the auth.ietf.org
    authorize endpoint. With a signed-in session there, that answers with a
    code, get.ietf.org sets its own session and redirects to the file. Without
    one it redirects to the sign-in page, which this script never requests.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if "/accounts/login" in target.path:
            raise NeedsLogin(f"{req.full_url} redirected to the sign-in page; the sessionid "
                             "cookie for auth.ietf.org is missing or expired. Export fresh "
                             "cookies from a signed-in browser and run again")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(cookie_file):
    jar = http.cookiejar.MozillaCookieJar()
    jar.load(str(cookie_file), ignore_discard=True, ignore_expires=True)
    # Exports write 0 as the expiry of a session cookie. The loader keeps it as
    # a 1970 timestamp, and the jar would then never send the cookie.
    for cookie in jar:
        if cookie.expires == 0:
            cookie.expires = None
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _StopAtLogin())


def _download(opener, url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = opener.open(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.headers.get("cf-mitigated"):
            raise Challenged(f"{url}: Cloudflare answered with a challenge; this script does "
                             "not get past it. Download the remaining files in the browser "
                             "and use hash-local") from None
        raise HttpFailed(f"{url}: HTTP {e.code}") from None
    with resp:
        ctype = resp.headers.get("Content-Type", "")
        if ctype.startswith("text/html"):
            raise NeedsLogin(f"{url}: the server sent a web page, not audio; the session "
                             "is not signed in")
        length = int(resp.headers.get("Content-Length") or 0)
        if shutil.disk_usage(dest.parent).free - length < MIN_FREE:
            raise NoSpace(f"{url}: {length} bytes would leave less than "
                          f"{MIN_FREE // 1024**3} GiB free in {dest.parent}")
        h = hashlib.sha512()
        size = 0
        part = dest.with_name(dest.name + ".part")
        try:
            with open(part, "wb") as f:
                while chunk := resp.read(CHUNK):
                    if size == 0 and _looks_like_html(chunk[:64]):
                        raise NeedsLogin(f"{url}: the body is a web page, not audio")
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
            if length and size != length:
                raise HttpFailed(f"{url}: got {size} of {length} bytes")
            part.rename(dest)
        finally:
            part.unlink(missing_ok=True)
    return Row(url, dest.name, size, content_hash(h))


def fetch_all(urls, out, cookie_file, delay=0.0, log=lambda s: None):
    """Download each URL not already in the manifest; return the rows, in URL order."""
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    done = read_manifest(out)
    opener = _opener(cookie_file)
    rows = []
    for n, url in enumerate(urls, 1):
        dest = out / filename(url)
        if url in done and dest.exists():
            size, h, _ = hash_file(dest)
            if (size, h) != (done[url].size, done[url].content_hash):
                raise Mismatch(f"{dest}: no longer matches its manifest row; delete both and run again")
            rows.append(done[url])
            continue
        row = _download(opener, url, dest)
        _append(out, row)
        rows.append(row)
        log(f"[{n}/{len(urls)}] {row.filename} {row.size} bytes")
        if delay:
            time.sleep(delay)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--urls", required=True)
    d.add_argument("--cookies", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--delay", type=float, default=2.0, help="seconds between downloads (default 2)")
    h = sub.add_parser("hash-local")
    h.add_argument("--urls", required=True)
    h.add_argument("--dir", required=True)
    args = parser.parse_args(argv)
    try:
        urls = read_urls(args.urls)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.cmd == "hash-local":
        rows, missing, unknown = hash_local(urls, args.dir)
        write_manifest(args.dir, rows)
        print(f"{len(rows)} hashed, {len(missing)} of {len(urls)} URLs have no usable file, "
              f"{len(unknown)} files match no URL; wrote {pathlib.Path(args.dir) / MANIFEST}")
        return 0
    try:
        rows = fetch_all(urls, args.out, args.cookies, args.delay, log=print)
    except FetchStopped as e:
        print(f"stopped: {e}", file=sys.stderr)
        saved = read_manifest(args.out)
        print(f"{sum(u in saved for u in urls)} of {len(urls)} files are in "
              f"{pathlib.Path(args.out) / MANIFEST}; run again to continue", file=sys.stderr)
        return 1
    print(f"done: {len(rows)} of {len(urls)} files, manifest {pathlib.Path(args.out) / MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
