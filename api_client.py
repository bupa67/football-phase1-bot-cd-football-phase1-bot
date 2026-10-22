"""Client per API-Football.com (apifootball.com) con debug avanzato."""
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

# Configura logging per mostrare i messaggi anche su Streamlit Cloud
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

_last_call = 0.0


class ApiError(RuntimeError):
    pass


class QuotaExceeded(ApiError):
    pass


def _get_params() -> dict:
    """Restituisce i parametri di autenticazione per apifootball.com."""
    key = get_secret("API_FOOTBALL_KEY")
    if not key or not key.strip():
        raise ApiError(
            "API_FOOTBALL_KEY mancante. "
            "Locale: controlla il file .env\n"
            "Cloud: Settings → Secrets → salva e fai Restart app"
        )
    # NOTA: apifootball.com richiede ESATTAMENTE "APIkey" (case-sensitive)
    return {"APIkey": key.strip()}


def _api_request(action: str, params: dict) -> list:
    """Esegue richiesta HTTP a apifootball.com con debug completo."""
    global _last_call
    wait = 1.2 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    req_params = {**_get_params(), "action": action, **params}
    
    # Costruiamo l'URL completo per il debug (così vediamo se c'è un errore di battitura)
    query_string = "&".join([f"{k}={v}" for k, v in req_params.items()])
    full_url = f"{BASE_URL.rstrip('/')}?{query_string}"
    
    # Mascheriamo la chiave API nel log per sicurezza
    safe_url = full_url.replace(req_params["APIkey"], "CHIAVE_NASCOSTA")
    logger.info(f"🔗 URL Richiesta: {safe_url}")
    
    try:
        r = requests.get(BASE_URL, params=req_params, timeout=20)
        logger.info(f"📥 Status Code: {r.status_code}")
        logger.info(f"📄 Raw Response: {r.text[:1000]}")  # Prime 1000 caratteri
        
        if r.status_code != 200:
            raise ApiError(f"Errore HTTP {r.status_code}: {r.text}")
            
        payload = r.json()
        
        # apifootball a volte restituisce {"error": "messaggio"} invece di una lista
        if isinstance(payload, dict) and "error" in payload:
            err_msg = str(payload["error"])
            logger.error(f"❌ Errore dal server API: {err_msg}")
            
            if "invalid api key" in err_msg.lower() or "wrong api key" in err_msg.lower():
                raise ApiError(
                    "Chiave API non valida.\n"
                    "1. Vai su https://apifootball.com/admin/\n"
                    "2. Copia la chiave ESATTAMENTE come appare (no spazi)\n"
                    "3. Su Streamlit Cloud: ricorda le virgolette \" \" nei Secrets e fai Restart app"
                )
            raise ApiError(f"Errore API: {err_msg}")
            
        return payload if isinstance(payload, list) else []
        
    except requests.RequestException as exc:
        logger.error(f"💥 Errore di rete: {exc}")
        raise ApiError(f"Errore di rete: {exc}") from exc
    except ValueError:
        logger.error(f"❌ Risposta non JSON: {r.text}")
        raise ApiError("Risposta API non valida (non JSON)")


# ----------------------------------------------------------------------
# NORMALIZZAZIONE DATI
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# ENDPOINTS
# ----------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _fixtures_cached(date_str: str, league_ids: tuple) -> list:
    raw = _api_request("get_events", {
        "from": date_str,
        "to": date_str,
        "league_id": ",".join(str(x) for x in league_ids)
    })
    return [_normalize_match(m) for m in raw if m.get("match_status") in ("Not Started", "NS", "TBD")]


def get_fixtures_today(cfg: FilterConfig, day: Optional[str] = None) -> list:
    day = day or date.today().isoformat()
    return _fixtures_cached(day, tuple(sorted(cfg.LEAGUES)))


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
    from_date = (today - timedelta(days=120)).isoformat()
    to_date = today.isoformat()
    
    all_finished = _history_cached(int(team_id), from_date, to_date)
    sorted_matches = sorted(all_finished, key=lambda x: x["fixture"]["date"], reverse=True)
    return sorted_matches[:last]


# ----------------------------------------------------------------------
# PARSING QUOTE
# ----------------------------------------------------------------------
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
