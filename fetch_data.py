#!/usr/bin/env python3
"""Pull everything the dashboard needs into data/season.json.

Sources, all public and unauthenticated:
  School schedule pages   <school>/sports/<sport>/schedule        (games, results, links, live stats)
  School roster pages     <school>/sports/<sport>/roster          (which season is posted)
  School stats pages      <school>/sports/<sport>/stats           (category leaders)
  D3hoops.com             d3hoops.com/top25/<men|women>/          (Top 25 poll)
  D3 Datacast             published Google Sheet CSV              (men's NPI, efficiency)
  The D3 Stat Lab         thed3statlab.com/data/*.json            (women's NPI, preseason rank)

Olivet runs PrestoSports instead of Sidearm, so it has its own parsers.
"""
import csv
import html
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SCHOOLS = json.loads((BASE / "schools.json").read_text())
SEASON = "2026-27"
SEASON_START_YEAR = 2026
FIRST_GAME_DAY = "2026-11-06"  # NCAA Division III opening day; anything earlier is an exhibition
LAST_GAME_DAY = "2027-02-21"  # last regular-season day; later rows are placeholders for MIAA Tournament games
DEPARTURES = json.loads((BASE / "departures.json").read_text()) if (BASE / "departures.json").exists() else {}
GONE_YEARS = {"Senior", "Graduate", "Redshirt Senior", "Fifth Year"}
SPORTS = {"mbb": "Men's Basketball", "wbb": "Women's Basketball"}
SIDEARM_SPORT = {"mbb": "mbball", "wbb": "wbball"}
EASTERN = ZoneInfo("America/Detroit")
CENTRAL = ZoneInfo("America/Chicago")
ZONES = {"ET": EASTERN, "EST": EASTERN, "EDT": EASTERN, "EASTERN": EASTERN,
         "CT": CENTRAL, "CST": CENTRAL, "CDT": CENTRAL, "CENTRAL": CENTRAL,
         "MT": ZoneInfo("America/Denver"), "MST": ZoneInfo("America/Denver"), "MDT": ZoneInfo("America/Denver"), "MOUNTAIN": ZoneInfo("America/Denver"),
         "PT": ZoneInfo("America/Los_Angeles"), "PST": ZoneInfo("America/Los_Angeles"), "PDT": ZoneInfo("America/Los_Angeles"), "PACIFIC": ZoneInfo("America/Los_Angeles")}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36 (MIAA dashboard)",
      "Accept": "text/html,application/json,text/csv;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
TAG = re.compile(r"<[^>]+>")
WARNINGS = []  # parser fallbacks worth a look; written to season.json["errors"] so the page footer shows them
D3DATACAST_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR1ycFpv6ciu3cCFcVptinzHtlVFaM4hmZpV0KZSmMCMlb9h39m3n4bByXz3i_SKuE0Me7tXmmhZHYT/pub?gid={gid}&single=true&output=csv"
D3DATACAST = {
    "mbb": {"npi_gid": "1357390615", "eff_gid": "201951160", "npi_url": "https://d3datacast.com/npi/mbb/", "eff_url": "https://d3datacast.com/efficiency-ratings/"},
}
STATLAB = "https://thed3statlab.com"
MEMBERS = {sport: {s["slug"] for s in SCHOOLS if sport in s["sports"]} for sport in SPORTS}
MEMBER_NAMES = {s["slug"]: {s["name"].lower(), s["full_name"].lower(), s["name"].lower().replace("saint", "st.")} for s in SCHOOLS}


def now():
    return datetime.now(CENTRAL)


def get(url, as_json=False, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            break
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt == 2 or not isinstance(getattr(exc, "reason", exc), TimeoutError) and "timed out" not in str(exc):
                raise
    return json.loads(body) if as_json else body.decode("utf-8", "replace")


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", fragment or ""))).strip()


def absolute(url, base):
    return urllib.parse.urljoin(base, html.unescape(url.strip())) if url else None


def season_date(month, day, hour=12, minute=0, zone=EASTERN):
    """A calendar date in the 2026-27 season: August to December fall in 2026, January to July in 2027."""
    year = SEASON_START_YEAR if month >= 8 else SEASON_START_YEAR + 1
    return datetime(year, month, day, hour, minute, tzinfo=zone)


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_month_day(label):
    m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})", label or "")
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return MONTHS[m.group(1).lower()], int(m.group(2))


def parse_time(label):
    """'7 PM (CT)', '7:30 PM EST', '6:00 PM Central', '12 PM', 'TBA' -> (hour, minute, zone) or None when the time is TBA."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?(?:\s*\(?([A-Za-z]{2,8})\)?)?", label or "", re.I)
    if not m:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).upper() == "P" else 0)
    zone = ZONES.get((m.group(4) or "ET").upper(), EASTERN)
    return hour, int(m.group(2) or 0), zone


def text_schedule_times(cfg):
    """Tipoff times from the school's plain-text schedule feed (schedule_txt.ashx), keyed by (month, day, opponent lowercased).

    The feed is a fixed-width table: 'Nov 7 (Sat)    5:00 PM    Home   Franklin College    Holland, MI ...'. It is the
    fallback when the schedule page's markup hides a time. Returns {} when the school has no feed or the feed fails."""
    url = cfg.get("schedule_txt")
    if not url:
        return {}
    try:
        body = get(url)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {}
    times = {}
    for line in body.splitlines():
        m = re.match(r"\s*([A-Za-z]{3})\.?\s+(\d{1,2})\s+\([A-Za-z]{3}\)\s{2,}(.+?)\s{2,}(Home|Away|Neutral)\s{2,}(.+?)(?:\s{2,}|$)", line)
        if not m or m.group(1).lower() not in MONTHS:
            continue
        month_day = (MONTHS[m.group(1).lower()], int(m.group(2)))
        parts = parse_time(m.group(3))
        if parts:
            times[month_day + (strip_poll_marks(m.group(5)).lower(),)] = parts
    return times


