# MIAA basketball site: build plan

Working name: miaa-hoops (final name follows the domain the user picks).
Sibling of ~/projects/alma-mater-saturday; same architecture: `fetch_data.py` writes
`data/season.json`, `build_site.py` renders `docs/index.html`, GitHub Pages serves `docs/`,
a scheduled workflow refreshes it.

## Requirements (from the user, 2026-10-03)

- Division III basketball, MIAA only, men's and women's, 2026-27 season (no games played yet).
- Structure like almamatersaturday.com: This week cards, team cards, rankings and ratings,
  top players, schedules and results, footer.
- Toggles: men's/women's, time zone, light/dark. Team filter or search for one team.
- Links: men's NPI to d3datacast.com, women's NPI to thed3statlab.com. Every team card links
  to roster and schedule. All outbound links open in a new tab.
- Game cards like football; at halftime show which team has the possession arrow.
- Rosters: some 2026-27 rosters are up, some are not; handle both.
- d3hoops.com Top 25 (men and women).
- Team colors and logos from ~/projects/d3-bball-npi/myapp/data (team_colors.json, logos/).
- Mine d3datacast.com and thed3statlab.com for data worth showing per team, but only a
  headline number or two each. The user's steer (2026-10-03): this is a dashboard and a
  traffic controller, a one-stop shop that sends people to the right page. It must not be
  comprehensive on player stats or NPI. Show the rank, link to the source for the rest.
- Domain: cheeky name suggestions, RDAP-checked.

## Sections

1. [ ] Reconnaissance (five agents): membership and URLs, d3datacast, thed3statlab, rankings
       and live feeds, domain names.
2. [ ] schools.json: one entry per school with per-sport URLs (schedule, roster, stats,
       live stats), colors, logo, external ids (ESPN, Massey, d3hoops, NPI pages).
3. [ ] fetch_data.py: schedules (school pages or ESPN), records, d3hoops poll ranks, NPI rank
       and value per team (one number each, from d3datacast and thed3statlab), live stats links
       and feed discovery. No player statistics, no rating tables. Carry forward on failure.
4. [ ] build_site.py: sport toggle renders both sports into the page and shows one; team
       filter; This week game cards; team cards whose main job is links out (schedule, roster,
       stats, live stats, tickets or video if the school lists one, NPI page, d3hoops); one
       compact standings-style table (record, conference record, d3hoops rank, NPI rank with
       link); schedules and results tabs; new-tab links; theme and tz controls.
5. [ ] Live JS: Sidearm basketball feed (period, clock, score, last play, possession arrow at
       halftime); ESPN if it covers D3.
6. [ ] README, workflow, local preview check, commit. User creates the public repo and
       domain; then Pages and DNS like almamatersaturday.

## Decisions

- Page order: NPI rank within the chosen sport, best first (fallback alphabetical before data).
- Players section stays (user, 2026-10-03): top 2 in points per game, top 1 in rebounds,
  assists, steals, blocks, per team and sport, from the school stats page. Before the first
  game the section says stats appear after the opener.
- Before the season: This week shows each team's first game. Roster link
  says "2026-27 roster" or "2025-26 roster (new one not posted yet)" based on the page's season label.
