#!/usr/bin/env python3
"""Unit tests for check_links.py — no network calls needed.

Fixtures simulate the HTTP responses that Google Drive, Docs, and generic
servers return so that the gone-vs-alive classification can be verified
offline.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from check_links import (
    classify_response,
    is_google_url,
    check_url,
    check_all,
    format_summary,
    load_resources,
)

# ── HTML fixtures ───────────────────────────────────────────────────────────

DRIVE_GONE_HTML = """\
<!DOCTYPE html>
<html><head>
<link rel="shortcut icon" href="//docs.google.com/favicon.ico">
<title>Page Not Found</title>
</head><body>
<p class="errorMessage" style="padding-top: 50px">Sorry, the file you have
requested does not exist.</p>
<p>Make sure that you have the correct URL and the file exists.</p>
</body></html>
"""

DRIVE_ALIVE_HTML = """\
<!DOCTYPE html>
<html><head>
<title>Context Engineering: Sessions &amp; Memory.pdf - Google Drive</title>
</head><body>
<div id="drive-viewer-main">
  <div class="ndfHFb-c4YZDc-cYSp0e-s2gQvd">File preview content</div>
</div>
<a href="https://accounts.google.com/ServiceLogin">Sign in</a>
</body></html>
"""

DRIVE_SIGNIN_HTML = """\
<!DOCTYPE html>
<html><head>
<title>Google Drive - Access Denied</title>
</head><body>
<p>You need permission to access this file.</p>
<a href="https://accounts.google.com/ServiceLogin">Sign in</a>
</body></html>
"""

DRIVE_TRASHED_HTML = """\
<!DOCTYPE html>
<html><head><title>Google Drive</title></head>
<body>
<p>This file has been removed. Contact the owner for access.</p>
</body></html>
"""

GENERIC_404_HTML = "<html><body>Not Found</body></html>"
GENERIC_OK_HTML = "<html><body>Welcome</body></html>"


# ── classify_response ──────────────────────────────────────────────────────

class TestClassifyResponse:
    def test_404_is_dead(self):
        assert classify_response("https://example.com", 404, "") == "dead"

    def test_410_is_dead(self):
        assert classify_response("https://example.com", 410, "") == "dead"

    def test_200_generic_is_alive(self):
        assert classify_response("https://example.com", 200, GENERIC_OK_HTML) == "alive"

    def test_200_drive_gone_is_dead(self):
        url = "https://drive.google.com/file/d/FAKE/view"
        assert classify_response(url, 200, DRIVE_GONE_HTML) == "dead"

    def test_200_drive_alive_is_alive(self):
        url = "https://drive.google.com/file/d/REAL/view"
        assert classify_response(url, 200, DRIVE_ALIVE_HTML) == "alive"

    def test_200_drive_signin_is_alive(self):
        """A sign-in page is NOT dead — the file may still exist."""
        url = "https://drive.google.com/file/d/PRIVATE/view"
        assert classify_response(url, 200, DRIVE_SIGNIN_HTML) == "alive"

    def test_200_drive_trashed_is_dead(self):
        url = "https://drive.google.com/file/d/TRASHED/view"
        assert classify_response(url, 200, DRIVE_TRASHED_HTML) == "dead"

    def test_200_docs_gone_is_dead(self):
        url = "https://docs.google.com/document/d/GONE/edit"
        assert classify_response(url, 200, DRIVE_GONE_HTML) == "dead"

    def test_403_is_skip(self):
        assert classify_response("https://example.com", 403, "") == "skip"

    def test_429_is_skip(self):
        assert classify_response("https://example.com", 429, "") == "skip"

    def test_500_is_skip(self):
        assert classify_response("https://example.com", 500, "") == "skip"

    def test_301_redirect_is_alive(self):
        assert classify_response("https://example.com", 301, "") == "alive"

    def test_drive_404_is_dead(self):
        """The known dead URL returns 404 — must be flagged."""
        url = "https://drive.google.com/file/d/1-z9OJ_b6LCwv-U9go-o9T-GDainDafMP/view"
        assert classify_response(url, 404, DRIVE_GONE_HTML) == "dead"


# ── is_google_url ──────────────────────────────────────────────────────────

class TestIsGoogleUrl:
    def test_drive(self):
        assert is_google_url("https://drive.google.com/file/d/ABC/view")

    def test_docs(self):
        assert is_google_url("https://docs.google.com/document/d/ABC/edit")

    def test_generic(self):
        assert not is_google_url("https://example.com/page")

    def test_share_google(self):
        assert not is_google_url("https://share.google/xyz")


# ── check_url (mocked network) ────────────────────────────────────────────

class TestCheckUrl:
    def _mock_get(self, status, text=""):
        resp = MagicMock()
        resp.status_code = status
        resp.text = text
        return resp

    @patch("check_links._get_session")
    def test_known_dead_drive_url(self, mock_sess_fn):
        sess = MagicMock()
        mock_sess_fn.return_value = sess
        sess.get.return_value = self._mock_get(404, DRIVE_GONE_HTML)

        url = "https://drive.google.com/file/d/1-z9OJ_b6LCwv-U9go-o9T-GDainDafMP/view"
        verdict, status, reason = check_url(url)
        assert verdict == "dead"
        assert status == 404

    @patch("check_links._get_session")
    def test_alive_url(self, mock_sess_fn):
        sess = MagicMock()
        mock_sess_fn.return_value = sess
        sess.head.return_value = self._mock_get(200)

        verdict, status, reason = check_url("https://example.com")
        assert verdict == "alive"
        assert status == 200

    @patch("check_links._get_session")
    def test_timeout_is_skip(self, mock_sess_fn):
        sess = MagicMock()
        mock_sess_fn.return_value = sess
        import requests as req
        sess.head.side_effect = req.exceptions.Timeout("timed out")

        verdict, status, reason = check_url("https://slow.example.com")
        assert verdict == "skip"
        assert status is None
        assert "timeout" in reason

    def test_non_http_is_skip(self):
        verdict, status, reason = check_url("ftp://files.example.com/data")
        assert verdict == "skip"
        assert "non-HTTP" in reason


# ── check_all (integration with mocked network) ───────────────────────────

class TestCheckAll:
    @patch("check_links.check_url")
    def test_aggregates_results(self, mock_check):
        mock_check.side_effect = [
            ("alive", 200, "HTTP 200"),
            ("dead", 404, "HTTP 404"),
            ("skip", None, "timeout"),
        ]
        resources = [
            {"id": 1, "url": "https://a.com", "title": "A"},
            {"id": 2, "url": "https://dead.com", "title": "Dead"},
            {"id": 3, "url": "https://slow.com", "title": "Slow"},
        ]
        results = check_all(resources, delay=0)
        assert len(results["alive"]) == 1
        assert len(results["dead"]) == 1
        assert len(results["skipped"]) == 1
        assert results["dead"][0]["url"] == "https://dead.com"


# ── format_summary ─────────────────────────────────────────────────────────

class TestFormatSummary:
    def test_with_dead_links(self):
        results = {
            "dead": [{"id": 24, "url": "https://dead.example.com",
                       "title": "Dead Link", "status": 404, "reason": "HTTP 404"}],
            "alive": [{"id": 1, "url": "https://a.com", "title": "A",
                        "status": 200, "reason": "HTTP 200"}],
            "skipped": [],
        }
        md = format_summary(results)
        assert "Dead links found" in md
        assert "https://dead.example.com" in md
        assert "2" in md  # total checked

    def test_all_alive(self):
        results = {"dead": [], "alive": [{"id": 1, "url": "https://a.com",
                   "title": "A", "status": 200, "reason": ""}], "skipped": []}
        md = format_summary(results)
        assert "All links are alive" in md


# ── load_resources ─────────────────────────────────────────────────────────

def test_load_resources(tmp_path):
    data = [{"id": 1, "url": "https://x.com", "title": "X"}]
    p = tmp_path / "resources.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    loaded = load_resources(p)
    assert loaded == data


import json

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
