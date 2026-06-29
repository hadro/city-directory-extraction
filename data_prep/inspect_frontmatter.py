#!/usr/bin/env python3
"""Resolve a directory volume (source,id) -> IIIF manifest -> canvas list, and download a
canvas range as JPEGs for visual inspection (find the front matter / abbreviations key page /
listing-start page). Free; no Gemini. stdlib only.

Usage:
  inspect_frontmatter.py list  <source> <id> [N]         # print first N canvases (idx|label|url)
  inspect_frontmatter.py get   <source> <id> i j         # download canvas idx i..j-1
  inspect_frontmatter.py sheet <source> <id> i j         # get + build a labeled contact sheet
  inspect_frontmatter.py dir   <source> <id>             # print this volume's cache dir

<source> = nypl | ia | loc | iiif.  Files cache to a PERSISTENT, git-ignored dir keyed by
(source,id), so re-runs and later sessions reuse pages instead of re-hitting slow IA:
  - $FM_OUT if set, else
  - ../../directory-pipeline/output/_frontmatter/<src>_<id>/  (sibling pipeline output, gitignored), else
  - ../data/fm_cache/<src>_<id>/  (this repo's gitignored data/)
Pages are named p<idx>.jpg (idx = 0-based canvas index). Downloads SKIP files already present and
complete (JPEG EOI verified), and RETRY each fetch up to 3x — so a re-run only refetches what's
missing/truncated. IA is slow/flaky; NYPL is fast.
"""
import json, sys, os, re, time, shutil, subprocess, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (research; city-directory metadata)'}


def out_root():
    env = os.environ.get('FM_OUT')
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))                    # data_prep/
    pipe = os.path.normpath(os.path.join(here, '..', '..', 'directory-pipeline', 'output'))
    if os.path.isdir(pipe):
        return os.path.join(pipe, '_frontmatter')
    return os.path.normpath(os.path.join(here, '..', 'data', 'fm_cache'))


def vol_dir(source, ident):
    d = os.path.join(out_root(), re.sub(r'[^A-Za-z0-9._-]', '_', f"{source}_{ident}")[:90])
    os.makedirs(d, exist_ok=True)
    return d


def manifest_url(source, ident):
    source, ident = source.strip().lower(), ident.strip()
    if source == 'nypl': return f"https://api-collections.nypl.org/manifests/{ident}"
    if source == 'ia':   return f"https://iiif.archive.org/iiif/{ident}/manifest.json"
    if source == 'loc':  return ident if ident.startswith('http') else f"https://www.loc.gov/item/{ident}/manifest.json"
    if source == 'iiif': return ident
    raise ValueError(f"unknown source {source!r} (want nypl|ia|loc|iiif)")


def fetch_url(url, tries=3, timeout=120):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:                                           # noqa: BLE001
            last = e
            if a + 1 < tries:
                time.sleep(1.5 * (a + 1))
    raise last


def get_manifest(source, ident):
    """Fetch + cache the manifest JSON in the volume dir (avoids re-hitting IA on every call)."""
    mp = os.path.join(vol_dir(source, ident), 'manifest.json')
    if os.path.exists(mp) and os.path.getsize(mp) > 100:
        try:
            return json.load(open(mp))
        except Exception:                                               # noqa: BLE001
            pass
    m = json.loads(fetch_url(manifest_url(source, ident), timeout=90))
    json.dump(m, open(mp, 'w'))
    return m


def label_str(lab):
    if isinstance(lab, dict):
        for v in lab.values():
            return v[0] if isinstance(v, list) else str(v)
    return str(lab)


def canvases(m):
    """Normalize IIIF v2 or v3 -> [{idx, label, service, direct}]."""
    out = []
    if 'sequences' in m:                                                # v2
        for i, c in enumerate(m['sequences'][0]['canvases']):
            res = c['images'][0]['resource']
            svc = res.get('service') or {}
            if isinstance(svc, list): svc = svc[0]
            out.append({'idx': i, 'label': label_str(c.get('label', i)),
                        'service': svc.get('@id') or svc.get('id'), 'direct': res.get('@id')})
    elif 'items' in m:                                                  # v3
        for i, c in enumerate(m['items']):
            body = c['items'][0]['items'][0]['body']
            svc = body.get('service') or {}
            if isinstance(svc, list): svc = svc[0]
            sid = (svc.get('@id') or svc.get('id')) if svc else None
            out.append({'idx': i, 'label': label_str(c.get('label', i)),
                        'service': sid, 'direct': body.get('id')})
    return out


def image_url(c, width=1300):
    if c['service']:
        return f"{c['service'].rstrip('/')}/full/{width},/0/default.jpg"
    return c['direct']


def complete_jpeg(path):
    """True if path is a non-trivial, non-truncated JPEG (EOI marker present)."""
    try:
        if os.path.getsize(path) < 2000:
            return False
        with open(path, 'rb') as f:
            f.seek(-2, os.SEEK_END)
            return f.read() == b'\xff\xd9'
    except Exception:                                                   # noqa: BLE001
        return False


def download_range(source, ident, i, j):
    cs = canvases(get_manifest(source, ident))
    d = vol_dir(source, ident)
    got = cached = failed = 0
    paths = []
    for c in cs[i:j]:
        path = os.path.join(d, f"p{c['idx']:03d}.jpg")
        if complete_jpeg(path):
            cached += 1
            paths.append(path)
            print(f"  c{c['idx']:>3} (label {c['label']}) cached")
            continue
        last = None
        for a in range(3):
            try:
                data = fetch_url(image_url(c), tries=1)
                with open(path, 'wb') as f:
                    f.write(data)
                if complete_jpeg(path):
                    break
                last = 'incomplete jpeg'
            except Exception as e:                                      # noqa: BLE001
                last = e
            time.sleep(1.5 * (a + 1))
        if complete_jpeg(path):
            got += 1
            paths.append(path)
            print(f"  c{c['idx']:>3} (label {c['label']}) -> {os.path.basename(path)} {os.path.getsize(path)} B")
        else:
            failed += 1
            print(f"  c{c['idx']:>3} FAILED: {last}")
    print(f"[{got} fetched, {cached} cached, {failed} failed]  dir: {d}")
    return d, paths


def main():
    if len(sys.argv) < 4:
        print(__doc__); sys.exit(1)
    cmd, source, ident = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == 'dir':
        print(vol_dir(source, ident)); return
    if cmd == 'list':
        cs = canvases(get_manifest(source, ident))
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 25
        print(f"total canvases: {len(cs)}   dir: {vol_dir(source, ident)}")
        for c in cs[:n]:
            print(f"{c['idx']:>3} | label={c['label']:>6} | {image_url(c)[:78]}")
        return
    i, j = int(sys.argv[4]), int(sys.argv[5])
    d, paths = download_range(source, ident, i, j)
    if cmd == 'sheet':
        if not shutil.which('montage'):
            print("(montage not found; install ImageMagick to auto-build contact sheets)"); return
        if not paths:
            print("(no pages to montage)"); return
        sheet = os.path.join(d, f"_sheet_{i}_{j}.jpg")
        cols = 5
        subprocess.run(['montage', *paths, '-tile', f'{cols}x', '-geometry', '250x340+3+3',
                        '-pointsize', '20', '-label', '%f', sheet], check=False)
        print(f"sheet -> {sheet}")


if __name__ == '__main__':
    main()
