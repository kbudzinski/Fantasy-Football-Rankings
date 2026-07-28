#!/usr/bin/env python3
"""
Free public-data updater for the static fantasy draft board.

Public data refreshed:
- ESPN projections and injury status
- Multi-site ADP, including Underdog
- FantasyPros PPR consensus rankings
- 2024 and 2025 nflverse statistics
- 2025 position finish
- Public season-long sportsbook stat lines ("Vegas" lines)

Personal rankings and drafted state remain in browser localStorage.
"""
from __future__ import annotations

import csv
import html as html_lib
import io
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "players.js"
SEASON = 2026
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/149 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TEAM_MAP = {
    1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",10:"TEN",
    11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",18:"NO",19:"NYG",
    20:"NYJ",21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",27:"TB",28:"WAS",
    29:"CAR",30:"JAX",33:"BAL",34:"HOU"
}
POS_MAP = {1:"QB",2:"RB",3:"WR",4:"TE",5:"K",16:"DST"}

VEGAS_MARKETS = {
    "passYds": {
        "label": "Passing Yards",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-passing-yards/",
        "minimum": 1000, "maximum": 6000,
    },
    "passTD": {
        "label": "Passing Touchdowns",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-passing-touchdowns/",
        "minimum": 3, "maximum": 65,
    },
    "rushYds": {
        "label": "Rushing Yards",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-rushing-yards/",
        "minimum": 25, "maximum": 2500,
    },
    "rushTD": {
        "label": "Rushing Touchdowns",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-rushing-touchdowns/",
        "minimum": 0.5, "maximum": 35,
    },
    "recYds": {
        "label": "Receiving Yards",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-receiving-yards/",
        "minimum": 25, "maximum": 2500,
    },
    "recTD": {
        "label": "Receiving Touchdowns",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-rec-touchdowns/",
        "minimum": 0.5, "maximum": 35,
    },
    "receptions": {
        "label": "Receptions",
        "url": "https://www.bettingpros.com/nfl/odds/player-futures/total-receptions/",
        "minimum": 5, "maximum": 180,
    },
}

def norm_name(value):
    value = str(value or "").lower()
    value = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", value)
    return re.sub(r"[^a-z0-9]+", "", value)

def key(name, pos):
    return f"{norm_name(name)}|{pos}"

def load_data():
    text = DATA_FILE.read_text(encoding="utf-8").strip()
    prefix = "window.FANTASY_DATA = "
    if not text.startswith(prefix):
        raise RuntimeError("Unexpected players.js format")
    return json.loads(text[len(prefix):].rstrip(";\n"))

def write_data(data):
    DATA_FILE.write_text(
        "window.FANTASY_DATA = " +
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) +
        ";\n",
        encoding="utf-8",
    )

def request(url, **kwargs):
    headers = {**UA, **kwargs.pop("headers", {})}
    response = requests.get(url, headers=headers, timeout=45, **kwargs)
    response.raise_for_status()
    return response

def ensure(players_by_key, name, pos, team=""):
    player_key = key(name, pos)
    if player_key not in players_by_key:
        players_by_key[player_key] = {
            "key":player_key, "name":name, "pos":pos, "team":team,
            "rank":9999, "tier":"", "drafted":False, "draftedBy":"",
            "overallPick":"", "rosterSlot":"", "notes":"",
            "categories":{}, "sourceRanks":{}, "stats2025":{},
            "stats2024":{}, "vegas":{},
        }
    player = players_by_key[player_key]
    player.setdefault("sourceRanks", {})
    player.setdefault("stats2025", {})
    player.setdefault("stats2024", {})
    player.setdefault("vegas", {})
    return player

def update_espn(players):
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}"
        "/segments/0/leaguedefaults/3?scoringPeriodId=0&view=kona_player_info"
    )
    fantasy_filter = {
        "players": {
            "limit":1200,
            "sortDraftRanks":{"sortPriority":1,"sortAsc":True,"value":"PPR"},
            "filterRanksForRankTypes":{"value":["PPR"]},
            "filterRanksForScoringPeriodIds":{"value":[1]},
        }
    }
    response = request(
        url,
        headers={
            "X-Fantasy-Filter":json.dumps(fantasy_filter),
            "X-Fantasy-Source":"kona",
        },
    )
    count = 0
    for entry in response.json().get("players", []):
        info = entry.get("player", {})
        pos = POS_MAP.get(info.get("defaultPositionId"))
        name = info.get("fullName") or info.get("name")
        if not pos or not name:
            continue
        player = ensure(players, name, pos, TEAM_MAP.get(info.get("proTeamId"), ""))
        player["team"] = TEAM_MAP.get(info.get("proTeamId"), player.get("team", ""))
        player["injuryStatus"] = info.get("injuryStatus", "")
        for stat in info.get("stats", []):
            if (
                stat.get("seasonId") == SEASON
                and stat.get("statSourceId") == 1
                and stat.get("appliedTotal") is not None
            ):
                player["proj2026"] = round(float(stat["appliedTotal"]), 1)
        count += 1
    if not count:
        raise RuntimeError("No ESPN players loaded")
    print(f"Loaded {count} ESPN players")

