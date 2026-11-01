"""
A Gradio page over space/search.py: every line in the city directories that may give an
address, OCR misreadings included, each with its line image from the Internet Archive.

    uv run --with-requirements space/requirements.txt python space/app.py     # http://127.0.0.1:7860

RECORDS_PARQUET names the records file (default data/space/records.parquet, which
space/build_parquet.py makes); on Hugging Face it will be the release's hf:// path.
"""
from __future__ import annotations

import collections
import csv
import html
import os
import re
import tempfile
from pathlib import Path

import gradio as gr

from search import PLACES, Records, fa

PARQUET = os.environ.get("RECORDS_PARQUET", str(
    Path(__file__).resolve().parent.parent / "data" / "space" / "records.parquet"))
NEAR_SHOWN = 300
ABOUT = {
    "exact": "The number and the street as asked.",
    "street": "The number as asked; the street misspelled or split by the OCR.",
    "number": "The number in look-alike characters (I66, hl66).",
    "wrapped": "The number at the end of a line, the street at the start of the next.",
    "near": "One digit off. Mostly real neighbours: the ones flagged SAME NAME or SURNAME have "
            "that person, or surname, at the exact address in another year, and are the "
            "likeliest misreadings.",
}
CSS = """
.hits { width: 100%; border-collapse: collapse; font-size: 14px; }
.hits td { border-top: 1px solid var(--border-color-primary); padding: 6px 8px; vertical-align: top; }
.hits td.y { white-space: nowrap; width: 1%; }
.hits img { height: 32px; width: auto; max-width: 100%; object-fit: contain;
            object-position: left; display: block; background: #fff; }
.hits .name { font-weight: 600; margin-bottom: 3px; }
.hits .raw { font-family: var(--font-mono); font-size: 13px; margin-top: 2px; }
.hits .meta { color: var(--body-text-color-subdued); font-size: 12px; }
.flag { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 8px;
        border: 1px solid var(--border-color-primary); white-space: nowrap; }
.flag.look { border-color: #d97706; color: #d97706; }
.terms { color: var(--body-text-color-subdued); font-size: 13px; }
"""

# Line images ask IA's image server for nothing until they are on screen. An image carries its
# URL in data-src; this sets src once the image is within 200px of the viewport, at most
# IMG_AT_ONCE at a time. An image in a closed <details> is not rendered, so it never intersects
# and is never fetched until the section is opened. A request IA leaves hanging (it can take
# ~60 s to fail) frees its slot after 15 s. gr.HTML's output runs no scripts, so this goes in the
# page head and watches for result rows as they arrive.
IMG_AT_ONCE = 4
LAZY_JS = """
<script>
(() => {
  const MAX = %d; let busy = 0; const queue = [];
  const pump = () => {
    while (busy < MAX && queue.length) {
      const img = queue.shift();
      if (!img.isConnected || img.getAttribute('src')) continue;
      busy++;
      let freed = false;
      const free = () => { if (!freed) { freed = true; busy--; pump(); } };
      img.addEventListener('load', free, {once: true});
      img.onerror = () => {         // one fallback size, in the same slot
        if (img.dataset.fallback && img.getAttribute('src') !== img.dataset.fallback) {
          img.src = img.dataset.fallback;
        } else { img.onerror = null; free(); }
      };
      setTimeout(free, 15000);
      img.src = img.dataset.src;
    }
  };
  const io = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) { io.unobserve(e.target); queue.push(e.target); }
    pump();
  }, {rootMargin: '200px 0px'});
  const watch = root => {
    if (root.nodeType !== 1) return;
    const imgs = root.matches('img[data-src]') ? [root] : root.querySelectorAll('img[data-src]');
    for (const img of imgs) if (!img.dataset.watched) { img.dataset.watched = '1'; io.observe(img); }
  };
  new MutationObserver(ms => { for (const m of ms) m.addedNodes.forEach(watch); })
    .observe(document.documentElement, {childList: true, subtree: true});
})();
</script>
""" % IMG_AT_ONCE

