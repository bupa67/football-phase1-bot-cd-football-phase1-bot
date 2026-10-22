"""Client per API-Football.com (apifootball.com) - FIX formato data e debug."""
from __future__ import annotations

import time
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

from config import FilterConfig
from credentials import get_secret

BASE_URL = "https://apiv3.apifootball.com/"
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

_last_call = 0.0


class ApiError(RuntimeError):
    pass


class QuotaExceeded(ApiError):
    pass


def _get_params() -> dict:
    key = get_secret("API_FOOTBALL_KEY")
    if not key or not key.strip():
        raise ApiError(
            "API_FOOTBALL_KEY mancante. "
            "Locale: controlla il file .env\n"
            "Cloud: Settings → Secrets → salva e fai Restart app"
        )
    return {"APIkey": key.strip()}


def _api_request(action: str, params: dict) -> list:
    global _last_call
    wait = 1.2 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    req_params = {**_get_params(), "action": action, **params}
    
    try:
        r = requests.get(BASE_URL, params=req_params, timeout=20)
        
        if r.status_code != 200:
            safe_url = r.url.replace(req_params["APIkey"], "CHIAVE_NASCOSTA")
            raise ApiError(
                f"Errore HTTP {r.status_code}\n"
                f"URL: {safe_url}\n"
                f"Risposta: {r.text[:500]}"
            )
            
        payload = r.json()
        
        if isinstance(payload, dict) and "error" in payload:
            err_msg = str(payload["error"])
            if "invalid api key" in err_msg.lower() or "wrong api key" in err_msg.lower():
                raise ApiError("Chiave API non valida. Controlla la dashboard di apifootball.com")
            raise ApiError(f"Errore API: {err_msg}")
            
        return payload if isinstance(payload, list) else []
        
    except requests.RequestException as exc:
        raise ApiError(f"Errore di rete: {exc}") from exc
    except ValueError:
        raise ApiError("Risposta API non valida (non JSON)")


def _normalize_match(m: dict) -> dict:
    def safe_int(val):
        try:
            return int(val) if val not in ("", None, "?") else None
        except (ValueError, TypeError):
            return None

    ft_h = safe_int(m.get("match_hometeam_score"))
    ft_a = safe_int(m.get("match_awayteam_score"))
    ht_h = safe_int(m.get("match_hometeam_halftime_score"))
    ht_a = safe_int(m.get("match_awayteam_halftime_score"))

    status_raw = m.get("match_status", "NS")
    status_map = {"Finished": "FT", "Not Started": "NS", "Halftime": "HT", "Cancelled": "CANC"}
    status = status_map.get(status_raw, status_raw[:2].upper() if status_raw else "NS")

    return {
        "fixture": {
            "id": int(m.get("match_id", 0)),
            "date": f"{m.get('match_date', '')} {m.get('match_time', '')}".strip(),
            "timestamp": None,
            "status": {"short": status},
        },
        "league": {
            "id": int(m.get("league_id", 0)),
            "name": m.get("league_name", "Unknown"),
            "season": int(m.get("league_season", 2026)),
        },
        "teams": {
            "home": {"id": int(m.get("match_hometeam_id", 0)), "name": m.get("match_hometeam_name", "Unknown")},
            "away": {"id": int(m.get("match_awayteam_id", 0)), "name": m.get("match_awayteam_name", "Unknown")},
        },
        "score": {
            "fulltime": {"home": ft_h, "away": ft_a},
            "halftime": {"home": ht_h, "away": ht_a},
        }
    }


