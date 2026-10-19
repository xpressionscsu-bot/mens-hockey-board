#!/usr/bin/env python3
"""Fetch the USCHO Division I men's poll and the NCHC men's standings,
then write them to a JSON file the website reads.

Safe by design: if one source fails, the last good data for that source stays
in the file and is marked "stale", so the site never goes blank.

Usage:
    python scraper/scrape.py --out site/data.json
    python scraper/scrape.py --poll-html poll.html --standings-html st.html --out /tmp/data.json
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

# The NCHC link always shows the current season. Override with environment
# variables (GitHub Actions variables work) if either address ever changes.
NCHC_URL = os.environ.get("NCHC_URL") or "https://nchchockey.com/standings.aspx?path=mhockey"
USCHO_URL = os.environ.get("USCHO_URL") or "https://www.uscho.com/rankings/d-i-mens-poll/"
UA = "Mozilla/5.0 (compatible; MensHockeyBoard/1.0; personal project)"

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

REC = re.compile(r"^\d+-\d+-\d+$")      # 3-1-1
PAIR = re.compile(r"^\d+-\d+$")         # 22-10
INT = re.compile(r"^\d+$")              # 5
PCT = re.compile(r"^\d?\.\d{3}$")       # .800 or 1.000


# ---------------------------------------------------------------- helpers
def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def to_int(text, default=None):
    m = re.search(r"-?\d+", clean(text))
    return int(m.group()) if m else default


def header_cells(table):
    row = table.select_one("thead tr:last-of-type") or table.find("tr")
    return [clean(c.get_text()) for c in row.find_all(["th", "td"])] if row else []


def body_rows(table):
    rows = table.select("tbody tr") or table.find_all("tr")[1:]
    return [r for r in rows if r.find_all(["td", "th"])]


def team_text(cell):
    link = cell.find("a")
    return clean((link or cell).get_text())


def ints_of(text):
    return [int(x) for x in text.split("-")]


# ----------------------------------------------------------------- NCHC
def parse_nchc(html):
    """Read the NCHC standings table by the shape of each value, not by header
    names, then cross-check the numbers (W+L+T must equal games played)."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    m = re.search(r"(\d{4}-\d{2})", title.get_text() if title else "")
    season = m.group(1) if m else None

    table = None
    for t in soup.find_all("table"):
        hits = sum(
            1 for r in body_rows(t)
            if any(REC.match(clean(c.get_text())) for c in r.find_all(["td", "th"]))
        )
        if hits >= 6:
            table = t
            break
    if table is None:
        raise ValueError("NCHC standings table not found (page layout may have changed)")

    rows = []
    for tr in body_rows(table):
        cells = tr.find_all(["td", "th"])
        texts = [clean(c.get_text()) for c in cells]
        team = team_text(cells[0])
        if not team or INT.match(team):
            continue
        rest = texts[1:]
        if rest and rest[0] == team:  # the page repeats the team name for mobile layouts
            rest = rest[1:]

        ints = [int(x) for x in rest if INT.match(x)]
        recs = [x for x in rest if REC.match(x)]
        pairs = [x for x in rest if PAIR.match(x)]
        pcts = [x for x in rest if PCT.match(x)]

        try:
            if len(ints) >= 5:
                pts, conf_gp, sw, gp = ints[0], ints[2], ints[3], ints[-1]
            elif len(ints) == 4:
                pts, conf_gp, sw, gp = ints[0], ints[1], ints[2], ints[3]
            else:
                raise ValueError("too few whole-number columns")
            if len(recs) < 2:
                raise ValueError("too few W-L-T columns")
            conf_rec, overall_rec = recs[0], recs[1]
            if sum(ints_of(conf_rec)) != conf_gp or sum(ints_of(overall_rec)) != gp:
                conf_rec, overall_rec = overall_rec, conf_rec  # columns may be in the other order
                if sum(ints_of(conf_rec)) != conf_gp or sum(ints_of(overall_rec)) != gp:
                    raise ValueError("W-L-T totals do not match games played")
            if len(pairs) < 3:
                raise ValueError("too few OW-OL / GF-GA columns")
            ow_ol, conf_gfga, overall_gfga = pairs[0], pairs[1], pairs[-1]
            ow, ol = ints_of(ow_ol)
            cgf, cga = ints_of(conf_gfga)
            ogf, oga = ints_of(overall_gfga)
            if ogf < cgf or oga < cga:
                raise ValueError("overall goals are lower than conference goals")
            if ow + ol > conf_gp or sw > conf_gp:
                raise ValueError("overtime or shootout results exceed conference games played")
        except ValueError as exc:
            raise ValueError(f"NCHC row for {team} not understood ({exc}); cells: {rest}") from exc

        cw, cl, ct = ints_of(conf_rec)
        all_w, all_l, all_t = ints_of(overall_rec)
        rows.append({
            "rank": len(rows) + 1,
            "team": team,
            "conference": {"gp": conf_gp, "pts": pts, "w": cw, "l": cl, "t": ct,
                           "ow": ow, "ol": ol, "sw": sw, "gf": cgf, "ga": cga},
            "overall": {"gp": gp, "w": all_w, "l": all_l, "t": all_t,
                        "win_pct": float(pcts[0]) if pcts else None, "gf": ogf, "ga": oga},
        })

    if len(rows) < 8:
        raise ValueError(f"Only found {len(rows)} NCHC teams; expected 10")
    return {"season": season, "rows": rows}