records = Records(PARQUET)


def resize(url: str, upright: str, turned: str) -> str:
    """The crop at another IIIF size. browse/plugins/records_cells.py's rule: `full` (what
    `crop` holds) hangs on some lines for ~60 s while `,64` comes back in ~1 s, and the reverse on
    others, so ask `,64` (also the smallest download) and fall back to `max`. IIIF scales before
    it rotates, so a turned line is sized on its width."""
    parts = url.split("/")
    if len(parts) < 5 or parts[-1] != "default.jpg":
        return url
    parts[-3] = turned if parts[-2] in ("90", "270") else upright
    return "/".join(parts)


def links(crop: str) -> str:
    m = re.match(r"(https://iiif\.archive\.org/iiif/[^/]+)/(\d+),(\d+),(\d+),(\d+)/", crop or "")
    if not m:
        return ""
    base, x, y, w, h = m.group(1), *map(int, m.groups()[1:])
    page = f"{base}/full/1200,/0/default.jpg"
    context = f"{base}/{x},{max(0, y - 3 * h)},{w},{7 * h}/full/0/default.jpg"
    return f'<a href="{context}" target="_blank">context</a> · <a href="{page}" target="_blank">page</a>'


def row_html(h: dict, show_grade: bool = False) -> str:
    e = html.escape
    flag = h.get("flag") or ""
    badge = (f' <span class="flag{" look" if flag in ("SAME NAME", "SURNAME") else ""}">{e(flag)}</span>'
             if flag and not flag.startswith("OTHER STREET") else "")
    if flag.startswith("OTHER STREET"):
        badge = f' <span class="flag">{e(flag[len("OTHER STREET "):].strip("()"))}</span>'
    if h.get("place"):     # how it was decided: the line's marker, or the directory's own place
        why = f"marked {h['marker']}" if h["marker"] else "no marker: the directory's own place"
        label = h["place"] + (f" · {h['marker']}" if h["marker"] else "")
        badge = f' <span class="flag" title="{e(why)}">{e(label)}</span>' + badge
    grade = f'<span class="flag">{e(h["grade"])}</span> ' if show_grade and h.get("grade") else ""
    img = ""
    if h.get("crop"):      # LAZY_JS sets src from data-src once on screen, data-fallback on error
        img = (f'<img data-src="{e(resize(h["crop"], ",64", "64,"))}" '
               f'data-fallback="{e(resize(h["crop"], "max", "max"))}" alt="line image">')
    name = h.get("name_resolved") or "(no name read)"
    occ = f' <span class="meta">{e(h["occupation_role"])}</span>' if h.get("occupation_role") else ""
    return (f'<tr><td class="y">{h["year"] or ""}</td><td><div class="name">{e(name)}{occ}</div>{img}'
            f'<div class="raw">{e(h["raw_line"] or "")}</div>'
            f'<div class="meta">{grade}{e(h.get("label") or h["volume"])} · {e(h["record_id"])} · '
            f'{links(h.get("crop"))}{badge}</div></td></tr>')


