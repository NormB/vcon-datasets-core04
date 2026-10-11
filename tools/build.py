#!/usr/bin/env python3
"""Regenerate the corrected corpus from the pinned upstream datasets, or check it.

    build.py build --cache DIR    fetch each pin into DIR (or reuse a clean
                                  checkout there), correct every container,
                                  write datasets/, report.json and REPORT.md
    build.py check                judge the committed datasets/ again and
                                  compare with report.json and REPORT.md;
                                  needs no network and no upstream checkout

Only git touches an upstream repository, with hooks, symbolic links,
submodules and LFS off, and no GIT_* variable from the caller. Nothing in a
dataset is executed. Exit codes: 0 done, 1 a check or build failed.
"""

import argparse
import copy
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import core04

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "vcon.schema.json"
PINS = ROOT / "PINS.tsv"
OUT = ROOT / "datasets"
REPORT_JSON = ROOT / "report.json"
REPORT_MD = ROOT / "REPORT.md"
HASHES = ROOT / "hashes"

SAFE_CONFIG = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.symlinks=false",
    "-c", "submodule.recurse=false",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.process=",
    "-c", "filter.lfs.required=false",
    "-c", "advice.detachedHead=false",
]


class BuildError(Exception):
    """An upstream dataset could not be fetched or is not at its pin."""


