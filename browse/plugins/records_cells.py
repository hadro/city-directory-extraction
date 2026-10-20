"""How the records browser draws its pages (browse/README.md). Display only: the database keeps
the files' values.

    crop          `show` loads the line's image into the row, `open` opens it full size, `page`
                  opens the page viewer (below). No image is fetched until asked for: one row's,
                  or every row on the page with the "Show all line images" button
    canvas        the page viewer too
    leaf          a link to every line of that leaf, in reading order
    ditto_source  a link to the line the surname was carried from, with that line's text under
                  it -- where a wrong surname came from, at a glance

in the volumes table, a volume's `records` count links to its records and `ia_url` to the item;
at /-/line-page, a record's whole page with the line's box drawn on it (line_page); and, on
every table and row page:

    column order  the table's `column_order` in metadata.yml first (after Link and rowid), the
                  rest in the table's own order. Edit it and reload the page: serve.sh runs
                  Datasette with --reload. A ?_col= in the URL is an order already chosen, and
                  is left alone (Datasette keeps _col's order, CSV and JSON exports included)
    descriptions  folded into a closed "Column descriptions" toggle. Datasette 0.65 lists them
                  in full above the table, a screen and a half; each is also in its column's
                  header menu

Thumbnails ask IA for `,64` (64 px high), and for `max` if that fails. IA's image server hangs on
some requests -- a 504 after ~60 s, again on every retry -- while the same box at another size
comes back in ~1 s, and which size hangs differs line to line: probed 2026-10-20, `full` (what
assemble_records.py writes into `crop`) hung on micro_IABROOKLYN_0001 5:1 and `,64` did not;
`,64` hung on brooklynnewyorkc19123broo 113:45 and `max` did not; `max` hung on 113:56 and `,64`
did not. A browser shows the 504 as an error, so the fallback fires, but only after that wait.
"""
import json
from urllib.parse import urlencode

from datasette import hookimpl
from markupsafe import Markup, escape

IIIF = "https://iiif.archive.org/iiif/"
LEAF_PAGE = 200          # lines per page in the leaf view; a dense leaf has ~150

PAGE_SCRIPT = """
(function () {
  var ORDER = %ORDER%;
  document.head.insertAdjacentHTML("beforeend", "<style>" +
    "td.col-raw_line { min-width: 22em } td.col-name_resolved { min-width: 10em }" +
    "td.col-title { min-width: 24em } td.col-catalog_notes { min-width: 40em }" +
    "td.col-ia_collections { min-width: 18em } td.col-reocr { min-width: 18em }" +
    "td.col-ia_publisher, td.col-ia_ocr { min-width: 11em }" +
    ".line-crop { white-space: nowrap } .line-crop button { font-size: 0.85em }" +
    "td.col-ditto_source { min-width: 16em } .carried-from { color: #666; font-size: 0.85em }" +
    ".line-crop img { max-height: 32px; max-width: 36em; display: block }" +
    ".line-crop-all { margin: 0.6em 0 }</style>");

  document.querySelectorAll("dl.column-descriptions").forEach(function (dl) {
    var d = document.createElement("details"), s = document.createElement("summary");
    s.textContent = "Column descriptions";
    dl.parentNode.insertBefore(d, dl);
    d.appendChild(s);
    d.appendChild(dl);
  });

  var table = document.querySelector("table.rows-and-columns");
  if (table && ORDER.length && !new URLSearchParams(location.search).has("_col")) {
    var ths = Array.from(table.tHead.rows[0].cells);
    var name = function (i) { return ths[i].dataset.column; };
    var all = ths.map(function (_, i) { return i; });
    var rank = new Map();         // a column listed twice goes where it is listed first
    ORDER.forEach(function (c, k) { if (!rank.has(c)) rank.set(c, k); });
    var lead = all.filter(function (i) {
      return name(i) === "Link" || ths[i].dataset.isPk === "1";
    });
    var picked = all.filter(function (i) { return rank.has(name(i)) && lead.indexOf(i) < 0; })
      .sort(function (a, b) { return rank.get(name(a)) - rank.get(name(b)); });
    var perm = lead.concat(picked, all.filter(function (i) {
      return lead.indexOf(i) < 0 && picked.indexOf(i) < 0;
    }));
    Array.from(table.rows).forEach(function (tr) {
      var cells = Array.from(tr.cells);
      if (cells.length === perm.length) perm.forEach(function (i) { tr.appendChild(cells[i]); });
    });
  }

  var crops = Array.from(document.querySelectorAll(".line-crop"));
  var unshown = new Map(crops.map(function (s) { return [s, s.innerHTML]; }));
  function show(span) {
    if (span.querySelector("img")) return;
    var a = document.createElement("a"), img = document.createElement("img");
    a.href = span.dataset.big; a.target = "_blank"; a.rel = "noopener";
    img.alt = "line image"; img.loading = "lazy";
    img.onerror = function () { img.onerror = null; img.src = span.dataset.big; };
    img.src = span.dataset.thumb;
    a.appendChild(img);
    span.replaceChildren(a);
  }
  function hide(span) { span.innerHTML = unshown.get(span); }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".line-crop-show");
    if (b) show(b.closest(".line-crop"));
  });
  if (table && crops.length > 1) {
    var on = false, toggle = document.createElement("button");
    var label = function () {
      toggle.textContent = on ? "Hide line images" : "Show all " + crops.length + " line images";
    };
    toggle.type = "button"; toggle.className = "line-crop-all";
    toggle.onclick = function () { on = !on; crops.forEach(on ? show : hide); label(); };
    label();
    var wrap = table.closest(".table-wrapper") || table;
    wrap.parentNode.insertBefore(toggle, wrap);
  }
})();
"""