def render(res: dict, places: list) -> str:
    e = html.escape
    hidden = collections.Counter(h["place"] for h in res["hits"] if h["place"] not in places)
    shown_hits = [h for h in res["hits"] if h["place"] in places]
    other = [h for h in shown_hits if h["flag"].startswith("OTHER STREET")]
    hits = [h for h in shown_hits if not h["flag"].startswith("OTHER STREET")]
    counts = {g: sum(h["grade"] == g for h in hits) for g in fa.GRADES}
    out = [f'<p><b>{len(hits):,} lines</b> in {res["seconds"]:.1f} s, from '
           f'{res["candidates"]:,} holding a spelling below. '
           + " · ".join(f"{g} {n:,}" for g, n in counts.items() if n)
           + (f" · another street {len(other):,}" if other else "")
           + (" · not shown, in " + ", ".join(f"{p} {n:,}" for p, n in hidden.items()) if hidden else "")
           + "</p>",
           '<p class="terms">Street spellings searched: '
           + e(", ".join(f"{t} ({n:,})" for t, n in res["streets"][:30]))
           + (" …" if len(res["streets"]) > 30 else "")
           + ("<br>Not searched, common enough to be another street: "
              + e(", ".join(f"{t} ({n:,})" for t, n in res["dropped"])) if res["dropped"] else "")
           + "<br>Number forms: " + e(", ".join(f"{t} ({n:,})" for t, n in res["numbers"])) + "</p>"]
    if not hits:
        out.append("<p>Nothing at this address. Try a larger spelling distance, or drop the street "
                   "type" + (", or see the same number on another street below" if other else "")
                   + ".</p>")
    for g in fa.GRADES:
        rows = [h for h in hits if h["grade"] == g]
        if not rows:
            continue
        if g == "near":
            rows.sort(key=lambda h: h["flag"] not in ("SAME NAME", "SURNAME"))
            shown = rows[:NEAR_SHOWN]
            more = f" (first {NEAR_SHOWN}, flagged first)" if len(rows) > NEAR_SHOWN else ""
            out.append(f'<details><summary><b>near: {len(rows):,}</b>{more}. {e(ABOUT[g])}</summary>'
                       f'<table class="hits">{"".join(row_html(h) for h in shown)}</table></details>')
        else:
            out.append(f'<h3>{g}: {len(rows):,}</h3><p class="terms">{e(ABOUT[g])}</p>'
                       f'<table class="hits">{"".join(row_html(h) for h in rows)}</table>')
    if other:
        other.sort(key=lambda h: (fa.GRADES.index(h["grade"]), h["year"] or 0))
        shown = other[:NEAR_SHOWN]
        out.append(f'<details{" open" if not hits else ""}><summary><b>Another street: '
                   f'{len(other):,}</b>. The same number and name with another direction or type '
                   f'(E 110th for W 110th, Lefferts av for Lefferts pl): a different street, not a '
                   f'misreading.</summary><table class="hits">'
                   f'{"".join(row_html(h, True) for h in shown)}</table></details>')
    names = {" ".join(fa.name_of(h)) for h in hits}      # residents found in the places shown
    people = {n: rows for n, rows in res["people"].items() if n in names}
    if people:
        out.append("<h3>The residents, in every volume</h3><p class='terms'>A year whose line "
                   "reads another address, or is missing, may be a misreading.</p>")
        for name, rows in people.items():
            out.append(f'<details open><summary><b>{e(name.title())}</b>: {len(rows)} lines</summary>'
                       f'<table class="hits">{"".join(row_html(p, True) for p in rows)}</table></details>')
    return "".join(out)


MATCH_COLUMNS = ["grade", "flag", "place", "place_marker", "year", "directory", "volume",
                 "record_id", "name_resolved", "occupation_role", "matched", "raw_line",
                 "address_resolved", "home_address_resolved", "line_image", "page_image"]
TRACE_COLUMNS = ["traced_name", "year", "directory", "volume", "record_id", "gives_address",
                 "name_resolved", "occupation_role", "raw_line", "address_resolved",
                 "home_address_resolved", "line_image", "page_image"]


def page_image(crop: str) -> str:
    m = re.match(r"(https://iiif\.archive\.org/iiif/[^/]+)/", crop or "")
    return f"{m.group(1)}/full/1200,/0/default.jpg" if m else ""


def write_csv(address: str, kind: str, columns: list, rows: list) -> str:
    """A CSV of `rows` in a fresh temporary folder (Gradio serves it from there), named after
    the search: 155-franklin_matches.csv."""
    slug = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    path = Path(tempfile.mkdtemp(prefix="address-")) / f"{slug}_{kind}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(path)


