"""Implementazione dei 5 filtri della Fase 1."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import FilterConfig
from api_client import get_team_last_matches, extract_odds


@dataclass
class FilterResult:
    """Risultato dell'analisi di una partita."""
    fixture_id: int
    home: str
    away: str
    league: str
    kickoff: str
    odds: Dict[str, Optional[float]] = field(default_factory=dict)
    filters: Dict[str, Dict] = field(default_factory=dict)
    passed: bool = False
    passed_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "Partita": f"{self.home} vs {self.away}",
            "Campionato": self.league,
            "Odds Over 2.5": f"{self.odds.get('over25', '-')}",
            "Odds Casa": f"{self.odds.get('home', '-')}",
            "Odds Pareggio": f"{self.odds.get('draw', '-')}",
            "Filtri superati": f"{self.passed_count}/5",
            "✅": "SÌ" if self.passed else "NO",
        }


def _count_0_0(matches: List[Dict]) -> int:
    count = 0
    for m in matches:
        ft = m["score"]["fulltime"]
        if ft["home"] == 0 and ft["away"] == 0:
            count += 1
    return count


def _count_1ht_over05(matches: List[Dict]) -> int:
    count = 0
    for m in matches:
        ht = m["score"]["halftime"]
        if ht["home"] is not None and (ht["home"] + ht["away"]) >= 1:
            count += 1
    return count


def analyze_fixture(fixture: Dict, odds_data: List[Dict], cfg: FilterConfig) -> FilterResult:
    """Analizza un singolo fixture contro tutti i 5 filtri."""
    result = FilterResult(
        fixture_id=fixture["fixture"]["id"],
        home=fixture["teams"]["home"]["name"],
        away=fixture["teams"]["away"]["name"],
        league=fixture["league"]["name"],
        kickoff=fixture["fixture"]["date"],
    )

    # Estrazione quote
    odds = extract_odds(odds_data, cfg.PREFERRED_BOOKMAKERS)
    result.odds = odds
    if not all(v is not None for v in odds.values()):
        result.filters["quote"] = {"value": "N/D", "pass": False, "msg": "Quote incomplete"}
        return result

    # === FILTRO 1: Over 2.5 <= 1.80 ===
    f1_pass = odds["over25"] <= cfg.over25_max_odds
    result.filters["F1_Over 2.5"] = {
        "value": f"{odds['over25']:.2f} (≤ {cfg.over25_max_odds})",
        "pass": f1_pass,
    }

    # === FILTRO 4: Favorita in casa 1.40 - 1.85 ===
    fav_is_home = odds["home"] < odds["away"]
    f4_pass = fav_is_home and cfg.home_fav_min_odds <= odds["home"] <= cfg.home_fav_max_odds
    result.filters["F4_Casa favorita"] = {
        "value": f"{odds['home']:.2f} ({cfg.home_fav_min_odds}-{cfg.home_fav_max_odds})",
        "pass": f4_pass,
    }

    # === FILTRO 5: Pareggio 3.40 - 4.30 ===
    f5_pass = cfg.draw_min_odds <= odds["draw"] <= cfg.draw_max_odds
    result.filters["F5_Pareggio"] = {
        "value": f"{odds['draw']:.2f} ({cfg.draw_min_odds}-{cfg.draw_max_odds})",
        "pass": f5_pass,
    }

    # Early exit: se le quote non passano, non sprechiamo API calls
    if not (f1_pass and f4_pass and f5_pass):
        result.passed_count = sum([f1_pass, f4_pass, f5_pass])
        return result

    # === FILTRI 2 e 3: statistiche squadre ===
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    league_id = fixture["league"]["id"]
    season = fixture["league"]["season"]

    home_matches = get_team_last_matches(home_id, league_id, season, cfg.zero_zero_sample_size)
    away_matches = get_team_last_matches(away_id, league_id, season, cfg.zero_zero_sample_size)

    # Filtro 2: 0-0 < 10%
    max_00 = int(cfg.zero_zero_max_pct / 100 * cfg.zero_zero_sample_size)
    h_00 = _count_0_0(home_matches)
    a_00 = _count_0_0(away_matches)
    f2_pass = (h_00 <= max_00) and (a_00 <= max_00)
    result.filters["F2_Freq. 0-0"] = {
        "value": f"Casa: {h_00}/{len(home_matches)} | Trasf: {a_00}/{len(away_matches)} (max {max_00})",
        "pass": f2_pass,
    }

    # Filtro 3: Over 0.5 1HT >= 70%
    min_1ht = int(cfg.ht_over05_min_pct / 100 * cfg.ht_sample_size)
    h_1ht = _count_1ht_over05(home_matches)
    a_1ht = _count_1ht_over05(away_matches)
    f3_pass = (h_1ht >= min_1ht) and (a_1ht >= min_1ht)
    result.filters["F3_Gol 1°T"] = {
        "value": f"Casa: {h_1ht}/{len(home_matches)} | Trasf: {a_1ht}/{len(away_matches)} (min {min_1ht})",
        "pass": f3_pass,
    }

    # Totale
    all_pass = [f1_pass, f2_pass, f3_pass, f4_pass, f5_pass]
    result.passed_count = sum(all_pass)
    result.passed = all(all_pass)
    return result
