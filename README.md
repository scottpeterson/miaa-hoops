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
- The next-game cards sort in three groups. Finished games come first, earliest finish first. Games in progress come next, furthest along first, measured as the share of regulation played. Games not yet started come last, by tipoff. The page sorts the cards again after each live score check, so a game that ends moves into the finished group. A finish time is known only for games that end while the page is open. Other finished games use tipoff plus two hours.
- Men's games carry an NPI label on the card and an NPI game column in the schedules. A game counts when the opponent is on the D3 Datacast 2026-27 team list (`npi.d3_teams` in `data/season.json`), except for the provisional stages that do not count, from [The D3 Stat Lab reference](https://thed3statlab.com/reference.html). Exhibitions never count. `content/npi_rules.json` holds the provisional members, the opponents that are not Division III, and aliases for schedule names that do not match the list. When an opponent matches nothing, `build_site.py` prints a warning and the page shows TBD. Add the name to `npi_rules.json`. Update the provisional list each season from the reference page.
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

## Sample in-game cards (temporary)

Until the season starts, each next-game card shows a sample in-game moment so you can see the live layout. `tools/make_sample_live.py` takes each team's most recent 2025-26 box score and stops its play-by-play at a random play, seeded by sport and school. It writes the score, the clock, the team's own last play, and the source game to `data/sample_live.json`. Each card labels the moment as sample data and names the source game.

- Rerun: `python3 tools/make_sample_live.py && python3 build_site.py`. To draw different moments, change the seed string in `main()`.
- Remove: delete `data/sample_live.json`, run `python3 build_site.py`, then commit and push. The cards go back to the countdown, and real live feeds work as before. Remove it before the first game, Friday, November 6, 2026, because sample cards ignore the live feeds.

## Deploying

1. Create the public repository and push `main`.
2. In the repository settings, enable GitHub Pages from the `main` branch, `/docs` folder.
3. Add the custom domain in Pages and put it in `docs/CNAME`.
4. Point the domain's DNS at GitHub Pages (DNS only, no proxy).
5. Run the Update site workflow once by hand to confirm it can push.

Live at [www.themissingmiaahoopsdashboard.com](https://www.themissingmiaahoopsdashboard.com/).
