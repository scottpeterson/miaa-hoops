#!/usr/bin/env python3
"""Render docs/index.html from schools.json and data/season.json."""
import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
SCHOOLS = json.loads((BASE / "schools.json").read_text())
SEASON = json.loads((BASE / "data" / "season.json").read_text())
OUT = BASE / "docs" / "index.html"
# Optional sample in-game moments for the next-game cards (tools/make_sample_live.py). Delete the file to remove them.
SAMPLE_FILE = BASE / "data" / "sample_live.json"
SAMPLE = json.loads(SAMPLE_FILE.read_text()) if SAMPLE_FILE.exists() else {}
EASTERN = ZoneInfo("America/Detroit")
BY_SLUG = {s["slug"]: s for s in SCHOOLS}
NOW = datetime.now(timezone.utc)
SPORTS = {"mbb": "Men", "wbb": "Women"}
SPORT_LABEL = {"mbb": "men's", "wbb": "women's"}
SITE_NAME = "MIAA Hoops Dashboard"


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def parse(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# ---------------------------------------------------------------- colors

def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(hex_color, target, amount):
    a, b = _rgb(hex_color), _rgb(target)
    return _hex(tuple(x + (y - x) * amount for x, y in zip(a, b)))


def _luminance(hex_color):
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def light_variant(hex_color):
    """A team color that reads as text on the light background."""
    lum = _luminance(hex_color)
    if lum > 0.45:
        return _mix(hex_color, "#000000", 0.5)
    if lum > 0.3:
        return _mix(hex_color, "#000000", 0.3)
    return hex_color


def dark_variant(hex_color):
    """A team color that reads as text on the dark background."""
    lum = _luminance(hex_color)
    if lum < 0.08:
        return _mix(hex_color, "#ffffff", 0.6)
    if lum < 0.2:
        return _mix(hex_color, "#ffffff", 0.45)
    return _mix(hex_color, "#ffffff", 0.2)


def color_vars(variant):
    return "".join(f"--c-{s['slug']}:{variant(s['color'])};" for s in SCHOOLS)


# ---------------------------------------------------------------- small helpers

def mascot(school, sport):
    if sport == "wbb" and school.get("mascot_wbb"):
        return school["mascot_wbb"]
    return school["mascot"]


def members(sport):
    return [s for s in SCHOOLS if sport in s["sports"]]


def teams(sport):
    return SEASON["sports"].get(sport, {}).get("teams", {})


def npi(sport):
    return SEASON["sports"].get(sport, {}).get("npi", {})


def poll(sport):
    return SEASON["sports"].get(sport, {}).get("poll", {})


def rating_rank(sport, slug):
    """The preseason ordering number: efficiency rank for men (D3 Datacast), preseason rank for women (Stat Lab)."""
    t = npi(sport).get("teams", {}).get(slug, {})
    key = "eff_rank" if sport == "mbb" else "preseason_rank"
    v = t.get(key) or t.get("rank")
    try:
        return int(v)
    except (TypeError, ValueError):
        return 9999


def ordered(sport):
    return sorted(members(sport), key=lambda s: (rating_rank(sport, s["slug"]), s["name"]))


def tip_text(game):
    dt = parse(game["date"]).astimezone(EASTERN)
    if game.get("time_tbd"):
        return dt.strftime("%a %b %-d") + ", time TBA"
    return dt.strftime("%a %b %-d, %-I:%M %p ET")


def time_tag(game, fmt="full"):
    dt = parse(game["date"])
    label = tip_text(game) if fmt == "full" else dt.astimezone(EASTERN).strftime("%-I:%M %p ET")
    tbd = ' data-tbd="1"' if game.get("time_tbd") else ""
    return f'<time datetime="{esc(dt.isoformat())}" data-fmt="{fmt}"{tbd}>{esc(label)}</time>'


def date_only(game):
    return parse(game["date"]).astimezone(EASTERN).strftime("%a %b %-d")


def opp_logo_src(game):
    slug = game["opponent"].get("slug")
    if slug and slug in BY_SLUG:
        return BY_SLUG[slug]["logo"]
    return game["opponent"].get("logo")


def opp_name(game, sport):
    slug = game["opponent"].get("slug")
    if slug and slug in BY_SLUG:
        return BY_SLUG[slug]["name"]
    return game["opponent"]["short"]


def opponent_label(game, sport):
    prefix = "at " if (not game["home"] and not game.get("neutral")) else "vs "
    exh = ' <span class="chip exh">Exhibition</span>' if game.get("exhibition") else ""
    rank = poll(sport).get("ranks", {}).get(game["opponent"].get("slug") or "")
    rk = f'<span class="rk">#{rank["rank"]}</span> ' if rank else ""
    logo = opp_logo_src(game)
    img = f'<img src="{esc(logo)}" alt=""> ' if logo else ""
    conf = ' <span class="chip conf">MIAA</span>' if game["conference"] else ""
    return f'{prefix}{img}{rk}{esc(opp_name(game, sport))}{conf}{exh}'


def result_text(game):
    if game["result"]:
        return f'{game["result"]} {game["pf"]}-{game["pa"]}'
    if game["state"] == "in":
        return f'{game["pf"] or 0}-{game["pa"] or 0}, {esc(game["status"])}'
    return ""


def site_text(game):
    if game.get("neutral"):
        return "Neutral"
    return "Home" if game["home"] else "Away"


def link(href, label, cls=""):
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{esc(href)}" target="_blank" rel="noopener">{label}</a>'


def game_links(game):
    out = []
    names = (("live_stats", "Live stats"), ("video", "Watch"), ("tickets", "Tickets"), ("boxscore", "Box score"), ("recap", "Recap"))
    for key, label in names:
        if game["links"].get(key):
            if game["state"] == "post" and key in ("live_stats", "tickets"):
                continue
            out.append(link(game["links"][key], label))
    return out


# ---------------------------------------------------------------- pairing the two copies of a conference game

def pair_index(sport):
    """{(slug, day, opponent slug): game} for every member's copy of a game against another member."""
    idx = {}
    for slug, team in teams(sport).items():
        for g in team["games"]:
            opp = g["opponent"].get("slug")
            if opp:
                idx[(slug, g["date"][:10], opp)] = (BY_SLUG[slug], g)
    return idx


def twin_of(sport, school, g, idx=None):
    idx = idx if idx is not None else pair_index(sport)
    opp = g["opponent"].get("slug")
    if not opp:
        return None
    return idx.get((opp, g["date"][:10], school["slug"]))


def game_key(school, g):
    opp = g["opponent"].get("slug")
    if opp:
        return (g["date"][:10], tuple(sorted((school["slug"], opp))))
    return (g["date"][:10], (school["slug"], g["id"]))


def perspective(school, g, twin):
    """Show a conference game from the home team's side."""
    if twin and twin[1]["home"] and not g["home"]:
        return twin[0], twin[1], (school, g)
    return school, g, twin


# ---------------------------------------------------------------- sections

def featured_games(sport):
    """One game per team: in progress, a final from the last 36 hours, the next game within 8 days, or the next game at all."""
    best = {}
    rank = {"in": 0, "post": 1, "pre": 2, "far": 3}
    for school in ordered(sport):
        team = teams(sport).get(school["slug"])
        if not team:
            continue
        for g in team["games"]:
            dt = parse(g["date"])
            if g["state"] == "in":
                kind = "in"
            elif g["state"] == "pre" and dt <= NOW + timedelta(days=8):
                kind = "pre"
            elif g["state"] == "post" and dt >= NOW - timedelta(hours=36):
                kind = "post"
            elif g["state"] == "pre" and not g.get("exhibition"):
                kind = "far"
            else:
                continue
            current = best.get(school["slug"])
            if current is None or (rank[kind], g["date"]) < (rank[current[2]], current[1]["date"]):
                best[school["slug"]] = (school, g, kind)
    idx = pair_index(sport)
    seen = set()
    cards = []
    for school, g, kind in sorted(best.values(), key=lambda r: r[1]["date"]):
        key = game_key(school, g)
        if key in seen:
            continue
        seen.add(key)
        cards.append((kind,) + perspective(school, g, twin_of(sport, school, g, idx)))
    return cards


def game_card(sport, school, g, twin, kind="pre", sample=None):
    opp = g["opponent"]
    opp_logo = opp_logo_src(g)
    opp_img = f'<img src="{esc(opp_logo)}" alt="">' if opp_logo else '<span class="nologo"></span>'
    where = site_text(g)
    if where == "Neutral":
        where = "Neutral site"
    live = g["state"] == "in"
    final = g["state"] == "post"
    status_class = "live" if live else "final" if final else "pre"
    score = f'{g["pf"] if g["pf"] is not None else 0}<span class="dash">-</span>{g["pa"] if g["pa"] is not None else 0}' if (live or final) else ""
    status = esc(g["status"]) if live else (f'Final · {g["result"]}' if final else "")
    countdown = f'<span class="count" data-tip="{esc(parse(g["date"]).isoformat())}"></span>' if g["state"] == "pre" and not g.get("time_tbd") else ""
    situation = ""
    if sample:
        status_class = "live"
        score = f'{sample["pf"]}<span class="dash">-</span>{sample["pa"]}'
        status = esc(sample["status"])
        situation = f'<div class="last">Last play: {esc(sample["last"])}</div>' if sample.get("last") else ""
    feed = {} if sample else (g.get("live_feed") or {})
    progress_attr = f' data-progress="{progress(sample["status"] if sample else g["status"], sport):.4f}"' if live or sample else ""
    feed_attrs = f' data-feed="{esc(feed["url"])}" data-feed-type="{esc(feed["type"])}"' if feed.get("url") else ""
    team_slugs = school["slug"] + (f' {twin[0]["slug"]}' if twin else "")
    twin_attr = f' data-twin="{esc(twin[1]["id"])}"' if twin else ""
    rank = poll(sport).get("ranks", {}).get(opp.get("slug") or "")
    rk = f'<span class="rk">#{rank["rank"]}</span> ' if rank else ""
    my_rank = poll(sport).get("ranks", {}).get(school["slug"])
    my_rk = f'<span class="rk">#{my_rank["rank"]}</span> ' if my_rank else ""
    links = game_links(g)
    links_row = f'<dt>Links</dt><dd>{" · ".join(links)}</dd>' if links else ""
    conf = '<span class="chip conf">MIAA game</span>' if g["conference"] else ""
    regular = [x for x in teams(sport)[school["slug"]]["games"] if not x.get("exhibition")]
    opener = '<span class="chip">Season opener</span>' if kind == "far" and regular and g is regular[0] else ""
    if g.get("exhibition"):
        opener = '<span class="chip">Exhibition</span>'
        if g["state"] == "post":
            opener += '<span class="chip">Not counted in the record</span>' 
    note = f'<dt>Note</dt><dd>{esc(g["note"])}</dd>' if g.get("note") else ""
    if sample:
        note += f'<dt>Sample</dt><dd>The score, clock, and last play are a moment from {esc(school["name"])} vs. {esc(sample["game"])}. Live scores replace them when the season starts.</dd>'
        opener = '<span class="chip">Sample data</span>' + opener
    return f'''<article class="game {status_class}" data-game="{esc(g["id"])}"{twin_attr} data-teams="{esc(team_slugs)}" data-date="{esc(g["date"])}" data-home="{1 if g["home"] else 0}"{feed_attrs}{progress_attr} style="--team:var(--c-{school["slug"]})">
<header><img src="{esc(school["logo"])}" alt=""><div><div class="who">{my_rk}{esc(school["name"])} <span class="muted">{esc(mascot(school, sport))}</span></div><div class="what">{"vs" if g["home"] or g.get("neutral") else "at"} {rk}{esc(opp["name"] if not opp.get("slug") else BY_SLUG[opp["slug"]]["name"] + " " + mascot(BY_SLUG[opp["slug"]], sport))}</div></div>{opp_img}</header>
<div class="body">
<div class="scoreline"><span class="score">{score}</span><span class="status">{status}</span></div>
<div class="situation{" on" if situation else ""}">{situation}</div>
<dl>
<dt>Tipoff</dt><dd>{time_tag(g)} {countdown}</dd>
<dt>Where</dt><dd>{esc(where)}{" · " + esc(g["location"]) if g.get("location") else ""}</dd>
{links_row}{note}
</dl>
<div class="chips">{conf}{opener}</div>
</div></article>'''


def progress(status, sport):
    """Share of regulation played, from a status such as "10:31 2nd half", "Halftime", or "2:00 OT"."""
    regulation, length = (2, 1200) if sport == "mbb" else (4, 600)
    total = regulation * length
    status = (status or "").strip()
    if status == "Halftime":
        return 0.5
    m = re.match(r"(?:(\d+):(\d+) )?(?:End of )?(?:(\d)\w\w (?:half|quarter)|OT(\d*))$", status)
    if not m:
        return 0.0
    clock = int(m.group(1)) * 60 + int(m.group(2)) if m.group(1) else 0
    if m.group(4) is not None:
        extra = int(m.group(4) or 1)
        return (total + (extra - 1) * 300 + (300 - clock)) / total
    return ((int(m.group(3)) - 1) * length + (length - clock)) / total


def card_order(sport, sample, g):
    """Finished games first (earliest first), then games in progress (furthest along first), then upcoming games by tipoff."""
    if sample:
        return (1, -progress(sample["status"], sport), g["date"])
    if g["state"] == "post":
        return (0, 0.0, g["date"])
    if g["state"] == "in":
        return (1, -progress(g["status"], sport), g["date"])
    return (2, 0.0, g["date"])


def this_week(sport):
    samples = SAMPLE.get(sport, {})
    featured = sorted(featured_games(sport), key=lambda c: card_order(sport, samples.get(c[1]["slug"]), c[2]))
    cards = [game_card(sport, s, g, twin, kind, samples.get(s["slug"])) for kind, s, g, twin in featured]
    if not cards:
        return '<p class="muted">No games scheduled.</p>'
    return '<div class="games">' + "\n".join(cards) + "</div>"


def poll_badge(sport, slug):
    p = poll(sport)
    if not p.get("label"):
        return ""
    r = p.get("ranks", {}).get(slug)
    school = BY_SLUG[slug]
    rv = p.get("receiving_votes", {}).get(school.get("d3hoops_name") or school["name"])
    if r:
        body = f'<b>#{r["rank"]}</b> D3hoops.com'
        cls = "badge"
    elif rv:
        body = f'RV D3hoops.com ({rv})'
        cls = "badge rv"
    else:
        body = "NR D3hoops.com"
        cls = "badge nr"
    return link(p["url"], body, cls)


def npi_badges(sport, slug):
    n = npi(sport)
    t = n.get("teams", {}).get(slug)
    if not t:
        return ""
    out = []
    if sport == "mbb":
        out.append(link(n.get("url", "https://d3datacast.com/npi/mbb/"), f'<b>#{t["rank"]}</b> NPI <span class="src">D3 Datacast</span>', "badge"))
        if t.get("eff_rank"):
            out.append(link(n.get("eff_url", "https://d3datacast.com/efficiency-ratings/"), f'<b>#{t["eff_rank"]}</b> Efficiency <span class="src">{esc(t.get("adj_em", ""))} AdjEM</span>', "badge"))
    else:
        out.append(link(n.get("url", "https://thed3statlab.com/npi.html"), f'<b>#{t["rank"]}</b> NPI <span class="src">The D3 Stat Lab</span>', "badge"))
        if t.get("preseason_rank"):
            out.append(link(n.get("preseason_url", "https://thed3statlab.com/preseason_rankings.html"), f'<b>#{t["preseason_rank"]}</b> Preseason <span class="src">The D3 Stat Lab</span>', "badge"))
        if t.get("tourney_pct"):
            out.append(link(n.get("sims_url", "https://thed3statlab.com/season_simulations.html"), f'<b>{esc(t["tourney_pct"].replace(".00%", "%"))}</b> tournament odds <span class="src">The D3 Stat Lab</span>', "badge"))
    return "".join(out)


def last_and_next(sport, team):
    played = [g for g in team["games"] if g["result"] and not g.get("exhibition")]
    upcoming = [g for g in team["games"] if g["state"] != "post"]
    parts = []
    if played:
        last = played[-1]
        parts.append(f'<dt>Last</dt><dd>{result_text(last)} {opponent_label(last, sport)}</dd>')
    if upcoming:
        nxt = upcoming[0]
        parts.append(f'<dt>Next</dt><dd>{opponent_label(nxt, sport)}, {time_tag(nxt)}</dd>')
    return "".join(parts)


def common_link(team, key):
    """The link most home games share, for the team card (the school's stream or ticket page)."""
    c = Counter(g["links"][key] for g in team["games"] if g["home"] and g["links"].get(key))
    return c.most_common(1)[0][0] if c else None


def roster_line(team):
    r = team.get("roster") or {}
    if not r.get("players"):
        return "Roster", "Roster page"
    if r.get("current"):
        return f'{esc(r["season"])} roster', f'{r["players"]} players listed'
    return f'{esc(r["season"])} roster', f'{esc(SEASON["season"])} roster not posted yet'


def team_card(sport, school):
    team = teams(sport).get(school["slug"])
    cfg = school["sports"][sport]
    if not team:
        return ""
    roster_label, roster_note = roster_line(team)
    links = [link(cfg["schedule_url"], "Schedule"), link(team["roster"]["url"], roster_label), link(cfg["stats_url"], "Stats")]
    if cfg.get("live_stats_url"):
        links.append(link(cfg["live_stats_url"], "Live stats"))
    video = common_link(team, "video")
    if video:
        links.append(link(video, "Watch"))
    tickets = common_link(team, "tickets")
    if tickets:
        links.append(link(tickets, "Tickets"))
    conf_rec = f'{team["conf_record"]} MIAA'
    played = team["played"]
    pts = f'<dt>Points</dt><dd>{team["pf"]} for, {team["pa"]} against, {team["pf"] - team["pa"]:+d} margin</dd>' if played else ""
    return f'''<article class="team" id="team-{sport}-{school["slug"]}" data-teams="{school["slug"]}" style="--team:var(--c-{school["slug"]})">
<header style="background:{esc(school["color"])};color:{esc(school["text"])}"><img src="{esc(school["logo"])}" alt="{esc(school["name"])} logo"><div><div class="who">{esc(school["name"])} {esc(mascot(school, sport))}</div><div class="what">{esc(school["full_name"])} · {esc(school["city"])}</div></div><button type="button" class="focus" data-focus="{school["slug"]}" title="Show only this team">Focus</button></header>
<div class="body">
<div class="record"><span class="big">{esc(team["record"])}</span><span class="standing">{esc(conf_rec)}</span></div>
<div class="badges">{poll_badge(sport, school["slug"])}{npi_badges(sport, school["slug"])}</div>
<dl>
{pts}{last_and_next(sport, team)}
<dt>Roster</dt><dd>{roster_note}</dd>
</dl>
<p class="links">{" · ".join(links)} · <a href="#sched-{sport}-{school["slug"]}" class="tablink" data-tab="{school["slug"]}">Full schedule below</a></p>
</div></article>'''


def standings_table(sport):
    rows = []
    def pct(w, l):
        return w / (w + l) if (w + l) else -1
    members_sorted = sorted(members(sport), key=lambda s: (
        -pct(teams(sport)[s["slug"]]["conf_wins"], teams(sport)[s["slug"]]["conf_losses"]),
        -pct(teams(sport)[s["slug"]]["wins"], teams(sport)[s["slug"]]["losses"]),
        rating_rank(sport, s["slug"]), s["name"]))
    n = npi(sport).get("teams", {})
    for s in members_sorted:
        t = teams(sport)[s["slug"]]
        r = poll(sport).get("ranks", {}).get(s["slug"])
        rv = poll(sport).get("receiving_votes", {}).get(s.get("d3hoops_name") or s["name"])
        poll_cell = f'#{r["rank"]}' if r else (f"RV ({rv})" if rv else "NR")
        npi_cell = f'#{n[s["slug"]]["rank"]}' if s["slug"] in n else "–"
        rating = n.get(s["slug"], {}).get("eff_rank" if sport == "mbb" else "preseason_rank")
        upcoming = [g for g in t["games"] if g["state"] != "post"]
        nxt = f'{opponent_label(upcoming[0], sport)}, {time_tag(upcoming[0])}' if upcoming else "Season over"
        margin = f'{t["pf"] - t["pa"]:+d}' if t["played"] else "–"
        rows.append(f'<tr data-teams="{s["slug"]}" data-keep="1"><td class="lead"><img src="{esc(s["logo"])}" alt=""> {esc(s["name"])}</td><td>{esc(t["conf_record"])}</td><td>{esc(t["record"])}</td><td>{margin}</td><td>{poll_cell}</td><td>{npi_cell}</td><td>{"#" + str(rating) if rating else "–"}</td><td class="next">{nxt}</td></tr>')
    rating_head = "Efficiency rank" if sport == "mbb" else "Preseason rank"
    return f'<div class="tablewrap"><table class="standings"><thead><tr><th>Team</th><th>MIAA</th><th>Overall</th><th>Margin</th><th>D3hoops.com</th><th>NPI rank</th><th>{rating_head}</th><th>Next</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def numbers_section(sport):
    n = npi(sport)
    t = n.get("teams", {})
    if not t:
        return '<p class="muted">Ratings unavailable this run.</p>'
    rows = []
    if sport == "mbb":
        head = "<tr><th>Team</th><th>NPI rank</th><th>NPI</th><th>Record in the NPI table</th><th>Bid</th><th>At-large rank</th><th>Efficiency rank</th><th>Adj. efficiency margin</th></tr>"
        for s in sorted(members(sport), key=lambda s: int(t.get(s["slug"], {}).get("rank") or 9999)):
            d = t.get(s["slug"])
            if not d:
                continue
            rows.append(f'<tr data-teams="{s["slug"]}" data-keep="1"><td class="lead"><img src="{esc(s["logo"])}" alt=""> {esc(s["name"])}</td><td>#{d["rank"]}</td><td>{esc(d["npi"])}</td><td>{esc(d["record"])}</td><td>{esc(d["bid"])}</td><td>{esc(d["at_large_rank"])}</td><td>{"#" + str(d["eff_rank"]) if d.get("eff_rank") else "–"}</td><td>{esc(d.get("adj_em", "–"))}</td></tr>')
        intro = (f'<p class="small">From {link("https://d3datacast.com/", "D3 Datacast")}: the {link(n["url"], "men\'s NPI table")} (updated {esc(n.get("updated", ""))}) and the '
                 f'{link(n["eff_url"], "efficiency ratings")} (updated {esc(n.get("eff_updated", ""))}). The NPI stays on last season\'s final numbers until this season\'s games count. '
                 f'The {link("https://d3datacast.com/conference-ratings/miaa/", "MIAA conference page")} has the full picture.</p>')
    else:
        head = "<tr><th>Team</th><th>NPI rank</th><th>NPI</th><th>Record in the NPI table</th><th>Bid</th><th>Preseason rank</th><th>Returning production</th><th>Tournament odds</th><th>Auto bid odds</th><th>Median record</th></tr>"
        for s in sorted(members(sport), key=lambda s: int(t.get(s["slug"], {}).get("rank") or 9999)):
            d = t.get(s["slug"])
            if not d:
                continue
            rows.append(f'<tr data-teams="{s["slug"]}" data-keep="1"><td class="lead"><img src="{esc(s["logo"])}" alt=""> {esc(s["name"])}</td><td>#{d["rank"]}</td><td>{esc(d["npi"])}</td><td>{esc(d["record"])}</td><td>{esc(d["bid"])}</td><td>{"#" + str(d["preseason_rank"]) if d.get("preseason_rank") else "–"}</td><td>{esc(d.get("returning", "–"))}</td><td>{esc(d.get("tourney_pct", "–"))}</td><td>{esc(d.get("aq_pct", "–"))}</td><td>{esc(d.get("median_record", "–"))}</td></tr>')
        intro = (f'<p class="small">From {link("https://thed3statlab.com/", "The D3 Stat Lab")}: the {link(n["url"], "women\'s NPI table")}, '
                 f'{link(n["preseason_url"], "preseason rankings")} with returning production, and {link(n["sims_url"], "season simulations")} with tournament odds and the median simulated record. '
                 f'The NPI stays on last season\'s final numbers until this season\'s games count.</p>')
    return intro + f'<div class="tablewrap"><table class="ratings"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'


def poll_section(sport):
    p = poll(sport)
    if not p.get("label"):
        return '<p class="muted">Poll unavailable this run.</p>'
    ranks = p.get("ranks", {})
    rv = p.get("receiving_votes", {})
    mentions = []
    for s in members(sport):
        r = ranks.get(s["slug"])
        v = rv.get(s.get("d3hoops_name") or s["name"])
        if r:
            mentions.append(f'<span class="badge" data-teams="{s["slug"]}" data-keep="1"><b>#{r["rank"]}</b> {esc(s["name"])} ({esc(r["record"])}, {esc(r["points"])} points)</span>')
        elif v:
            mentions.append(f'<span class="badge rv" data-teams="{s["slug"]}" data-keep="1">RV {esc(s["name"])} ({v} points)</span>')
    miaa = f'<div class="badges">{"".join(mentions)}</div>' if mentions else '<p class="small">No MIAA team is ranked or receiving votes in this poll.</p>'
    member_names = {s.get("d3hoops_name") or s["name"] for s in members(sport)}
    rows = "".join(
        f'<tr class="{"miaa" if r["team"] in member_names else ""}"><td class="lead">{r["rank"]}</td><td>{esc(r["team"])}{" (" + str(r["first_place"]) + ")" if r.get("first_place") else ""}</td><td>{esc(r["record"])}</td><td>{esc(r["points"])}</td><td>{esc(r.get("prev") or "")}</td></tr>'
        for r in p.get("top25", []))
    others = ", ".join(f'{esc(k)} {v}' for k, v in rv.items())
    return (f'<p class="small">{esc(p["label"])}. Source: {link(p["url"], "d3hoops.com")}. Teams in bold are MIAA members. First-place votes in parentheses.</p>{miaa}'
            f'<details class="poll"><summary>Full Top 25</summary><div class="tablewrap"><table class="poll"><thead><tr><th>#</th><th>Team</th><th>Record</th><th>Points</th><th>Prev</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'{"<p class=small>Others receiving votes: " + others + "</p>" if others else ""}</details>')


def players_section(sport):
    blocks = []
    seasons = set()
    for s in ordered(sport):
        team = teams(sport).get(s["slug"], {})
        players = team.get("players") or []
        if not players:
            continue
        seasons.add(team.get("stats_season") or "")
        cards = []
        for p in players:
            if p.get("headshot"):
                face = f'<img class="face" src="{esc(p["headshot"])}" alt="" loading="lazy">'
            else:
                initials = "".join(w[0] for w in (p.get("name") or "?").split()[:2])
                face = f'<span class="face initials" style="background:{esc(s["color"])};color:{esc(s["text"])}">{esc(initials)}</span>'
            sub = " · ".join(x for x in (p.get("position"), f'#{p["jersey"]}' if p.get("jersey") else None, p.get("year")) if x)
            cards.append(f'<div class="player">{face}<div><span class="label">{esc(p["label"])}</span><div class="pname">{esc(p["name"])}</div><div class="psub">{esc(sub)}</div><div class="pline">{esc(p["line"])}</div></div></div>')
        label = f' <span class="muted small">{esc(team.get("stats_season"))} statistics</span>' if team.get("stats_season") else ""
        gone = team.get("departed") or []
        gone_html = ""
        if gone:
            items = "; ".join(f'{esc(g["name"])} ({esc(g["line"])}, {esc(g["reason"])})' for g in gone)
            gone_html = f'<p class="small gone">Not back for {esc(SEASON["season"])}: {items}.</p>'
        blocks.append(f'<div class="teamplayers" data-teams="{s["slug"]}" style="--team:var(--c-{s["slug"]})"><h3><img src="{esc(s["logo"])}" alt=""> {esc(s["name"])} {esc(mascot(s, sport))}{label} {link(s["sports"][sport]["stats_url"], "Full stats", "sitelink")}</h3><div class="players">{"".join(cards)}</div>{gone_html}</div>')
    note = ""
    if seasons and all(x and x != SEASON["season"] for x in seasons):
        note = f'<p class="small">No {esc(SEASON["season"])} games count yet. These are last season\'s numbers for the players who are back.</p>'
    return note + "\n".join(blocks)


def links_cell(game):
    return " · ".join(game_links(game))


def schedule_table(sport, school, team):
    rows = []
    for g in team["games"]:
        res = result_text(g)
        cls = "w" if g["result"] == "W" else "l" if g["result"] == "L" else "live" if g["state"] == "in" else ""
        when = time_tag(g) if g["state"] != "post" else date_only(g)
        rows.append(f'<tr class="{cls}" data-game="{esc(g["id"])}" data-home="{1 if g["home"] else 0}"><td class="lead">{when}</td><td class="opp">{opponent_label(g, sport)}</td><td>{esc(site_text(g))}</td><td class="loc">{esc(g.get("location") or "")}</td><td class="lk">{links_cell(g)}</td><td class="res">{res}</td></tr>')
    return f'<div class="tablewrap"><table class="sched"><thead><tr><th>Date</th><th>Opponent</th><th>Site</th><th>Location</th><th>Links</th><th>Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def schedules(sport):
    order = ordered(sport)
    tabs = [f'<button class="tab active" data-tab="all">All teams</button>'] + [f'<button class="tab" data-tab="{s["slug"]}" data-teams="{s["slug"]}" data-keep="1" style="--team:var(--c-{s["slug"]})">{esc(s["name"])}</button>' for s in order]
    panes = []
    all_rows = []
    idx = pair_index(sport)
    seen = set()
    for s in order:
        team = teams(sport).get(s["slug"])
        if not team:
            continue
        panes.append(f'<div class="pane" id="sched-{sport}-{s["slug"]}" data-pane="{s["slug"]}" data-teams="{s["slug"]}" hidden>{schedule_table(sport, s, team)}</div>')
        for g in team["games"]:
            key = game_key(s, g)
            if key in seen:
                continue
            seen.add(key)
            school, game, twin = perspective(s, g, twin_of(sport, s, g, idx))
            all_rows.append((game["date"], school, game, twin))
    rows = []
    for _, s, g, twin in sorted(all_rows, key=lambda r: r[0]):
        res = result_text(g)
        cls = "w" if g["result"] == "W" else "l" if g["result"] == "L" else "live" if g["state"] == "in" else ""
        when = time_tag(g) if g["state"] != "post" else date_only(g)
        slugs = s["slug"] + (f' {twin[0]["slug"]}' if twin else "")
        rows.append(f'<tr class="{cls}" data-game="{esc(g["id"])}" data-home="{1 if g["home"] else 0}" data-teams="{esc(slugs)}"><td class="lead">{when}</td><td class="opp"><img src="{esc(s["logo"])}" alt=""> {esc(s["name"])}</td><td class="opp">{opponent_label(g, sport)}</td><td class="loc">{esc(g.get("location") or "")}</td><td class="lk">{links_cell(g)}</td><td class="res">{res}</td></tr>')
    all_pane = f'<div class="pane" id="sched-{sport}-all" data-pane="all"><div class="tablewrap"><table class="sched"><thead><tr><th>Date</th><th>Team</th><th>Opponent</th><th>Location</th><th>Links</th><th>Result</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    return f'<div class="tabs">{"".join(tabs)}</div>{all_pane}{"".join(panes)}'


def filter_bar(sport):
    pills = [f'<button type="button" class="pill active" data-team="">All teams</button>'] + [
        f'<button type="button" class="pill" data-team="{s["slug"]}" style="--team:var(--c-{s["slug"]})"><img src="{esc(s["logo"])}" alt="">{esc(s["name"])}</button>' for s in sorted(members(sport), key=lambda s: s["name"])]
    return f'<div class="filterbar"><label class="search"><span class="seglabel">Find a team</span><input type="search" placeholder="Type a school, mascot, or city" autocomplete="off" data-sport="{sport}"></label><div class="pills">{"".join(pills)}</div></div>'


def sport_section(sport):
    label = SPORT_LABEL[sport]
    n = npi(sport)
    npi_source = "D3 Datacast" if sport == "mbb" else "The D3 Stat Lab"
    npi_url = n.get("url") or ("https://d3datacast.com/npi/mbb/" if sport == "mbb" else "https://thed3statlab.com/npi.html")
    count = len(members(sport))
    poll_label = poll(sport).get("label") or "D3hoops.com Top 25"
    return f'''<section class="sport" data-sport="{sport}">
{filter_bar(sport)}

<h2 id="{sport}-week">Next game for each team</h2>
<p class="small"><span class="tznote">Tipoff times are in your device's time zone.</span> Use the Eastern, Central, and Device buttons at the top to switch.</p>
<p class="small">Scores refresh every minute while a game is in progress, from each school's live stats feed. During a game a card shows the clock, the score, the bonus, and the last play. At halftime it shows which team holds the possession arrow. The page infers the arrow from the play-by-play, so the card labels it an estimate. <span class="livestamp"></span></p>
{this_week(sport)}

<h2 id="{sport}-standings">Standings</h2>
<p class="small">MIAA record first, then overall record. Before the first game, the table sorts by {"D3 Datacast's preseason efficiency rank" if sport == "mbb" else "The D3 Stat Lab's preseason rank"}. The NPI rank is last season's final rank until this season's games count. Official standings: {link("https://miaa.org/standings.aspx?path=" + ("mbball" if sport == "mbb" else "wbball"), "miaa.org")}. Tournament dates and the tiebreaker evidence are <a href="#tournament">near the bottom of the page</a>.</p>
{standings_table(sport)}

<h2 id="{sport}-teams">The {count} teams</h2>
<p class="small">One card per team with the links you need: schedule, roster, statistics, live stats, the school's stream, and tickets where the school lists them. The NPI badge opens the {link(npi_url, npi_source + " " + label + " NPI table")}. The {esc(poll_label)} badge opens the poll. Use Focus to show one team everywhere on the page.</p>
<div class="teams">
{"".join(team_card(sport, s) for s in ordered(sport))}
</div>

<h2 id="{sport}-poll">{esc(poll_label.split(",")[0])}</h2>
{poll_section(sport)}

<h2 id="{sport}-numbers">NPI and ratings</h2>
{numbers_section(sport)}

<h2 id="{sport}-players">Players to know</h2>
<p class="small">Top two in points per game and the leader in rebounds, assists, steals, and blocks for each team, from the school's official statistics page. The list skips last season's seniors and graduates. It also skips players who transferred or who are missing from a posted {esc(SEASON["season"])} roster, and names them under the team.</p>
{players_section(sport)}

<h2 id="{sport}-schedules">Schedules and results</h2>
<p class="small">The All teams tab lists every game once. A conference game appears from the home team's side. Games before Friday, November 6 are exhibitions and do not count in the records. Opponent ranks come from the {esc(poll_label.split(",")[0])}.</p>
{schedules(sport)}
</section>'''


# ---------------------------------------------------------------- tournament and tiebreakers

def tournament_section():
    """What is known about the 2027 MIAA Tournaments and the conference tiebreakers, with sources."""
    det = link("https://miaa.org/sports/2024/5/29/Championship%20Determination.aspx", "Championship Determination page")
    champs = link("https://miaa.org/sports/2025/8/5/miaa-championships-25-26.aspx", "2025-26 championships page")
    tickets = link("https://www.miaa.org/landing/tickets", "MIAA tickets page")
    tc_m = link("https://miaa.org/tournaments/?id=27", "2026 men's tournament page")
    tc_w = link("https://miaa.org/tournaments/?id=28", "2026 women's tournament page")
    olivet26 = link("https://www.olivetcomets.com/sports/mbkb/2025-26/26_MIAA_TOURNAMENT", "Olivet's 2026 men's tournament page")
    hope26 = link("https://athletics.hope.edu/news/2026/3/1/mens-basketball-storms-back-to-win-miaa-tournament-championship.aspx", "Hope's 2026 title game story")
    hope23 = link("https://athletics.hope.edu/story.aspx?filename=miaa-womens-basketball-tournament-semifinal-preview&file_date=2/24/2023", "Hope release, February 24, 2023")
    calvin24m = link("https://calvinknights.com/news/2024/2/18/calvin-mens-basketball-gains-no-2-seed-and-first-round-bye-for-miaa-tourney.aspx", "Calvin release, February 18, 2024")
    cciw = link("https://cciw.org/sports/2010/6/29/Gen._0629100226.aspx?id=616", "basketball tiebreaker procedures")
    calvin24w = link("https://calvinknights.com/news/2024/2/18/calvin-womens-basketball-gains-no-2-seed-and-first-round-bye-for-miaa-tournament.aspx", "Calvin release, February 18, 2024")
    return f'''<section class="rules" id="tournament">
<h2>2027 MIAA Tournaments</h2>
<p class="small">Checked October 3, 2026. The MIAA lists no 2027 tournament dates, brackets, or hosts yet. This section gives last season's format and a projection from it.</p>
<div class="rulegrid">
<article class="rule">
<h3>Format, from the 2025-26 tournaments</h3>
<ul>
<li>Six teams qualify. The top two seeds skip the first round. The higher seed hosts each first-round game. The No. 1 seed hosts the semifinals and the final, and keeps hosting the final after a semifinal loss. In 2026 Olivet, the men's No. 1 seed, lost its semifinal to Trine. Hope beat Trine in the final at Olivet the next night.</li>
<li>Men: first round on Tuesday, semifinals on Friday, final on Saturday. Women: first round on Wednesday, semifinals on Friday, final on Saturday.</li>
<li>The regular-season champion is the team with the best MIAA won-loss record. The tournament champion gets the conference's automatic bid to the NCAA Division III Championship.</li>
</ul>
<p class="small">Sources: the MIAA's {det}, {champs}, {tc_m}, and {tc_w}. Also {olivet26} and {hope26}.</p>
</article>
<article class="rule">
<h3>Projected 2027 dates</h3>
<p>The schedules on this page end on Saturday, February 20 and Sunday, February 21, 2027. If the MIAA keeps the 2026 pattern, the tournaments fall on these days. None of these dates is official.</p>
<ul>
<li>Men: first round Tuesday, February 23; semifinals Friday, February 26; final Saturday, February 27, 2027.</li>
<li>Women: first round Wednesday, February 24; semifinals Friday, February 26; final Saturday, February 27, 2027.</li>
</ul>
<p class="small">The MIAA posts one tournament page per sport. The {tc_m} and {tc_w} list every game with the score, a box score, and each school's recap. They also link to tickets, the program, standings, and statistics. Expect the 2027 pages to look the same, in the last week of the regular season. Tickets go through the {tickets}.</p>
</article>
</div>

<h2 id="tiebreakers">Tiebreakers</h2>
<p><b>The MIAA does not publish its basketball tiebreaker rules.</b> As of October 3, 2026, miaa.org has no handbook, bylaws, sport regulations, or tiebreaker procedure for men's or women's basketball. The conference's {det} says that the champion is the team with the best MIAA won-loss record. It says that the tournament champion gets the NCAA bid. It does not say how the MIAA orders teams with the same record.</p>
<p>These rules decide seeds, first-round byes, home games, and in a tie for first place the regular-season title. They affect every team, player, and fan in the conference, and the conference should post them where anyone can read them.</p>
<p>Peer Division III leagues do. The CCIW, for example, posts its {cciw} on its public site.</p>
<p>This page will link to the MIAA's document the day it appears. Until then, the best available evidence is the school releases and fan posts below.</p>
<p class="small">Documents at miaa.net belong to the Mid-America Intercollegiate Athletics Association, a Division II league, and do not apply here.</p>
<article class="rule">
<h3>What the evidence supports</h3>
<p>This is an inference from the three ties below and the fan posts, not a published rule. Each step says how much evidence backs it.</p>
<ol>
<li><b>Head-to-head record among the tied teams.</b> Every source lists this first. In all three verified ties the teams split, so it decided nothing.</li>
<li><b>Record against the other teams, one at a time, from the top of the standings down.</b> Confirmed by the 2024 men's race. Trine and Calvin split, Trine went 2-0 against third-place Hope, and Calvin went 1-1. Trine got the No. 1 seed even though Calvin had the better second-half record, 6-1 to 5-2. So this step comes before the second-half step.</li>
<li><b>Road record in conference games.</b> Fan-posted only. In all three verified ties the road records were equal, so no case confirms this step or its place in the order.</li>
<li><b>Record in the second half of the double round robin.</b> Confirmed by the 2023 and 2024 women's races, and both school releases name it. In both cases the teams split head to head, had identical records against every other team, and had identical road records. That fits a step that sits after the first three.</li>
<li><b>Coin flip.</b> One fan post. No case.</li>
</ol>
<p class="small">Open questions: how the MIAA handles a three-team tie, which one fan post says it once resolved from the bottom of the standings up, and whether the second-half step counts the last half of the schedule or the second meeting with each opponent. The two readings matched in every case here.</p>
<details class="poll"><summary>The three verified ties</summary>
<div class="tablewrap"><table>
<thead><tr><th>Tie</th><th>Head to head</th><th>Vs. the next team down</th><th>Road</th><th>Second half</th><th>Result</th></tr></thead>
<tbody>
<tr><td class="lead">Women 2022-23, Hope and Trine, 14-2</td><td>1-1</td><td>Both 1-1 vs. Albion, both 2-0 vs. everyone else</td><td>7-1 each</td><td>Hope 8-0, Trine 6-2</td><td>Hope No. 1 seed</td></tr>
<tr><td class="lead">Women 2023-24, Calvin and Trine, 12-4</td><td>1-1</td><td>Both 0-2 vs. Hope, both 1-1 vs. Albion, both 2-0 vs. everyone else</td><td>6-2 each</td><td>Calvin 6-2, Trine 5-3</td><td>Calvin No. 2 seed</td></tr>
<tr><td class="lead">Men 2023-24, Trine and Calvin, 12-2</td><td>1-1</td><td>Trine 2-0 vs. Hope, Calvin 1-1 vs. Hope</td><td>6-1 each</td><td>Trine 5-2, Calvin 6-1</td><td>Trine No. 1 seed</td></tr>
</tbody></table></div>
<p class="small">Records computed from the schools' schedule pages for those seasons. Second half means each team's last eight (women) or seven (men) conference games, which were the second meetings with each opponent in each case.</p>
</details>
</article>
<div class="rulegrid">
<article class="rule">
<h3>What school releases say the MIAA used</h3>
<ul>
<li>Men, 2024: Trine took the No. 1 seed over co-champion Calvin. Trine swept third-place Hope and Calvin split with Hope. That is head-to-head results against the next team down the standings. Source: {calvin24m}.</li>
<li>Women, 2024: Calvin took the No. 2 seed over Trine "on a tiebreaker edge based on a superior second half record." Source: {calvin24w}.</li>
<li>Women, 2023: Hope took the No. 1 seed over co-champion Trine "after winning a second-half league record tiebreaker." Source: {hope23}.</li>
</ul>
</article>
<article class="rule">
<h3>What fans posted on d3boards.com</h3>
<p class="small">These are forum posts. The posters disagree with each other on the order of the steps, and none of it is official. Each quote names the poster and the date. This page does not link to d3boards.com threads.</p>
<ul>
<li><b>HOPEful</b>, quoted by deiscanton, d3boards.com, January 28, 2022. The MIAA order is head to head, then results against the other teams in descending order of the standings, then record in road league games.</li>
<li><b>deiscanton</b>, d3boards.com, January 28, 2022. In the MIAA the fourth step "apparently is best record/winning pct in the second half of the double round robin," and the fifth is a coin flip. The same post says that the conference does not publish the list on its website.</li>
<li><b>Flying Dutch Fan</b>, quoted in the same thread, d3boards.com, January 28, 2022. "The rules are clear - look at records the 2nd time through the double round robin."</li>
<li><b>sac</b>, d3boards.com, February 18, 2023. After a head-to-head split, the next step "should be go down the standings." The post says the MIAA broke the previous year's three-way tie by going through the standings from the bottom up instead.</li>
</ul>
</article>
</div>
</section>'''


# ---------------------------------------------------------------- page

CSS = r"""
/* Design tokens. Spacing steps: 4, 8, 12, 16, 24, 32, 48. Radii: 6, 10, 14. Control heights: 40 (top controls, inputs), 32 (pills, tabs). */
:root{--s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;--r1:6px;--r2:10px;--r3:14px;--ctl:40px;--pill:32px;--card-min:300px;
--fs-xs:.72rem;--fs-sm:.82rem;--fs-md:.9rem;--fs-base:1rem;--fs-h3:1.25rem;--fs-h2:1.6rem;--fs-h1:2.6rem;--fs-big:2.4rem;--fs-score:2rem}
:root{color-scheme:light;--bg:#f4f3ef;--surface:#ffffff;--surface2:#ecebe5;--line:#d8d5cb;--ink:#1e2229;--muted:#616873;--faint:#8c939d;--link:#1f4e79;--pos:#2e8b57;--neg:#c0504d;--live:#d6323c;--accent:#1f5fbf;--chip:#e9e7df;--on-team:#ffffff;__LIGHT__}
:root[data-theme="dark"]{color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#7d848f;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--accent:#7fb0ff;--chip:#2e343d;--on-team:#15181d;__DARK__}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#15181d;--surface:#1d2128;--surface2:#252a32;--line:#363c46;--ink:#e7e9ec;--muted:#a7adb7;--faint:#7d848f;--link:#8ab8e6;--pos:#5fc08a;--neg:#e2807c;--accent:#7fb0ff;--chip:#2e343d;--on-team:#15181d;__DARK__}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 "Barlow",-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:var(--link)}img{max-width:100%}p{margin:0 0 var(--s4)}p:last-child{margin-bottom:0}
main{max-width:1120px;margin:0 auto;padding:var(--s5) var(--s4) var(--s7)}
h1,h2,h3,.big,.score,.tab{font-family:"Barlow Condensed","Avenir Next Condensed","Arial Narrow",sans-serif}
h1{font-size:var(--fs-h1);line-height:1;margin:0 0 var(--s2);letter-spacing:.01em}
h2{font-size:var(--fs-h2);line-height:1.2;margin:var(--s7) 0 var(--s3);padding-bottom:var(--s2);border-bottom:1px solid var(--line)}
h3{font-size:var(--fs-h3);line-height:1.2;margin:var(--s5) 0 var(--s3);display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}h3 img{height:26px;width:26px;object-fit:contain}
.filterbar+h2{margin-top:var(--s6)}
.top{display:flex;flex-direction:column;align-items:flex-start;gap:var(--s4)}.sub{color:var(--muted);margin:0;max-width:760px}
.muted{color:var(--muted)}.small{font-size:var(--fs-md);color:var(--muted)}p.small{margin:0 0 var(--s4)}.pos{color:var(--pos)}.neg{color:var(--neg)}
button{font:inherit;cursor:pointer}
.disclaimer{margin:0 0 var(--s4);padding:var(--s2) var(--s3);border:1px solid var(--line);border-radius:var(--r2);background:var(--surface2);font-size:var(--fs-md);color:var(--muted)}
.controls{display:flex;gap:var(--s4);align-items:flex-start;flex-wrap:wrap}.ctl{display:flex;flex-direction:column;gap:var(--s1)}
.seg{display:inline-flex;align-items:stretch;height:var(--ctl);border:1px solid var(--line);border-radius:999px;overflow:hidden;background:var(--surface)}
.seglabel{font-size:var(--fs-xs);font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding-left:2px;line-height:1.4}
.seg button{border:0;background:transparent;color:var(--muted);padding:0 var(--s4);font:inherit;font-size:.95rem;cursor:pointer;min-width:44px}.seg button+button{border-left:1px solid var(--line)}.seg button.active{background:var(--accent);color:#fff;font-weight:700}.seg button.active::before{content:"\2713\00a0"}:root[data-theme="dark"] .seg button.active{color:#15181d}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .seg button.active{color:#15181d}}
.sp.active{background:var(--ink)!important;color:var(--bg)!important}
.livepill{display:none;align-items:center;gap:var(--s2);margin-top:var(--s3);font-size:var(--fs-sm);font-weight:600;color:var(--live)}.livepill i{width:8px;height:8px;border-radius:50%;background:var(--live);animation:pulse 1.4s infinite}body.has-live .livepill{display:inline-flex}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sport[hidden]{display:none}
.filterbar{position:sticky;top:0;z-index:5;background:var(--bg);margin-top:var(--s5);padding:var(--s3) 0;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:var(--s3) var(--s4);align-items:flex-end}
.search{display:flex;flex-direction:column;gap:var(--s1)}.search input{font:inherit;height:var(--ctl);padding:0 var(--s3);border:1px solid var(--line);border-radius:var(--r2);background:var(--surface);color:var(--ink);min-width:260px}
.pills{display:flex;flex-wrap:wrap;gap:var(--s2);align-items:center;min-height:var(--ctl)}
.pill{display:inline-flex;align-items:center;gap:var(--s2);height:var(--pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s3) 0 var(--s2);font-size:var(--fs-md)}.pill img{width:18px;height:18px;object-fit:contain}.pill.active{background:var(--team,var(--ink));color:var(--on-team);border-color:transparent;font-weight:700}.pill[data-team=""]{padding-left:var(--s3)}
.filtered [data-teams]:not([data-keep]):not(.on-team){display:none}.filtered [data-keep][data-teams]:not(.on-team){opacity:.45}.filtered tr.on-team td{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.games,.teams{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--card-min),1fr));gap:var(--s4)}
.game,.team{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);overflow:hidden;display:flex;flex-direction:column}
.game header,.team header{display:flex;align-items:center;gap:var(--s3);padding:var(--s3) var(--s4)}
.game header{border-bottom:1px solid var(--line)}.game header img,.game header .nologo{width:40px;height:40px;object-fit:contain;flex:none}.game header div{flex:1;min-width:0}
.who{font-weight:700;line-height:1.2}.what{font-size:var(--fs-md);color:var(--muted)}.team header .what{color:inherit;opacity:.85}
.team header img{width:48px;height:48px;object-fit:contain;flex:none;background:rgba(255,255,255,.92);border-radius:var(--r2);padding:var(--s1)}
.focus{margin-left:auto;align-self:flex-start;font-size:var(--fs-xs);font-weight:600;letter-spacing:.04em;text-transform:uppercase;border:1px solid currentColor;border-radius:999px;padding:2px var(--s2);background:transparent;color:inherit;opacity:.9;white-space:nowrap}
.body{padding:var(--s3) var(--s4) var(--s4);display:flex;flex-direction:column;gap:var(--s2)}
.scoreline{display:flex;align-items:baseline;justify-content:space-between;gap:var(--s3)}.game.pre .scoreline{display:none}.score{font-size:var(--fs-score);font-weight:700;line-height:1}.dash{color:var(--faint);padding:0 .1em}.status{font-weight:600;color:var(--muted)}
.game.live .status{color:var(--live)}.game.live .scoreline .status::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--live);margin-right:6px;animation:pulse 1.4s infinite}
dl{display:grid;grid-template-columns:max-content 1fr;gap:var(--s1) var(--s3);margin:0;font-size:.95rem}dt{color:var(--muted)}dd{margin:0}
.situation{display:none;padding:var(--s2) var(--s3);border-radius:var(--r2);background:var(--surface2);font-size:var(--fs-md);line-height:1.35}.situation.on{display:block}.situation .arrow{font-weight:600}.situation .arrow::before{content:"\25B6\00a0";color:var(--team)}.situation .bonus{color:var(--muted)}.situation .last{color:var(--muted);margin-top:var(--s1)}.situation .est{font-size:var(--fs-xs);color:var(--faint)}
.chip{display:inline-block;background:var(--chip);border-radius:var(--r1);padding:1px 7px;font-size:var(--fs-sm);margin:1px var(--s1) 1px 0;white-space:nowrap}.chip.conf{background:var(--accent);color:#fff;font-size:var(--fs-xs);font-weight:700;letter-spacing:.03em;vertical-align:1px;padding:0 6px}:root[data-theme="dark"] .chip.conf{color:#15181d}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .chip.conf{color:#15181d}}.chip.exh{font-size:var(--fs-xs);vertical-align:1px;padding:0 6px;color:var(--muted)}.chips:empty{display:none}.chips{margin:0}
.count{color:var(--muted);font-size:var(--fs-md)}
.record{display:flex;align-items:baseline;gap:var(--s3);flex-wrap:wrap}.big{font-size:var(--fs-big);font-weight:700;line-height:1;color:var(--team)}.standing{color:var(--muted)}
.badges{display:flex;flex-wrap:wrap;gap:var(--s2);margin:0}.badge{font-size:var(--fs-sm);border:1px solid var(--line);border-radius:var(--r1);padding:2px 7px;background:var(--surface2)}.badge b{color:var(--team)}a.badge{color:inherit;text-decoration:none}a.badge:hover{border-color:var(--team)}.badge.rv,.badge.nr{color:var(--muted)}.badge .src{font-size:var(--fs-xs);color:var(--muted);margin-left:3px}
.sitelink{font-size:var(--fs-sm);font-weight:600;border:1px solid var(--team);border-radius:999px;padding:3px var(--s3);text-decoration:none;color:var(--team);white-space:nowrap;margin-left:auto}.sitelink:hover{background:var(--team);color:var(--on-team)}
.rk{font-size:.8em;color:var(--muted);font-weight:600}
.links{font-size:var(--fs-md);margin:0;line-height:1.7}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r2);background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.93rem}th,td{padding:var(--s2) var(--s3);border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}th{background:var(--surface2);font-weight:600;font-size:var(--fs-sm);text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}
tbody tr:last-child td{border-bottom:0}td.lead,td:first-child,th:first-child{text-align:left}td img,dd img,.badge img{height:20px;width:20px;object-fit:contain;vertical-align:-4px;margin-right:var(--s1)}
tr.w td.res{color:var(--pos);font-weight:600}tr.l td.res{color:var(--neg);font-weight:600}tr.live td.res{color:var(--live);font-weight:600}td.loc{white-space:normal;min-width:160px;color:var(--muted);font-size:var(--fs-sm)}td.next{white-space:normal;min-width:220px}td.lk{font-size:var(--fs-sm)}
table.poll tr.miaa td{font-weight:700}
.tabs{display:flex;flex-wrap:wrap;gap:var(--s2);margin-bottom:var(--s3)}.tab{height:var(--pill);border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:0 var(--s4);font-size:var(--fs-base)}.tab.active{background:var(--team,var(--ink));color:var(--on-team);border-color:transparent;font-weight:700}
.teamplayers{margin-bottom:var(--s5)}.teamplayers h3{margin-top:0}.players{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:var(--s3)}
.player{display:flex;gap:var(--s3);align-items:center;min-width:0;background:var(--surface);border:1px solid var(--line);border-radius:var(--r2);padding:var(--s3)}.player .label{display:block;font-size:var(--fs-xs);text-transform:uppercase;letter-spacing:.05em;color:var(--team);font-weight:700}
.face{width:48px;height:48px;border-radius:50%;object-fit:cover;background:var(--surface2);flex:none}.initials{display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:var(--fs-base)}
.player>div{min-width:0}.pname{font-weight:700;line-height:1.2}.psub{font-size:var(--fs-sm);color:var(--muted)}.pline{font-size:var(--fs-md);margin-top:2px}
.gone{margin:var(--s3) 0 0}
details.poll{margin-top:var(--s3)}details.poll summary{cursor:pointer;color:var(--link);font-weight:600}details.poll .tablewrap{margin-top:var(--s3)}details.poll p{margin-top:var(--s3)}
.rules h2:first-child{margin-top:var(--s7)}.rulegrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:var(--s4)}.rule{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);padding:var(--s4)}.rule h3{margin:0 0 var(--s3)}.rule ul,.rule ol{margin:0 0 var(--s3);padding-left:1.2em}
.rule ol li{margin-bottom:var(--s2)}
.rules>article.rule{margin-bottom:var(--s4)}.rule li{margin-bottom:var(--s2)}.rule li:last-child{margin-bottom:0}.rule p:last-child{margin-bottom:0}
.more{margin-top:var(--s7);padding:var(--s4);border:1px solid var(--line);border-radius:var(--r2);background:var(--surface)}.more h2{margin:0 0 var(--s2);border:0;padding:0;font-size:var(--fs-h3)}.more p{margin:0 0 var(--s2)}.more p:last-child{margin-bottom:0}
footer{margin-top:var(--s6);font-size:var(--fs-sm);color:var(--muted);line-height:1.6}
@media (max-width:640px){:root{--fs-h1:2.1rem;--fs-score:1.7rem;--fs-big:2rem}main{padding-top:var(--s4)}.search input{min-width:0;width:100%}.search{width:100%}}
thead th[aria-sort]{cursor:pointer;user-select:none}thead th[aria-sort]::after{content:"";display:inline-block;width:.9em;color:var(--faint,var(--muted))}thead th[aria-sort="ascending"]::after{content:"\25B4"}thead th[aria-sort="descending"]::after{content:"\25BE"}
"""

JS = r"""
(function(){
const root=document.documentElement;
function store(k,v){try{localStorage.setItem(k,v)}catch(e){}}
function load(k){try{return localStorage.getItem(k)}catch(e){return null}}
const saved=load('miaa-theme');
if(saved==='dark'||saved==='light')root.setAttribute('data-theme',saved);
function isDark(){const t=root.getAttribute('data-theme');return t==='dark'||(!t&&matchMedia('(prefers-color-scheme:dark)').matches)}
function paintTheme(){const dark=isDark();document.querySelectorAll('.th').forEach(b=>b.classList.toggle('active',(b.dataset.theme==='dark')===dark));document.querySelectorAll('meta[name=theme-color]').forEach(m=>{m.removeAttribute('media');m.content=dark?'#15181d':'#f4f3ef'});}
document.querySelectorAll('.th').forEach(b=>b.addEventListener('click',()=>{root.setAttribute('data-theme',b.dataset.theme);store('miaa-theme',b.dataset.theme);paintTheme();}));
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',paintTheme);
paintTheme();

// Sport and team live in the hash (#wbb or #wbb/hope) so a view can be shared; the last sport is also remembered.
let sport='mbb',team='';
function readHash(){const h=location.hash.replace(/^#/,'');const m=/^(mbb|wbb)(?:\/([a-z]+))?$/.exec(h);if(m){sport=m[1];team=m[2]||'';return true;}return false;}
if(!readHash()){const s=load('miaa-sport');if(s==='wbb'||s==='mbb')sport=s;}
function writeHash(){const h='#'+sport+(team?'/'+team:'');if(location.hash!==h)history.replaceState(null,'',h);}
function paintSport(){
  document.querySelectorAll('.sport').forEach(s=>{s.hidden=s.dataset.sport!==sport;});
  document.querySelectorAll('.sp').forEach(b=>b.classList.toggle('active',b.dataset.sport===sport));
  store('miaa-sport',sport);
}
document.querySelectorAll('.sp').forEach(b=>b.addEventListener('click',()=>{sport=b.dataset.sport;team='';paintSport();paintFilter();writeHash();}));

// Team filter: hide everything that is not about the team; tables and tabs keep their rows and dim the others.
function paintFilter(){
  const sec=document.querySelector('.sport[data-sport="'+sport+'"]');if(!sec)return;
  document.querySelectorAll('.sport').forEach(s=>s.classList.remove('filtered'));
  sec.querySelectorAll('.on-team').forEach(el=>el.classList.remove('on-team'));
  sec.querySelectorAll('.pill').forEach(p=>p.classList.toggle('active',(p.dataset.team||'')===team));
  const input=sec.querySelector('.search input');
  if(input&&!team)input.value='';
  if(!team){showTab(sec,'all');return;}
  sec.classList.add('filtered');
  sec.querySelectorAll('[data-teams]').forEach(el=>{if(el.dataset.teams.split(' ').includes(team))el.classList.add('on-team');});
  showTab(sec,team);
}
function setTeam(slug){team=slug||'';paintFilter();writeHash();}
document.querySelectorAll('.pill').forEach(p=>p.addEventListener('click',()=>setTeam(p.dataset.team)));
document.querySelectorAll('.focus').forEach(b=>b.addEventListener('click',()=>{setTeam(b.dataset.focus);window.scrollTo({top:0,behavior:'smooth'});}));
document.querySelectorAll('.search input').forEach(inp=>{
  const sec=inp.closest('.sport');
  const pills=[...sec.querySelectorAll('.pill[data-team]')].filter(p=>p.dataset.team);
  const words=p=>{const card=sec.querySelector('.team[data-teams="'+p.dataset.team+'"]');return (p.textContent+' '+(card?card.querySelector('header').textContent:'')).toLowerCase();};
  inp.addEventListener('input',()=>{
    const q=inp.value.trim().toLowerCase();
    pills.forEach(p=>{p.hidden=q&&!words(p).includes(q);});
    const vis=pills.filter(p=>!p.hidden);
    if(q&&vis.length===1){team=vis[0].dataset.team;paintFilter();writeHash();inp.value=q;}
    else if(!q&&team){team='';paintFilter();writeHash();}
  });
});
window.addEventListener('hashchange',()=>{if(readHash()){paintSport();paintFilter();}});
paintSport();paintFilter();writeHash();

// Tipoff times in the chosen time zone: Eastern, Central, or the device's own.
const deviceTz=Intl.DateTimeFormat().resolvedOptions().timeZone||'America/Detroit';
const tzNames={'America/Detroit':'Eastern time','America/Chicago':'Central time'};
let tzChoice=load('miaa-tz')||'local';
function zone(){return tzChoice==='local'?deviceTz:tzChoice}
function renderTimes(){
  const z=zone();
  document.querySelectorAll('time[datetime]').forEach(t=>{
    if(t.dataset.tbd)return;
    const d=new Date(t.getAttribute('datetime'));
    const opts=t.dataset.fmt==='full'?{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:z}:{hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:z};
    t.textContent=new Intl.DateTimeFormat('en-US',opts).format(d);
  });
  document.querySelectorAll('.tz').forEach(b=>b.classList.toggle('active',b.dataset.tz===tzChoice));
  document.querySelectorAll('.tznote').forEach(note=>{note.textContent='Tipoff times are in '+(tzChoice==='local'?"your device's time zone ("+deviceTz.replace(/_/g,' ')+")":tzNames[tzChoice])+'.';});
}
document.querySelectorAll('.tz').forEach(b=>b.addEventListener('click',()=>{tzChoice=b.dataset.tz;store('miaa-tz',tzChoice);renderTimes();}));
renderTimes();

// Countdowns.
function tick(){
  const now=Date.now();
  document.querySelectorAll('.count[data-tip]').forEach(el=>{
    const ms=new Date(el.dataset.tip)-now;
    if(ms<=0){el.textContent='';return}
    const m=Math.floor(ms/60000),d=Math.floor(m/1440),h=Math.floor((m%1440)/60),mm=m%60;
    el.textContent='in '+(d?d+'d ':'')+(d||h?h+'h ':'')+(d?'':mm+'m');
  });
}
tick();setInterval(tick,60000);

// Live scores from the stat crew's own feed: Sidearm (sidearmstats.com/<client>/<sport>/game.json)
// or PrestoSports (data.prestolivestats.com/xml/<site>/events/<event>.xml). No national API covers these games.
const cards=[...document.querySelectorAll('.game[data-game]')];
function etParts(iso){const p=new Intl.DateTimeFormat('en-US',{timeZone:'America/Detroit',year:'numeric',month:'numeric',day:'numeric'}).formatToParts(new Date(iso));const g=k=>p.find(x=>x.type===k).value;return {y:g('year'),m:g('month'),d:g('day')};}
function mdy(iso){const t=etParts(iso);return t.m+'/'+t.d+'/'+t.y;}
function inWindow(c,now){const t=new Date(c.dataset.date).getTime();return c.classList.contains('live')||(t-now<30*60000&&now-t<4*3600000);}
function windowOpen(){const now=Date.now();return cards.some(c=>inWindow(c,now));}
function escHtml(t){return String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function ordinal(n){return ['','1st','2nd','3rd','4th'][n]||'';}
// Crews write players as "Last,First" or "LAST,FIRST"; readers want "First Last".
function fixNames(t){return String(t||'').replace(/\b([A-Z][\w'\-]+(?:,? (?:Jr|Sr|II|III|IV)\.?)?),([A-Z][\w'\-.]+)\b/g,(m,a,b)=>cap(b)+' '+cap(a));}
function cap(s){return s.length>3&&s===s.toUpperCase()?s.charAt(0)+s.slice(1).toLowerCase():s;}
function fmtClock(sec){sec=Math.max(0,+sec||0);return Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0');}
// Period labels: two 20-minute halves for the men, four 10-minute quarters for the women, then OT.
function periodLabel(period,regulation){
  if(period>regulation)return 'OT'+(period-regulation>1?period-regulation:'');
  return regulation===2?ordinal(period)+' half':ordinal(period)+' quarter';
}
function statusText(period,clockSec,clockText,regulation){
  const zero=clockSec===0||/^0?0:00$/.test(clockText||'');
  if(zero&&period===regulation/2)return 'Halftime';
  if(zero&&period<regulation)return 'End of '+periodLabel(period,regulation);
  return (clockText||fmtClock(clockSec))+' '+periodLabel(period,regulation);
}
function isHalftime(period,clockSec,clockText,regulation){return period===regulation/2&&(clockSec===0||/^0?0:00$/.test(clockText||''));}
function setScore(el,home,away,status){
  const mine=el.dataset.home==='1'?home:away,other=el.dataset.home==='1'?away:home;
  el.querySelector('.score').innerHTML=mine+'<span class="dash">-</span>'+other;
  el.querySelector('.status').textContent=status;
  [el.dataset.game,el.dataset.twin].filter(Boolean).forEach(id=>{
    document.querySelectorAll('tr[data-game="'+id+'"]').forEach(tr=>{const h=tr.dataset.home==='1';tr.querySelector('td.res').textContent=(h?home:away)+'-'+(h?away:home)+', '+status;tr.classList.add('live');});
  });
}
function showSituation(el,s){
  const box=el.querySelector('.situation');if(!box)return;
  if(!s){box.classList.remove('on');box.textContent='';return;}
  const parts=[];
  if(s.arrow)parts.push('<span class="arrow">'+escHtml(s.arrow)+' has the possession arrow</span> <span class="est">estimated from the play-by-play</span>');
  if(s.bonus)parts.push('<span class="bonus">'+escHtml(s.bonus)+'</span>');
  let h=parts.length?'<div>'+parts.join(' · ')+'</div>':'';
  if(s.last)h+='<div class="last">Last play: '+escHtml(s.last)+'</div>';
  if(!h){box.classList.remove('on');box.textContent='';return;}
  box.innerHTML=h;box.classList.add('on');
}
// Sidearm's Context string reads "Adrian BONUS; Calvin BONUS2".
function bonusText(ctx,H,V){
  const out=[];String(ctx||'').split(';').forEach(tok=>{const m=/^\s*(.+?)\s+BONUS(2?)\s*$/i.exec(tok);if(m)out.push(m[1]+(m[2]?' in the double bonus':' in the bonus'));});
  return out.join(', ');
}
// Possession arrow. No feed publishes it, so it is worked out: the team that did not get the opening possession
// holds the arrow first, each held ball flips it, and in a quarters game each quarter start after the first uses it.
const arrows=new Map();
function arrowFrom(plays,regulation){
  // plays: oldest first, each {team, period, text}; team is 'H' or 'V'.
  const first=plays.find(p=>p.team&&!/^(START|END|SUBS?|COMMERCIAL|TIMEOUT|FULL|SHORT|MEDIA)$/i.test(p.type||''));
  if(!first)return null;
  let holder=first.team==='H'?'V':'H';
  let period=1;
  for(const p of plays){
    if(p.period&&p.period>period){period=p.period;if(regulation===4&&period>1&&period<=regulation&&period!==regulation/2+1)holder=holder==='H'?'V':'H';}
    if(/held ball|jump ball|alternat/i.test(p.text||''))holder=holder==='H'?'V':'H';
  }
  return holder;
}
function sidearmArrow(url,regulation){
  if(!arrows.has(url))arrows.set(url,(async()=>{
    const r=await fetch(url+'?detail=full',{cache:'no-store'});const j=await r.json();
    const plays=(j.Plays||[]).map(p=>({team:p.Team==='HomeTeam'?'H':p.Team==='VisitingTeam'?'V':null,period:+p.Period||0,type:p.Type,text:p.Narrative}));
    return arrowFrom(plays,regulation);
  })().catch(()=>null));
  return arrows.get(url);
}
function prestoArrow(x,regulation){
  const plays=[];x.querySelectorAll('plays period').forEach(per=>{const n=+per.getAttribute('number')||0;per.querySelectorAll('play').forEach(p=>plays.push({team:p.getAttribute('vh'),period:n,type:p.getAttribute('action'),text:(p.getAttribute('action')||'')+' '+(p.getAttribute('type')||'')}));});
  return arrowFrom(plays,regulation);
}
// Share of regulation played: halves of 20 minutes for the men, quarters of 10 for the women, 5-minute overtimes.
function progressOf(period,clockSec,regulation){
  const len=regulation===2?1200:600,total=regulation*len;
  if(period<=regulation)return((period-1)*len+(len-clockSec))/total;
  return(total+(period-regulation-1)*300+(300-clockSec))/total;
}
function clockToSec(t){const m=/^(\d+):(\d+)/.exec(t||'');return m?(+m[1])*60+(+m[2]):0;}
// Card order: finished games first (earliest finish first), then games in progress (furthest along first),
// then upcoming games by tipoff. A finish time is known only for games that ended while the page was open,
// so other finals use tipoff plus two hours.
function cardKey(el){
  const tip=new Date(el.dataset.date).getTime();
  if(el.classList.contains('final'))return[0,el.dataset.finished?+el.dataset.finished:tip+7200000];
  if(el.classList.contains('live'))return[1,-(+el.dataset.progress||0)];
  return[2,tip];
}
function sortCards(){
  document.querySelectorAll('.games').forEach(box=>{
    const items=[...box.children].filter(c=>c.matches('.game'));
    items.sort((a,b)=>{const x=cardKey(a),y=cardKey(b);return x[0]-y[0]||x[1]-y[1]||new Date(a.dataset.date)-new Date(b.dataset.date);});
    items.forEach(c=>box.appendChild(c));
  });
}
async function feedState(el){
  const url=el.dataset.feed,type=el.dataset.feedType;if(!url)return null;
  const r=await fetch(url,{cache:'no-store'});if(!r.ok)return null;
  const day=mdy(el.dataset.date);
  if(type==='sidearm'){
    const g=(await r.json()).Game;
    if(!g||!g.HasStarted||g.Date!==day)return null;
    const rules=g.Rules||{};const regulation=(+rules.PeriodMinutes||20)>=20?2:4;
    const H={id:g.HomeTeam.Id,name:g.HomeTeam.Name},V={id:g.VisitingTeam.Id,name:g.VisitingTeam.Name};
    const period=+g.Period||0,clockSec=+g.ClockSeconds||0;
    const last=(g.LastPlays||[])[0];
    let arrow=null;
    if(isHalftime(period,clockSec,'',regulation)){const a=await sidearmArrow(url,regulation);arrow=a==='H'?H.name:a==='V'?V.name:null;}
    return {complete:!!g.IsComplete,home:+g.HomeTeam.Score||0,away:+g.VisitingTeam.Score||0,status:statusText(period,clockSec,'',regulation),progress:progressOf(period,clockSec,regulation),
      arrow,bonus:bonusText(g.Context,H,V),last:last?fixNames(last.Narrative):''};
  }
  if(type==='presto'){
    const x=new DOMParser().parseFromString(await r.text(),'application/xml');
    const venue=x.querySelector('venue'),st=x.querySelector('status'),rules=x.querySelector('rules');
    if(!venue||!st||venue.getAttribute('date')!==day||!x.querySelector('play'))return null;
    const regulation=+(rules&&rules.getAttribute('prds'))||2;
    const teams={};x.querySelectorAll('team').forEach(t=>{const ls=t.querySelector('linescore');teams[t.getAttribute('vh')]={name:t.getAttribute('name'),score:+(ls&&ls.getAttribute('score'))||0};});
    const period=+st.getAttribute('period')||0,clockText=st.getAttribute('clock')||'';
    const H=teams.H||{name:venue.getAttribute('homename'),score:0},V=teams.V||{name:venue.getAttribute('visname'),score:0};
    let arrow=null;
    if(isHalftime(period,-1,clockText,regulation)){const a=prestoArrow(x,regulation);arrow=a==='H'?H.name:a==='V'?V.name:null;}
    const plays=[...x.querySelectorAll('plays period:last-of-type play')];const lp=plays[plays.length-1];
    const last=lp?[lp.getAttribute('team'),fixNames(lp.getAttribute('checkname')||''),lp.getAttribute('action'),lp.getAttribute('type')].filter(Boolean).join(' ').toLowerCase().replace(/^\w/,c=>c.toUpperCase()):'';
    return {complete:st.getAttribute('complete')==='Y',home:H.score,away:V.score,status:statusText(period,-1,clockText,regulation),progress:progressOf(period,clockToSec(clockText),regulation),arrow,bonus:'',last};
  }
  return null;
}
async function applyFeed(el){
  let f=null;try{f=await feedState(el);}catch(e){}
  if(!f)return false;
  if(f.complete){
    const home=el.dataset.home==='1';const mine=home?f.home:f.away,other=home?f.away:f.home;
    setScore(el,f.home,f.away,'Final · '+(mine>other?'W':mine<other?'L':'T'));
    if(!el.classList.contains('final'))el.dataset.finished=Date.now();
    el.classList.add('final');el.classList.remove('live','pre');showSituation(el,null);
    return false;
  }
  setScore(el,f.home,f.away,f.status);
  el.dataset.progress=f.progress;
  el.classList.add('live');el.classList.remove('pre');
  showSituation(el,f);
  return true;
}
async function refresh(){
  const now=Date.now();
  const pending=cards.filter(c=>c.dataset.feed&&!c.classList.contains('final')&&inWindow(c,now));
  if(!pending.length){document.body.classList.remove('has-live');return;}
  let anyLive=false;
  await Promise.all(pending.map(async c=>{if(await applyFeed(c))anyLive=true;}));
  sortCards();
  document.body.classList.toggle('has-live',anyLive);
  const stamp='Live scores checked '+new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:zone()}).format(new Date());
  document.querySelectorAll('.livestamp').forEach(s=>s.textContent=stamp);
}
sortCards();
refresh();
setInterval(()=>{if(windowOpen())refresh();},60000);

// Schedule tabs, one set per sport.
function showTab(sec,name){
  const tabs=[...sec.querySelectorAll('.tab')];
  if(!tabs.some(t=>t.dataset.tab===name))name='all';
  tabs.forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  sec.querySelectorAll('.pane').forEach(p=>p.hidden=p.dataset.pane!==name);
}
document.querySelectorAll('.sport').forEach(sec=>{
  sec.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>showTab(sec,t.dataset.tab)));
  sec.querySelectorAll('.tablink').forEach(a=>a.addEventListener('click',()=>showTab(sec,a.dataset.tab)));
});
})();
// Sortable tables: click a header to sort by that column; click again to reverse.
(function(){
function cellKey(td){if(!td)return '';const t=td.querySelector('time[datetime]');const raw=td.dataset.sort!==undefined?td.dataset.sort:t?t.getAttribute('datetime'):td.textContent.trim();const n=parseFloat(String(raw).replace(/[,%#$]/g,''));return isNaN(n)||!/^[-+#$]?[\d.,]+%?$/.test(String(raw).replace(/\s/g,''))?String(raw).toLowerCase():n;}
document.querySelectorAll('table').forEach(t=>{
  const head=t.tHead,body=t.tBodies[0];if(!head||!body||body.rows.length<2)return;
  const ths=[...head.rows[head.rows.length-1].cells];
  ths.forEach((th,i)=>{th.setAttribute('aria-sort','none');th.setAttribute('role','button');th.tabIndex=0;
    const go=()=>{const dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';ths.forEach(h=>h.setAttribute('aria-sort','none'));th.setAttribute('aria-sort',dir);
      const rows=[...body.rows];rows.sort((a,b)=>{const x=cellKey(a.cells[i]),y=cellKey(b.cells[i]);const r=typeof x==='number'&&typeof y==='number'?x-y:typeof x==='number'?-1:typeof y==='number'?1:String(x).localeCompare(String(y));return dir==='ascending'?r:-r;});
      rows.forEach(r=>body.appendChild(r));};
    th.addEventListener('click',go);th.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});});
});
})();
"""


def main():
    built = datetime.now(EASTERN).strftime("%Y-%m-%d %-I:%M %p")
    fetched = datetime.fromisoformat(SEASON["fetched_at"]).astimezone(EASTERN).strftime("%Y-%m-%d %-I:%M %p")
    css = CSS.replace("__LIGHT__", color_vars(light_variant)).replace("__DARK__", color_vars(dark_variant))
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="darkreader-lock">
<meta name="theme-color" content="#f4f3ef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#15181d" media="(prefers-color-scheme: dark)">
<title>{esc(SITE_NAME)}</title>
<meta name="description" content="MIAA Division III basketball, men's and women's, on one page: schedules, live scores, records, standings, D3hoops.com poll, NPI rank, rosters, stats, and where to watch.">
<link rel="icon" href="assets/miaa.png"><link rel="apple-touch-icon" href="assets/miaa.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;600;700&display=swap" rel="stylesheet">
<script data-goatcounter="https://themissingmiaahoopsdashboard.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>
<style>{css}</style></head><body><main>
<p class="disclaimer">This site is not affiliated with the Michigan Intercollegiate Athletic Association (MIAA).</p>
<div class="top"><div><h1>{esc(SITE_NAME)}</h1>
<p class="sub">Every MIAA basketball team, men's and women's, on one page for {esc(SEASON["season"])}. The next game and the live score, standings, the D3hoops.com poll, and NPI rank, with links to each school's schedule, roster, statistics, live stats, and stream. The numbers here are headlines. Each one links to the page that has the rest.</p>
<span class="livepill"><i></i>Games in progress</span></div><div class="controls"><div class="ctl"><span class="seglabel" id="lbl-sport">Sport</span><div class="seg" role="group" aria-labelledby="lbl-sport"><button type="button" class="sp" data-sport="mbb">Men</button><button type="button" class="sp" data-sport="wbb">Women</button></div></div><div class="ctl"><span class="seglabel" id="lbl-times">Times</span><div class="seg" role="group" aria-labelledby="lbl-times"><button type="button" class="tz" data-tz="America/Detroit">Eastern</button><button type="button" class="tz" data-tz="America/Chicago">Central</button><button type="button" class="tz" data-tz="local">Device</button></div></div><div class="ctl"><span class="seglabel" id="lbl-theme">Theme</span><div class="seg" role="group" aria-labelledby="lbl-theme"><button type="button" class="th" data-theme="light">Light</button><button type="button" class="th" data-theme="dark">Dark</button></div></div></div></div>

{sport_section("mbb")}
{sport_section("wbb")}
{tournament_section()}

<section class="more">
<h2>Where the numbers come from</h2>
<p>Men's NPI, efficiency ratings, and projections: {link("https://d3datacast.com/", "D3 Datacast")}.</p>
<p>Women's NPI, preseason rankings, and season simulations: {link("https://thed3statlab.com/", "The D3 Stat Lab")}, run by the person behind this page.</p>
<p>Polls: {link("https://www.d3hoops.com/top25/", "D3hoops.com")}.</p>
<p>Schedules, results, rosters, statistics, and live stats: each school's athletics site.</p>
<p>Official conference standings: {link("https://miaa.org/", "miaa.org")}.</p>
</section>
<footer>Built {esc(built)} Eastern. School data fetched {esc(fetched)} Eastern. This page is not affiliated with the MIAA, its member schools, D3hoops.com, D3 Datacast, or the NCAA. Logos belong to their schools.</footer>
</main>
<script>{JS}</script>
</body></html>
"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
