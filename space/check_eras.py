"""
The finder's renumbered-street cases, through the page in headless Chrome (README "Checks for the
old numbers"). Start the app on a port of your own, never serve.sh's 8001:

    PORT=7871 uv run --with-requirements space/requirements.txt python space/app.py
    uv run --with playwright python space/check_eras.py http://127.0.0.1:7871 [dump_dir]

Each case is a fresh page: type the address, press Search, read the headings and notes. With a
dump_dir the result HTML of the cases with no old numbers is written there (seconds blanked), to
diff against another version's page. CHROME names the browser (macOS default below).
"""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
NEW = "As {a}, 1875 on"
OLD = "As {a}, before 1871-75 (renumbered between those directories)"
# The brackets are the built crosswalk's: when a rebuild moves an anchor, a case here moves too.
# address -> the headings the page must print (h2), the number of "Search the range" links, and
# lines it must show in the open (not under "Another street" or "near"): the same person before and
# after, which is the proof an old group is the old number on the old street
CASES = {
    "465 Court st": ([NEW.format(a="465 Court st"), OLD.format(a="643-651 Court st")], 0),
    "462 Court st": ([NEW.format(a="462 Court st"), OLD.format(a="644-696 Court st")], 1),
    "294 Court st": ([NEW.format(a="294 Court st"), OLD.format(a="216 Court st"),
                      OLD.format(a="198-230 Court st")], 1),
    "181 Bridge st": ([NEW.format(a="181 Bridge st"), OLD.format(a="158 Bridge st")], 0),
    "677 Myrtle av": ([NEW.format(a="677 Myrtle av"), OLD.format(a="689-731 Myrtle av"),
                       OLD.format(a="893-967 Myrtle av")], 2),
    "43 Atlantic av": ([NEW.format(a="43 Atlantic av"), OLD.format(a="37 Atlantic st"),
                        OLD.format(a="37-47 Atlantic av"), OLD.format(a="107 Atlantic av")], 0),
    # the old numbers' street is old_street (the crosswalk's street is the registry's id):
    # Fulton's were on Fulton st and on Fulton av
    "11 Fulton st": ([NEW.format(a="11 Fulton st"), OLD.format(a="33 Fulton st")], 0,
                     "Goodwin & Co. manfs. 33 Fulton", "Goodwin & Co. washing fluid, 11 Fulton"),
    "985 Fulton st": ([NEW.format(a="985 Fulton st"), OLD.format(a="1173 Fulton av")], 0,
                      "Crawford James R. drugs, 1173 Fulton av", "Crawford James R. clk. h 985 Fulton"),
    # Atlantic's were on Atlantic st (renamed) and on Atlantic av
    "13 Atlantic av": ([NEW.format(a="13 Atlantic av"), OLD.format(a="3 Atlantic st"),
                        OLD.format(a="3 Atlantic av")], 0,
                       "Valentine Edward H. grocer, h 3 Atlantic",
                       "Valentine Edward H. groceries, 13 Atlantic av"),
    # one Baltic number was two houses before 1875; E. and W. Baltic lines after it are Baltic's
    "146 Baltic st": ([NEW.format(a="146 Baltic st"), OLD.format(a="96 W Baltic st")], 0,
                      "Bauer Augustus, clerk, h 96 W. Baltic", "Bauer Augustus, printer, 53 Murray, N. Y. h 146 Baltic",
                      "h 146 W. Baltic, B\u2019klyn"),
    "271 Baltic st": ([NEW.format(a="271 Baltic st"), OLD.format(a="1 E Baltic st")], 0,
                      "Dunn Elizabeth, wid. h 1 E. Baltic", "Dunn Elizabeth, wid. John, h 271 Baltic"),
    # Elliott pl is S Elliott pl, typed either way
    "49 Elliott pl": ([NEW.format(a="49 Elliott pl"), OLD.format(a="45 Elliott pl")], 0,
                      "Lamb Thomas, h 45 Elliott pl", "Lamb Thomas, h 49 S. Elliott pl"),
    "49 S Elliott pl": ([NEW.format(a="49 S Elliott pl"), OLD.format(a="45 Elliott pl")], 0,
                        "Lamb Thomas, h 45 Elliott pl", "Lamb Thomas, h 49 S. Elliott pl"),
    "155 Franklin": ([], 0),             # untyped is a st, not Franklin av: the page as it was
    "62 Euclid av": ([], 0),                                    # no event: the page as it was
    "1 Wall st": ([], 0),                                       # Manhattan
}


def run(base: str, dump: Path | None):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, headless=True)
        for address, (want, links, *rows) in CASES.items():
            page = browser.new_page()
            page.goto(base)
            page.fill("#address textarea", address)
            page.click("#go")
            page.wait_for_function(
                "() => /\\d+ lines in [\\d.]+ s/.test(document.body.innerText)", timeout=180000)
            heads = [h.inner_text() for h in page.query_selector_all("h2")
                     if h.inner_text().startswith("As ")]
            rests = [t.inner_text() for t in page.query_selector_all("p.terms")
                     if t.inner_text().startswith(("Grade", "Not searched"))]
            n_links = len(page.query_selector_all("a.era-run"))
            print(f"{address!r}: {heads}\n    {rests}\n    links: {n_links}")
            assert heads == want, (address, heads)
            if links is not None:
                assert n_links == links, (address, n_links)
            for text in rows:
                row = page.locator("tr", has_text=text).first
                assert row.count() and not row.evaluate("e => !!e.closest('details')"), (address, text)
            if not want and dump:
                body = re.sub(r"in [\d.]+ s", "in X s", page.inner_html("#result"))
                (dump / f"{re.sub(r'[^a-z0-9]+', '-', address.lower())}.html").write_text(body)
            page.close()
        # the link of a too-wide bracket runs the range
        page = browser.new_page()
        page.goto(base)
        page.fill("#address textarea", "462 Court st")
        page.click("#go")
        page.wait_for_selector("a.era-run", timeout=180000)
        page.click("a.era-run")
        page.wait_for_function("() => document.querySelector('#address textarea').value.includes('644-696')")
        page.wait_for_function(
            "() => [...document.querySelectorAll('h2')].some(h => h.innerText.startsWith('As 644-696'))"
            " && !document.querySelector('a.era-run')", timeout=300000)
        print("link:", page.input_value("#address textarea"), "->",
              [h.inner_text() for h in page.query_selector_all("h2")])
        browser.close()


if __name__ == "__main__":
    dump = Path(sys.argv[2]) if sys.argv[2:] else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)
    run(sys.argv[1] if sys.argv[1:] else "http://127.0.0.1:7871", dump)
    print("eras page checks pass")
