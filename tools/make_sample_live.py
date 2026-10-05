#!/usr/bin/env python3
"""Write data/sample_live.json: a frozen in-game moment for each team's next-game card.

Each team gets its most recent 2025-26 game. The script stops that game's
play-by-play at a random play, so the cards show different points of a game
(early, a period break, the closing minutes). The draw is seeded by sport and
school, so a rerun gives the same moments. It records the score, the clock,
and the team's own last play at that point.
build_site.py shows the moment on the team's next-game card, labeled as a
sample. Delete data/sample_live.json to remove the samples.
"""
import html
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fetch_data import get  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data" / "sample_live.json"
SCHOOLS = json.loads((BASE / "schools.json").read_text())
SEASON = "2025-26"
SKIP = re.compile(r"\bSUB\b|SUB IN|SUB OUT|TIMEOUT|substitution|timeout|enters the game|goes to the bench", re.I)

# Sidearm writes "GOOD 3PTR by BLAUCH,KYLE"; PrestoSports writes "BLAUCH,KYLE made 3-pt. jump shot".
SIDEARM_ACTIONS = {
    "GOOD 3PTR": "made a 3-pointer", "MISS 3PTR": "missed a 3-pointer",
    "GOOD JUMPER": "made a jump shot", "MISS JUMPER": "missed a jump shot",
    "GOOD LAYUP": "made a layup", "MISS LAYUP": "missed a layup",
    "GOOD DUNK": "made a dunk", "MISS DUNK": "missed a dunk",
    "GOOD TIPIN": "made a tip-in", "MISS TIPIN": "missed a tip-in",
    "GOOD FT": "made a free throw", "MISS FT": "missed a free throw",
    "REBOUND OFF": "offensive rebound", "REBOUND DEF": "defensive rebound",
    "TURNOVR": "turnover", "STEAL": "steal", "ASSIST": "assist", "BLOCK": "block", "FOUL": "foul",
}


def person(raw, team):
    """BLAUCH,KYLE -> Kyle Blauch. Drops play tags such as (Fastbreak). TEAM -> the school name."""
    raw = re.sub(r"\([^)]*\)", "", raw).strip()
    if raw.upper() == "TEAM":
        return team
    if "," not in raw:
        return raw.title()
    last, first = raw.split(",", 1)
    return f"{first.strip().title()} {last.strip().title()}"


def sidearm_text(play, team):
    m = re.match(r"(.+?) by (.+)$", play)
    if not m:
        return play.capitalize()
    action = SIDEARM_ACTIONS.get(m.group(1).strip(), m.group(1).strip().lower())
    return f"{person(m.group(2), team)}: {action}"


def presto_text(play, team):
    m = re.match(r"([A-Z'\-. ]+,[A-Z'\-. ]+?) (.+)$", play)
    if m:
        return f"{person(m.group(1), team)}: {m.group(2)}"
    m = re.match(r"(.+?) by ([A-Z'\-. ]+,[A-Z'\-. ]+)$", play)
    if m:
        return f"{person(m.group(2), team)}: {m.group(1).lower()}"
    return play


def clock_seconds(text):
    m = re.match(r"(\d+):(\d+)", text or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).split() and " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def sidearm_plays(page):
    """Return (periods, plays). Each play: period, clock, mine (bool), text, away, home."""
    periods = re.findall(r'<div id="period-(\d+)" class="panel">(.*?)</table>', page, re.S)
    plays = []
    for num, body in periods:
        for row in re.findall(r"<tr>(.*?)</tr>", body, re.S):
            cells = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
            if len(cells) < 6:
                continue
            side = "team" if "play team" in cells[3][0] else "opponent" if "play opponent" in cells[3][0] else None
            away_play, home_play = strip_tags(cells[1][1]) or "", strip_tags(cells[5][1]) or ""
            plays.append({
                "period": int(num), "clock": strip_tags(cells[0][1]) or "",
                "side": side, "text": away_play or home_play, "col": "away" if away_play else "home",
                "away": strip_tags(cells[2][1]) or "", "home": strip_tags(cells[4][1]) or "",
            })
    return len(periods), plays


def presto_plays(page, school_name):
    periods = re.findall(r'<span id="prd(\d+)">(.*?)</table>', page, re.S)
    plays = []
    for num, body in periods:
        for cls, row in re.findall(r'<tr class="row (visitor|home)[^"]*">(.*?)</tr>', body, re.S):
            text = strip_tags("".join(re.findall(r'<span class="text">(.*?)</span>', row, re.S))) or ""
            alt = re.search(r'alt="([^"]*)" class="team-logo', row)
            v = re.search(r"<span class='v-score'>(\d+)</span>", row)
            h = re.search(r"<span class='h-score'>(\d+)</span>", row)
            plays.append({
                "period": int(num), "clock": strip_tags(re.search(r'<td class="time">(.*?)</td>', row, re.S).group(1)) or "",
                "side": "team" if alt and alt.group(1) == school_name else "opponent",
                "text": text, "col": "away" if cls == "visitor" else "home",
                "away": v.group(1) if v else "", "home": h.group(1) if h else "",
            })
    return len(periods), plays


