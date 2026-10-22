"""I 5 filtri della Fase 1, con parsing difensivo e soglie corrette."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from api_client import extract_odds, get_team_last_matches
from config import FilterConfig


@dataclass
class FilterResult:
    fixture_id: int
    home: str
    away: str
    league: str
    kickoff: str
    odds: Dict[str, Optional[float]] = field(default_factory=dict)
    filters: Dict[str, dict] = field(default_factory=dict)
    bookmaker: str = ""
    passed: bool = False
    passed_count: int = 0

    def to_dict(self) -> dict:
        def fmt(key):
            v = self.odds.get(key)
            return f"{v:.2f}" if v is not None else "n/d"

        return {
            "Partita": f"{self.home} vs {self.away}",
            "Campionato": self.league,
            "Bookmaker": self.bookmaker or "n/d",
            "Over 2.5": fmt("over25"),
            "Casa": fmt("home"),
            "Pareggio": fmt("draw"),
            "Filtri": f"{self.passed_count}/5",
            "✅ Qualificata": "SÌ" if self.passed else "NO",
        }


def _record(r: FilterResult, key: str, value: str, ok: bool, skipped: bool = False):
    r.filters[key] = {"value": value, "pass": bool(ok), "skipped": skipped}


def _score(match: dict, period: str):
    s = (match.get("score") or {}).get(period) or {}
    h, a = s.get("home"), s.get("away")
    if isinstance(h, int) and isinstance(a, int):
        return h, a
    return None


def _team_stats(matches: list) -> dict:
    n = zeros = ht = ht_n = total = 0

    for m in matches:
        ft = _score(m, "fulltime")
        if ft is None:
            continue
        n += 1
        total += ft[0] + ft[1]
        if ft == (0, 0):
            zeros += 1

        half = _score(m, "halftime")
        if half is not None:
            ht_n += 1
            if sum(half) > 0:
                ht += 1

    return {
        "n": n,
        "zeros": zeros,
        "zero_pct": 100.0 * zeros / n if n else 100.0,
        "ht": ht,
        "ht_n": ht_n,
        "ht_pct": 100.0 * ht / ht_n if ht_n else 0.0,
        "avg_goals": total / n if n else 0.0,
    }


def analyze_fixture(fixture: dict, odds_data: list, cfg: FilterConfig) -> FilterResult:
    r = FilterResult(
        fixture_id=fixture["fixture"]["id"],
        home=fixture["teams"]["home"]["name"],
        away=fixture["teams"]["away"]["name"],
        league=fixture["league"]["name"],
        kickoff=fixture["fixture"]["date"],
    )

    odds, bookmaker = extract_odds(odds_data, cfg.PREFERRED_BOOKMAKERS)
    r.odds, r.bookmaker = odds, bookmaker

    if any(odds.get(k) is None for k in ("home", "draw", "away")):
        _record(r, "Quote", "non disponibili", False)
        return r

    over = odds["over25"]
    f1_odds = over is not None and over <= cfg.over25_max_odds
    f4 = (odds["home"] < odds["away"]) and (
        cfg.home_fav_min_odds <= odds["home"] <= cfg.home_fav_max_odds
    )
    f5 = cfg.draw_min_odds <= odds["draw"] <= cfg.draw_max_odds

    over_txt = f"{over:.2f}" if over is not None else "n/d"

    # Early exit: non sprecare chiamate API se i filtri quota sono gia' falliti
    if not (f4 and f5):
        _record(r, "F1 Over 2.5", over_txt, f1_odds,
                skipped=cfg.use_avg_goals_alternative and not f1_odds)
        _record(r, "F2 Freq. 0-0", "non valutato", False, skipped=True)
        _record(r, "F3 Gol 1°T", "non valutato", False, skipped=True)
        _record(r, "F4 Casa favorita",
                f"{odds['home']:.2f} [{cfg.home_fav_min_odds:.2f}-{cfg.home_fav_max_odds:.2f}]", f4)
        _record(r, "F5 Pareggio",
                f"{odds['draw']:.2f} [{cfg.draw_min_odds:.2f}-{cfg.draw_max_odds:.2f}]", f5)
        r.passed_count = sum(v["pass"] for v in r.filters.values())
        return r

    # --- Storico (una chiamata per squadra, condiviso tra filtro 2 e 3) ---
    size = max(cfg.zero_zero_sample_size, cfg.ht_sample_size)
    home_id = fixture["teams"]["home"]["id"]
    away_id = fixture["teams"]["away"]["id"]
    league_id = fixture["league"]["id"]
    season = fixture["league"]["season"]

    h_all = get_team_last_matches(home_id, league_id, season, size)
    a_all = get_team_last_matches(away_id, league_id, season, size)

    h_z = _team_stats(h_all[:cfg.zero_zero_sample_size])
    a_z = _team_stats(a_all[:cfg.zero_zero_sample_size])
    h_h = _team_stats(h_all[:cfg.ht_sample_size])
    a_h = _team_stats(a_all[:cfg.ht_sample_size])

    enough = (
        h_z["n"] >= cfg.min_sample_size and a_z["n"] >= cfg.min_sample_size
        and h_h["ht_n"] >= cfg.min_sample_size and a_h["ht_n"] >= cfg.min_sample_size
    )

    # F2: STRICT < 10%  → su 20 gare significa AL MASSIMO 1 zero-a-zero
    f2 = enough and (
        h_z["zero_pct"] < cfg.zero_zero_max_pct
        and a_z["zero_pct"] < cfg.zero_zero_max_pct
    )

    # F3: >= 70%
    f3 = enough and (
        h_h["ht_pct"] >= cfg.ht_over05_min_pct
        and a_h["ht_pct"] >= cfg.ht_over05_min_pct
    )

    # F1: quota OVER 2.5 OPPURE media gol delle due squadre
    avg = (h_z["avg_goals"] + a_z["avg_goals"]) / 2 if enough else 0.0
    f1 = f1_odds or (cfg.use_avg_goals_alternative and avg > cfg.avg_goals_min)

    f1_txt = over_txt
    if cfg.use_avg_goals_alternative:
        f1_txt += f" | media {avg:.2f} (>{cfg.avg_goals_min})"

    _record(r, "F1 Over 2.5", f1_txt, f1)
    _record(r, "F2 Freq. 0-0",
            f"C {h_z['zeros']}/{h_z['n']} ({h_z['zero_pct']:.0f}%) · "
            f"T {a_z['zeros']}/{a_z['n']} ({a_z['zero_pct']:.0f}%)", f2)
    _record(r, "F3 Gol 1°T",
            f"C {h_h['ht']}/{h_h['ht_n']} ({h_h['ht_pct']:.0f}%) · "
            f"T {a_h['ht']}/{a_h['ht_n']} ({a_h['ht_pct']:.0f}%)", f3)
    _record(r, "F4 Casa favorita",
            f"{odds['home']:.2f} [{cfg.home_fav_min_odds:.2f}-{cfg.home_fav_max_odds:.2f}]", f4)
    _record(r, "F5 Pareggio",
            f"{odds['draw']:.2f} [{cfg.draw_min_odds:.2f}-{cfg.draw_max_odds:.2f}]", f5)

    r.passed_count = sum(v["pass"] for v in r.filters.values())
    r.passed = r.passed_count == 5 and not any(v["skipped"] for v in r.filters.values())
    return r
