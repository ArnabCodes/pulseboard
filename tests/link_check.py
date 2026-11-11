#!/usr/bin/env python3
"""Weekly link health check for PulseBoard.

Checks three fixed surfaces and reports broken links as GitHub-flavored
markdown (the workflow opens an issue with the report on failure):

  1. teachings_db.json YouTube links — every videoUrl is probed via its
     thumbnail (https://i.ytimg.com/vi/<id>/hqdefault.jpg), which answers
     200 only for videos that still exist.
  2. NEWS_SOURCES RSS URLs in scripts/curate.py — every feed must still
     answer 200 (redirects are followed; a dead feed raises).
  3. pulse_feed.json story cover + gallery images — must answer 200.

Exit 1 if anything is broken. Run:
    python3 tests/link_check.py [--report-file PATH]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, HERE)

from curate import NEWS_SOURCES  # noqa: E402  (constants only; import is side-effect free)
from validate_feed import http_status  # noqa: E402

YT_ID_RE = re.compile(r'[?&]v=([A-Za-z0-9_-]{11})')


def youtube_thumb(url):
    m = YT_ID_RE.search(url or '')
    return f'https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg' if m else None


def check_teachings():
    """[(label, url, status)] for every teachings_db.json videoUrl."""
    with open(os.path.join(ROOT, 'teachings_db.json'), encoding='utf-8') as f:
        teachings = json.load(f).get('teachings', [])
    out = []
    for t in teachings:
        url = t.get('videoUrl')
        if not url:
            continue
        thumb = youtube_thumb(url)
        if not thumb:
            out.append((f'teaching "{t.get("id")}" (unparseable videoUrl)', url, 'no video id found'))
            continue
        out.append((f'teaching "{t.get("id")}" ({t.get("videoLabel", "video")})', url, http_status(thumb)))
    return out


def check_rss():
    """[(label, url, status)] for every NEWS_SOURCES RSS URL."""
    out = []
    for topic, sources in NEWS_SOURCES.items():
        for outlet, url in sources:
            out.append((f'RSS {outlet} [{topic}]', url, http_status(url, timeout=20)))
    return out


def check_feed_images():
    """[(label, url, status)] for every story cover + gallery image."""
    with open(os.path.join(ROOT, 'pulse_feed.json'), encoding='utf-8') as f:
        feed = json.load(f)
    out = []
    for st in feed.get('stories', []):
        if st.get('image'):
            out.append((f'cover of story "{st.get("id")}"', st['image'], http_status(st['image'])))
        for g in st.get('gallery') or []:
            g_url = g if isinstance(g, str) else (g or {}).get('url')
            if g_url:
                out.append((f'gallery image of story "{st.get("id")}"', g_url, http_status(g_url)))
    return out


OK = (200, 206)


def main(argv):
    report_path = None
    args = argv[1:]
    if '--report-file' in args:
        report_path = args[args.index('--report-file') + 1]

    groups = [
        ('YouTube teaching videos', check_teachings()),
        ('NEWS_SOURCES RSS feeds', check_rss()),
        ('Feed images', check_feed_images()),
    ]
    broken = []
    total = 0
    for name, results in groups:
        total += len(results)
        bad = [(label, url, status) for label, url, status in results
               if status is None or status not in OK]
        broken.append((name, bad))

    lines = ['# Weekly link check', '']
    any_broken = any(bad for _, bad in broken)
    if any_broken:
        lines.append(f'**{sum(len(b) for _, b in broken)} of {total} checked links are broken.**')
        for name, bad in broken:
            if not bad:
                continue
            lines += ['', f'## {name}', '']
            for label, url, status in bad:
                status_txt = 'unreachable (timeout/error)' if status is None else f'HTTP {status}'
                lines.append(f'- **{status_txt}** — {label}: {url}')
    else:
        lines.append(f'All {total} checked links are healthy.')

    report = '\n'.join(lines) + '\n'
    print(report)
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
    return 1 if any_broken else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