def update_multisite_adp(players):
    soup = BeautifulSoup(request("https://www.4for4.com/adp").text, "html.parser")
    table = None
    headers = []
    for candidate in soup.select("table"):
        candidate_headers = [c.get_text(" ", strip=True) for c in candidate.select("thead th")]
        normalized = [h.strip().lower() for h in candidate_headers]
        if "adp" in normalized and "player" in normalized and "underdog" in normalized:
            table = candidate
            headers = candidate_headers
            break
    if table is None:
        raise RuntimeError("Could not find the 4for4 multi-site ADP table")

    header_index = {h.strip().lower(): i for i, h in enumerate(headers)}
    def column(*names):
        for name in names:
            if name.lower() in header_index:
                return header_index[name.lower()]
        return None
    def parse_number(value):
        cleaned = re.sub(r"[^0-9.\-]", "", value or "")
        try:
            return float(cleaned) if cleaned else ""
        except ValueError:
            return ""

    columns = {
        "market":column("ADP"), "cbs":column("CBS"), "espn":column("ESPN"),
        "nfl":column("NFL"), "sleeper":column("Sleeper"),
        "yahoo":column("Y!", "Yahoo"), "underdog":column("Underdog"),
    }
    pos_i, player_i, team_i = column("Position"), column("Player"), column("Team")
    if None in (pos_i, player_i, team_i, columns["market"]):
        raise RuntimeError("Required ADP columns are missing")

    found = 0
    for row in table.select("tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if len(cells) <= max(pos_i, player_i, team_i, columns["market"]):
            continue
        position_value = cells[pos_i]
        if not re.fullmatch(r"(QB|RB|WR|TE|K|DEF|DST)-\d+", position_value, re.I):
            continue
        pos = position_value.split("-")[0].upper().replace("DEF", "DST")
        player = ensure(players, cells[player_i], pos, cells[team_i])
        for source, index in columns.items():
            if index is not None and index < len(cells):
                player["sourceRanks"][source] = parse_number(cells[index])
        found += 1
    if not found:
        raise RuntimeError("No multi-site ADP rows parsed")
    print(f"Loaded {found} multi-site ADP rows")

def update_fantasypros(players):
    """
    Parse FantasyPros' public 2026 PPR consensus page.

    The parser intentionally uses several strategies because FantasyPros changes
    table markup. A failed refresh preserves the last successful values.
    """
    url = "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php"
    raw = request(url).text
    soup = BeautifulSoup(raw, "html.parser")

    name_map = {}
    for player in players.values():
        name_map.setdefault(norm_name(player.get("name")), []).append(player)
    known_names = sorted(name_map, key=len, reverse=True)
    found = {}

    for row in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        if not cells:
            continue
        rank = None
        for cell in cells[:2]:
            match = re.search(r"\b(\d{1,4})\b", cell)
            if match:
                rank = int(match.group(1))
                break
        if not rank:
            rank_attr = row.get("data-rank") or row.get("data-ecr")
            if rank_attr and str(rank_attr).isdigit():
                rank = int(rank_attr)
        if not rank:
            continue

        attr_name = (
            row.get("data-player-name")
            or row.get("data-name")
            or row.get("data-player")
            or ""
        )
        normalized_row = norm_name(attr_name or " ".join(cells))
        matched_name = next((name for name in known_names if name and name in normalized_row), None)
        if not matched_name:
            continue
        candidate_players = name_map[matched_name]
        # Full-name matching is usually unique; when not, use position text.
        selected = candidate_players[0]
        row_text = " ".join(cells).upper()
        for candidate in candidate_players:
            if re.search(rf"\b{re.escape(candidate.get('pos',''))}\d*\b", row_text):
                selected = candidate
                break
        found[selected["key"]] = rank

    # Fallback for JSON blobs embedded in the page.
    if len(found) < 20:
        compact = html_lib.unescape(raw)
        for player in players.values():
            if player["key"] in found:
                continue
            escaped = re.escape(player["name"])
            patterns = [
                rf'"player_name"\s*:\s*"{escaped}".{{0,500}}?"rank_ecr"\s*:\s*(\d+)',
                rf'"rank_ecr"\s*:\s*(\d+).{{0,500}}?"player_name"\s*:\s*"{escaped}"',
                rf'"name"\s*:\s*"{escaped}".{{0,500}}?"rank"\s*:\s*(\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, compact, re.I | re.S)
                if match:
                    found[player["key"]] = int(match.group(1))
                    break

    if not found:
        raise RuntimeError("FantasyPros page did not expose parseable PPR rankings")
    for player_key, rank in found.items():
        players[player_key]["sourceRanks"]["fantasyPros"] = rank
    print(f"Loaded {len(found)} FantasyPros PPR rankings")

def update_history(players, season):
    url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"stats_player/stats_player_reg_{season}.csv"
    )
    rows = csv.DictReader(io.StringIO(request(url).text))
    count = 0
    for row in rows:
        pos = (row.get("position") or row.get("position_group") or "").upper()
        if pos not in {"QB","RB","WR","TE","K"}:
            continue
        name = row.get("player_display_name") or row.get("player_name")
        if not name:
            continue
        player = ensure(players, name, pos, row.get("team") or row.get("recent_team") or "")
        def number(*names):
            for field in names:
                try:
                    return float(row.get(field) or 0)
                except (TypeError, ValueError):
                    continue
            return 0
        games = number("games", "games_played")
        ppr = number("fantasy_points_ppr")
        player[f"stats{season}"] = {
            "gp":games,
            "ppr":round(ppr, 1),
            "ppg":round(ppr / games, 1) if games else "",
            "targets":number("targets"),
            "receptions":number("receptions"),
            "recYds":number("receiving_yards"),
            "carries":number("carries", "rushing_attempts"),
            "rushYds":number("rushing_yards"),
            "td":(
                number("passing_tds") + number("rushing_tds")
                + number("receiving_tds") + number("special_teams_tds")
            ),
        }
        count += 1
    if not count:
        raise RuntimeError(f"No {season} nflverse player rows loaded")
    print(f"Loaded {count} rows for {season}")

def calculate_position_finishes(players, season=2025):
    field = f"stats{season}"
    for pos in ("QB", "RB", "WR", "TE", "K"):
        eligible = [
            player for player in players.values()
            if player.get("pos") == pos and float(player.get(field, {}).get("ppr") or 0) > 0
        ]
        eligible.sort(
            key=lambda player: (
                -float(player.get(field, {}).get("ppr") or 0),
                player.get("name", ""),
            )
        )
        previous_points = None
        previous_rank = 0
        for index, player in enumerate(eligible, 1):
            points = float(player[field].get("ppr") or 0)
            rank = previous_rank if previous_points == points else index
            player[field]["posFinish"] = rank
            previous_points, previous_rank = points, rank
    print(f"Calculated {season} position finishes")

def valid_line(value, minimum, maximum):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if minimum <= value <= maximum else None

def extract_lines_from_text(text, players, label, minimum, maximum, allow_unlabeled=False):
    """
    Find lines near known player names. Public sportsbook pages commonly render
    text like: Player Regular Season Receiving Yards ... Over 999.5.
    """
    normalized_text = re.sub(r"\s+", " ", html_lib.unescape(text))
    values = {}
    for player in players.values():
        name = player.get("name", "")
        if not name:
            continue
        escaped_name = re.escape(name)
        escaped_label = re.escape(label)
        patterns = [
            rf"{escaped_name}.{{0,180}}?{escaped_label}.{{0,180}}?(?:Over|Under)\s+(\d+(?:\.\d+)?)",
            rf"{escaped_label}.{{0,180}}?{escaped_name}.{{0,180}}?(?:Over|Under)\s+(\d+(?:\.\d+)?)",
        ]
        if allow_unlabeled:
            patterns.append(rf"{escaped_name}.{{0,220}}?(?:Over|Under)\s+(\d+(?:\.\d+)?)")
        candidates = []
        for pattern in patterns:
            for match in re.finditer(pattern, normalized_text, re.I):
                line = valid_line(match.group(1), minimum, maximum)
                if line is not None:
                    candidates.append(line)
        if candidates:
            values[player["key"]] = statistics.median(candidates)
    return values

def extract_lines_from_json_scripts(soup, players, minimum, maximum):
    """
    Generic fallback for JSON embedded by modern sportsbook pages. It recursively
    searches dictionaries for a known player name plus a line/handicap value.
    """
    by_normalized_name = {norm_name(p.get("name")): p for p in players.values()}
    collected = {}

    def walk(node):
        if isinstance(node, dict):
            strings = []
            numbers = []
            for field, value in node.items():
                field_lower = str(field).lower()
                if isinstance(value, str):
                    strings.append(value)
                if field_lower in {
                    "line", "handicap", "points", "value", "consensusline",
                    "displayline", "mainline"
                }:
                    line = valid_line(value, minimum, maximum)
                    if line is not None:
                        numbers.append(line)
            combined_text = " ".join(strings)
            combined = norm_name(combined_text)
            matched = None
            if len(combined_text) < 800:
                matched = next((name for name in by_normalized_name if name and name in combined), None)
            if matched and numbers:
                player_key = by_normalized_name[matched]["key"]
                collected.setdefault(player_key, []).extend(numbers)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for script in soup.select('script[type="application/json"], script#__NEXT_DATA__'):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return {player_key: statistics.median(lines) for player_key, lines in collected.items() if lines}

def update_vegas(players):
    """
    Load season-long sportsbook over/under totals.

    FanDuel's public NFL player-props page is tried first. BettingPros' public
    market-specific pages are used as a fallback. Because sportsbook markets are
    released gradually, blank values are expected for some players.
    """
    results = {market: {} for market in VEGAS_MARKETS}
    source_used = []

    # Primary: one public FanDuel page can contain several regular-season markets.
    try:
        fanduel_url = "https://sportsbook.fanduel.com/navigation/nfl?tab=player-props"
        raw = request(fanduel_url).text
        soup = BeautifulSoup(raw, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        for market, config in VEGAS_MARKETS.items():
            extracted = extract_lines_from_text(
                page_text, players, config["label"], config["minimum"], config["maximum"]
            )
            results[market].update(extracted)
        if any(results.values()):
            source_used.append("FanDuel")
    except Exception as exc:
        print(f"WARN FanDuel Vegas lines: {exc}", file=sys.stderr)

    # Fallback / gap-filling: BettingPros market pages.
    for market, config in VEGAS_MARKETS.items():
        try:
            raw = request(config["url"]).text
            soup = BeautifulSoup(raw, "html.parser")
            extracted = extract_lines_from_text(
                soup.get_text(" ", strip=True),
                players,
                config["label"],
                config["minimum"],
                config["maximum"],
                allow_unlabeled=True,
            )
            embedded = extract_lines_from_json_scripts(
                soup, players, config["minimum"], config["maximum"]
            )
            for player_key, line in embedded.items():
                extracted.setdefault(player_key, line)
            for player_key, line in extracted.items():
                results[market].setdefault(player_key, line)
            if extracted and "BettingPros" not in source_used:
                source_used.append("BettingPros")
        except Exception as exc:
            print(f"WARN {market} sportsbook lines: {exc}", file=sys.stderr)

    total = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    for market, player_lines in results.items():
        for player_key, line in player_lines.items():
            players[player_key].setdefault("vegas", {})[market] = round(float(line), 1)
            players[player_key]["vegas"]["updatedAt"] = timestamp
            players[player_key]["vegas"]["source"] = " + ".join(source_used)
            total += 1
    if not total:
        raise RuntimeError(
            "No public sportsbook season totals were parsed; previous Vegas values retained"
        )
    print(f"Loaded {total} sportsbook stat lines from {' + '.join(source_used)}")

def main():
    data = load_data()
    players = {player["key"]: player for player in data.get("players", [])}

    steps = [
        ("ESPN projections", lambda: update_espn(players)),
        ("multi-site ADP", lambda: update_multisite_adp(players)),
        ("FantasyPros rankings", lambda: update_fantasypros(players)),
        ("2025 stats", lambda: update_history(players, 2025)),
        ("2024 stats", lambda: update_history(players, 2024)),
        ("Vegas season totals", lambda: update_vegas(players)),
    ]
    for label, function in steps:
        try:
            function()
            print("OK", label)
        except Exception as exc:
            print("WARN", label, exc, file=sys.stderr)

    calculate_position_finishes(players, 2025)

    # News was intentionally removed from the website.
    data["news"] = []
    for player in players.values():
        for field in ("newsFlag", "newsDate", "newsSummary", "newsUrl"):
            player.pop(field, None)

    ordered = sorted(
        players.values(),
        key=lambda player: (
            float(player.get("sourceRanks", {}).get("market") or player.get("rank") or 9999),
            player.get("name", ""),
        ),
    )
    for index, player in enumerate(ordered, 1):
        if not player.get("rank") or player["rank"] == 9999:
            player["rank"] = index

    data["players"] = ordered
    data.setdefault("meta", {}).update({
        "season":SEASON,
        "scoring":"ESPN PPR",
        "updatedAt":datetime.now(timezone.utc).isoformat(),
        "vegasSource":"Season-long public sportsbook over/under lines",
    })
    write_data(data)

if __name__ == "__main__":
    main()