def time_from_text_feed(times, month_day, opponent):
    """The text feed's time for a game: by date and opponent, else by date when the feed lists one game that day."""
    if not times or month_day is None:
        return None
    exact = times.get(month_day + ((opponent or "").lower(),))
    if exact:
        return exact
    same_day = [v for k, v in times.items() if k[:2] == month_day]
    return same_day[0] if len(same_day) == 1 else None


def member_slug(opponent_name):
    name = (opponent_name or "").lower()
    name = re.sub(r"\s+", " ", name)
    for slug, names in MEMBER_NAMES.items():
        if any(n and (name == n or name.startswith(n + " ") or n in name) for n in names):
            return slug
    return None


def short_name(name):
    """'University of Wisconsin-Eau Claire' -> 'UW-Eau Claire', 'Edgewood College' -> 'Edgewood'."""
    n = html.unescape(name or "").strip()
    n = re.sub(r"^The\s+", "", n)
    n = re.sub(r"^University of Wisconsin[-\s]", "UW-", n)
    n = re.sub(r"^University of (.+)$", r"\1", n)
    n = re.sub(r"\s+(University|College)(\s+of\s+[A-Z][a-z]+)?$", "", n)
    n = re.sub(r"\s+\(.*?\)$", "", n) if len(n) > 22 else n
    return n or name


def strip_poll_marks(name):
    """Drop the poll marks some schools print before an opponent: "#14/21 Baldwin Wallace", "RV/RV Calvin", "(RV) DePauw or (#20/RV) Illinois Wesleyan"."""
    return re.sub(r"(^|\bor )\(?(?:#\d+|RV)(?:/(?:#?\d+|RV))*\)?\s+", r"\1", name or "").strip()


def game_record(school, sport, index, month_day, time_parts, home, neutral, opponent, opp_logo, location, links, result_text, note=""):
    if month_day is None:
        return None
    opponent = strip_poll_marks(opponent)
    # A tournament host lists the games it does not play ("La Roche vs Oshkosh" on Trine's 2026-11-13 schedule).
    # Two names in the opponent cell mean the row is not this school's game.
    if re.search(r"\S\s+vs\.?\s+\S", opponent, re.I):
        return None
    month, day = month_day
    if time_parts:
        hour, minute, zone = time_parts
        when = season_date(month, day, hour, minute, zone)
        tbd = False
    else:
        when = season_date(month, day, 12, 0, EASTERN)
        tbd = True
    result = pf = pa = None
    state = "pre"
    status = ""
    m = re.search(r"\b([WLT])\b\s*,?\s*(\d{1,3})\s*-\s*(\d{1,3})", result_text or "")
    if m:
        result, pf, pa = m.group(1), int(m.group(2)), int(m.group(3))
        state = "post"
        if re.search(r"\bOT\b|\(\d*OT\)", result_text):
            status = "Final (OT)"
    elif re.search(r"postponed|canceled|cancelled", result_text or "", re.I):
        status = re.search(r"postponed|canceled|cancelled", result_text, re.I).group(0).capitalize()
    opp_slug = member_slug(opponent)
    local_day = when.astimezone(EASTERN).strftime("%Y-%m-%d")
    if local_day > LAST_GAME_DAY:
        return None
    exhibition = local_day < FIRST_GAME_DAY or bool(re.search(r"exhibition|scrimmage", f"{note} {opponent}", re.I))
    return {
        "id": f"{school['slug']}-{sport}-{index}",
        "exhibition": exhibition,
        "date": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "time_tbd": tbd,
        "home": home,
        "neutral": neutral,
        "opponent": {"name": opponent, "short": short_name(opponent), "logo": opp_logo, "slug": opp_slug},
        "conference": bool(opp_slug) and opp_slug in MEMBERS[sport] and school["slug"] in MEMBERS[sport] and when.month in (12, 1, 2),
        "location": location,
        "note": note,
        "state": state,
        "result": result,
        "pf": pf,
        "pa": pa,
        "status": status,
        "links": links,
        "live_feed": None,
    }


# ---------------------------------------------------------------- Sidearm schedule

def game_blocks(page, start_pattern):
    """Slices of the page, one per game, from each game's opening tag to the next game's (the last one ends at the page footer)."""
    starts = [m.start() for m in re.finditer(start_pattern, page)]
    blocks = []
    for i, a in enumerate(starts):
        b = starts[i + 1] if i + 1 < len(starts) else len(page)
        chunk = page[a:b]
        if i + 1 == len(starts):
            cut = re.search(r"<footer|</section>|<div[^>]*class=\"[^\"]*(?:footer|page-content-body)", chunk)
            if cut:
                chunk = chunk[:cut.start()]
        blocks.append(chunk)
    return blocks


