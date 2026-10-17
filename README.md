# Men's Hockey Board

A one-page site that shows the USCHO Division I men's poll and the NCHC standings.
A scraper writes both to `site/data.json`, and the page reads that file. A GitHub Actions
workflow re-runs the scraper on a schedule and publishes the site with GitHub Pages.

```
site/index.html            the page (reads data.json)
site/data.json             the data, also readable by anything else
scraper/scrape.py          fetches both sources and writes data.json
.github/workflows/update.yml   schedule + deploy
```

## Set it up (about 5 minutes)

Use a new, separate GitHub repository. Each repository gets one Pages site, so this will not
share a repo with the women's board.

1. Create a new **Public** repository and upload the contents of this folder (`site`, `scraper`,
   `README.md`, and the hidden `.github` folder) to the `main` branch.
2. In the repo, open **Settings > Pages** and set **Source** to **GitHub Actions**.
3. Open the **Actions** tab, choose **Update data and deploy site**, and click **Run workflow**.
4. When the run turns green, your site is at `https://<your-username>.github.io/<repo-name>/`.

The workflow then runs every day (standings) and several times on Monday and Tuesday (the poll).
To change the times, edit the `cron` lines in `.github/workflows/update.yml`. Times are in UTC.

## Check the first run

The scraper was tested against sample pages, not the live sites, so look at the first run in the
Actions tab. In the "Fetch poll and standings" step you should see `[poll] updated (20 rows)` and
`[standings] updated (10 rows)`.

If a source fails, the site keeps the last good data and shows a yellow "could not be refreshed"
note on that section. The log line starting with `FAILED` says what it could not read. For the
standings, it also prints the row it could not understand. Send that line to get the parser fixed.

## The JSON

`site/data.json` has two sections, `poll` and `standings`, each with `status` (`ok` or `stale`),
`updated_at`, `source`, and `rows`. Other tools can read it from
`https://<your-username>.github.io/<repo-name>/data.json`.

```json
{
  "poll": {
    "poll_date": "2026-10-12",
    "rows": [{ "rank": 1, "team": "Denver", "first_place_votes": 33,
               "record": "2-0-0", "points": 979, "last_rank": 1 }]
  },
  "standings": {
    "season": "2026-27",
    "rows": [{ "rank": 1, "team": "North Dakota",
               "conference": { "gp": 0, "pts": 0, "w": 0, "l": 0, "t": 0, "gf": 0, "ga": 0 },
               "overall": { "gp": 3, "w": 3, "l": 0, "t": 0, "win_pct": 1.0, "gf": 12, "ga": 5 } }]
  }
}
```

## Things to know

- **NCHC table:** the scraper reads the standings table by the shape of its values (records, goals,
  percentages) and checks that wins, losses and ties add up to games played. If the NCHC changes its
  table so those checks fail, the standings go stale instead of showing wrong numbers.
- **Season changes:** the NCHC link always shows the current season, so nothing needs updating each year.
  If the address ever changes, add a repository variable named `NCHC_URL` under
  **Settings > Secrets and variables > Actions > Variables**.
- **USCHO page:** the poll table is built with JavaScript, so the scraper opens the page in a headless
  browser (Playwright). If USCHO changes its layout, the poll section goes stale until `parse_uscho`
  in `scraper/scrape.py` is updated.
- **Be polite:** the schedule fetches each page a few times a day. Check each site's terms of use
  before sharing the page widely.
- **Run it on your computer:** `pip install -r scraper/requirements.txt`,
  `python -m playwright install chromium`, then `python scraper/scrape.py`. To view the page, run
  `python -m http.server -d site` and open http://localhost:8000 (opening the file directly will
  not load the JSON).
