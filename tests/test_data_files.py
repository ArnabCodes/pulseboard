"""Data-file integrity tests (item 93).

The app fetches its content JSONs at runtime with no schema on either side,
so a malformed entry degrades the UI silently. These tests pin the shapes
the rendering code actually relies on:

- teachings_db.json — unique ids, non-empty quote/reflection, and YouTube
  links whose video ids are the sane 11-character form;
- deadlines.json — ISO dates, non-empty names (past dates are allowed —
  history is honest);
- this_day.json — exactly 30 entries, each with an in-range month/day.
  NOTE: the file stores dates as "MM-DD" strings (see the first entry),
  so the month/day integers are parsed from that string, not read from
  separate fields.

Run: python3 -m pytest tests/test_data_files.py -v
"""
import json
import re
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

YT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


def _load(name):
    path = ROOT / name
    assert path.exists(), f'{name} is missing from the repo root'
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


# ---------------------------------------------------------------- teachings

def test_teachings_ids_are_unique():
    teachings = _load('teachings_db.json')['teachings']
    ids = [t.get('id') for t in teachings]
    assert len(ids) == len(set(ids)), 'duplicate teaching ids'
    assert all(isinstance(i, str) and i for i in ids), 'empty/non-string ids'


def test_teachings_quote_and_reflection_non_empty():
    teachings = _load('teachings_db.json')['teachings']
    for t in teachings:
        assert isinstance(t.get('quote'), str) and t['quote'].strip(), \
            f'teaching {t.get("id")!r} has an empty quote'
        assert isinstance(t.get('reflection'), str) and t['reflection'].strip(), \
            f'teaching {t.get("id")!r} has an empty reflection'


def test_teachings_youtube_ids_are_sane_11_char():
    teachings = _load('teachings_db.json')['teachings']
    checked = 0
    for t in teachings:
        url = t.get('videoUrl')
        if not url:
            continue  # video links are optional
        checked += 1
        assert isinstance(url, str) and 'youtube.com/watch?v=' in url, \
            f'teaching {t.get("id")!r} videoUrl is not a watch URL: {url!r}'
        vid = url.split('watch?v=', 1)[1].split('&', 1)[0]
        assert YT_ID_RE.match(vid), \
            f'teaching {t.get("id")!r} has a malformed YouTube id: {vid!r}'
    assert checked > 0, 'no videoUrl entries found — the sanity check went vacuous'


# ---------------------------------------------------------------- deadlines

def test_deadlines_dates_iso_and_names_non_empty():
    db = _load('deadlines.json')
    deadlines = db['deadlines']
    assert deadlines, 'deadlines.json has no entries'
    for d in deadlines:
        assert isinstance(d.get('name'), str) and d['name'].strip(), \
            f'deadline with empty name: {d!r}'
        assert isinstance(d.get('date'), str) and d['date'], \
            f'deadline {d.get("name")!r} has no date'
        # strict YYYY-MM-DD (fromisoformat rejects anything looser)
        date.fromisoformat(d['date'])
        assert d.get('verified') is True, f'unverified deadline link: {d.get("name")!r}'
    # past-dated entries are allowed and expected — no assertion on recency.
    for key in ('career_jobs', 'postdocs'):
        items = db.get(key, [])
        assert items, f'deadlines.json[{key!r}] must be non-empty'
        ids = [x.get('id') for x in items]
        assert len(ids) == len(set(ids)), f'duplicate ids in {key}'
        for x in items:
            assert isinstance(x.get('name'), str) and x['name'].strip()
            assert isinstance(x.get('org'), str) and x['org'].strip()
            assert isinstance(x.get('url'), str) and x['url'].startswith('https://')
            assert x.get('verified') is True, f'unverified opportunity link: {x.get("id")!r}'
            date.fromisoformat(x['date'])


# ---------------------------------------------------------------- this day

def test_this_day_has_30_entries_with_in_range_month_day():
    entries = _load('this_day.json')['entries']
    assert len(entries) == 30, f'expected 30 entries, found {len(entries)}'
    for e in entries:
        assert isinstance(e.get('date'), str) and re.match(r'^\d{2}-\d{2}$', e['date']), \
            f'entry date is not MM-DD: {e.get("date")!r}'
        month, day = (int(x) for x in e['date'].split('-'))
        assert 1 <= month <= 12, f'month out of range in {e["date"]!r}'
        assert 1 <= day <= 31, f'day out of range in {e["date"]!r}'
        assert isinstance(e.get('event'), str) and e['event'].strip(), \
            f'entry {e["date"]!r} has an empty event'
