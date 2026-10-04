# MIAA Hoops Dashboard

One page for MIAA Division III basketball, men's and women's, for the 2026-27 season. The page is a dashboard and a traffic controller. It shows the next game, live scores, standings, the D3hoops.com poll, NPI rank, and a few returning leaders. For everything else it links to each school's schedule, roster, statistics, live stats, and stream.

Sibling of [almamatersaturday.com](https://www.almamatersaturday.com/) and built the same way.

## How it works

- `schools.json` lists the nine schools with colors, logos, and per-sport URLs. There are eight men's teams and nine women's teams, because Saint Mary's is women only.
- `fetch_data.py` reads each school's schedule, roster, and statistics pages and the D3hoops.com Top 25. It also reads the D3 Datacast sheet (men's NPI and efficiency) and The D3 Stat Lab JSON (women's NPI, preseason rank, simulations). It writes `data/season.json`. When a source fails, it keeps the previous run's data for that piece and records the error.
- `build_site.py` renders `docs/index.html`. The page contains both sports, and the browser shows one.
- `departures.json` names players who left the program and still appear on last season's statistics pages.
- `.github/workflows/update.yml` runs both scripts on a schedule and commits the result. GitHub Pages serves `docs/`.

Run it locally:

```
python3 fetch_data.py
python3 build_site.py
python3 -m http.server 8000 --directory docs
```

## Rules the scripts follow

- Games before Friday, November 6, 2026 are exhibitions. They appear in the schedule with an Exhibition tag and do not count in the records.
- Games after February 21, 2027 are dropped. Some schools list placeholder rows for MIAA Tournament games.
- A game between two members is a conference game when it falls in December, January, or February.
- The roster link points at this season's roster when that roster page lists players. Otherwise it points at last season's roster and the card says so.
- Players to know lists the top two scorers and the leader in rebounds, assists, steals, and blocks from the latest statistics page. The list skips last season's seniors and graduates, anyone in `departures.json`, and, when this season's roster page lists players, anyone missing from it. Players skipped for the last two reasons are named under the team.
- Page order within a sport is the preseason rating: D3 Datacast efficiency rank for the men, The D3 Stat Lab preseason rank for the women. Standings sort by conference record, then overall record, then that rating. The MIAA does not publish its tiebreaker rules. The tournament section on the page says so and cites school releases and d3boards.com posts instead. The section's text is hand-written in `tournament_section()` in `build_site.py`. Recheck miaa.org for the 2027 tournament pages and a published tiebreaker procedure. Update that function when either appears.

## Live scores

No national API covers these games. The page polls each school's live stats feed once a minute while a game is in its window. The window runs from 30 minutes before tipoff until 4 hours after.

- Sidearm schools (every member except Olivet): `https://sidearmstats.com/<client>/{mbball|wbball}/game.json`. The fetcher finds the client name on the school's live stats page. The game date in the feed must match the card's date.
- Olivet (PrestoSports): `https://data.prestolivestats.com/xml/<site>/events/<event>.xml`, from the StatView link on the schedule.

For a conference game the page uses the home team's feed, so every home game of a member has one. Away games at non-members have a feed only when the schedule page links live stats on a Sidearm or Presto host.

At halftime the card names the team that holds the possession arrow. No feed publishes the arrow, so the page infers it from the play-by-play:

1. The team that did not get the opening possession holds the arrow first.
2. Each held ball flips it.
3. In a quarters game, each quarter start after the first uses it.

The card labels the result as an estimate.

## Deploying

1. Create the public repository and push `main`.
2. In the repository settings, enable GitHub Pages from the `main` branch, `/docs` folder.
3. Add the custom domain in Pages and put it in `docs/CNAME`.
4. Point the domain's DNS at GitHub Pages (DNS only, no proxy).
5. Run the Update site workflow once by hand to confirm it can push.

Live at [www.themissingmiaahoopsdashboard.com](https://www.themissingmiaahoopsdashboard.com/).