# ---------------------------------------------------------------- USCHO
def parse_uscho(html):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" "))

    poll_date = None
    m = re.search(r"Poll\s*[-–—]\s*((?:%s)\.?\s+\d{1,2},\s+\d{4})" % MONTHS, text)
    if m:
        poll_date = dt.datetime.strptime(re.sub(r"\.", "", m.group(1)), "%B %d, %Y").date().isoformat()

    for table in soup.find_all("table"):
        headers = [h.lower() for h in header_cells(table)]
        if any(h.startswith("team") for h in headers) and any(h.startswith("pts") or h == "points" for h in headers):
            break
    else:
        raise ValueError("USCHO poll table not found (page may not have rendered)")

    def find(pred):
        for i, h in enumerate(headers):
            if pred(h):
                return i
        return None

    col = {
        "rank": find(lambda h: h in ("rnk", "rk", "rank", "#")),
        "team": find(lambda h: h.startswith("team")),
        "fpv": find(lambda h: "first" in h),
        "record": find(lambda h: h.startswith("rec")),
        "pts": find(lambda h: h.startswith("pts") or h == "points"),
        "last": find(lambda h: h.startswith("last")),
    }
    if col["team"] is None or col["pts"] is None:
        raise ValueError("USCHO poll table is missing the Team or Pts column")

    rows = []
    for tr in body_rows(table):
        cells = tr.find_all(["td", "th"])
        if len(cells) <= max(v for v in col.values() if v is not None):
            continue
        get = lambda key: clean(cells[col[key]].get_text()) if col[key] is not None else ""
        team = team_text(cells[col["team"]])
        fpv = to_int(get("fpv"), 0) if col["fpv"] is not None else 0
        # Some layouts put the first-place votes in the team cell: "Denver (33)".
        inline = re.search(r"\((\d+)\)\s*$", team)
        if inline:
            fpv = int(inline.group(1))
            team = clean(team[: inline.start()])
        last_text = get("last")
        rows.append({
            "rank": to_int(get("rank"), len(rows) + 1),
            "team": team,
            "first_place_votes": fpv or 0,
            "record": get("record") or None,
            "points": to_int(get("pts")),
            "last_rank": to_int(last_text) if re.search(r"\d", last_text) else None,
        })

    if len(rows) < 10:
        raise ValueError(f"Only found {len(rows)} poll rows; expected 20")
    return {"poll_date": poll_date, "rows": rows}


# -------------------------------------------------------------- fetching
def fetch_static(url):
    import requests
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_rendered(url):
    """USCHO builds its poll table with JavaScript, so load it in a real browser."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_selector("table tbody tr", timeout=30000)
        html = page.content()
        browser.close()
    return html


# ------------------------------------------------------------------ main
def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def core(section):
    return {k: v for k, v in (section or {}).items() if k not in ("updated_at", "status", "error")}


def refresh(name, old, build):
    """Return the section to store. Keeps the old data (marked stale) on failure."""
    try:
        data = build()
    except Exception as exc:  # noqa: BLE001 - any failure must not blank the site
        print(f"[{name}] FAILED: {exc}", file=sys.stderr)
        if old:
            return {**old, "status": "stale", "error": str(exc)[:300]}, False
        return {"status": "error", "error": str(exc)[:300], "rows": []}, False
    if old and old.get("status") == "ok" and core(old) == core(data):
        print(f"[{name}] no change")
        return old, True
    print(f"[{name}] updated ({len(data['rows'])} rows)")
    return {**data, "status": "ok", "updated_at": now_iso()}, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/data.json")
    ap.add_argument("--poll-html", help="parse this saved file instead of fetching USCHO")
    ap.add_argument("--standings-html", help="parse this saved file instead of fetching the NCHC")
    args = ap.parse_args()

    out = Path(args.out)
    old = json.loads(out.read_text()) if out.exists() else {}

    def build_poll():
        html = Path(args.poll_html).read_text() if args.poll_html else fetch_rendered(USCHO_URL)
        return {"source": USCHO_URL, "name": "USCHO.com Division I Men's Poll", **parse_uscho(html)}

    def build_standings():
        html = Path(args.standings_html).read_text() if args.standings_html else fetch_static(NCHC_URL)
        return {"source": NCHC_URL, "name": "NCHC Standings", **parse_nchc(html)}

    poll, poll_ok = refresh("poll", old.get("poll"), build_poll)
    standings, st_ok = refresh("standings", old.get("standings"), build_standings)

    new = {"poll": poll, "standings": standings}
    if json.dumps(new, sort_keys=True) != json.dumps({k: old.get(k) for k in new}, sort_keys=True):
        new["generated_at"] = now_iso()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
    else:
        print("data.json unchanged")

    # Fail the run only when there is nothing usable to show at all.
    if not poll.get("rows") and not standings.get("rows"):
        sys.exit(1)


if __name__ == "__main__":
    main()
