"""How the records browser draws its pages (browse/README.md). Display only: the database keeps
the files' values.

    crop          `show` loads the line's image into the row, `open` opens it full size. No image
                  is fetched until asked for: one row's, or every row on the page with the
                  "Show all line images" button above the table
    canvas        a link to the whole leaf's image
    leaf          a link to every line of that leaf, in reading order
    ditto_source  a link to the line the surname was carried from

in the volumes table, a volume's `records` count links to its records and `ia_url` to the item;
and, on every table and row page:

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


def _resize(url: str, size_upright: str, size_turned: str) -> str:
    """`<IIIF>/<id>/<region>/<size>/<rotation>/default.jpg` with another size. IIIF scales before
    it rotates, so a turned line (Trow 1915/1917) is sized on its width."""
    parts = url.split("/")
    if len(parts) < 4 or parts[-1] != "default.jpg":
        return url
    parts[-3] = size_turned if parts[-2] in ("90", "270") else size_upright
    return "/".join(parts)


@hookimpl
def extra_body_script(view_name, database, table, datasette):
    if view_name not in ("table", "row"):
        return ""
    order = datasette.metadata("column_order", database=database, table=table) if table else None
    return PAGE_SCRIPT.replace("%ORDER%", json.dumps(order or []).replace("</", "<\\/"))


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
        return Markup(f'<span class="line-crop" data-thumb="{escape(thumb)}" '
                      f'data-big="{escape(big)}"><button type="button" class="line-crop-show">'
                      f'show</button> <a href="{escape(big)}" target="_blank" rel="noopener">'
                      f'open</a></span>')
    if column == "canvas" and str(value).startswith(IIIF) and value.endswith("/canvas"):
        page = value[: -len("/canvas")] + "/full/1200,/0/default.jpg"
        return Markup(f'<a href="{escape(page)}" target="_blank" rel="noopener">page image</a>')
    if column == "leaf" and _get(row, "volume"):
        params = {"volume": _get(row, "volume"), "leaf": value, "_size": LEAF_PAGE}
        if _get(row, "run"):
            params["run"] = _get(row, "run")
        return _filter_link(datasette, database, table, str(value), **params)
    if column == "ditto_source":
        params = {"record_id": value}
        if _get(row, "run"):
            params["run"] = _get(row, "run")
        return _filter_link(datasette, database, table, str(value), **params)
    return None