def score(cell):
    """Sidearm writes "52 (+2)" on the scoring team's side; keep the score."""
    m = re.match(r"\d+", cell)
    return int(m.group(0)) if m else None


def period_name(period, regulation):
    if period > regulation:
        extra = period - regulation
        return "OT" if extra == 1 else f"OT{extra}"
    ordinal = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[period]
    return f"{ordinal} {'half' if regulation == 2 else 'quarter'}"


def status_text(period, clock, regulation):
    """Match the page's live status: a running clock, a period break, or halftime."""
    if clock == 0 and period == regulation // 2:
        return "Halftime"
    if clock == 0 and period < regulation:
        return f"End of {period_name(period, regulation)}"
    return f"{clock // 60}:{clock % 60:02d} {period_name(period, regulation)}"


def freeze(periods, plays, render, rng):
    """Stop after a random play, somewhere from 5% to 97% of the way through the game."""
    regulation = 4 if periods >= 4 else 2
    my_col = next((p["col"] for p in plays if p["side"] == "team" and p["text"]), None)
    if my_col is None:
        raise ValueError("no plays by the school's team")
    stop = rng.randint(int(len(plays) * 0.05), int(len(plays) * 0.97))
    away = home = 0
    clock = None
    last = ""
    for p in plays[: stop + 1]:
        if p["away"] and score(p["away"]) is not None:
            away, home = score(p["away"]), score(p["home"])
        secs = clock_seconds(p["clock"])
        if secs is not None:
            clock = secs
        if p["side"] == "team" and p["text"] and not SKIP.search(p["text"]):
            last = render(p["text"])
    period = plays[stop]["period"]
    mine, other = (away, home) if my_col == "away" else (home, away)
    return {"pf": mine, "pa": other, "status": status_text(period, clock or 0, regulation), "last": last}


def last_boxscore(school, sport):
    if school["vendor"] == "presto":
        code = {"mbb": "mbkb", "wbb": "wbkb"}[sport]
        base = f"https://{school['host']}"
        page = get(f"{base}/sports/{code}/{SEASON}/schedule")
        links = re.findall(rf'href="(/sports/{code}/{SEASON}/boxscores/[^"]+\.xml)"', page)
        return base + links[-1] + "?view=plays" if links else None
    sched = school["sports"][sport]["schedule_url"].rstrip("/") + f"/{SEASON}"
    page = get(sched)
    links = re.findall(rf'href="(/sports/[a-z-]+basketball/stats/{SEASON}/[^"]+/boxscore/\d+)"', page)
    seen = list(dict.fromkeys(links))
    return f"https://{school['host']}{seen[-1]}" if seen else None


def game_label(page, school, url):
    """Opponent and date of the source game, for example "Calvin University, February 24, 2026"."""
    if school["vendor"] == "presto":
        names = [" ".join(html.unescape(n).split()) for n in re.findall(r'<span class="team-name">(.*?)</span>', page)]
        opp = next((n for n in names if n != school["name"]), "")
        ymd = re.search(r"/boxscores/(\d{4})(\d{2})(\d{2})_", url)
        y, m, d = (int(x) for x in ymd.groups())
    else:
        title = " ".join(html.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1)).split())
        hit = re.search(r" vs (.+?) on (\d+)/(\d+)/(\d{4})", title)
        opp = re.sub(r"^#?\d+\s+", "", hit.group(1))
        m, d, y = (int(x) for x in hit.groups()[1:])
    month = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"][m - 1]
    return f"{opp}, {month} {d}, {y}"


def main():
    out = {"season": SEASON, "mbb": {}, "wbb": {}}
    for school in SCHOOLS:
        for sport in school["sports"]:
            rng = random.Random(f"{sport}-{school['slug']}")
            try:
                url = last_boxscore(school, sport)
                if not url:
                    raise ValueError("no box score links")
                page = get(url)
                if school["vendor"] == "presto":
                    periods, plays = presto_plays(page, school["name"])
                    moment = freeze(periods, plays, lambda t: presto_text(t, school["name"]), rng)
                else:
                    periods, plays = sidearm_plays(page)
                    moment = freeze(periods, plays, lambda t: sidearm_text(t, school["name"]), rng)
                moment["source"] = url
                moment["game"] = game_label(page, school, url)
                out[sport][school["slug"]] = moment
                print(f"{sport} {school['slug']}: {moment['pf']}-{moment['pa']} {moment['status']} | {moment['last']}")
            except Exception as e:  # one school failing should not stop the rest
                print(f"{sport} {school['slug']}: FAILED {e}")
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
