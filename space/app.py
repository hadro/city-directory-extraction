"""
A Gradio page over space/search.py: every line in the city directories that may give an
address, OCR misreadings included, each with its line image from the Internet Archive. A second
tab, Browse (space/browse.py), searches every text column and narrows by facets.

    uv run --with-requirements space/requirements.txt python space/app.py     # http://127.0.0.1:7860

RECORDS_PARQUET names the records file (default: a records.parquet beside this file, as on the
test Space, else data/space/records.parquet, which space/build_parquet.py makes).
"""
from __future__ import annotations

import collections
import csv
import html
import os
import re
import tempfile
import urllib.parse
from pathlib import Path

import gradio as gr

import browse
import where
from search import PLACES, TRACE_YEARS, Records, fa

HERE = Path(__file__).resolve().parent
# deployed, the records sit beside this file; in the repo, build_parquet.py's output
PARQUET = os.environ.get("RECORDS_PARQUET") or str(
    HERE / "records.parquet" if (HERE / "records.parquet").exists()
    else HERE.parent / "data" / "space" / "records.parquet")
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
details.aside { margin: 4px 0 12px 16px; color: var(--body-text-color-subdued); }
.where { display: flex; flex-wrap: wrap; gap: 16px; }
.where > div { flex: 1 1 320px; min-width: 0; }
.where iframe { width: 100%; height: 260px; border: 1px solid var(--border-color-primary); }
.hits mark { background: #fde68a; color: #111; padding: 0 1px; }
"""
# Where the address is today, below each map: the reason the map comes with no claim about the
# line's own building
TODAY = ("Where this address is today, from NYC GeoSearch. Streets were renumbered, renamed and "
         "cut through over the years these directories cover, so for an older line it may not be "
         "the same building, or even the same block.")

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
browser = browse.Browser(records, PARQUET)

try:
    import spaces       # on Hugging Face ZeroGPU, the one Gradio hardware a free account may use
except ImportError:
    spaces = None
if spaces:
    @spaces.GPU
    def _never_called():
        """ZeroGPU stops a Space with no GPU function ("No @spaces.GPU function detected during
        startup"); the search uses none, so this one is never called."""


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


def render(res: dict, places: list, narrow: bool = True) -> str:
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
                   "reads another address, or is missing, may be a misreading."
                   + (f" Narrowed: a line whose home is in another place than the person's lines "
                      f"at the address, or more than {TRACE_YEARS} years from them, is probably a "
                      f"namesake and is set aside below each person." if narrow else "")
                   + "</p>")
        for name, rows in people.items():
            kept = [p for p in rows if not (narrow and p["left_out"])]
            out_rows = [p for p in rows if narrow and p["left_out"]]
            out.append(f'<details open><summary><b>{e(name.title())}</b>: {len(kept)} lines'
                       + (f" ({len(out_rows)} set aside)" if out_rows else "") + '</summary>'
                       f'<table class="hits">{"".join(row_html(p, True) for p in kept)}</table>')
            if out_rows:
                out.append(f'<details class="aside"><summary>{len(out_rows)} set aside, probably '
                           f'namesakes</summary><table class="hits">'
                           f'{"".join(row_html(dict(p, flag="SET ASIDE: " + p["left_out"]), True) for p in out_rows)}'
                           f'</table></details>')
            out.append("</details>")
    return "".join(out)


def osm_search(text: str) -> str:
    return "https://www.openstreetmap.org/search?query=" + urllib.parse.quote(text)


def where_html(res: dict | None, places: list) -> str:
    """A map of the address today for each borough it is found in, or why there is none."""
    if not res:
        return ""
    e = html.escape
    out = []
    for w in where.locate(res, places or []):
        named = w["label"].split(",")[0].title() if "lat" in w else w["query"]   # GeoSearch's own
        head = f'<p><b>{e(named)}, {e(w["place"])}, today</b></p>'
        if "error" in w:
            out.append(f'<div>{head}<p class="terms">NYC GeoSearch did not answer. '
                       f'<a href="{osm_search(w["query"] + ", " + w["place"])}" target="_blank">'
                       f'Search OpenStreetMap ↗</a></p></div>')
        elif "lat" in w:
            lat, lon = w["lat"], w["lon"]
            bbox = ",".join(f"{v:.6f}"
                            for v in (lon - 0.004, lat - 0.003, lon + 0.004, lat + 0.003))
            embed = (f"https://www.openstreetmap.org/export/embed.html?bbox={bbox}"
                     f"&layer=mapnik&marker={lat},{lon}")
            big = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=18/{lat}/{lon}"
            sv = w.get("street_view")
            sv = (f' · <a href="{e(sv["url"])}" target="_blank">Street View'
                  f'{" (" + e(sv["date"]) + ")" if sv["date"] else ""} ↗</a>' if sv else "")
            out.append(f'<div>{head}<iframe src="{e(embed)}" loading="lazy" '
                       f'title="{e(w["label"])} on OpenStreetMap"></iframe>'
                       f'<p class="terms">{e(TODAY)} '
                       f'<a href="{e(big)}" target="_blank">Larger map ↗</a>{sv}</p></div>')
        elif w["streets"]:
            out.append(f'<div>{head}<p class="terms">{e(w["place"])} has more than one street by '
                       f'that name today, and the lines found don\'t say which: '
                       + ", ".join(f'<a href="{osm_search(s)}" target="_blank">'
                                   f'{e(s.split(",")[0].title())}</a>' for s in w["streets"])
                       + '.</p></div>')
        else:
            out.append(f'<div>{head}<p class="terms">No such address in {e(w["place"])} today: the '
                       f'street may have been renamed or renumbered, or be gone. '
                       f'<a href="{osm_search(w["query"] + ", " + w["place"])}" target="_blank">'
                       f'Search OpenStreetMap ↗</a></p></div>')
    return f'<div class="where">{"".join(out)}</div>' if out else ""


MATCH_COLUMNS = ["grade", "flag", "place", "place_marker", "year", "directory", "volume",
                 "record_id", "name_resolved", "occupation_role", "matched", "raw_line",
                 "address_resolved", "home_address_resolved", "line_image", "page_image"]
TRACE_COLUMNS = ["traced_name", "year", "directory", "volume", "record_id", "gives_address",
                 "left_out", "place", "place_marker", "name_resolved", "occupation_role",
                 "raw_line", "address_resolved", "home_address_resolved", "line_image",
                 "page_image"]


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
    # every traced line, the set-aside ones too: `left_out` says why, so a reader can filter
    trace = [dict(p, traced_name=name, directory=p.get("label"), gives_address=p["grade"] or "no",
                  place_marker=p["marker"], line_image=p.get("crop"),
                  page_image=page_image(p.get("crop")))
             for name, rows in res["people"].items() if name in names for p in rows]
    return (write_csv(res["address"], "matches", MATCH_COLUMNS, matches) if matches else None,
            write_csv(res["address"], "residents", TRACE_COLUMNS, trace) if trace else None)


def search(address: str, dist: int, people: bool, places: list, narrow: bool = True):
    """The results page, then the two downloads (each hidden when there is nothing in it), then
    the result for the map to be drawn from."""
    hide = gr.DownloadButton(visible=False)
    if not (address or "").strip():
        return "", hide, hide, None
    try:
        res = records.find(address.strip(), int(dist), people)
    except SystemExit as err:                     # find_address.parse's message for a bad address
        return f"<p>{html.escape(str(err))}</p>", hide, hide, None
    matches, trace = exports(res, places or [])
    return (render(res, places or [], narrow),
            gr.DownloadButton(value=matches, visible=bool(matches)),
            gr.DownloadButton(value=trace, visible=bool(trace)),
            {"address": res["address"], "hits": [
                {k: h.get(k) for k in ("place", "grade", "flag", "how", *fa.FIELDS)}
                for h in res["hits"]]})


def marked(text: str, marks: set) -> str:
    """The text escaped, each whitespace token holding a word searched for in <mark>."""
    return "".join(f"<mark>{html.escape(t)}</mark>" if marks & set(re.findall(r"[a-z0-9]+", t.lower()))
                   else html.escape(t) for t in re.split(r"(\s+)", text or ""))


def browse_row(h: dict, marks: set) -> str:
    e = html.escape
    name = marked(h.get("name_resolved") or "", marks) or "(no name read)"
    occ = " ".join(x for x in (h.get("occupation_role"), h.get("employer") and f"({h['employer']})") if x)
    occ = f' <span class="meta">{marked(occ, marks)}</span>' if occ else ""
    where_ = " · ".join(x for x in (marked(h.get("address_resolved"), marks),
                                    h.get("home_address_resolved")
                                    and "h " + marked(h["home_address_resolved"], marks)) if x)
    spouse = f' · spouse {marked(h["spouse_name"], marks)}' if h.get("spouse_name") else ""
    img = ""
    if h.get("crop"):
        img = (f'<img data-src="{e(resize(h["crop"], ",64", "64,"))}" '
               f'data-fallback="{e(resize(h["crop"], "max", "max"))}" alt="line image">')
    page = f'p. {h["printed_page"]} · ' if h.get("printed_page") else ""
    flags = " ".join(f'<span class="flag">{e(x)}</span>' for x in
                     (h.get("role"), "not usable" if h.get("usable") == 0 else "") if x)
    return (f'<tr><td class="y">{h["year"] or ""}</td><td><div class="name">{name}{occ}</div>'
            + (f'<div class="meta">{where_}{spouse}</div>' if where_ or spouse else "")
            + f'{img}<div class="raw">{marked(h["raw_line"], marks)}</div>'
            f'<div class="meta">{e(browser.labels.get(h["volume"], (h["volume"],))[0])} · {page}'
            f'{e(h["record_id"])} · {links(h.get("crop"))} {flags}</div></td></tr>')


def browse_html(res: dict) -> str:
    e = html.escape
    marks = {t for terms in res["spellings"] for t, _ in terms}
    pages = f' · page {res["page"] + 1:,} of {res["pages"]:,}' if res["pages"] > 1 else ""
    out = [f'<p><b>{res["total"]:,} lines</b>{pages} · {res["seconds"]:.1f} s</p>']
    if res["spellings"] and any(len(t) != 1 for t in res["spellings"]):
        out.append('<p class="terms">Words searched: ' + "; ".join(
            ", ".join(f"{e(t)} ({n:,})" for t, n in terms[:12]) + (" …" if len(terms) > 12 else "")
            if terms else "(no such word)" for terms in res["spellings"]) + "</p>")
    if not res["total"]:
        out.append("<p>Nothing found. Try another spelling, a word* for any ending, fewer words, "
                   "or fewer facets.</p>")
    out.append(f'<table class="hits">{"".join(browse_row(h, marks) for h in res["rows"])}</table>')
    return "".join(out)


def facet_choices(f: str, counts: list) -> list:
    shown = (lambda v: browser.labels.get(v, (v,))[0]) if f == "volume" else (lambda v: v)
    return [(f"{shown(v) if v else '(blank)'} ({n:,})", v) for v, n in counts]


def browse_args(query, in_col, dist, y0, y1, usable, sort, *chosen):
    return dict(query=query, in_col=in_col, dist=int(dist or 0),
                chosen=dict(zip(browser.facets, chosen)), years=(y0, y1), usable=usable, sort=sort)


def browse_run(page, *args):
    """The results, the page number, each facet's choices with counts, and Previous/Next."""
    res = browser.browse(page=max(0, int(page or 0)), **browse_args(*args))
    chosen = args[7:]
    return (browse_html(res), res["page"],
            *[gr.Dropdown(choices=facet_choices(f, res["facets"][f]), value=v)
              for f, v in zip(browser.facets, chosen)],
            gr.Button(interactive=res["page"] > 0),
            gr.Button(interactive=res["page"] + 1 < res["pages"]))


def browse_csv(*args):
    rows = browser.export(**browse_args(*args))
    if not rows:
        return gr.File(visible=False)
    rows = [dict(h, label=browser.labels.get(h["volume"], ("",))[0], line_image=h.get("crop"),
                 page_image=page_image(h.get("crop"))) for h in rows]
    cols = [c for c in rows[0] if c != "crop"]
    return gr.File(value=write_csv(args[0] or "all", "lines", cols, rows), visible=True)


with gr.Blocks(title="City directories") as demo:
    with gr.Tab("Address finder"):
        gr.Markdown(
            "## City directory address finder\n"
            f"Every line in {records.volumes} New York and Brooklyn city directories "
            f"({records.rows:,} lines) that may give an address, including the ones the OCR misread: "
            "a misspelled street, a number in look-alike characters, or an address split across "
            "two lines. Each line shows its image from the Internet Archive scan, to check against.")
        with gr.Row():
            address = gr.Textbox(label="Address", placeholder="155 Franklin", scale=3)
            dist = gr.Slider(1, 3, value=2, step=1, label="Street spelling distance", scale=1)
            with gr.Column(scale=1, min_width=160):
                people = gr.Checkbox(label="Trace the residents", value=False)
                narrow = gr.Checkbox(label=f"Set aside likely namesakes (another place, or "
                                           f"over {TRACE_YEARS} years away)", value=True)
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
        found = gr.State()
        today = gr.HTML()       # after the lines, from GeoSearch, so it never holds them up
        result = gr.HTML()
        # Clear first: gr.HTML patches the old DOM node by node, so a new search would reuse the
        # old <img> elements, which keep showing the old line until IA serves the new one
        hidden = (gr.DownloadButton(visible=False), gr.DownloadButton(visible=False))
        for trigger in (go.click, address.submit, places.change, narrow.change):
            trigger(lambda: ('<p class="terms">Searching…</p>', *hidden, ""), None,
                    [result, get_matches, get_trace, today]).then(
                search, [address, dist, people, places, narrow],
                [result, get_matches, get_trace, found]).then(
                where_html, [found, places], today)

    with gr.Tab("Browse"):
        gr.Markdown(
            "## Browse the lines\n"
            f"All {records.rows:,} lines, in the directories' own order. Search any column, "
            "narrow by year and by the facets (each shows how many lines it would leave), and page "
            "through. End a word with `*` for any ending: `groc*`. A line is *usable* when it "
            "reads as a directory entry with a name.")
        with gr.Row():
            b_query = gr.Textbox(label="Search", placeholder="smith grocer", scale=3,
                                 info="Every word must be in the line.")
            b_in = gr.Dropdown(list(browser.in_columns), value="any column", label="Search in",
                               scale=1)
            b_dist = gr.Radio([("exact", 0), ("1 letter off", 1), ("2 letters off", 2)], value=0,
                              label="Spelling", info="Off by a letter or two, for the OCR's "
                                                     "misreadings (words of 4 letters or more)",
                              scale=2)
        with gr.Row():
            b_y0 = gr.Number(label="From year", info="0: any", precision=0)
            b_y1 = gr.Number(label="To year", info="0: any", precision=0)
            b_usable = gr.Checkbox(label="Usable lines only", value=False)
            b_sort = gr.Dropdown(list(browse.SORTS), value="directory order", label="Order")
        with gr.Row():
            b_go = gr.Button("Search", variant="primary")
            b_clear = gr.Button("Clear")
        start = browser.browse()
        with gr.Row():
            with gr.Column(scale=1, min_width=260):
                b_facets = [gr.Dropdown(choices=facet_choices(f, start["facets"][f]), value=[],
                                        multiselect=True, label=label,
                                        allow_custom_value=f == "occupation")
                            for f, (label, *_) in browser.facets.items()]
            with gr.Column(scale=3):
                b_result = gr.HTML()
                with gr.Row():
                    b_prev = gr.Button("← Previous", size="sm", interactive=False)
                    b_next = gr.Button("Next →", size="sm")
                    b_get = gr.Button(f"Download these lines (CSV, the first "
                                      f"{browse.CSV_MAX:,})", size="sm")
                b_file = gr.File(visible=False, label="CSV")
        b_page = gr.State(0)
        b_inputs = [b_query, b_in, b_dist, b_y0, b_y1, b_usable, b_sort, *b_facets]
        b_outputs = [b_result, b_page, *b_facets, b_prev, b_next]
        searching = lambda: ('<p class="terms">Searching…</p>', gr.File(visible=False))  # noqa: E731
        # a facet's .input, not .change: browse_run sets each facet's choices, which would fire
        # .change again
        for trigger in (b_go.click, b_query.submit, b_y0.submit, b_y1.submit, b_in.input,
                        b_dist.input, b_usable.input, b_sort.input,
                        *(f.input for f in b_facets)):
            trigger(searching, None, [b_result, b_file]).then(
                lambda *a: browse_run(0, *a), b_inputs, b_outputs)
        for button, step in ((b_prev, -1), (b_next, 1)):
            button.click(searching, None, [b_result, b_file]).then(
                lambda page, *a, step=step: browse_run(page + step, *a), [b_page, *b_inputs],
                b_outputs)
        b_clear.click(lambda: ("", "any column", 0, None, None, False, "directory order",
                               *([[]] * len(b_facets))), None, b_inputs).then(
            lambda *a: browse_run(0, *a), b_inputs, b_outputs)
        b_get.click(browse_csv, b_inputs, b_file)
        demo.load(lambda *a: browse_run(0, *a), b_inputs, b_outputs)

if __name__ == "__main__":
    # A Space sets GRADIO_SERVER_NAME=0.0.0.0; an explicit 127.0.0.1 would override it
    demo.launch(server_name=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"), server_port=int(os.environ.get("PORT", 7860)), css=CSS,
                head=LAZY_JS)
