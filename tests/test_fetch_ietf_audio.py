"""Tests for tools/fetch_ietf_audio.py, against a server on 127.0.0.1.

The real host (get.ietf.org) needs a logged-in IETF session and cannot be
reached from a test. What can be driven here is everything the script does
with an answer: save and hash a file, stop on a login redirect or a
Cloudflare challenge, refuse an HTML page served as a file, resume, and
hash files that were downloaded by hand.
"""

import base64
import hashlib
import http.server
import pathlib
import sys
import threading
from typing import NamedTuple

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import fetch_ietf_audio as fia  # noqa: E402

AUDIO = b"ID3" + bytes(range(256)) * 300


class Handler(http.server.BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        Handler.hits.append((self.path, self.headers.get("Cookie")))
        if self.path.startswith("/audio/ok/"):
            if self.headers.get("Cookie") != "sessionid=good":
                self.send_response(302)
                self.send_header("Location", "/oidc?p=" + self.path)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(AUDIO)))
            self.end_headers()
            self.wfile.write(AUDIO)
        elif self.path.startswith("/audio/moved/"):
            self.send_response(301)
            self.send_header("Location", self.path.replace("/audio/moved/", "/audio/ok/"))
            self.end_headers()
        elif self.path.startswith("/audio/challenge/"):
            self.send_response(403)
            self.send_header("cf-mitigated", "challenge")
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>Just a moment...</html>")
        elif self.path.startswith("/audio/html/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html>login</html>")
        elif self.path.startswith("/audio/htmlbody/"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.end_headers()
            self.wfile.write(b"  <!DOCTYPE html><html>sign in</html>")
        elif self.path.startswith("/audio/htmltype/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(AUDIO)
        elif self.path.startswith("/audio/short/"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(AUDIO) + 10))
            self.end_headers()
            self.wfile.write(AUDIO)
        elif self.path.startswith("/oidc"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>sign in</html>")
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def server():
    Handler.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def cookies(tmp_path, value="good"):
    p = tmp_path / "cookies.txt"
    p.write_text("# Netscape HTTP Cookie File\n"
                 f"127.0.0.1\tFALSE\t/\tFALSE\t0\tsessionid\t{value}\n")
    return p


def expected_hash(data):
    return "sha512-" + base64.urlsafe_b64encode(hashlib.sha512(data).digest()).decode().rstrip("=")


# ---- the hash format ----

def test_content_hash_is_sha512_base64url_without_padding():
    h = fia.content_hash(hashlib.sha512(b"abc"))
    assert h == expected_hash(b"abc")
    assert h.startswith("sha512-") and "=" not in h and "+" not in h and "/" not in h


# ---- reading the URL list ----

def test_read_urls_skips_blanks_and_comments_and_keeps_order(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("# c\nhttps://a.example/x/one.mp3\n\nhttps://a.example/y/two.mp3\n")
    assert fia.read_urls(p) == ["https://a.example/x/one.mp3", "https://a.example/y/two.mp3"]


def test_read_urls_refuses_two_urls_with_one_filename(tmp_path):
    p = tmp_path / "u.txt"
    p.write_text("https://a.example/x/one.mp3\nhttps://a.example/y/one.mp3\n")
    with pytest.raises(ValueError):
        fia.read_urls(p)


# ---- downloading ----

def test_downloads_saves_and_hashes(server, tmp_path):
    url = server + "/audio/ok/a.mp3"
    out = tmp_path / "out"
    rows = fia.fetch_all([url], out, cookies(tmp_path))
    assert (out / "a.mp3").read_bytes() == AUDIO
    assert rows == [fia.Row(url, "a.mp3", len(AUDIO), expected_hash(AUDIO))]
    assert not list(out.glob("*.part"))


def test_follows_a_redirect_to_the_file(server, tmp_path):
    url = server + "/audio/moved/b.mp3"
    rows = fia.fetch_all([url], tmp_path / "out", cookies(tmp_path))
    assert rows[0].content_hash == expected_hash(AUDIO)
    assert rows[0].url == url  # the hash belongs to the URL the container names


def test_a_login_redirect_stops_the_run(server, tmp_path):
    urls = [server + "/audio/ok/a.mp3", server + "/audio/ok/b.mp3"]
    with pytest.raises(fia.NeedsLogin):
        fia.fetch_all(urls, tmp_path / "out", cookies(tmp_path, value="expired"))
    assert not (tmp_path / "out" / "a.mp3").exists()
    assert len([h for h in Handler.hits if h[0].startswith("/audio/")]) == 1  # stopped at the first


def test_a_cloudflare_challenge_stops_the_run(server, tmp_path):
    with pytest.raises(fia.Challenged):
        fia.fetch_all([server + "/audio/challenge/a.mp3"], tmp_path / "out", cookies(tmp_path))


def test_an_html_page_is_never_saved_as_audio(server, tmp_path):
    with pytest.raises(fia.NeedsLogin):
        fia.fetch_all([server + "/audio/html/a.mp3"], tmp_path / "out", cookies(tmp_path))
    assert not list((tmp_path / "out").glob("*"))


def test_cookies_go_only_to_the_host_they_name(server, tmp_path):
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n"
                   "get.ietf.org\tFALSE\t/\tTRUE\t0\tsessionid\tgood\n")
    with pytest.raises(fia.NeedsLogin):
        fia.fetch_all([server + "/audio/ok/a.mp3"], tmp_path / "out", jar)
    assert Handler.hits[0][1] is None


def test_a_second_run_skips_files_already_in_the_manifest(server, tmp_path):
    url = server + "/audio/ok/a.mp3"
    out = tmp_path / "out"
    first = fia.fetch_all([url], out, cookies(tmp_path))
    Handler.hits = []
    second = fia.fetch_all([url], out, cookies(tmp_path))
    assert second == first
    assert Handler.hits == []


def test_a_saved_file_that_no_longer_matches_its_hash_is_refused(server, tmp_path):
    url = server + "/audio/ok/a.mp3"
    out = tmp_path / "out"
    fia.fetch_all([url], out, cookies(tmp_path))
    (out / "a.mp3").write_bytes(b"changed")
    with pytest.raises(fia.Mismatch):
        fia.fetch_all([url], out, cookies(tmp_path))


def test_manifest_is_written_after_each_file(server, tmp_path):
    urls = [server + "/audio/ok/a.mp3", server + "/audio/challenge/b.mp3"]
    out = tmp_path / "out"
    with pytest.raises(fia.Challenged):
        fia.fetch_all(urls, out, cookies(tmp_path))
    assert fia.read_manifest(out) == {urls[0]: fia.Row(urls[0], "a.mp3", len(AUDIO), expected_hash(AUDIO))}


# ---- files downloaded by hand ----

def test_hash_local_matches_files_to_urls_by_filename(tmp_path):
    src = tmp_path / "laptop"
    src.mkdir()
    (src / "a.mp3").write_bytes(AUDIO)
    (src / "stray.mp3").write_bytes(b"x")
    urls = ["https://get.example/x/a.mp3", "https://get.example/x/b.mp3"]
    rows, missing, unknown = fia.hash_local(urls, src)
    assert rows == [fia.Row(urls[0], "a.mp3", len(AUDIO), expected_hash(AUDIO))]
    assert missing == [urls[1]]
    assert unknown == ["stray.mp3"]


def test_hash_local_refuses_an_html_file_named_mp3(tmp_path):
    src = tmp_path / "laptop"
    src.mkdir()
    (src / "a.mp3").write_bytes(b"<!DOCTYPE html><html>sign in</html>")
    rows, missing, unknown = fia.hash_local(["https://get.example/x/a.mp3"], src)
    assert rows == [] and missing == ["https://get.example/x/a.mp3"]


def test_stops_before_a_download_that_would_not_fit(server, tmp_path, monkeypatch):
    class Usage(NamedTuple):
        total: int
        used: int
        free: int
    monkeypatch.setattr(fia.shutil, "disk_usage", lambda p: Usage(0, 0, fia.MIN_FREE + len(AUDIO) - 1))
    with pytest.raises(fia.NoSpace):
        fia.fetch_all([server + "/audio/ok/a.mp3"], tmp_path / "out", cookies(tmp_path))
    assert not list((tmp_path / "out").glob("*.mp3*"))


@pytest.mark.parametrize("kind", ["htmlbody", "htmltype"])
def test_either_html_signal_alone_stops_the_run(server, tmp_path, kind):
    # One test per guard: a page labeled audio, and audio-looking bytes labeled HTML.
    with pytest.raises(fia.NeedsLogin):
        fia.fetch_all([server + f"/audio/{kind}/a.mp3"], tmp_path / "out", cookies(tmp_path))
    assert not list((tmp_path / "out").glob("*.mp3*"))


def test_a_short_body_is_not_saved(server, tmp_path):
    with pytest.raises(fia.HttpFailed):
        fia.fetch_all([server + "/audio/short/a.mp3"], tmp_path / "out", cookies(tmp_path))
    assert not list((tmp_path / "out").glob("*.mp3*"))
