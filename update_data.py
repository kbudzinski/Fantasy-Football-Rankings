#!/usr/bin/env python3
"""
Free public-data updater for the static fantasy draft board.
It preserves user rankings/drafted state because those live in browser localStorage.
"""
from __future__ import annotations
import csv, io, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "players.js"
SEASON = 2026
UA = {"User-Agent":"Mozilla/5.0 Fantasy Draft Free Updater"}

TEAM_MAP = {
  1:"ATL",2:"BUF",3:"CHI",4:"CIN",5:"CLE",6:"DAL",7:"DEN",8:"DET",9:"GB",10:"TEN",
  11:"IND",12:"KC",13:"LV",14:"LAR",15:"MIA",16:"MIN",17:"NE",18:"NO",19:"NYG",
  20:"NYJ",21:"PHI",22:"ARI",23:"PIT",24:"LAC",25:"SF",26:"SEA",27:"TB",28:"WAS",
  29:"CAR",30:"JAX",33:"BAL",34:"HOU"
}
POS_MAP={1:"QB",2:"RB",3:"WR",4:"TE",5:"K",16:"DST"}

def norm_name(s):
    s=s.lower()
    s=re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b","",s)
    return re.sub(r"[^a-z0-9]+","",s)

def key(name,pos):
    return f"{norm_name(name)}|{pos}"

def load_data():
    text=DATA_FILE.read_text(encoding="utf-8").strip()
    prefix="window.FANTASY_DATA = "
    if not text.startswith(prefix):
        raise RuntimeError("Unexpected players.js format")
    return json.loads(text[len(prefix):].rstrip(";\n"))

def write_data(data):
    DATA_FILE.write_text("window.FANTASY_DATA = "+json.dumps(data,ensure_ascii=False,separators=(",",":"))+";\n",encoding="utf-8")

def request(url, **kwargs):
    r=requests.get(url,headers={**UA,**kwargs.pop("headers",{})},timeout=40,**kwargs)
    r.raise_for_status()
    return r

def ensure(players_by_key, name, pos, team=""):
    k=key(name,pos)
    if k not in players_by_key:
        players_by_key[k]={
          "key":k,"name":name,"pos":pos,"team":team,"rank":9999,"tier":"",
          "drafted":False,"draftedBy":"","overallPick":"","rosterSlot":"","notes":"",
          "categories":{},"sourceRanks":{},"stats2025":{},"stats2024":{}
        }
    return players_by_key[k]

def update_espn(players):
    url=f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leaguedefaults/3?scoringPeriodId=0&view=kona_player_info"
    fantasy_filter={"players":{"limit":1200,"sortDraftRanks":{"sortPriority":1,"sortAsc":True,"value":"PPR"},"filterRanksForRankTypes":{"value":["PPR"]},"filterRanksForScoringPeriodIds":{"value":[1]}}}
    r=request(url,headers={"X-Fantasy-Filter":json.dumps(fantasy_filter),"X-Fantasy-Source":"kona"})
    for entry in r.json().get("players",[]):
        info=entry.get("player",{})
        pos=POS_MAP.get(info.get("defaultPositionId"))
        name=info.get("fullName") or info.get("name")
        if not pos or not name: continue
        p=ensure(players,name,pos,TEAM_MAP.get(info.get("proTeamId"),""))
        p["team"]=TEAM_MAP.get(info.get("proTeamId"),p.get("team",""))
        p["injuryStatus"]=info.get("injuryStatus","")
        for st in info.get("stats",[]):
            if st.get("seasonId")==SEASON and st.get("statSourceId")==1 and st.get("appliedTotal") is not None:
                p["proj2026"]=round(float(st["appliedTotal"]),1)

def update_multisite_adp(players):
    html=request("https://www.4for4.com/adp").text
    soup=BeautifulSoup(html,"html.parser")
    found=0
    for tr in soup.select("tr"):
        cells=[c.get_text(" ",strip=True) for c in tr.select("th,td")]
        if len(cells)<15 or not re.fullmatch(r"\d+(?:\.\d+)?",cells[0]): continue
        if not re.fullmatch(r"(QB|RB|WR|TE|K|DEF|DST)-\d+",cells[1],re.I): continue
        pos=cells[1].split("-")[0].upper().replace("DEF","DST")
        name,team=cells[2],cells[3]
        p=ensure(players,name,pos,team)
        def num(i):
            try:return float(re.sub(r"[^0-9.\-]","",cells[i]))
            except:return ""
        p.setdefault("sourceRanks",{}).update({
          "market":num(0),"cbs":num(4),"espn":num(5),"nfl":num(9),
          "sleeper":num(10),"yahoo":num(11),"underdog":num(14)
        })
        found+=1
    if not found:
        raise RuntimeError("4for4 table layout changed; prior values retained")