def _convert_date_format(iso_date: str) -> str:
    """Converte 'yyyy-mm-dd' in 'dd-mm-yyyy' (formato richiesto da apifootball.com)."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return d.strftime("%d-%m-%Y")
    except ValueError:
        return iso_date


@st.cache_data(ttl=600, show_spinner=False)
def _fixtures_for_league_cached(date_ddmmyyyy: str, league_id: int) -> list:
    """Recupera le partite per UNA singola lega in una data."""
    raw = _api_request("get_events", {
        "from": date_ddmmyyyy,
        "to": date_ddmmyyyy,
        "league_id": str(league_id)
    })
    
    # Debug: mostra quanti match grezzi arrivano
    if raw:
        logger.info(f"✅ Lega {league_id}: ricevuti {len(raw)} match grezzi")
        sample_statuses = [m.get("match_status", "N/A") for m in raw[:3]]
        logger.info(f"📋 Status sample: {sample_statuses}")
    
    # NON filtrare per status - restituisci tutto per debug
    return [_normalize_match(m) for m in raw]


def get_fixtures_today(cfg: FilterConfig, day: Optional[str] = None) -> list:
    """Recupera partite per TUTTE le leghe selezionate, una alla volta."""
    day = day or date.today().isoformat()
    date_ddmmyyyy = _convert_date_format(day)
    
    all_fixtures = []
    for league_id in cfg.LEAGUES:
        try:
            fixtures = _fixtures_for_league_cached(date_ddmmyyyy, league_id)
            all_fixtures.extend(fixtures)
        except ApiError as e:
            logger.warning(f"Errore per lega {league_id}: {e}")
            continue
    
    logger.info(f"📊 Totale partite ricevute: {len(all_fixtures)}")
    return all_fixtures


@st.cache_data(ttl=900, show_spinner=False)
def _odds_cached(match_id: int) -> list:
    raw = _api_request("get_odds", {"match_id": str(match_id)})
    return raw


def get_odds(fixture_id: int) -> list:
    return _odds_cached(int(fixture_id))


@st.cache_data(ttl=21600, show_spinner=False)
def _history_cached(team_id: int, from_date: str, to_date: str) -> list:
    raw = _api_request("get_events", {
        "team_id": str(team_id),
        "from": from_date,
        "to": to_date
    })
    return [_normalize_match(m) for m in raw if m.get("fixture", {}).get("status", {}).get("short") == "FT"]


def get_team_last_matches(team_id: int, league_id: int, season: int, last: int = 20) -> list:
    today = date.today()
    from_date = _convert_date_format((today - timedelta(days=120)).isoformat())
    to_date = _convert_date_format(today.isoformat())
    
    all_finished = _history_cached(int(team_id), from_date, to_date)
    sorted_matches = sorted(all_finished, key=lambda x: x["fixture"]["date"], reverse=True)
    return sorted_matches[:last]


def extract_odds(odds_data: list, preferred: List[str]) -> Tuple[dict, str]:
    if not odds_data:
        return {"home": None, "draw": None, "away": None, "over25": None}, ""

    bookmakers_data = odds_data[0].get("odd_bookmakers", [])
    parsed: Dict[str, dict] = {}

    for bm in bookmakers_data:
        name = bm.get("odd_bookmaker", "Unknown").strip()
        try:
            parsed[name] = {
                "home": float(bm.get("odd_1", 0)) or None,
                "draw": float(bm.get("odd_x", 0)) or None,
                "away": float(bm.get("odd_2", 0)) or None,
                "over25": float(bm.get("odd_over", 0)) or None,
            }
        except (ValueError, TypeError):
            continue

    def complete(p: dict) -> bool:
        return all(p.get(k) is not None and p.get(k) > 1.0 for k in ("home", "draw", "away"))

    for name in preferred:
        if name in parsed and complete(parsed[name]):
            return parsed[name], name
    for name, p in parsed.items():
        if complete(p):
            return p, name
    for name in preferred:
        if name in parsed:
            return parsed[name], name

    return {"home": None, "draw": None, "away": None, "over25": None}, ""


def test_api_connection() -> str:
    key = get_secret("API_FOOTBALL_KEY")
    if not key or not key.strip():
        return "❌ La chiave API è vuota o non configurata."
    
    url = "https://apiv3.apifootball.com/"
    params = {"APIkey": key.strip(), "action": "get_countries"}
    
    try:
        r = requests.get(url, params=params, timeout=10)
        
        if r.status_code != 200:
            return f"❌ Errore HTTP {r.status_code}. Risposta: {r.text}"
            
        data = r.json()
        
        if isinstance(data, dict) and "error" in data:
            return f"❌ Errore dall'API: {data['error']}"
            
        if isinstance(data, list) and len(data) > 0:
            return f"✅ Connessione riuscita! Trovati {len(data)} paesi. La chiave è valida."
            
        return f"⚠️ Risposta inaspettata: {data}"
        
    except Exception as e:
        return f"❌ Eccezione: {str(e)}"

@st.cache_data(ttl=86400, show_spinner=False)
def get_available_leagues() -> list:
    """Recupera la lista di tutte le leghe disponibili su apifootball.com."""
    raw = _api_request("get_leagues", {})
    return raw

def search_leagues(query: str = "") -> list:
    """Cerca leghe per nome. Se query è vuota, restituisce le prime 50."""
    all_leagues = get_available_leagues()
    if not query:
        return all_leagues[:50]
    
    query_lower = query.lower()
    return [
        l for l in all_leagues
        if query_lower in l.get("league_name", "").lower()
        or query_lower in l.get("country_name", "").lower()
    ]