def sidearm_schedule(school, sport, cfg):
    page = get(cfg["schedule_url"])
    base = cfg["schedule_url"]
    blocks = game_blocks(page, r'<li[^>]*class="sidearm-schedule-game[\s"]')
    games = []
    text_times = None
    from_text_feed = 0
    for i, b in enumerate(blocks):
        cls = re.search(r'class="([^"]*)"', b).group(1)
        home = "sidearm-schedule-home-game" in cls
        neutral = "sidearm-schedule-neutral-game" in cls
        gid = re.search(r'data-game-id="(\d+)"', b)
        # The date cell holds the date and the time in spans, but the markup varies by school: Hope wraps a stray
        # </span> and a "/" separator between them. Read the time from the whole cell, not from a span position.
        date_m = re.search(r'sidearm-schedule-game-opponent-date[^>]*>(.*?)</div>', b, re.S)
        date_text = text(date_m.group(1)) if date_m else ""
        month_day = parse_month_day(date_text)
        time_m = re.search(r'sidearm-schedule-game-time[^>]*>(.*?)</span>', b, re.S)
        time_parts = parse_time(text(time_m.group(1))) if time_m else None
        if time_parts is None:
            time_parts = parse_time(re.sub(r"^.*?\(\w{3}\)", "", date_text))
        opp_m = re.search(r'sidearm-schedule-game-opponent-name[^>]*>(.*?)</div>', b, re.S)
        opponent = text(opp_m.group(1)) if opp_m else ""
        if time_parts is None:
            if text_times is None:
                text_times = text_schedule_times(cfg)
            time_parts = time_from_text_feed(text_times, month_day, strip_poll_marks(opponent))
            if time_parts:
                from_text_feed += 1
        logo_m = re.search(r'sidearm-schedule-game-opponent-logo.*?<img[^>]*(?:data-src|src)="([^"]+)"', b, re.S)
        opp_logo = absolute(logo_m.group(1), base) if logo_m else None
        loc_m = re.search(r'sidearm-schedule-game-location[^>]*>(.*?)</div>', b, re.S)
        location = ", ".join(text(s) for s in re.findall(r"<span[^>]*>(.*?)</span>", loc_m.group(1), re.S) if text(s)) if loc_m else ""
        # Anchor on the class boundary: Hope's date cell carries a "sidearm-schedule-game-result-final" span that
        # would otherwise match first and hide the score.
        result_m = re.search(r'sidearm-schedule-game-result[\s"][^>]*>(.*?)</div>', b, re.S)
        result_text = text(result_m.group(1)) if result_m else ""
        links = {}
        for href, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S):
            label_t = text(label).lower()
            key = {"watch": "video", "video": "video", "live stats": "live_stats", "live stats (opens in new window)": "live_stats",
                   "tickets": "tickets", "box score": "boxscore", "recap": "recap"}.get(label_t)
            if key and key not in links:
                links[key] = absolute(href, base)
        tourney = re.search(r'sidearm-schedule-game-tournament[^>]*>(.*?)</div>', b, re.S)
        note = text(tourney.group(1)) if tourney else ""
        g = game_record(school, sport, gid.group(1) if gid else i, month_day, time_parts, home, neutral, opponent, opp_logo, location, links, result_text, note)
        if g and opponent:
            games.append(g)
    if not games:
        raise ValueError("no games parsed")
    if from_text_feed:
        WARNINGS.append(f"{school['name']} {sport} schedule: {from_text_feed} of {len(games)} tipoff times came from the text feed, not the page")
    return sorted(games, key=lambda g: g["date"])


# ---------------------------------------------------------------- PrestoSports schedule (Olivet)

def presto_schedule(school, sport, cfg):
    page = get(cfg["schedule_url"])
    base = cfg["schedule_url"]
    blocks = game_blocks(page, r'<div class="card w-100 event-row\b')
    games = []
    for i, b in enumerate(blocks):
        eid = re.search(r'data-event-id="([^"]+)"', b)
        if not eid:
            continue  # the "next event" card at the top of the page repeats the first game without an id
        opp_m = re.search(r'<span class="team-name">(.*?)</span>', b, re.S)
        opponent = text(opp_m.group(1)) if opp_m else ""
        badge = re.search(r'event-location-badge[^>]*>(.*?)</span>', b, re.S)
        badge_t = text(badge.group(1)).lower() if badge else ""
        home = badge_t.startswith("vs")
        neutral = "neutral" in badge_t or "neutral" in re.search(r'class="card w-100 event-row\b([^"]*)"', b).group(1)
        logo_m = re.search(r'<img src="([^"]+)"[^>]*alt="[^"]*team logo"', b)
        opp_logo = absolute(logo_m.group(1), base) if logo_m else None
        date_m = re.search(r'class="date[^"]*"[^>]*>.*?<span>\s*(.*?)\s*</span>', b, re.S)
        month_day = parse_month_day(text(date_m.group(1)) if date_m else "")
        status_m = re.search(r'class="status[^"]*"[^>]*>.*?<span>\s*(.*?)\s*</span>', b, re.S)
        status_t = text(status_m.group(1)) if status_m else ""
        time_parts = parse_time(status_t)
        result_m = re.search(r'event-result[^>]*>(.*?)</div>', b, re.S)
        result_text = text(result_m.group(1)) if result_m else ""
        loc_m = re.search(r'event-location[^>]*>(.*?)</(?:div|span)>', b, re.S)
        location = text(loc_m.group(1)) if loc_m and "badge" not in loc_m.group(0)[:40] else ""
        links = {}
        for href, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S):
            label_t = text(label).lower()
            key = {"statview": "live_stats", "live stats": "live_stats", "watch": "video", "video": "video", "tickets": "tickets",
                   "box score": "boxscore", "recap": "recap"}.get(label_t)
            if key and key not in links:
                links[key] = absolute(href, base)
        g = game_record(school, sport, eid.group(1), month_day, time_parts, home, neutral, opponent, opp_logo, location, links, result_text)
        if g and opponent:
            games.append(g)
    if not games:
        raise ValueError("no games parsed")
    return sorted(games, key=lambda g: g["date"])


# ---------------------------------------------------------------- live feeds

_feed_cache = {}


def live_feed(url):
    """The machine-readable feed behind a live stats link, or None when there is none."""
    if not url:
        return None
    if url in _feed_cache:
        return _feed_cache[url]
    feed = None
    try:
        m = re.match(r"https?://(?:www\.)?sidearmstats\.com/([^/]+)/([^/?#]+)", url)
        p = re.match(r"https?://(?:www\.)?prestolivestats\.com/([^/]+)/([^/?#]+)", url)
        s = re.match(r"(https?://[^/]+)/sidearmstats/([^/?#]+)", url)
        if m:
            feed = {"type": "sidearm", "url": f"https://sidearmstats.com/{m.group(1)}/{m.group(2)}/game.json"}
        elif p:
            feed = {"type": "presto", "url": f"https://data.prestolivestats.com/xml/{p.group(1)}/events/{p.group(2)}.xml"}
        elif s:
            page = get(url)
            # The stat crew publishes under the folder name, which can differ from the client name
            # (Case Western: client "casewestern", folder "case").
            client = (re.search(r'livestats_foldername\s*=\s*"([^"]+)"', page)
                      or re.search(r'client_shortname\s*=\s*"([^"]+)"', page))
            if client:
                feed = {"type": "sidearm", "url": f"https://sidearmstats.com/{client.group(1)}/{s.group(2)}/game.json"}
    except (urllib.error.URLError, TimeoutError, ValueError):
        feed = None
    _feed_cache[url] = feed
    return feed