def exports(res: dict, places: list) -> tuple:
    """The matches shown (the place filter applied) and the resident trace, as CSV paths."""
    shown = [h for h in res["hits"] if h["place"] in places]
    matches = [dict(h, place_marker=h["marker"], directory=h.get("label"), matched=h["how"],
                    line_image=h.get("crop"), page_image=page_image(h.get("crop")))
               for h in shown]
    names = {" ".join(fa.name_of(h)) for h in shown if h["grade"] != "near"}
    trace = [dict(p, traced_name=name, directory=p.get("label"), gives_address=p["grade"] or "no",
                  line_image=p.get("crop"), page_image=page_image(p.get("crop")))
             for name, rows in res["people"].items() if name in names for p in rows]
    return (write_csv(res["address"], "matches", MATCH_COLUMNS, matches) if matches else None,
            write_csv(res["address"], "residents", TRACE_COLUMNS, trace) if trace else None)


def search(address: str, dist: int, people: bool, places: list):
    """The results page, then the two downloads (each hidden when there is nothing in it)."""
    hide = gr.DownloadButton(visible=False)
    if not (address or "").strip():
        return "", hide, hide
    try:
        res = records.find(address.strip(), int(dist), people)
    except SystemExit as err:                     # find_address.parse's message for a bad address
        return f"<p>{html.escape(str(err))}</p>", hide, hide
    matches, trace = exports(res, places or [])
    return (render(res, places or []),
            gr.DownloadButton(value=matches, visible=bool(matches)),
            gr.DownloadButton(value=trace, visible=bool(trace)))


with gr.Blocks(title="City directory address finder") as demo:
    gr.Markdown(
        "## City directory address finder\n"
        f"Every line in {records.volumes} New York and Brooklyn city directories "
        f"({records.rows:,} lines) that may give an address, including the ones the OCR misread: "
        "a misspelled street, a number in look-alike characters, or an address split across "
        "two lines. Each line shows its image from the Internet Archive scan, to check against.")
    with gr.Row():
        address = gr.Textbox(label="Address", placeholder="155 Franklin", scale=3)
        dist = gr.Slider(1, 3, value=2, step=1, label="Street spelling distance", scale=1)
        people = gr.Checkbox(label="Trace the residents", value=False, scale=1)
    places = gr.CheckboxGroup(
        PLACES, value=PLACES, label="Where the address is",
        info="A place printed after the address decides (Bklyn, Mhtn, N. Y., N J); without one, "
             "it is the directory's own city. Trow's lists Brooklyn homes marked Bklyn; Brooklyn's "
             "directories mark New York addresses N. Y. or Mhtn. Before 1898 \"Manhattan\" is the "
             "City of New York.")
    go = gr.Button("Search", variant="primary")
    # 155 Franklin: 20 lines 1845-1912, and Petzholt's laundry at 165 in 1906, 155 after.
    # 62 Euclid av: "Euelid" (1912), and Keiser August at "02 Euclid av" (1906), 62 elsewhere.
    gr.Examples([["155 Franklin"], ["62 Euclid av"], ["269 Broadway"]], inputs=[address])
    with gr.Row():
        get_matches = gr.DownloadButton("Download the matches (CSV)", visible=False, size="sm")
        get_trace = gr.DownloadButton("Download the resident trace (CSV)", visible=False, size="sm")
    result = gr.HTML()
    # Clear first: gr.HTML patches the old DOM node by node, so a new search would reuse the
    # old <img> elements, which keep showing the old line until IA serves the new one
    hidden = (gr.DownloadButton(visible=False), gr.DownloadButton(visible=False))
    for trigger in (go.click, address.submit, places.change):
        trigger(lambda: ('<p class="terms">Searching…</p>', *hidden), None,
                [result, get_matches, get_trace]).then(
            search, [address, dist, people, places], [result, get_matches, get_trace])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=int(os.environ.get("PORT", 7860)), css=CSS,
                head=LAZY_JS)
