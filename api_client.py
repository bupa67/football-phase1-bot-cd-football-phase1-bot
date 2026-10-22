"""Client per API-Football.com (apifootball.com) con normalizzazione dati."""
from __future__ import annotations

import time
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

from config import FilterConfig
from credentials import get_secret

BASE_URL = "https://apiv3.apifootball.com/"
logger = logging.getLogger(__name__)

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
    return {"APIkey": key.strip()}


def _api_request(action: str, params: dict) -> list:
    """Esegue richiesta HTTP a apifootball.com con rate limiting."""
    global _last_call
    wait = 1.2 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    req_params = {**_get_params(), "action": action, **params}
    
    try:
        r = requests.get(BASE_URL, params=req_params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        
        # apifootball restituisce un array, ma in caso di errore a volte restituisce {"error": "..."}
        if isinstance(payload, dict) and "error" in payload:
            err_msg = str(payload["error"]).lower()
            if "invalid api key" in err_msg or "wrong api key" in err_msg:
                raise ApiError("Chiave API non valida. Controlla la dashboard di apifootball.com")
            raise ApiError(f"Errore API: {payload['error']}")
            
        return payload if isinstance(payload, list) else []
        
    except requests.RequestException as exc:
        raise ApiError(f"Errore di rete: {exc}") from exc
    except ValueError:
        raise ApiError("Risposta API non valida (non JSON)")


# ----------------------------------------------------------------------
# NORMALIZZAZIONE DATI
# Trasforma il formato piatto di apifootball.com nel formato annidato 
# che filters.py e app.py si aspettano.
# ----------------------------------------------------------------------
def _normalize_match(m: dict) -> dict:
    """Converte il formato apifootball nel formato standardizzato."""
    # Gestione sicura dei punteggi (a volte sono stringhe vuote "")
    def safe_int(val):
        try:
            return int(val) if val not in ("", None, "?") else None
        except (ValueError, TypeError):
            return None

    ft_h = safe_int(m.get("match_hometeam_score"))
    ft_a = safe_int(m.get("match_awayteam_score"))
    ht_h = safe_int(m.get("match_hometeam_halftime_score"))
    ht_a = safe_int(m.get("match_awayteam_halftime_score"))

    # Apifootball usa "Finished", "Not Started", "Halftime", ecc.
    status_raw = m.get("match_status", "NS")
    status_map = {"Finished": "FT", "Not Started": "NS", "Halftime": "HT", "Cancelled": "CANC"}
    status = status_map.get(status_raw, status_raw[:2].upper() if status_raw else "NS")

    return {
        "fixture": {
            "id": int(m.get("match_id", 0)),
            "date": f"{m.get('match_date', '')} {m.get('match_time', '')}".strip(),
            "timestamp": None,  # Apifootball non lo fornisce direttamente, useremo la data
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
    """Recupera le partite di una specifica data per una lista di leghe."""
    # Apifootball richiede from e to. Per un singolo giorno, sono uguali.
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
    """Recupera le quote per una specifica partita."""
    raw = _api_request("get_odds", {"match_id": str(match_id)})
    return raw  # Ritorniamo raw, lo parseremo in extract_odds


def get_odds(fixture_id: int) -> list:
    return _odds_cached(int(fixture_id))


@st.cache_data(ttl=21600, show_spinner=False)
def _history_cached(team_id: int, from_date: str, to_date: str) -> list:
    """Recupera lo storico partite di una squadra in un range di date."""
    raw = _api_request("get_events", {
        "team_id": str(team_id),
        "from": from_date,
        "to": to_date
    })
    # Filtriamo solo le partite finite
    return [_normalize_match(m) for m in raw if m.get("fixture", {}).get("status", {}).get("short") == "FT"]


def get_team_last_matches(team_id: int, league_id: int, season: int, last: int = 20) -> list:
    """Recupera le ultime N partite. Usiamo un range di 4 mesi per sicurezza."""
    today = date.today()
    from_date = (today - timedelta(days=120)).isoformat()
    to_date = today.isoformat()
    
    all_finished = _history_cached(int(team_id), from_date, to_date)
    # Ordiniamo per data decrescente (più recenti prima) e prendiamo le ultime N
    # Nota: la data è "YYYY-MM-DD HH:MM", l'ordinamento stringa funziona
    sorted_matches = sorted(all_finished, key=lambda x: x["fixture"]["date"], reverse=True)
    return sorted_matches[:last]


# ----------------------------------------------------------------------
# PARSING QUOTE (Specifico per apifootball.com)
# ----------------------------------------------------------------------
def extract_odds(odds_data: list, preferred: List[str]) -> Tuple[dict, str]:
    """
    Estrae le quote dal formato specifico di apifootball.com.
    odds_data è una lista con un elemento: [{"match_id": "123", "odd_bookmakers": [...]}]
    """
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

    # 1) Cerca bookmaker preferito completo
    for name in preferred:
        if name in parsed and complete(parsed[name]):
            return parsed[name], name
            
    # 2) Cerca qualsiasi bookmaker completo
    for name, p in parsed.items():
        if complete(p):
            return p, name
            
    # 3) Fallback parziale
    for name in preferred:
        if name in parsed:
            return parsed[name], name

    return {"home": None, "draw": None, "away": None, "over25": None}, ""
