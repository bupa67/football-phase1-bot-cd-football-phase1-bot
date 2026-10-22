"""Configurazione centrale dei filtri e parametri."""
from dataclasses import dataclass
from typing import List

@dataclass
class FilterConfig:
    """Parametri dei 5 filtri della Fase 1 (modificabili dalla UI)."""
    # Filtro 1: Over 2.5
    over25_max_odds: float = 1.80
    avg_goals_min: float = 2.6  # alternativa al filtro 1

    # Filtro 2: 0-0 storici
    zero_zero_max_pct: float = 10.0  # percentuale
    zero_zero_sample_size: int = 20

    # Filtro 3: Over 0.5 1HT
    ht_over05_min_pct: float = 70.0
    ht_sample_size: int = 20

    # Filtro 4: Favorita in casa
    home_fav_min_odds: float = 1.40
    home_fav_max_odds: float = 1.85

    # Filtro 5: Pareggio
    draw_min_odds: float = 3.40
    draw_max_odds: float = 4.30

    # Campionati target (ID API-Football)
    LEAGUES: List[int] = [39, 140, 78, 135, 61, 88]  # PL, Liga, BL, SA, L1, Ere
    LEAGUES_NAMES: dict = {
        39: "Premier League",
        140: "La Liga",
        78: "Bundesliga",
        135: "Serie A",
        61: "Ligue 1",
        88: "Eredivisie",
    }
    SEASON: int = 2026

    # Bookmaker di riferimento per le quote
    PREFERRED_BOOKMAKERS: List[str] = ["Pinnacle", "Betfair", "1xBet", "Bet365"]
