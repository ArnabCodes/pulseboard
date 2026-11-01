#!/usr/bin/env python3
"""PulseBoard feed validator.

Hard invariants (exit 1 on any violation):
  - pulse_feed.json is valid JSON
  - at least 1 story; every story has non-empty id / title / content / image
  - at least 1 paper; every paper has non-empty id / title / url
  - no duplicate story ids
  - no duplicate cover images across stories (the distinct-covers invariant)

Soft check (warnings only, never fails the run):
  - every story cover / gallery image answers HTTP 200 (HEAD with a
    ranged-GET fallback for CDNs that reject HEAD); slow or unreachable
    images are reported, not fatal.

Used by .github/workflows/validate-feed.yml and imported by tests/test_curate.py.
Usage: python3 tests/validate_feed.py [--check-images] [pulse_feed.json ...]
"""
import json
import sys
import urllib.error
import urllib.request

HEAD_TIMEOUT = 10
UA = 'PulseBoard-FeedValidator/1.0'


def http_status(url, timeout=HEAD_TIMEOUT):
    """200/206/... for the URL, or None if unreachable. Falls back to a
    1-byte ranged GET when a CDN rejects HEAD (405/501)."""
    for method, extra in (('HEAD', {}), ('GET', {'Range': 'bytes=0-1'})):
        req = urllib.request.Request(
            url, method=method,
            headers={'User-Agent': UA, **extra})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if method == 'HEAD' and e.code in (405, 501):
                continue
            return e.code
        except Exception:
            continue
    return None


def check_feed(feed, check_images=False):
    """Return (errors, warnings) for a parsed feed dict."""
    errors, warnings = [], []

    stories = feed.get('stories')
    if not isinstance(stories, list) or not stories:
        errors.append('feed has no stories (need >= 1)')
        stories = stories if isinstance(stories, list) else []

    ids, covers = [], []
    for i, st in enumerate(stories):
        where = f'story[{i}]' + (f' ({st.get("id")})' if isinstance(st, dict) and st.get('id') else '')
        for field in ('id', 'title', 'content', 'image'):
            v = st.get(field) if isinstance(st, dict) else None
            if not v or not str(v).strip():
                errors.append(f'{where}: missing/empty {field}')
        if isinstance(st, dict) and st.get('id'):
            ids.append(st['id'])
        if isinstance(st, dict) and st.get('image'):
            covers.append(st['image'])

    for d in sorted({x for x in ids if ids.count(x) > 1}):
        errors.append(f'duplicate story id: {d}')
    for d in sorted({x for x in covers if covers.count(x) > 1}):
        errors.append(f'duplicate cover image across stories (distinct-covers invariant): {d}')

    papers = feed.get('papers')
    if not isinstance(papers, list) or not papers:
        errors.append('feed has no papers (need >= 1)')
        papers = papers if isinstance(papers, list) else []
    paper_ids, paper_imgs = [], []
    for i, p in enumerate(papers):
        where = f'paper[{i}]' + (f' ({p.get("id")})' if isinstance(p, dict) and p.get('id') else '')
        for field in ('id', 'title', 'url'):
            v = p.get(field) if isinstance(p, dict) else None
            if not v or not str(v).strip():
                errors.append(f'{where}: missing/empty {field}')
        if isinstance(p, dict) and p.get('id'):
            paper_ids.append(p['id'])
        if isinstance(p, dict) and p.get('image'):
            paper_imgs.append(p['image'])
    for d in sorted({x for x in paper_ids if paper_ids.count(x) > 1}):
        errors.append(f'duplicate paper id: {d}')
    for d in sorted({x for x in paper_imgs if paper_imgs.count(x) > 1}):
        errors.append(f'duplicate paper image (distinct-paper-images invariant): {d}')

    if check_images:
        urls = []
        for st in stories:
            if isinstance(st, dict):
                urls.append(st.get('image'))
                urls.extend(st.get('gallery') or [])
        urls.extend(u for u in paper_imgs if u)
        for u in [u for u in urls if u]:
            status = http_status(u)
            if status is None:
                warnings.append(f'image unreachable (timeout/error): {u}')
            elif status not in (200, 206):
                warnings.append(f'image returned HTTP {status}: {u}')
    return errors, warnings


def main(argv):
    args = argv[1:]
    check_images = '--check-images' in args
    paths = [a for a in args if not a.startswith('--')] or ['pulse_feed.json']
    failed = False
    for path in paths:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                feed = json.load(f)
        except Exception as e:
            print(f'FAIL {path}: does not parse as JSON: {e}')
            failed = True
            continue
        errors, warnings = check_feed(feed, check_images=check_images)
        for w in warnings:
            print(f'WARN {path}: {w}')
        if errors:
            failed = True
            for e in errors:
                print(f'FAIL {path}: {e}')
        else:
            n, p = len(feed.get('stories') or []), len(feed.get('papers') or [])
            extra = f', {len(warnings)} image warning(s)' if warnings else ''
            print(f'OK {path}: {n} stories, {p} papers{extra}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
