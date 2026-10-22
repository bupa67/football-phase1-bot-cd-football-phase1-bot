"""Configurazione centrale dei filtri Fase 1."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class FilterConfig:
    # --- Filtro 1 ---
    over25_max_odds: float = 1.80
    avg_goals_min: float = 2.6
    use_avg_goals_alternative: bool = True   # accetta ALSO Media Gol > soglia

    # --- Filtro 2 ---
    zero_zero_max_pct: float = 10.0          # STRICT < 10%
    zero_zero_sample_size: int = 20

    # --- Filtro 3 ---
    ht_over05_min_pct: float = 70.0          # >= 70%
    ht_sample_size: int = 20

    # --- guardia statistica ---
    min_sample_size: int = 10                # sotto 10 gare = non valutabile

    # --- Filtro 4 ---
    home_fav_min_odds: float = 1.40
    home_fav_max_odds: float = 1.85

    # --- Filtro 5 ---
    draw_min_odds: float = 3.40
    draw_max_odds: float = 4.30

    # ==========================================================
    # CAMPI MUTABILI: obbligatorio default_factory, MAI = [] o = {}
    # ==========================================================
    LEAGUES: List[int] = field(
        default_factory=lambda: [39, 140, 78, 135, 61, 88]
    )
    LEAGUES_NAMES: Dict[int, str] = field(
        default_factory=lambda: {
            39: "Premier League",
            140: "La Liga",
            78: "Bundesliga",
            135: "Serie A",
            61: "Ligue 1",
            88: "Eredivisie",
        }
    )
    PREFERRED_BOOKMAKERS: List[str] = field(
        default_factory=lambda: ["Pinnacle", "Betfair", "1xBet", "Bet365"]
    )
    SEASON: int = 2026