# ---------------------------------------------------------------- Sidearm hub
HUB = "https://aggregation-service.sidearmsports.com/services/games.ashx"
HUB_SPORT = {"mbb": "mbball", "wbb": "wbball"}
GENERIC_WORDS = {"university", "college", "the", "of", "at", "vs", "and", "st", "saint", "u"}


def name_words(name):
    """The distinctive words of a team name: "St. Francis (PA)" -> {"francis", "pa"}."""
    return {w for w in re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and ")).split() if w not in GENERIC_WORDS}


def hub_games():
    """Every game a Sidearm school lists with a live stats link, yesterday through tomorrow, from the feed behind
    sidearmstats.com/hub. It answers only for about that window. Canceled games (status C) are left out."""
    start = (now().astimezone(timezone.utc) - timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
    stamp = lambda d: d.isoformat().replace("+00:00", "Z")
    query = urllib.parse.urlencode({"start_date": stamp(start), "end_date": stamp(start + timedelta(days=3)), "livestats": 1})
    return [g for g in get(f"{HUB}?{query}", as_json=True).get("data") or [] if g.get("status") != "C"]


def hub_feeds(teams, sport, hub):
    """Live stats links from the hub for games whose schedule row has none: a tournament host runs the crew and the
    member's page links nothing (Albion vs St. Francis (PA) at Heidelberg, 2026-11-13). A listing fits a game when
    the sport and tipoff agree (the local date for a TBA game), one side names the member, and the other names share
    a word with the opponent. Returns the number of games that got a feed."""
    by_slug = {s["slug"]: s for s in SCHOOLS}
    found = 0
    for slug, team in teams.items():
        us = name_words(by_slug[slug]["name"])
        for g in team["games"]:
            if g["state"] == "post" or g["live_feed"]:
                continue
            them = name_words(g["opponent"]["name"])
            local_day = datetime.fromisoformat(g["date"].replace("Z", "+00:00")).astimezone(EASTERN).strftime("%Y-%m-%d")
            for h in hub:
                info, link = h.get("date_info") or {}, (h.get("media") or {}).get("livestats")
                if (h.get("sport") or {}).get("shortname") != HUB_SPORT[sport] or not link:
                    continue
                if (info.get("date") or "")[:10] != local_day if g["time_tbd"] else info.get("datetime_utc") != g["date"]:
                    continue
                sides = [name_words((h.get(k) or {}).get("name")) for k in ("home_team", "away_team")]
                if not any(us <= side for side in sides) or not them & ((sides[0] | sides[1]) - us):
                    continue
                feed = live_feed(link)
                if feed:
                    g["links"].setdefault("live_stats", link)
                    g["live_feed"] = feed
                    found += 1
                    break
    return found


def attach_feeds(games, previous_games):
    prev = {g["id"]: g for g in previous_games or []}
    for g in games:
        if g["state"] == "post":
            g["live_feed"] = None
            continue
        g["live_feed"] = live_feed(g["links"].get("live_stats")) or (prev.get(g["id"]) or {}).get("live_feed")


def cross_fill(teams, sport):
    """Copies feed and location between the two members' copies of a head-to-head game (same day, each listing the other)."""
    by_slug = {s["slug"]: s for s in SCHOOLS}
    own_feed = {}
    for slug, team in teams.items():
        cfg = by_slug[slug]["sports"][sport]
        own_feed[slug] = live_feed(cfg.get("live_stats_url"))
        if not own_feed[slug]:
            for g in team["games"]:
                if g["live_feed"] and g["home"] and not g["neutral"]:
                    own_feed[slug] = g["live_feed"]
                    break
        own_feed = {k: v for k, v in own_feed.items() if v}
    index = {}
    for slug, team in teams.items():
        for g in team["games"]:
            index[(slug, g["date"][:10], g["opponent"].get("slug"))] = g
    for slug, team in teams.items():
        for g in team["games"]:
            opp = g["opponent"].get("slug")
            twin = index.get((opp, g["date"][:10], slug)) if opp else None
            if twin:
                if not g["live_feed"] and g["state"] != "post":
                    g["live_feed"] = twin["live_feed"]
                if not g["location"]:
                    g["location"] = twin["location"]
            if not g["live_feed"] and g["state"] != "post" and not g["neutral"]:
                host = slug if g["home"] else opp
                if host in own_feed:
                    g["live_feed"] = own_feed[host]
            if not g["location"] and g["home"] and not g["neutral"]:
                g["location"] = by_slug[slug].get("venue", "")


# ---------------------------------------------------------------- rosters

def _roster_page(school, url):
    """(season label, player count) for one roster page, or (None, 0) when it does not exist."""
    try:
        page = get(url)
    except (urllib.error.URLError, TimeoutError):
        return None, 0
    if school["vendor"] == "presto":
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        m = re.search(r"(20\d\d-\d\d)", text(title.group(1)) if title else "")
        return (m.group(1) if m else None), len(re.findall(r'class="player-name-social-row', page))
    sel = re.search(r'<option[^>]*selected[^>]*roster[^>]*>\s*([^<]*)', page)
    m = re.search(r"(20\d\d-\d\d)", text(sel.group(1)) if sel else "")
    section = re.search(r"sidearm-roster-players.*?(?:sidearm-roster-coaches|$)", page, re.S)
    count = len(re.findall(r'<li[^>]*class="sidearm-roster-player\b', section.group(0) if section else page))
    return (m.group(1) if m else None), count


def roster_info(school, cfg):
    """The roster page worth linking: this season's when it lists players, otherwise last season's."""
    url = cfg["roster_url"]
    season, players = _roster_page(school, url)
    if players and season == SEASON:
        return {"url": url, "season": season, "players": players, "current": True}
    last = f"{SEASON_START_YEAR - 1}-{str(SEASON_START_YEAR)[2:]}"
    last_url = url.replace(SEASON, last) if school["vendor"] == "presto" else f"{url.rstrip('/')}/{last}"
    last_season, last_players = _roster_page(school, last_url)
    if last_players:
        return {"url": last_url, "season": last_season or last, "players": last_players, "current": False}
    return {"url": url, "season": season, "players": players, "current": bool(players)}


def sidearm_roster_people(url):
    """Headshot, position, and class year by jersey and by name, for the leaders section."""
    page = get(url)
    by_number, by_name = {}, {}
    for block in re.findall(r'<li[^>]*class="sidearm-roster-player\b.*?</li>\s*(?=<li|</ul>)', page, flags=re.S):
        name = re.search(r'sidearm-roster-player-name.*?<a[^>]*>(.*?)</a>', block, re.S)
        if not name:
            continue
        number = re.search(r'sidearm-roster-player-jersey-number[^>]*>\s*([^<]*?)\s*<', block)
        pos = re.search(r'sidearm-roster-player-position[^>]*>.*?<span[^>]*>\s*([^<]*?)\s*</span>', block, re.S)
        year = re.search(r'sidearm-roster-player-academic-year[^>]*>\s*([^<]*?)\s*<', block)
        img = re.search(r'<img[^>]*(?:data-src|src)="([^"]+)"', block)
        info = {"name": text(name.group(1)), "position": text(pos.group(1)) if pos else None,
                "year": class_year(text(year.group(1))) if year else None,
                "headshot": re.sub(r"width=\d+", "width=200", urllib.parse.urljoin(url, html.unescape(img.group(1)))) if img and "no-photo" not in img.group(1) else None}
        if number and number.group(1).strip():
            by_number[number.group(1).strip().lstrip("0") or "0"] = info
        by_name[info["name"].lower()] = info
    return by_number, by_name


def presto_roster_people(url):
    """Same shape as sidearm_roster_people, for PrestoSports roster tables."""
    page = get(url)
    by_number, by_name = {}, {}
    for row in re.findall(r"<tr>.*?</tr>", page, re.S):
        if "player-name-social-row" not in row:
            continue
        name = re.search(r'player-name-social-row.*?<a[^>]*>\s*(.*?)\s*</a>', row, re.S)
        if not name:
            continue
        def cell(field):
            m = re.search(r'data-field="' + field + r'"[^>]*>(?:\s*<span[^>]*>.*?</span>)?\s*([^<]*?)\s*</td>', row, re.S)
            return m
        number, year, pos = cell("number"), cell("year"), cell("position")
        img = re.search(r"background-image:url\('([^']+)'\)", row)
        info = {"name": text(name.group(1)), "position": text(pos.group(1)) if pos else None,
                "year": class_year(text(year.group(1))) if year else None,
                "headshot": urllib.parse.urljoin(url, html.unescape(img.group(1))) if img else None}
        if number and number.group(1).strip():
            by_number[number.group(1).strip().lstrip("0") or "0"] = info
        by_name[info["name"].lower()] = info
    return by_number, by_name


YEARS = {"fr": "First-year", "so": "Sophomore", "jr": "Junior", "sr": "Senior", "gr": "Graduate", "gs": "Graduate", "5th": "Fifth Year",
         "r-fr": "Redshirt First-year", "r-so": "Redshirt Sophomore", "r-jr": "Redshirt Junior", "r-sr": "Redshirt Senior",
         "freshman": "First-year", "sophomore": "Sophomore", "junior": "Junior", "senior": "Senior", "graduate": "Graduate"}


def class_year(label):
    if not label:
        return None
    key = label.strip().rstrip(".").lower()
    return YEARS.get(key, label.strip())


# ---------------------------------------------------------------- leaders

def _player_name(raw):
    """'#04 Overway, Jalen' -> ('Jalen Overway', '4')."""
    raw = text(raw)
    jersey = re.match(r"#?(\d+)\s+", raw)
    name = raw[jersey.end():] if jersey else raw
    name = re.sub(r"\.{2,}", "", name).strip()
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        name = f"{first} {last}"
    return name, (jersey.group(1).lstrip("0") or "0") if jersey else None


def _table_rows(section_html):
    t = re.search(r"<table.*?</table>", section_html, re.S)
    if not t:
        return [], []
    heads = [text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", t.group(0), re.S)]
    body = re.search(r"<tbody.*?</tbody>", t.group(0), re.S)
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body.group(0) if body else t.group(0), re.S):
        cells = [text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells:
            rows.append(cells)
    return heads, rows


CATEGORIES = [("scoring", "Points", 2, ("Pts", "Pts/G")), ("reb", "Rebounds", 1, ("REB", "AVG/G")),
              ("ast", "Assists", 1, ("AST", "AST/G")), ("stl", "Steals", 1, ("STL", "STL/G")), ("blk", "Blocks", 1, ("BLK", "BLK/G"))]


def sidearm_leaders(cfg):
    page = get(cfg["stats_url"])
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    season = re.search(r"(20\d\d-\d\d)", text(title.group(1)) if title else "")
    players = []
    for key, label, count, (tot_h, avg_h) in CATEGORIES:
        sec = re.search(r'<section[^>]*id="category-leaders-' + key + r'".*?</section>', page, re.S)
        if not sec:
            continue
        heads, rows = _table_rows(sec.group(0))
        try:
            ti, ai = heads.index(tot_h), heads.index(avg_h)
        except ValueError:
            continue
        for r in rows:
            if len(r) <= max(ti, ai):
                continue
            name, jersey = _player_name(r[0])
            players.append({"label": label, "want": count, "name": name, "jersey": jersey, "gp": r[1] if len(r) > 1 else None,
                            "total": r[ti], "avg": r[ai], "line": f"{r[ai]} per game, {r[ti]} total"})
    return season.group(1) if season else None, players


def presto_leaders(cfg):
    url = cfg["stats_url"] + "?tmpl=teaminfo-network-monospace-template&sort=ptspg"
    page = get(url)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    season = re.search(r"(20\d\d-\d\d)", text(title.group(1)) if title else "")
    table = next((t for t in re.findall(r"<table.*?</table>", page, re.S) if "PTS" in t and "BLK" in t and "Player" in t), None)
    if not table:
        return (season.group(1) if season else None), []
    rows = [[text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)]
    head = next((r for r in rows if "Player" in r and "PTS" in r), None)
    if not head:
        return (season.group(1) if season else None), []
    data = [r for r in rows if len(r) == len(head) and r[0].strip().isdigit() and r[1] and not re.match(r"(Total|Opponents|TM|Team)\b", r[1])]
    cols = {"gp": head.index("GP"), "reb": head.index("TOT"), "ast": head.index("A"), "blk": head.index("BLK"), "stl": head.index("STL"), "pts": head.index("PTS")}
    avg_of = {"pts": cols["pts"] + 1, "reb": cols["reb"] + 1, "ast": head.index("A/G"), "blk": head.index("BLK/G"), "stl": head.index("STL/G")}

    def num(v):
        try:
            return float(v)
        except ValueError:
            return -1.0
    players = []
    for key, label, count in (("pts", "Points", 2), ("reb", "Rebounds", 1), ("ast", "Assists", 1), ("stl", "Steals", 1), ("blk", "Blocks", 1)):
        for r in sorted(data, key=lambda r: num(r[avg_of[key]]), reverse=True):
            if num(r[avg_of[key]]) < 0:
                continue
            name, jersey = _player_name(f"#{r[0]} {r[1]}")
            players.append({"label": label, "want": count, "name": name, "jersey": jersey, "gp": r[cols["gp"]], "total": r[cols[key]], "avg": r[avg_of[key]],
                            "line": f"{r[avg_of[key]]} per game, {r[cols[key]]} total"})
    return (season.group(1) if season else None), players


def _norm(name):
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", name.lower())
    return re.sub(r"[^a-z ]", "", name).split()


def same_person(a, b):
    """Full-name match, or last name plus first initial (stats pages shorten first names)."""
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    return x[-1] == y[-1] and x[0][0] == y[0][0]


def leaders(school, cfg, roster, sport):
    """Top players from the latest statistics page, minus the ones who are not back this season.

    Dropped: last season's seniors and graduates, players listed in departures.json, and, when the
    school has posted this season's roster, anyone who is not on it. The second list holds the players dropped for
    the last two reasons, so the page can say who is gone."""
    people = sidearm_roster_people if school["vendor"] == "sidearm" else presto_roster_people
    season, pool = presto_leaders(cfg) if school["vendor"] == "presto" else sidearm_leaders(cfg)
    if not pool and school["vendor"] == "presto" and SEASON in cfg["stats_url"]:
        last = f"{SEASON_START_YEAR - 1}-{str(SEASON_START_YEAR)[2:]}"
        season, pool = presto_leaders({**cfg, "stats_url": cfg["stats_url"].replace(SEASON, last)})
    pool = [p for p in pool if p["name"] and not re.fullmatch(r"(#?tm\s*)?(team|total|totals|opponents?|tm)", p["name"].strip(), re.I)]
    if not pool:
        return season, [], []
    # Class year, position, and headshot from the roster that matches the statistics season.
    try:
        if school["vendor"] == "presto":
            stats_roster = cfg["roster_url"].replace(SEASON, season) if season else cfg["roster_url"]
        else:
            stats_roster = cfg["roster_url"] + (f"/{season}" if season else "")
        by_number, by_name = people(stats_roster)
    except (urllib.error.URLError, TimeoutError):
        by_number, by_name = {}, {}
    for p in pool:
        info = by_number.get(str(p.get("jersey")))
        if info and not same_person(p["name"], info["name"]):
            info = None
        if not info:
            info = by_name.get(p["name"].lower()) or next((v for v in by_name.values() if same_person(p["name"], v["name"])), None)
        if info:
            p.update({k: v for k, v in info.items() if k != "name" and v})
    # Names on this season's roster, when the school has posted it.
    current_names = None
    if roster.get("current") and roster.get("season") == SEASON:
        try:
            current_names = [v["name"] for v in people(roster["url"])[1].values()]
        except (urllib.error.URLError, TimeoutError):
            current_names = None
    departures = DEPARTURES.get(sport, {}).get(school["slug"], [])

    def gone_reason(p):
        for d in departures:
            if same_person(p["name"], d["name"]):
                return d.get("note") or "not back"
        if p.get("year") in GONE_YEARS:
            return "class"
        if current_names is not None and not any(same_person(p["name"], n) for n in current_names):
            return f"not on the {SEASON} roster"
        return None

    players, gone, taken = [], {}, {}
    for p in pool:
        reason = gone_reason(p)
        rank_in_pool = taken.setdefault(("rank", p["label"]), 0)
        taken[("rank", p["label"])] = rank_in_pool + 1
        if reason is None:
            if taken.get(p["label"], 0) < p["want"]:
                taken[p["label"]] = taken.get(p["label"], 0) + 1
                players.append({k: v for k, v in p.items() if k != "want"})
        elif reason != "class":
            # Each departed player is listed by scoring; a player with no scoring row keeps their highest per-game average.
            try:
                avg = float(p["avg"])
            except (TypeError, ValueError):
                avg = 0.0
            order = (p["label"] != "Points", -avg)
            if p["name"] not in gone or order < gone[p["name"]]["order"]:
                gone[p["name"]] = {"name": p["name"], "reason": reason, "line": f'{p["avg"]} {p["label"].lower()} per game', "year": p.get("year"), "order": order}
    return season, players, [{k: v for k, v in g.items() if k != "order"} for g in sorted(gone.values(), key=lambda g: g["order"])]


# ---------------------------------------------------------------- D3hoops.com poll

def d3hoops_poll(sport, read_at):
    gender = "men" if sport == "mbb" else "women"
    req = urllib.request.Request(f"https://www.d3hoops.com/top25/{gender}/", headers=UA)
    with urllib.request.urlopen(req, timeout=40) as resp:
        final_url = resp.geturl()
        page = resp.read().decode("utf-8", "replace")
    heading = re.search(r"<h\d[^>]*>([^<]*Top 25[^<]*)</h\d>", page)
    table = next((t for t in re.findall(r"<table.*?</table>", page, re.S) if "Pts." in t), None)
    if not table:
        raise ValueError("poll table not found")
    cell_rows = [[text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)] for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)]
    rv_m = re.search(r"Others receiving votes:\s*(.*?)(?:</p>|</div>|<br|\n\n)", page, re.S | re.I)
    label = text(heading.group(1)) if heading else f"D3hoops.com {gender}'s Top 25"
    return poll_block(sport, label, final_url, cell_rows, text(rv_m.group(1)) if rv_m else "", read_at)


def manual_poll(sport):
    """The poll read by hand in a browser (content/d3hoops_poll.json), for when d3hoops.com blocks scripted requests."""
    path = BASE / "content" / "d3hoops_poll.json"
    entry = json.loads(path.read_text()).get(sport) if path.exists() else None
    if not entry:
        return None
    return poll_block(sport, entry["label"], entry["url"], entry["rows"], entry["receiving_votes"], entry["read_at"])


def poll_block(sport, label, url, cell_rows, receiving_text, read_at):
    """Build the poll from table rows ([rank, "School (first-place votes)", record, points, previous]) and the receiving-votes text."""
    m = re.search(r"/top25/\w+/(20\d\d-\d\d)/([a-z0-9]+)", url)
    season = m.group(1) if m else None
    week = m.group(2) if m else None
    ranks = {}
    rows = []
    for cells in cell_rows:
        cells = [str(c) for c in cells]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        fpv = re.search(r"\((\d+)\)\s*$", cells[1])
        team = re.sub(r"\s*\(\d+\)\s*$", "", cells[1]).strip()
        row = {"rank": int(cells[0]), "team": team, "record": cells[2], "points": cells[3], "first_place": int(fpv.group(1)) if fpv else 0,
               "prev": cells[4] if len(cells) > 4 else None}
        rows.append(row)
    receiving = {}
    for part in receiving_text.split(";"):
        pm = re.match(r"\s*(.+?)\s+(\d+)\s*\.?\s*$", part)
        if pm:
            receiving[pm.group(1).strip()] = int(pm.group(2))
    for s in SCHOOLS:
        if sport not in s["sports"]:
            continue
        key = s["d3hoops_name"]
        hit = next((r for r in rows if r["team"] == key or r["team"].lower().startswith(s["name"].lower())), None)
        if hit:
            ranks[s["slug"]] = hit
    return {"label": label, "season": season, "week": week, "url": url, "top25": rows, "ranks": ranks, "receiving_votes": receiving, "read_at": read_at}


# ---------------------------------------------------------------- NPI and ratings

def _datacast_rows(gid):
    body = get(D3DATACAST_CSV.format(gid=gid))
    rows = list(csv.reader(io.StringIO(body)))
    updated = None
    for r in rows[:8]:
        for i, c in enumerate(r):
            if c.strip().startswith("Updated"):
                updated = next((v.strip() for v in r[i + 1:] if v.strip()), None)
    head_i = next(i for i, r in enumerate(rows) if r[:2] == ["Rank", "Team"])
    head = rows[head_i]
    data = [dict(zip(head, r)) | {"_cells": r} for r in rows[head_i + 1:] if len(r) >= 3 and r[0].strip().isdigit()]
    return updated, data


def datacast_npi(sport, prev):
    cfg = D3DATACAST[sport]
    updated, data = _datacast_rows(cfg["npi_gid"])
    teams, count = {}, len(data)
    if not any(r["Team"].strip() for r in data):
        # Between seasons D3 Datacast blanks the NPI sheet (ranks with no team names, a 12/30/99 date).
        # Keep last season's NPI fields until the new table fills; efficiency still refreshes below.
        npi_keys = ("rank", "record", "npi", "bid", "at_large_rank", "seed")
        teams = {slug: {k: t[k] for k in npi_keys if k in t} for slug, t in prev.get("teams", {}).items() if "rank" in t}
        updated, count, data = prev.get("updated"), prev.get("count", 0), []
    for s in SCHOOLS:
        if sport not in s["sports"] or s["slug"] in teams:
            continue
        row = next((r for r in data if r["Team"].strip() == s["npi_name"]), None)
        if row:
            c = row["_cells"]
            teams[s["slug"]] = {"rank": int(c[0]), "record": f"{c[4]}-{c[5]}", "npi": c[9], "bid": c[10], "at_large_rank": c[11], "seed": c[12] if len(c) > 12 else None}
    eff_updated, eff = _datacast_rows(cfg["eff_gid"])
    for s in SCHOOLS:
        if sport not in s["sports"]:
            continue
        row = next((r for r in eff if r["Team"].strip() == s["npi_name"]), None)
        if row:
            c = row["_cells"]
            teams.setdefault(s["slug"], {})
            teams[s["slug"]].update({"eff_rank": int(c[0]), "adj_em": c[4], "eff_updated": eff_updated})
    # The efficiency table lists this season's Division III teams; build_site.py uses it to mark NPI games.
    return {"source": "D3 Datacast", "url": cfg["npi_url"], "eff_url": cfg["eff_url"], "updated": updated, "eff_updated": eff_updated,
            "count": count, "teams": teams, "d3_teams": sorted(r["Team"].strip() for r in eff)}


def as_int(value, default=0):
    """An int from a JSON cell that may hold a number, a numeric string, or a placeholder such as '#N/A'. Returns default otherwise."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def statlab_npi():
    npi = get(f"{STATLAB}/data/npi.json", as_json=True)
    pre = get(f"{STATLAB}/data/preseasonRankings.json", as_json=True)
    sims = get(f"{STATLAB}/data/seasonSimulations.json", as_json=True)
    teams = {}
    for s in SCHOOLS:
        if "wbb" not in s["sports"]:
            continue
        key = s["statlab_name"]
        row = next((r for r in npi if r.get("Team") == key), None)
        if row:
            teams[s["slug"]] = {"rank": as_int(row.get("NPI Rank"), None), "npi": row.get("NPI Value"), "rank_change": as_int(row.get("Rank Diff"), None), "bid": row.get("Bid Type"),
                                "record": f'{as_int(row.get("Qual Wins"))}-{as_int(row.get("Qual Games")) - as_int(row.get("Qual Wins"))} qualifying'}
        p = next((r for r in pre if r.get("Team") == key), None)
        if p:
            teams.setdefault(s["slug"], {})
            teams[s["slug"]].update({"preseason_rank": p.get("Projected Preseason Rank"), "returning": p.get("Returning")})
        sim = next((r for r in sims if r.get("Team") == key), None)
        if sim:
            teams.setdefault(s["slug"], {})
            teams[s["slug"]].update({"tourney_pct": sim.get("Tourn%"), "aq_pct": sim.get("AQ%"), "median_record": f'{sim.get("MedW")}-{sim.get("MedL")}'})
    return {"source": "The D3 Stat Lab", "url": f"{STATLAB}/npi.html", "preseason_url": f"{STATLAB}/preseason_rankings.html",
            "sims_url": f"{STATLAB}/season_simulations.html", "count": len(npi), "teams": teams,
            # Every women's team in the NPI table; build_site.py uses it to mark NPI games for schools
            # that have no men's team on the D3 Datacast list.
            "d3_teams": sorted(r["Team"].strip() for r in npi if r.get("Team"))}


# ---------------------------------------------------------------- main

def main():
    DATA.mkdir(exist_ok=True)
    previous = {}
    if (DATA / "season.json").exists():
        try:
            previous = json.loads((DATA / "season.json").read_text())
        except ValueError:
            previous = {}
    out = {"fetched_at": now().isoformat(timespec="seconds"), "season": SEASON, "sports": {}, "errors": [], "stale": {}}
    hub = None
    for sport in SPORTS:
        prev_sport = previous.get("sports", {}).get(sport, {})
        block = {"teams": {}, "poll": {}, "npi": {}}
        for school in SCHOOLS:
            cfg = school["sports"].get(sport)
            if not cfg:
                continue
            slug = school["slug"]
            prev_team = prev_sport.get("teams", {}).get(slug, {})
            team = {"games": [], "roster": {}, "players": [], "departed": [], "stats_season": None}
            try:
                games = presto_schedule(school, sport, cfg) if school["vendor"] == "presto" else sidearm_schedule(school, sport, cfg)
                attach_feeds(games, prev_team.get("games"))
                team["games"] = games
                if games and all(g["time_tbd"] for g in games):
                    out["errors"].append(f"{school['name']} {sport} schedule: every tipoff time parsed as TBA; check the page markup")
            except (urllib.error.URLError, TimeoutError, ValueError, AttributeError) as exc:
                out["errors"].append(f"{school['name']} {sport} schedule: {exc}")
                team["games"] = prev_team.get("games", [])
                if team["games"]:
                    out["stale"][f"{slug}-{sport}-schedule"] = prev_team.get("fetched") or previous.get("fetched_at")
            played = [g for g in team["games"] if g["result"] and not g["exhibition"]]
            conf = [g for g in played if g["conference"]]
            team.update({
                "played": len(played),
                "wins": sum(g["result"] == "W" for g in played), "losses": sum(g["result"] == "L" for g in played),
                "conf_wins": sum(g["result"] == "W" for g in conf), "conf_losses": sum(g["result"] == "L" for g in conf),
                "pf": sum(g["pf"] for g in played), "pa": sum(g["pa"] for g in played),
            })
            team["record"] = f'{team["wins"]}-{team["losses"]}'
            team["conf_record"] = f'{team["conf_wins"]}-{team["conf_losses"]}'
            team["roster"] = roster_info(school, cfg)
            try:
                team["stats_season"], team["players"], team["departed"] = leaders(school, cfg, team["roster"], sport)
            except (urllib.error.URLError, TimeoutError, ValueError, IndexError) as exc:
                out["errors"].append(f"{school['name']} {sport} leaders: {exc}")
                team["players"] = prev_team.get("players", [])
                team["departed"] = prev_team.get("departed", [])
                team["stats_season"] = prev_team.get("stats_season")
            team["fetched"] = out["fetched_at"]
            block["teams"][slug] = team
        cross_fill(block["teams"], sport)
        try:
            if hub is None:
                hub = hub_games()
            hub_feeds(block["teams"], sport, hub)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            out["errors"].append(f"Sidearm hub: {exc}")
        try:
            block["poll"] = d3hoops_poll(sport, out["fetched_at"])
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            out["errors"].append(f"d3hoops {sport}: {exc}")
            # Keep whichever poll was read later: the last scripted read or the hand-read file.
            carried = prev_sport.get("poll", {})
            manual = manual_poll(sport)
            if manual and manual["read_at"] >= carried.get("read_at", ""):
                block["poll"] = manual
            else:
                block["poll"] = carried
                if carried:
                    out["stale"][f"{sport}-poll"] = previous.get("fetched_at")
        try:
            block["npi"] = datacast_npi(sport, prev_sport.get("npi", {})) if sport == "mbb" else statlab_npi()
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, StopIteration, TypeError, IndexError, AttributeError) as exc:
            out["errors"].append(f"npi {sport}: {type(exc).__name__}: {exc}")
            block["npi"] = prev_sport.get("npi", {})
            if block["npi"]:
                out["stale"][f"{sport}-npi"] = previous.get("fetched_at")
        out["sports"][sport] = block
    (DATA / "season.json").write_text(json.dumps(out, indent=1))
    for sport, block in out["sports"].items():
        summary = ", ".join(f'{k} {len(v["games"])}g {v["record"]} ({len(v["players"])} leaders)' for k, v in block["teams"].items())
        print(f"[{now():%Y-%m-%d %H:%M}] {sport}: {summary}")
    out["errors"].extend(WARNINGS)
    if out["errors"]:
        print("errors:", *out["errors"], sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
