# MIAA basketball site: build plan

Working name: miaa-hoops (final name follows the domain the user picks).
The site shares its architecture with ~/projects/alma-mater-saturday. `fetch_data.py` writes
`data/season.json`. `build_site.py` renders `docs/index.html`. GitHub Pages serves `docs/`.
A scheduled workflow refreshes it.

## Requirements (from the user, 2026-10-03)

- Division III basketball, MIAA only, men's and women's, 2026-27 season (no games played yet).
- Structure like almamatersaturday.com: This week cards, team cards, rankings and ratings,
  top players, schedules and results, footer.
- Toggles: men's/women's, time zone, light/dark. Team filter or search for one team.
- Links: men's NPI to d3datacast.com, women's NPI to thed3statlab.com. Every team card links
  to roster and schedule. All outbound links open in a new tab.
- Game cards like football. At halftime, show which team has the possession arrow.
- Rosters: some 2026-27 rosters are posted and some are not. Handle both.
- d3hoops.com Top 25 (men and women).
- Team colors and logos from ~/projects/d3-bball-npi/myapp/data (team_colors.json, logos/).
- Mine d3datacast.com and thed3statlab.com for data worth showing per team, but only a
  headline number or two each. The user's steer (2026-10-03): this is a dashboard and a
  traffic controller, a one-stop shop that sends people to the right page. It must not try to
  cover player stats or NPI in full. Show the rank. Link to the source for the rest.
- Domain: cheeky name suggestions, RDAP-checked.

## Sections

1. [x] Reconnaissance (five agents): membership and URLs, d3datacast, thed3statlab, rankings
       and live feeds, domain names.
2. [x] schools.json: one entry per school. Each entry holds per-sport URLs (schedule, roster,
       stats, live stats), colors, logo, and external ids (ESPN, Massey, d3hoops, NPI pages).
3. [x] fetch_data.py: schedules (school pages or ESPN), records, and d3hoops poll ranks. NPI
       rank and value per team (one number each, from d3datacast and thed3statlab). Live stats
       links and feed discovery. It does not fetch player statistics or rating tables. On a
       failure it carries forward the previous run's data.
4. [x] build_site.py: the sport toggle renders both sports into the page and shows one. A team
       filter. This week game cards. Team cards whose main job is links out. The links are schedule,
       roster, stats, live stats, tickets or video if the school lists one, NPI page, and d3hoops. One
       compact standings-style table (record, conference record, d3hoops rank, NPI rank with
       link). Schedules and results tabs. New-tab links. Theme and time zone controls.
5. [x] Live JavaScript: Sidearm basketball feed (period, clock, score, last play, possession
       arrow at halftime). ESPN if it covers D3.
6. [x] README, workflow, local preview check, commit. The user creates the public repository
       and the domain. Pages and DNS then follow the almamatersaturday steps.

## Decisions

- Page order: NPI rank within the chosen sport, best first (fallback alphabetical before data).
- Players section stays (user, 2026-10-03): top 2 in points per game and top 1 in rebounds,
  assists, steals, and blocks. Per team and sport, from the school stats page. Before the first
  game the section says stats appear after the opener.
- Before the season: This week shows each team's first game. Roster link
  says "2026-27 roster" or "2025-26 roster (new one not posted yet)" based on the page's season label.

## Status (2026-10-03)

Built and committed locally (first commit 8886d4d). Not yet pushed: the user creates the public
repository, then Pages and the domain follow the almamatersaturday steps in README.md.
Added after the first build, all from the user:

- Exhibitions before November 6 do not count.
- Games after February 21, 2027 are dropped.
- Seniors, graduates, listed transfers, and players missing from a posted 2026-27 roster leave
  the leaders.
- MIAA favicon.
- Disclaimer at the top.
- Design tokens for spacing.
- First section renamed "Next game for each team".