def _git(*args, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    run = subprocess.run(["git", *SAFE_CONFIG, *args], cwd=cwd, env=env,
                         capture_output=True, text=True)
    if run.returncode != 0:
        raise BuildError(f"git {' '.join(args)}: {run.stderr.strip()}")
    return run.stdout.strip()


def fetch(pin, cache):
    """A clean checkout of ``pin`` under ``cache``, verified."""
    tree = pathlib.Path(cache) / pin.name
    if not (tree / ".git").exists():
        tree.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--no-checkout", pin.url, str(tree))
    try:
        _git("cat-file", "-e", f"{pin.commit}^{{commit}}", cwd=tree)
    except BuildError:
        _git("fetch", "--quiet", "origin", pin.commit, cwd=tree)
    _git("checkout", "--quiet", "--detach", pin.commit, cwd=tree)
    if _git("rev-parse", "HEAD", cwd=tree) != pin.commit:
        raise BuildError(f"{pin.name}: HEAD is not {pin.commit}")
    if _git("status", "--porcelain", "--untracked-files=all", cwd=tree):
        raise BuildError(f"{pin.name}: checkout has local changes")
    return tree


def containers(tree):
    """Every ``*.vcon.json`` under ``tree``, outside .git, in a stable order."""
    return sorted(p for p in pathlib.Path(tree).rglob("*.vcon.json")
                  if ".git" not in p.relative_to(tree).parts and p.is_file())


def _bump(counter, key, n=1):
    counter[key] = counter.get(key, 0) + n


class _Judge:
    """Validity, findings and index errors over a set of containers."""

    def __init__(self):
        self.valid = 0
        self.valid_with_index_errors = 0
        self.findings = {}
        self.index_errors = {}
        self.unhashed_url_hosts = {}

    def add(self, doc, v):
        keys = core04.findings(doc, v)
        errors = core04.index_errors(doc)
        if not keys:
            self.valid += 1
            if errors:
                self.valid_with_index_errors += 1
        for k in keys:
            _bump(self.findings, k)
        for e in errors:
            _bump(self.index_errors, e)
        for host, n in core04.unhashed_url_hosts(doc).items():
            _bump(self.unhashed_url_hosts, host, n)


def _tree_digest(root):
    h = hashlib.sha256()
    for path in containers(root):
        rel = path.relative_to(root).as_posix()
        h.update(f"{rel}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def default_hash_tables():
    return sorted(HASHES.glob("*.tsv"))


def _tables_digest(tables):
    return {pathlib.Path(t).name: hashlib.sha256(pathlib.Path(t).read_bytes()).hexdigest()
            for t in tables}


def load_hashes(tables):
    merged = {}
    for t in tables:
        for url, token in core04.read_hashes(t).items():
            if merged.get(url, token) != token:
                raise ValueError(f"{t}: {url} has a different hash in another table")
            merged[url] = token
    return merged


def build(pins, cache, out, schema, hash_tables=()):
    """Correct every pinned dataset into ``out``; return the report."""
    v = core04.validator(schema)
    hashes = load_hashes(hash_tables)
    report = {"schema_sha256": hashlib.sha256(pathlib.Path(schema).read_bytes()).hexdigest(),
              "hash_tables": _tables_digest(hash_tables),
              "datasets": {}}
    for pin in pins:
        tree = fetch(pin, cache)
        dest = pathlib.Path(out) / pin.name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.copyfile(tree / "LICENSE", dest / "LICENSE")
        before, after = _Judge(), _Judge()
        applied, unresolved = {}, {}
        changed = count = 0
        for path in containers(tree):
            count += 1
            raw = path.read_bytes()
            doc = json.loads(raw)
            style = core04.detect_style(raw, doc)
            original = copy.deepcopy(doc)
            before.add(original, v)
            result = core04.correct(doc, hashes=hashes)
            core04.assert_additive(original, doc)
            for c in result.applied:
                _bump(applied, c.rule)
            for c in result.unresolved:
                _bump(unresolved, c.rule)
            target = dest / path.relative_to(tree)
            target.parent.mkdir(parents=True, exist_ok=True)
            if doc != original:
                changed += 1
                target.write_bytes(core04.dump(doc, style))
            else:
                target.write_bytes(raw)
            after.add(doc, v)
        report["datasets"][pin.name] = {
            "url": pin.url,
            "commit": pin.commit,
            "license": pin.license,
            "containers": count,
            "changed_containers": changed,
            "applied": applied,
            "unresolved": unresolved,
            "valid_before": before.valid,
            "valid_after": after.valid,
            "findings_before": before.findings,
            "findings_after": after.findings,
            "index_errors": after.index_errors,
            "valid_with_index_errors": after.valid_with_index_errors,
            "unhashed_url_hosts": after.unhashed_url_hosts,
            "tree_sha256": _tree_digest(dest),
        }
    return report


def verify(out, report, schema, hash_tables=()):
    """Problems found judging ``out`` again against ``report``; empty when it matches."""
    v = core04.validator(schema)
    problems = []
    if _tables_digest(hash_tables) != report.get("hash_tables", {}):
        problems.append("hash tables: hashes/ differs from the tables the report was built with")
    if hashlib.sha256(pathlib.Path(schema).read_bytes()).hexdigest() != report.get("schema_sha256"):
        problems.append("schema: vendored schema differs from the one the report was built with")
    for name, want in report["datasets"].items():
        dest = pathlib.Path(out) / name
        if not dest.is_dir():
            problems.append(f"{name}: missing from {out}")
            continue
        judge = _Judge()
        files = containers(dest)
        for path in files:
            judge.add(json.loads(path.read_bytes()), v)
        got = {"containers": len(files), "valid_after": judge.valid,
               "findings_after": judge.findings, "index_errors": judge.index_errors,
               "valid_with_index_errors": judge.valid_with_index_errors,
               "unhashed_url_hosts": judge.unhashed_url_hosts,
               "tree_sha256": _tree_digest(dest)}
        for key, value in got.items():
            if want.get(key) != value:
                problems.append(f"{name}: {key} is {value!r}, report says {want.get(key)!r}")
    return problems


def _table(counts, label, unit="Containers"):
    if not counts:
        return ["None.", ""]
    lines = [f"| {label} | {unit} |", "|---|---:|"]
    lines += [f"| `{k}` | {n} |" for k, n in sorted(counts.items())]
    return lines + [""]


def render(report):
    """REPORT.md, from the report alone, so every number in it was measured."""
    out = [
        "# Report",
        "",
        "Generated by `tools/build.py` from `report.json`. Do not edit by hand.",
        "",
        f"Schema: `schema/vcon.schema.json`, SHA-256 `{report['schema_sha256']}`.",
        "",
        "| Dataset | Containers | Corrected | Valid before | Valid after |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, d in sorted(report["datasets"].items()):
        out.append(f"| {name} | {d['containers']} | {d['changed_containers']} | "
                   f"{d['valid_before']} | {d['valid_after']} |")
    out.append("")
    for name, d in sorted(report["datasets"].items()):
        out += [f"## {name}", "",
                f"Upstream {d['url']} at `{d['commit']}`, license {d['license']}.", ""]
        applied = ", ".join(f"`{k}` {n}" for k, n in sorted(d["applied"].items())) or "none"
        out += [f"Corrections applied (count of objects): {applied}.", ""]
        unresolved = ", ".join(f"`{k}` {n}" for k, n in sorted(d["unresolved"].items())) or "none"
        out += [f"Found and not settled by the data (count of objects): {unresolved}.", ""]
        out += ["Schema findings after correction:", ""] + _table(d["findings_after"], "Finding")
        out += ["Index errors (not visible to the schema):", ""] + _table(d["index_errors"], "Error")
        if d["index_errors"]:
            out += [f"{d['valid_with_index_errors']} of the valid containers carry an index error.", ""]
        out += ["Dialogs with `url` and no `content_hash`, by host:", ""]
        out += _table(d["unhashed_url_hosts"], "Host", "Dialogs")
    return "\n".join(out)


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--cache", required=True, help="directory holding the upstream checkouts")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            pins = core04.parse_pins(PINS.read_text())
            report = build(pins, args.cache, OUT, SCHEMA, default_hash_tables())
            _write_json(REPORT_JSON, report)
            REPORT_MD.write_text(render(report))
            print(render(report).split("\n## ")[0])
            return 0
        report = json.loads(REPORT_JSON.read_text())
        problems = verify(OUT, report, SCHEMA, default_hash_tables())
        if REPORT_MD.read_text() != render(report):
            problems.append("REPORT.md: not what report.json renders to; rerun build")
        pinned = {p.name: p.commit for p in core04.parse_pins(PINS.read_text())}
        if pinned != {n: d["commit"] for n, d in report["datasets"].items()}:
            problems.append("PINS.tsv: datasets or commits differ from report.json")
        for p in problems:
            print(p, file=sys.stderr)
        print(f"check: {len(problems)} problem(s)")
        return 1 if problems else 0
    except (BuildError, core04.NotAdditive, core04.UnknownStyle, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
