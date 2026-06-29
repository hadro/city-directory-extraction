#!/usr/bin/env python3
"""Resolve a master row (source,id) -> IIIF manifest -> normalized canvas list,
and download a canvas range as JPEGs for visual inspection. Free; no Gemini.

Usage:
  frontmatter.py list  <source> <id> [N]            # print first N canvases (default 25)
  frontmatter.py get   <source> <id> i j [tag]      # download canvas idx i..j-1 -> tag_<idx>.jpg
"""
import json, sys, urllib.request, os

OUT = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0 (research; city-directory metadata)'}

def manifest_url(source, ident):
    source, ident = source.strip().lower(), ident.strip()
    if source == 'nypl': return f"https://api-collections.nypl.org/manifests/{ident}"
    if source == 'ia':   return f"https://iiif.archive.org/iiif/{ident}/manifest.json"
    if source == 'loc':  return ident if ident.startswith('http') else f"https://www.loc.gov/item/{ident}/manifest.json"
    if source == 'iiif': return ident
    raise ValueError(f"unknown source {source!r}")

def fetch_json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=90))

def label_str(lab):
    if isinstance(lab, dict):
        for v in lab.values():
            return v[0] if isinstance(v, list) else str(v)
    return str(lab)

def canvases(m):
    """Return list of dicts: {idx, label, service, direct} for v2 or v3."""
    out = []
    if 'sequences' in m:                                   # IIIF v2
        cs = m['sequences'][0]['canvases']
        for i, c in enumerate(cs):
            res = c['images'][0]['resource']
            svc = res.get('service') or {}
            if isinstance(svc, list): svc = svc[0]
            sid = svc.get('@id') or svc.get('id')
            out.append({'idx': i, 'label': label_str(c.get('label', i)),
                        'service': sid, 'direct': res.get('@id')})
    elif 'items' in m:                                     # IIIF v3
        for i, c in enumerate(m['items']):
            body = c['items'][0]['items'][0]['body']
            svc = body.get('service') or {}
            if isinstance(svc, list): svc = svc[0]
            sid = svc.get('@id') or svc.get('id') if svc else None
            out.append({'idx': i, 'label': label_str(c.get('label', i)),
                        'service': sid, 'direct': body.get('id')})
    return out

def image_url(c, width=1300):
    if c['service']:
        s = c['service'].rstrip('/')
        return f"{s}/full/{width},/0/default.jpg"
    return c['direct']

def main():
    cmd = sys.argv[1]
    source, ident = sys.argv[2], sys.argv[3]
    m = fetch_json(manifest_url(source, ident))
    cs = canvases(m)
    if cmd == 'list':
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 25
        print(f"total canvases: {len(cs)}")
        for c in cs[:n]:
            print(f"{c['idx']:>3} | label={c['label']:>6} | {image_url(c)[:78]}")
    elif cmd == 'get':
        i, j = int(sys.argv[4]), int(sys.argv[5])
        tag = sys.argv[6] if len(sys.argv) > 6 else f"{source}_{ident[:12]}"
        for c in cs[i:j]:
            url = image_url(c)
            path = os.path.join(OUT, f"{tag}_{c['idx']:03d}.jpg")
            try:
                req = urllib.request.Request(url, headers=UA)
                data = urllib.request.urlopen(req, timeout=90).read()
                open(path, 'wb').write(data)
                print(f"  c{c['idx']:>3} (label {c['label']}) -> {os.path.basename(path)} {len(data)} B")
            except Exception as e:
                print(f"  c{c['idx']:>3} FAILED: {e}")

if __name__ == '__main__':
    main()
