"""Client per API-Football (v3) con caching e rate limiting."""
import os
import time
import requests
from datetime import date
from typing import List, Dict, Optional
import streamlit as st

from config import FilterConfig

BASE_URL = "https://v3.football.api-sports.io"


def _get_headers() -> dict:
    key = os.getenv("API_FOOTBALL_KEY") or st.secrets.get("API_FOOTBALL_KEY", "")
    if not key:
        raise ValueError("API_FOOTBALL_KEY non configurata. Vedi .env.example")
    return {"x-apisports-key": key}


def _rate_limit():
    """Rispetta il rate limit del piano free (~10 req/min)."""
    time.sleep(1.2)


@st.cache_data(ttl=3600, show_spinner=False)
def get_fixtures_today(cfg: FilterConfig) -> List[Dict]:
    """Recupera le partite di oggi per i campionati target."""
    today = date.today().strftime("%Y-%m-%d")
    leagues = ",".join(str(l) for l in cfg.LEAGUES)
    params = {"date": today, "league": leagues, "season": cfg.SEASON}
    try:
        r = requests.get(
            f"{BASE_URL}/fixtures",
            headers=_get_headers(),
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception as e:
        st.error(f"Errore recupero partite: {e}")
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def get_odds(fixture_id: int) -> List[Dict]:
    """Recupera le quote pre-match per un fixture."""
    _rate_limit()
    try:
        r = requests.get(
            f"{BASE_URL}/odds",
            headers=_get_headers(),
            params={"fixture": fixture_id},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception:
        return []


@st.cache_data(ttl=7200, show_spinner=False)
def get_team_last_matches(team_id: int, league_id: int, season: int, last: int = 20) -> List[Dict]:
    """Recupera le ultime N partite giocate da una squadra."""
    _rate_limit()
    try:
        r = requests.get(
            f"{BASE_URL}/fixtures",
            headers=_get_headers(),
            params={
                "team": team_id,
                "league": league_id,
                "season": season,
                "last": last,
                "status": "FT",
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("response", [])
    except Exception:
        return []


def extract_odds(odds_data: List[Dict], bookmakers: List[str]) -> Dict[str, Optional[float]]:
    """Estrae le quote chiave dai dati grezzi."""
    result = {"home": None, "draw": None, "away": None, "over25": None}
    for book in odds_data:
        for bm in book.get("bookmakers", []):
            if bm["name"] not in bookmakers:
                continue
            for bet in bm["bets"]:
                if bet["name"] == "Match Winner":
                    for v in bet["values"]:
                        if v["value"] == "Home":
                            result["home"] = float(v["odd"])
                        elif v["value"] == "Draw":
                            result["draw"] = float(v["odd"])
                        elif v["value"] == "Away":
                            result["away"] = float(v["odd"])
                elif bet["name"] == "Over/Under":
                    for v in bet["values"]:
                        if v["value"] == "Over 2.5":
                            result["over25"] = float(v["odd"])
            if all(v is not None for v in result.values()):
                return result
    return result
