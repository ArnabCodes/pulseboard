"""Platform tests: service worker, manifest, <head> hygiene, deploy headers.

Covers the platform-wave items (1-25): sw.js cache bump + strategies +
message handlers, manifest shortcuts and icon purposes, the index.html
<head> additions (CSP meta, connection hints, font display=swap), the 404
page actions, and the vercel.json cache headers.

These are static-file assertions only — no network, no browser.

Run: python3 -m pytest tests/ -q
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- sw.js


class TestServiceWorker:
    sw = read("sw.js")

    def test_cache_name_bumped_format(self):
        m = re.search(r"const CACHE_NAME = 'pulseboard-v(\d+)'", self.sw)
        assert m, "CACHE_NAME must be of the form pulseboard-v<N>"
        assert int(m.group(1)) >= 17, "CACHE_NAME must be bumped to v17 or newer"

    def test_message_handlers_present(self):
        assert "SKIP_WAITING" in self.sw, "SKIP_WAITING message flow must exist"
        assert "PURGE_CACHES" in self.sw, "PURGE_CACHES message handler must exist"

    def test_runtime_image_cache_strategy_exists(self):
        # A dedicated runtime image cache with a host allowlist and a cap.
        assert "IMAGE_CACHE_NAME" in self.sw
        assert "images.unsplash.com" in self.sw
        assert re.search(r"IMAGE_CACHE_MAX = \d+", self.sw), "soft cap constant required"

    def test_feed_served_stale_while_revalidate(self):
        # The feed branch must serve cache instantly (not network-first only).
        assert "pulse_feed.json" in self.sw
        assert "stale-while-revalidate" in self.sw


# ---------------------------------------------------------------- manifest.json


class TestManifest:
    manifest = json.loads(read("manifest.json"))

    def test_manifest_is_valid_json_with_core_fields(self):
        for key in ("name", "short_name", "start_url", "icons", "shortcuts"):
            assert key in self.manifest

    def test_every_icon_has_purpose(self):
        icons = self.manifest["icons"]
        assert icons, "manifest must declare icons"
        for icon in icons:
            assert icon.get("purpose"), f"icon {icon.get('src')} missing purpose"
        purposes = {icon["purpose"] for icon in icons}
        assert "maskable" in purposes, "a maskable icon entry is required"
        assert "monochrome" in purposes, "a monochrome icon entry is required"

    def test_shortcuts_at_least_three(self):
        shortcuts = self.manifest["shortcuts"]
        assert len(shortcuts) >= 3, "expected Morning/Night + Saved + Search"
        names = [s["name"] for s in shortcuts]
        assert "Morning edition" in names and "Night edition" in names
        assert "Saved" in names
        assert "Search" in names
        saved = next(s for s in shortcuts if s["name"] == "Saved")
        assert saved["url"] == "/?view=saved"


# ---------------------------------------------------------------- index.html <head>


class TestIndexHead:
    html = read("index.html")
    head = html.split("</head>", 1)[0]

    def test_csp_meta_present(self):
        assert 'http-equiv="Content-Security-Policy"' in self.head, "CSP meta required"
        csp = re.search(
            r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', self.head
        )
        assert csp
        policy = csp.group(1)
        assert "cdn.tailwindcss.com" in policy, "Tailwind Play CDN must be allowed"
        assert "'unsafe-eval'" in policy and "'unsafe-inline'" in policy

    def test_preconnect_hints_for_key_origins(self):
        for host in (
            "api.open-meteo.com",
            "images.unsplash.com",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "cdn.tailwindcss.com",
        ):
            assert (
                f'<link rel="preconnect" href="https://{host}"' in self.head
            ), f"missing preconnect for {host}"

    def test_dns_prefetch_fallbacks(self):
        assert self.head.count('rel="dns-prefetch"') >= 5

    def test_google_fonts_display_swap(self):
        assert "display=swap" in self.head, "Google Fonts link must use display=swap"

    def test_pwa_meta_tags(self):
        assert 'name="theme-color"' in self.head
        assert 'media="(prefers-color-scheme: dark)"' in self.head
        assert 'media="(prefers-color-scheme: light)"' in self.head
        assert "apple-mobile-web-app-capable" in self.head
        assert "apple-mobile-web-app-status-bar-style" in self.head
        assert 'rel="apple-touch-icon"' in self.head
        assert 'name="description"' in self.head


# ---------------------------------------------------------------- 404.html / vercel.json


class TestPlatformPagesAndHeaders:
    def test_404_links_home_and_back(self):
        page = read("404.html")
        assert 'href="/"' in page, "404 must link home"
        assert "history.back" in page, "404 must have a Back button"

    def test_vercel_cache_headers(self):
        cfg = json.loads(read("vercel.json"))
        routes = {h["source"]: h["headers"] for h in cfg["headers"]}
        sw = {d["key"]: d["value"] for d in routes["/sw.js"]}
        assert sw["Cache-Control"] == "public, max-age=0, must-revalidate"
        feed = {d["key"]: d["value"] for d in routes["/pulse_feed.json"]}
        assert feed["Cache-Control"] == "public, max-age=60"
