"""Configurazione centrale dei filtri Fase 1 (Compatibile con apifootball.com)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class FilterConfig:
    # --- Filtro 1 ---
    over25_max_odds: float = 1.80
    avg_goals_min: float = 2.6
    use_avg_goals_alternative: bool = True

    # --- Filtro 2 ---
    zero_zero_max_pct: float = 10.0
    zero_zero_sample_size: int = 20

    # --- Filtro 3 ---
    ht_over05_min_pct: float = 70.0
    ht_sample_size: int = 20

    # --- Guardia statistica ---
    min_sample_size: int = 10

    # --- Filtro 4 ---
    home_fav_min_odds: float = 1.40
    home_fav_max_odds: float = 1.85

    # --- Filtro 5 ---
    draw_min_odds: float = 3.40
    draw_max_odds: float = 4.30

    # ==========================================================
    # ID CAMPIONATI SPECIFICI DI APIFOOTBALL.COM
    # ==========================================================
    LEAGUES: List[int] = field(
        default_factory=lambda: [152, 302, 175, 207, 168, 266]
    )
    LEAGUES_NAMES: Dict[int, str] = field(
        default_factory=lambda: {
            152: "Premier League",
            302: "La Liga",
            175: "Bundesliga",
            207: "Serie A",
            168: "Ligue 1",
            266: "Eredivisie",
        }
    )
    PREFERRED_BOOKMAKERS: List[str] = field(
        default_factory=lambda: ["Bet365", "1xBet", "Pinnacle", "Betfair"]
    )
    SEASON: int = 2026  # Non strettamente usato da apifootball, ma mantenuto per compatibilità
