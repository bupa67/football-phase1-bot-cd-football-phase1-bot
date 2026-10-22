"""Client API-Football v3 con debug completo."""
from __future__ import annotations

import time
import logging
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import streamlit as st

from config import FilterConfig
from credentials import get_secret

# Configura logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"
FINISHED = {"FT", "AET", "PEN"}

_last_call = 0.0


class ApiError(RuntimeError):
    pass


class QuotaExceeded(ApiError):
    pass


def _headers() -> dict:
    """Costruisce gli header con debug completo."""
    key = get_secret("API_FOOTBALL_KEY")
    
    # Debug: mostra info sulla chiave (senza rivelarla tutta)
    if key:
        key_preview = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "chiave troppo corta"
        logger.info(f"✅ API Key trovata: {key_preview}")
        logger.info(f" Lunghezza chiave: {len(key)} caratteri")
    else:
        logger.error("❌ API Key NON trovata!")
        raise ApiError(
            "API_FOOTBALL_KEY mancante. "
            "Locale: controlla il file .env\n"
            "Cloud: Settings → Secrets → salva e fai Restart app"
        )
    
    # Verifica formato chiave
    if not key.strip():
        raise ApiError("API Key è vuota o contiene solo spazi")
    
    # Headers compatibili con TUTTE le versioni API
    headers = {
        "x-apisports-key": key.strip(),
    }
    
    # Aggiungi header RapidAPI solo se sembra una chiave RapidAPI
    if "rapid" in key.lower() or len(key) > 30:
        headers["x-rapidapi-key"] = key.strip()
        headers["x-rapidapi-host"] = "v3.football.api-sports.io"
    
    logger.info(f"📤 Headers inviati: {list(headers.keys())}")
    return headers


def _get(path: str, params: dict) -> list:
    """Esegue richiesta HTTP con logging completo."""
    global _last_call
    
    # Rate limiting
    wait = 1.2 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    
    url = BASE_URL + path
    headers = _headers()
    
    logger.info(f"🔗 Richiesta: {url}")
    logger.info(f"📦 Params: {params}")
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        logger.info(f"📥 Risposta HTTP {r.status_code}")
        
        # Log dettagliato errori
        if r.status_code != 200:
            logger.error(f" Errore HTTP {r.status_code}")
            logger.error(f"📄 Response: {r.text[:500]}")
        
    except requests.RequestException as exc:
        logger.error(f"💥 Errore di rete: {exc}")
        raise ApiError(f"Errore di rete verso API-Football: {exc}") from exc

    if r.status_code == 401:
        raise ApiError(
            "❌ Errore 401: Chiave API non valida.\n"
            "1. Verifica di aver copiato la chiave corretta da RapidAPI o API-Football\n"
            "2. Controlla che non ci siano spazi prima/dopo la chiave\n"
            "3. Su Streamlit Cloud: fai Manage app → Restart app"
        )
    
    if r.status_code == 403:
        raise ApiError(
            "❌ Errore 403: Accesso negato.\n"
            "- Il tuo piano API potrebbe essere scaduto\n"
            "- Verifica su https://rapidapi.com/developer/dashboard"
        )
    
    if r.status_code in (429, 499):
        raise QuotaExceeded("️ Quota API esaurita. Riprova domani.")

    try:
        payload = r.json()
    except ValueError:
        logger.error(f"❌ Risposta non è JSON: {r.text[:200]}")
        raise ApiError("Risposta API non valida (non JSON)")

    # Controlla errori nell'payload
    errors = payload.get("errors") or payload.get("error")
    if errors:
        error_msg = str(errors)
        logger.error(f"❌ Errore API: {error_msg}")
        
        if "key" in error_msg.lower() or "token" in error_msg.lower():
            raise ApiError(
                f"❌ Errore chiave API: {error_msg}\n"
                "SOLUZIONE:\n"
                "1. Vai su Manage app → Settings → Secrets\n"
                "2. Clicca 'Edit secrets'\n"
                "3. Assicurati che sia scritto ESATTAMENTE così:\n"
                '   API_FOOTBALL_KEY = "la_tua_chiave"\n'
                "4. Clicca Save\n"
                "5. Clicca Restart app"
            )
        raise ApiError(error_msg)

    response = payload.get("response")
    if response is None:
        logger.warning("⚠️ Campo 'response' vuoto nell'API")
        return []
    
    logger.info(f"✅ Ricevuti {len(response)} elementi")
    return response


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
        if status not in {"NS", "TBD"}:
            continue
        if fx.get("timestamp") and fx["timestamp"] < now:
            continue
        upcoming.append(f)
    return upcoming


@st.cache_data(ttl=900, show_spinner=False)
def _odds_cached(fixture_id: int) -> list:
    return _get("/odds", {"fixture": fixture_id})


def get_odds(fixture_id: int) -> list:
    return _odds_cached(int(fixture_id))


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
    parsed: Dict[str, dict] = {}
    for book in odds_data or []:
        for bm in book.get("bookmakers") or []:
            name = bm.get("name", "unknown")
            if name not in parsed:
                parsed[name] = _parse_bookmaker(bm)

    def complete(p: dict) -> bool:
        return all(p.get(k) is not None for k in ("home", "draw", "away"))

    for name in preferred:
        if complete(parsed.get(name, {})):
            return parsed[name], name
    for name, p in parsed.items():
        if complete(p):
            return p, name
    for name in preferred:
        if name in parsed:
            return parsed[name], name

    return {"home": None, "draw": None, "away": None, "over25": None}, ""
