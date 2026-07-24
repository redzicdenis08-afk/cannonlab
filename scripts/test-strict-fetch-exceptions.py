#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def load(name: str, filename: str):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


strict_fetch = load(
    "strict_fetch_public_cannon_corpus_exception_tests",
    "strict-fetch-public-cannon-corpus.py",
)


class TimeoutFetcher:
    @staticmethod
    def run_corpus(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["python", "audit.py"], 240)


def test_subprocess_timeout_fails_cleanly_and_removes_lock() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest = root / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        lock = root / "untrusted-lock.json"
        lock.write_text('{"should":"be-removed"}', encoding="utf-8")
        report_path = root / "report.json"
        original_argv = sys.argv
        original_loader = strict_fetch.load_fetcher
        strict_fetch.load_fetcher = lambda: TimeoutFetcher
        sys.argv = [
            "strict-fetch-public-cannon-corpus.py",
            str(manifest),
            "--output-directory",
            str(root / "out"),
            "--mode",
            "fetch",
            "--write-lock",
            str(lock),
            "--json-out",
            str(report_path),
        ]
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                code = strict_fetch.main()
        finally:
            strict_fetch.load_fetcher = original_loader
            sys.argv = original_argv
        assert code == 2, code
        assert not lock.exists(), lock
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "FAIL", report
        assert report["exception_type"] == "TimeoutExpired", report
        assert report["strict_validation"]["status"] == "FAIL", report
        printed = json.loads(output.getvalue())
        assert printed == report, (printed, report)


def test_remove_untrusted_lock_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "lock.json"
        strict_fetch.remove_untrusted_lock(path)
        path.write_text("{}", encoding="utf-8")
        strict_fetch.remove_untrusted_lock(path)
        strict_fetch.remove_untrusted_lock(path)
        assert not path.exists()


def main() -> int:
    tests = [
        test_subprocess_timeout_fails_cleanly_and_removes_lock,
        test_remove_untrusted_lock_is_idempotent,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS {len(tests)} strict-fetch exception regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