def update_history(players, season):
    url=f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_reg_{season}.csv"
    text=request(url).text
    for row in csv.DictReader(io.StringIO(text)):
        pos=(row.get("position") or row.get("position_group") or "").upper()
        if pos not in {"QB","RB","WR","TE","K"}: continue
        name=row.get("player_display_name") or row.get("player_name")
        if not name: continue
        p=ensure(players,name,pos,row.get("team") or row.get("recent_team") or "")
        def n(*names):
            for nm in names:
                try:return float(row.get(nm) or 0)
                except:pass
            return 0
        gp=n("games","games_played")
        ppr=n("fantasy_points_ppr")
        stats={
          "gp":gp,"ppr":round(ppr,1),"ppg":round(ppr/gp,1) if gp else "",
          "targets":n("targets"),"receptions":n("receptions"),"recYds":n("receiving_yards"),
          "carries":n("carries","rushing_attempts"),"rushYds":n("rushing_yards"),
          "td":n("passing_tds")+n("rushing_tds")+n("receiving_tds")+n("special_teams_tds")
        }
        p[f"stats{season}"]=stats

def update_news(players):
    url="https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=100"
    articles=request(url).json().get("articles",[])
    cutoff=datetime.now(timezone.utc)-timedelta(days=3)
    news=[]
    by_name={p["name"].lower():p for p in players.values()}
    for a in articles:
        raw=a.get("published") or a.get("lastModified")
        try: published=datetime.fromisoformat(raw.replace("Z","+00:00")) if raw else cutoff
        except: published=cutoff
        if published<cutoff: continue
        headline=a.get("headline",""); summary=a.get("description","")
        if not re.search(r"injur|questionable|out\b|ir\b|trade|sign|waiv|release|suspend|practice|limited",headline+" "+summary,re.I):
            continue
        matched=[]
        for cat in a.get("categories",[]):
            athlete=cat.get("athlete") or {}
            if athlete.get("displayName"): matched.append(athlete["displayName"])
        if not matched:
            lower=(headline+" "+summary).lower()
            matched=[p["name"] for p in players.values() if p["name"].lower() in lower]
        url=(a.get("links") or {}).get("web",{}).get("href","")
        for name in dict.fromkeys(matched):
            p=by_name.get(name.lower())
            if not p: continue
            flag="NEW" if datetime.now(timezone.utc)-published<timedelta(days=1) else "RECENT"
            p.update({"newsFlag":flag,"newsDate":published.isoformat(),"newsSummary":headline,"newsUrl":url})
            news.append({"published":published.isoformat(),"player":p["name"],"team":p.get("team",""),"headline":headline,"summary":summary,"url":url})
    return sorted(news,key=lambda x:x["published"],reverse=True)

def main():
    data=load_data()
    players={p["key"]:p for p in data.get("players",[])}
    steps=[
      ("ESPN projections",lambda:update_espn(players)),
      ("multi-site ADP",lambda:update_multisite_adp(players)),
      ("2025 stats",lambda:update_history(players,2025)),
      ("2024 stats",lambda:update_history(players,2024)),
    ]
    for label,fn in steps:
        try:
            fn(); print("OK",label)
        except Exception as exc:
            print("WARN",label,exc,file=sys.stderr)
    try:
        data["news"]=update_news(players); print("OK news")
    except Exception as exc:
        print("WARN news",exc,file=sys.stderr)
    ordered=sorted(players.values(),key=lambda p:(float(p.get("sourceRanks",{}).get("market") or p.get("rank") or 9999),p["name"]))
    for i,p in enumerate(ordered,1):
        if not p.get("rank") or p["rank"]==9999: p["rank"]=i
    data["players"]=ordered
    data.setdefault("meta",{}).update({"season":SEASON,"scoring":"ESPN PPR","updatedAt":datetime.now(timezone.utc).isoformat()})
    write_data(data)

if __name__=="__main__":
    main()
