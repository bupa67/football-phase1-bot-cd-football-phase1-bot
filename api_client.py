"""Client API-Football v3: cache su chiavi hashabili, rate limit, error handling robusto."""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

from config import FilterConfig
from credentials import get_secret

BASE_URL = "https://v3.football.api-sports.io"
FINISHED = {"FT", "AET", "PEN"}

_last_call = 0.0


class ApiError(RuntimeError):
    pass


class QuotaExceeded(ApiError):
    pass


# ----------------------------------------------------------------------
# HTTP & HEADERS (FIX CRUCIALE: invia entrambi i formati di chiave)
# ----------------------------------------------------------------------
def _headers() -> dict:
    key = get_secret("API_FOOTBALL_KEY")
    if not key:
        raise ApiError(
            "API_FOOTBALL_KEY mancante. Configura il file .env (in locale) o "
            "Settings → Secrets (su Streamlit Cloud)."
        )
    
    # Inviamo entrambi gli header per massima compatibilità.
    # Funziona sia per chi usa RapidAPI che per chi usa API-Football diretto.
    return {
        "x-apisports-key": key,
        "x-rapidapi-key": key,
        "x-rapidapi-host": "v3.football.api-sports.io"
    }


def _get(path: str, params: dict) -> list:
    global _last_call
    # Rate limiting: rispetta il limite di ~10-15 richieste al minuto del piano free
    wait = 1.2 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

    try:
        r = requests.get(
            BASE_URL + path, headers=_headers(), params=params, timeout=20
        )
    except requests.RequestException as exc:
        raise ApiError(f"Errore di rete verso API-Football: {exc}") from exc

    if r.status_code in (401, 403):
        raise ApiError("Chiave API non valida, scaduta o piano non attivo. Controlla la tua dashboard.")
    if r.status_code in (429, 499):
        raise QuotaExceeded("Quota / rate limit API-Football esaurito.")

    r.raise_for_status()
    payload = r.json()

    errors = payload.get("errors")
    if errors:
        text = str(errors)
        if any(word in text.lower() for word in ("limit", "quota", "plan", "key", "token")):
            raise QuotaExceeded(text)
        raise ApiError(text)

    return payload.get("response") or []


# ----------------------------------------------------------------------
# FIXTURES (solo pre-match)
# ----------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _fixtures_cached(day: str, leagues: tuple, season: int) -> list:
    return _get("/fixtures", {
        "date": day,
        "league": ",".join(str(x) for x in leagues),
        "season": season,
    })


def get_fixtures_today(cfg: FilterConfig, day: Optional[str] = None) -> list:
    day = day or date.today().isoformat()
    raw = _fixtures_cached(day, tuple(sorted(cfg.LEAGUES)), int(cfg.SEASON))

    now = datetime.now(timezone.utc).timestamp()
    upcoming = []
    for f in raw:
        fx = f.get("fixture") or {}
        status = (fx.get("status") or {}).get("short", "NS")
        
        # Accetta solo partite non iniziate (NS = Not Started, TBD = To Be Defined)
        if status not in {"NS", "TBD"}:
            continue
        
        # Sicurezza extra: scarta partite il cui timestamp è già passato
        if fx.get("timestamp") and fx["timestamp"] < now:
            continue
            
        upcoming.append(f)
    return upcoming


# ----------------------------------------------------------------------
# QUOTE
# ----------------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def _odds_cached(fixture_id: int) -> list:
    return _get("/odds", {"fixture": fixture_id})


def get_odds(fixture_id: int) -> list:
    return _odds_cached(int(fixture_id))


# ----------------------------------------------------------------------
# STORICO SQUADRA
# ----------------------------------------------------------------------
@st.cache_data(ttl=21600, show_spinner=False)
def _history_cached(team_id: int, league_id: int, season: int, last: int) -> list:
    return _get("/fixtures", {
        "team": team_id, "league": league_id,
        "season": season, "last": last, "status": "FT",
    })


def get_team_last_matches(team_id: int, league_id: int,
                          season: int, last: int = 20) -> list:
    raw = _history_cached(int(team_id), int(league_id), int(season), int(last))
    return [
        m for m in raw
        if ((m.get("fixture") or {}).get("status") or {}).get("short") in FINISHED
    ]


# ----------------------------------------------------------------------
# PARSING QUOTE (normalizzato per gestire "1/X/2" e "Home/Draw/Away")
# ----------------------------------------------------------------------
def _norm(value) -> str:
    return str(value).strip().lower().replace(" ", "")


_HOME = {"1", "home", "h", "homewin"}
_DRAW = {"x", "draw", "d"}
_AWAY = {"2", "away", "a", "awaywin"}
_WIN_NAMES = {"matchwinner", "1x2", "matchresult", "win/draw/win", "fulltimeresult"}
_OU_NAMES = {"over/under", "overunder", "totals", "goalline", "goals"}


def _is_over_25(value: str, line) -> bool:
    if value in {"over2.5", "over2.50", "o2.5", "over2,5"}:
        return True
    if value in {"over", "o"} and line is not None:
        try:
            return float(line) == 2.5
        except (TypeError, ValueError):
            return False
    return False


def _parse_bookmaker(bm: dict) -> Dict[str, Optional[float]]:
    out = {"home": None, "draw": None, "away": None, "over25": None}

    for bet in bm.get("bets") or []:
        name = _norm(bet.get("name", ""))
        for v in bet.get("values") or []:
            try:
                odd = float(v.get("odd"))
            except (TypeError, ValueError):
                continue
            if odd <= 1.0:
                continue

            value = _norm(v.get("value", ""))

            if name in _WIN_NAMES:
                if value in _HOME:
                    out["home"] = odd
                elif value in _DRAW:
                    out["draw"] = odd
                elif value in _AWAY:
                    out["away"] = odd

            elif name in _OU_NAMES:
                if _is_over_25(value, v.get("line", bet.get("line"))):
                    out["over25"] = odd

    return out


def extract_odds(odds_data: list, preferred: List[str]) -> Tuple[dict, str]:
    """Restituisce (quote, nome_bookmaker). Priorità al bookmaker preferito."""
    parsed: Dict[str, dict] = {}
    for book in odds_data or []:
        for bm in book.get("bookmakers") or []:
            name = bm.get("name", "unknown")
            if name not in parsed:
                parsed[name] = _parse_bookmaker(bm)

    def complete(p: dict) -> bool:
        return all(p.get(k) is not None for k in ("home", "draw", "away"))

    # 1) Cerca bookmaker preferito con dati completi
    for name in preferred:
        if complete(parsed.get(name, {})):
            return parsed[name], name
            
    # 2) Cerca qualsiasi bookmaker con dati completi
    for name, p in parsed.items():
        if complete(p):
            return p, name
            
    # 3) Fallback: restituisci il primo bookmaker preferito trovato (anche parziale)
    for name in preferred:
        if name in parsed:
            return parsed[name], name

    return {"home": None, "draw": None, "away": None, "over25": None}, ""