def _get(row, key):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _resize(url: str, size_upright: str, size_turned: str, region: str | None = None) -> str:
    """`<IIIF>/<id>/<region>/<size>/<rotation>/default.jpg` with another size (and region, if
    given). IIIF scales before it rotates, so a turned line (Trow 1915/1917) is sized on its
    width."""
    parts = url.split("/")
    if len(parts) < 5 or parts[-1] != "default.jpg":
        return url
    parts[-3] = size_turned if parts[-2] in ("90", "270") else size_upright
    if region:
        parts[-4] = region
    return "/".join(parts)


PAGE_WIDTH = 1400        # the direct whole-page links: enough to read the column the line sits in

# The page viewer (/-/line-page): the line's whole page with its box drawn on it. IA's image
# server fails a given URL at random -- probed 2026-10-20 over ten pages, `1400,` returned 6,
# `1200,` 7 and `max` 8, each failure a fast 403/500 or a ~45 s hang, and every page came back at
# SOME size -- so the viewer walks a list of sizes and gives each PAGE_TRY_S before moving on.
# Percentage sizes make the scale exact, which is what puts the box in the right place.
PAGE_PCTS = (40, 45, 35, 50, 30)
PAGE_TRY_S = 10

VIEWER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%TITLE%</title>
<style>
  body { font: 15px/1.4 -apple-system, system-ui, sans-serif; margin: 16px; background: #fafafa;
         color: #222 }
  .line { font-family: ui-monospace, Menlo, monospace; background: #fff; padding: 6px 8px;
          border: 1px solid #ddd; display: inline-block; margin: 4px 0 10px }
  #status { color: #a40; margin: 6px 0 }
  .page { position: relative; display: inline-block; box-shadow: 0 1px 4px rgba(0,0,0,.2) }
  .page img { display: block; max-width: none }
  #mark { position: absolute; display: none; border: 2px solid #d4002a;
          background: rgba(255, 220, 0, .25); box-sizing: border-box; pointer-events: none }
  .direct { color: #666; font-size: 13px; margin: 8px 0 }
  a { color: #1a5fa8 }
</style></head><body>
<div><a href="%RECORD%">%RID%</a> · <a href="%LEAF%">every line of this leaf</a></div>
<div class="line">%RAW%</div>
<div id="status"></div>
<div class="page"><img id="page" alt="the page"><div id="mark"></div></div>
<div class="direct">IA's image server fails some requests; straight to the image:
  %DIRECT%</div>
<script>
(function () {
  var P = %PARAMS%, k = 0, timer = null;
  var img = document.getElementById("page"), mark = document.getElementById("mark"),
      status = document.getElementById("status");
  function place(pct) {
    if (P.rot !== "0" || !P.box) return;      // a turned page: no box (its frame differs)
    var s = pct / 100, b = P.box;
    mark.style.left = b[0] * s - 4 + "px"; mark.style.top = b[1] * s - 4 + "px";
    mark.style.width = b[2] * s + 8 + "px"; mark.style.height = b[3] * s + 8 + "px";
    mark.style.display = "block";
    mark.scrollIntoView({block: "center", inline: "center"});
  }
  function next() {
    clearTimeout(timer);
    if (k >= P.pcts.length) {
      status.textContent = "IA did not return the page at any size; try the links below.";
      return;
    }
    var pct = P.pcts[k++];
    status.textContent = "loading the page at " + pct + "%" + (k > 1 ? " (the last size failed)" : "") + "…";
    img.onload = function () { clearTimeout(timer); status.textContent = ""; place(pct); };
    img.onerror = next;
    timer = setTimeout(next, P.tryMs);
    img.src = P.base + "/full/pct:" + pct + "/" + P.rot + "/default.jpg";
  }
  next();
})();
</script></body></html>"""


async def line_page(request, datasette):
    """/-/line-page?db=<database>&record_id=<id>[&run=<run>]: the record's whole page, its box
    drawn on it."""
    from datasette.utils.asgi import Response
    db_name, rid, run = (request.args.get(k) for k in ("db", "record_id", "run"))
    try:
        db = datasette.get_database(db_name)
    except KeyError:
        return Response.html("<p>No such database.</p>", status=404)
    sql = ("SELECT record_id, volume, leaf, run, raw_line, crop FROM records WHERE record_id = ?"
           + (" AND run = ?" if run else "") + " LIMIT 1")
    row = (await db.execute(sql, [rid, run] if run else [rid])).first()
    if not row or not str(row["crop"] or "").startswith(IIIF):
        return Response.html("<p>No such record, or it has no image.</p>", status=404)
    parts = row["crop"].split("/")
    base, region, rot = "/".join(parts[:-4]), parts[-4], parts[-2]
    try:
        box = [int(v) for v in region.split(",")]
    except ValueError:
        box = None
    records = datasette.urls.table(db_name, "records")
    record_url = records + "?" + urlencode({"record_id": row["record_id"], "run": row["run"]})
    leaf_url = records + "?" + urlencode({"volume": row["volume"], "leaf": row["leaf"],
                                          "run": row["run"], "_size": LEAF_PAGE})
    turned = rot in ("90", "270")
    direct = " · ".join(
        f'<a href="{escape(base)}/full/{escape(s)}/{escape(rot)}/default.jpg" target="_blank" '
        f'rel="noopener">{escape(label)}</a>'
        for label, s in ((f"{PAGE_WIDTH} px", f",{PAGE_WIDTH}" if turned else f"{PAGE_WIDTH},"),
                         ("1200 px", ",1200" if turned else "1200,"), ("full size", "max")))
    params = json.dumps({"base": base, "rot": rot, "box": box, "pcts": list(PAGE_PCTS),
                         "tryMs": PAGE_TRY_S * 1000}).replace("</", "<\\/")
    html = (VIEWER.replace("%TITLE%", str(escape(f"{row['record_id']} — page")))
            .replace("%RECORD%", str(escape(record_url))).replace("%LEAF%", str(escape(leaf_url)))
            .replace("%RID%", str(escape(row["record_id"])))
            .replace("%RAW%", str(escape(row["raw_line"] or "")))
            .replace("%DIRECT%", direct).replace("%PARAMS%", params))
    return Response.html(html)


@hookimpl
def register_routes():
    return [(r"^/-/line-page$", line_page)]


@hookimpl
def extra_body_script(view_name, database, table, datasette):
    if view_name not in ("table", "row"):
        return ""
    order = datasette.metadata("column_order", database=database, table=table) if table else None
    return PAGE_SCRIPT.replace("%ORDER%", json.dumps(order or []).replace("</", "<\\/"))


def _page_link(datasette, database, row) -> str | None:
    rid = _get(row, "record_id")
    if not rid:
        return None
    params = {"db": database, "record_id": rid}
    if _get(row, "run"):
        params["run"] = _get(row, "run")
    return datasette.urls.path("/-/line-page") + "?" + urlencode(params)


def _filter_link(datasette, database, table, text, **params) -> Markup:
    href = datasette.urls.table(database, table) + "?" + urlencode(params)
    return Markup(f'<a href="{escape(href)}">{escape(text)}</a>')


@hookimpl
def render_cell(row, value, column, table, database, datasette):
    if value in (None, ""):
        return None
    if table == "volumes":
        if column == "records" and _get(row, "volume"):
            return _filter_link(datasette, database, "records", f"{value:,}",
                                volume=_get(row, "volume"))
        if column == "ia_url":
            return Markup(f'<a href="{escape(value)}" target="_blank" rel="noopener">'
                          f'archive.org</a>')
        return None
    if table != "records":
        return None
    if column == "crop" and str(value).startswith(IIIF):
        thumb, big = _resize(value, ",64", "64,"), _resize(value, "max", "max")
        page = _page_link(datasette, database, row)
        return Markup(f'<span class="line-crop" data-thumb="{escape(thumb)}" '
                      f'data-big="{escape(big)}"><button type="button" class="line-crop-show">'
                      f'show</button> <a href="{escape(big)}" target="_blank" rel="noopener">'
                      f'open</a>' + (f' <a href="{escape(page)}" target="_blank" '
                                     f'rel="noopener" title="the whole page, this line outlined">'
                                     f'page</a>' if page else "") + '</span>')
    if column == "canvas" and str(value).startswith(IIIF):
        page = _page_link(datasette, database, row)
        if page:
            return Markup(f'<a href="{escape(page)}" target="_blank" rel="noopener">page image</a>')
    if column == "leaf" and _get(row, "volume"):
        params = {"volume": _get(row, "volume"), "leaf": value, "_size": LEAF_PAGE}
        if _get(row, "run"):
            params["run"] = _get(row, "run")
        return _filter_link(datasette, database, table, str(value), **params)
    if column == "ditto_source":
        run = _get(row, "run")
        link = _filter_link(datasette, database, table, str(value),
                            **({"record_id": value, "run": run} if run else {"record_id": value}))

        async def with_source_line():
            # the carried-from line's own text, so a surname planted by ad copy ("millions--
            # Try them.") shows without a click. One indexed lookup per cell.
            sql = "SELECT raw_line FROM records WHERE record_id = ?" + (" AND run = ?" if run
                                                                        else "") + " LIMIT 1"
            res = await datasette.get_database(database).execute(
                sql, [value, run] if run else [value])
            src = res.first()
            text = (src["raw_line"] or "") if src else ""
            return Markup(f'{link}<br><span class="carried-from">{escape(text[:70])}</span>')
        return with_source_line()
    return None
