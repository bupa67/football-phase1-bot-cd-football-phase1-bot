"""Football Phase 1 Analyzer - Interfaccia Streamlit completa."""
from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date, datetime
from dotenv import load_dotenv

from config import FilterConfig
from api_client import get_fixtures_today, get_odds, ApiError, QuotaExceeded
from filters import analyze_fixture, FilterResult
from telegram_bot import send_telegram, build_message
from credentials import get_secret

load_dotenv()

# ============================================================
# CONFIG PAGINA
# ============================================================
st.set_page_config(
    page_title="Football Phase 1 Analyzer",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# SIDEBAR: configurazione filtri
# ============================================================
with st.sidebar:
    st.title("⚙️ Parametri Filtri")
    st.caption("Modifica i valori per adattare la strategia")

    # --- Verifica credenziali ---
    if not get_secret("API_FOOTBALL_KEY"):
        st.warning("⚠️ **API_FOOTBALL_KEY** non configurata.\n\n"
                   "Configura `.env` (locale) o **Settings → Secrets** (Streamlit Cloud).")

    # --- Data e stagione ---
    scan_date = st.date_input("📅 Data partite", value=date.today())
    season = st.number_input("🗓️ Stagione API-Football", 2020, 2035, value=2026, step=1)

    # --- Campionati ---
    cfg_temp = FilterConfig()
    league_options = list(cfg_temp.LEAGUES_NAMES.values())
    selected_leagues = st.multiselect(
        "🏆 Campionati monitorati",
        league_options,
        default=league_options,
        help="Seleziona i campionati da analizzare. Meno campionati = meno chiamate API."
    )

    if not selected_leagues:
        st.error("❌ Seleziona almeno un campionato.")
        st.stop()

    name_to_id = {v: k for k, v in cfg_temp.LEAGUES_NAMES.items()}
    selected_league_ids = [name_to_id[n] for n in selected_leagues]

    st.caption(f"ℹ️ **Piano free ≈ 100 req/giorno**: con {len(selected_leagues)} leghe, "
               "una scan completa può esaurire la quota giornaliera.")

    st.divider()

    # --- Filtro 1: Over 2.5 ---
    st.subheader("📊 Filtro 1 - Over 2.5")
    over25_max = st.number_input("Quota max Over 2.5", 1.20, 2.50, 1.80, 0.05)
    use_avg = st.checkbox("Accetta anche Media Gol > soglia", value=True,
                          help="Se la quota Over 2.5 supera la soglia, accetta comunque se la media gol delle ultime 20 partite è > 2.6")
    avg_goals_min = st.number_input("Media gol minima (alternativa)", 2.0, 3.5, 2.6, 0.1)

    # --- Filtro 2: 0-0 storici ---
    st.subheader("🚫 Filtro 2 - 0-0 storici")
    zero_zero_pct = st.slider("Frequenza max 0-0 (%)", 0, 30, 10,
                              help="STRICT < 10%: su 20 gare significa AL MASSIMO 1 zero-a-zero")
    zero_zero_n = st.number_input("Campione partite", 10, 30, 20)

    # --- Filtro 3: Gol 1° Tempo ---
    st.subheader("⚽ Filtro 3 - Gol 1° Tempo")
    ht_pct = st.slider("Min % Over 0.5 1HT", 50, 90, 70)
    ht_n = st.number_input("Campione partite", 10, 30, 20)

    # --- Filtro 4: Favorita in casa ---
    st.subheader("🏠 Filtro 4 - Favorita in casa")
    home_min = st.number_input("Quota min casa", 1.10, 2.00, 1.40, 0.05)
    home_max = st.number_input("Quota max casa", 1.20, 2.50, 1.85, 0.05)

    if home_min >= home_max:
        st.error("❌ Il limite minimo deve essere inferiore al massimo.")
        st.stop()

    # --- Filtro 5: Pareggio ---
    st.subheader("🤝 Filtro 5 - Pareggio")
    draw_min = st.number_input("Quota min pareggio", 2.50, 4.00, 3.40, 0.05)
    draw_max = st.number_input("Quota max pareggio", 3.50, 5.00, 4.30, 0.05)

    if draw_min >= draw_max:
        st.error("❌ Il limite minimo deve essere inferiore al massimo.")
        st.stop()

    # --- Costruzione config finale ---
    cfg = FilterConfig(
        over25_max_odds=over25_max,
        avg_goals_min=avg_goals_min,
        use_avg_goals_alternative=use_avg,
        zero_zero_max_pct=zero_zero_pct,
        zero_zero_sample_size=int(zero_zero_n),
        ht_over05_min_pct=ht_pct,
        ht_sample_size=int(ht_n),
        home_fav_min_odds=home_min,
        home_fav_max_odds=home_max,
        draw_min_odds=draw_min,
        draw_max_odds=draw_max,
    )
    cfg.LEAGUES = selected_league_ids
    cfg.SEASON = int(season)

    st.divider()
    st.caption("💡 Le modifiche si applicano al prossimo scan")

# ============================================================
# HEADER
# ============================================================
st.title("⚽ Football Phase 1 Analyzer")
st.caption(f"📅 Analisi del **{scan_date.strftime('%d/%m/%Y')}** • Strategia Lay the Draw / Over 2.5")

col1, col2, col3 = st.columns(3)
with col1:
    scan_btn = st.button("🔍 Avvia scansione", type="primary", use_container_width=True)
with col2:
    total_placeholder = st.empty()
    total_placeholder.metric("Partite totali", "-")
with col3:
    passed_placeholder = st.empty()
    passed_placeholder.metric("✅ Qualificate", "-")

# ============================================================
# MAIN LOGIC
# ============================================================
if scan_btn:
    # --- Recupero partite ---
    try:
        with st.spinner("Recupero partite in corso..."):
            fixtures = get_fixtures_today(cfg, scan_date.isoformat())
    except ApiError as exc:
        st.error(f"❌ **Errore API**: {exc}")
        st.stop()

    if not fixtures:
        st.warning(f"⚠️ Nessuna partita pre-match trovata per il **{scan_date.strftime('%d/%m/%Y')}**.\n\n"
                   "Possibili cause:\n"
                   "- Nessuna partita in programma\n"
                   "- Partite già iniziate (lo script analizza solo pre-match)\n"
                   "- Stagione errata (verifica il parametro in sidebar)")
        st.stop()

    total_placeholder.metric("Partite totali", len(fixtures))
    st.info(f"🔄 Analisi di **{len(fixtures)} partite** in corso... (richiede ~2-3 minuti)")

    progress = st.progress(0)
    status = st.empty()

    results: list[FilterResult] = []
    raw_sample = None
    quota_hit = False

    for i, fx in enumerate(fixtures):
        home_name = fx["teams"]["home"]["name"]
        away_name = fx["teams"]["away"]["name"]
        status.write(f"Analisi **{i+1}/{len(fixtures)}**: {home_name} vs {away_name}")
        progress.progress((i + 1) / len(fixtures))

        try:
            odds_data = get_odds(fx["fixture"]["id"])
        except QuotaExceeded:
            quota_hit = True
            st.warning(f"⚠️ **Quota API esaurita** dopo {len(results)} partite analizzate. "
                       "Riprova domani o riduci i campionati in sidebar.")
            break
        except ApiError as exc:
            st.warning(f"⚠️ Quote non disponibili per {home_name} vs {away_name}: {exc}")
            continue

        if not odds_data:
            continue

        if raw_sample is None:
            raw_sample = odds_data

        result = analyze_fixture(fx, odds_data, cfg)
        results.append(result)

    status.empty()
    progress.empty()

    # ============================================================
    # RISULTATI
    # ============================================================
    passed = [r for r in results if r.passed]
    passed_placeholder.metric("✅ Qualificate", len(passed))

    st.divider()

    if passed:
        st.success(f"🎯 **{len(passed)} partite superano TUTTI i 5 filtri!**")

        # --- Tabella riassuntiva ---
        df = pd.DataFrame([r.to_dict() for r in passed])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # --- Dettaglio espandibile ---
        with st.expander(f"📋 Dettaglio completo ({len(passed)} partite)"):
            for r in passed:
                with st.container(border=True):
                    st.subheader(f"⚽ {r.home} vs {r.away}")
                    st.caption(f"{r.league} • {r.kickoff[:16]} • Bookmaker: {r.bookmaker or 'n/d'}")

                    cols = st.columns(5)
                    for (k, v), col in zip(r.filters.items(), cols):
                        if v.get("skipped"):
                            icon = "⏭️"
                        elif v["pass"]:
                            icon = "✅"
                        else:
                            icon = "❌"
                        col.markdown(f"**{icon} {k}**\n\n{v['value']}")

        # --- Invio Telegram ---
        st.divider()
        col_tg1, col_tg2, col_tg3 = st.columns([1, 1, 2])
        with col_tg1:
            if st.button("📱 Invia su Telegram", type="primary"):
                if not get_secret("TELEGRAM_BOT_TOKEN") or not get_secret("TELEGRAM_CHAT_ID"):
                    st.error("❌ Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
                else:
                    msg = build_message(passed)
                    if send_telegram(msg):
                        st.success("✅ Messaggio inviato su Telegram!")
                    else:
                        st.error("❌ Errore invio. Controlla le credenziali Telegram.")

    else:
        st.warning("❌ Nessuna partita supera tutti i 5 filtri oggi.")

        # --- Quasi qualificate (4/5 filtri) ---
        almost = [r for r in results if r.passed_count == 4]
        if almost:
            st.info(f"💡 **{len(almost)} partite** hanno superato 4 filtri su 5 (quasi qualificate):")
            for r in almost:
                failed = [k for k, v in r.filters.items() if not v["pass"] and not v.get("skipped")]
                st.write(f"• **{r.home} vs {r.away}** — fallisce: {', '.join(failed) if failed else 'filtro skipped'}")

    # --- Tutte le partite analizzate ---
    with st.expander(f"📊 Tutte le partite analizzate ({len(results)})"):
        df_all = pd.DataFrame([r.to_dict() for r in results])
        st.dataframe(df_all, use_container_width=True, hide_index=True)

    # --- Debug panel ---
    with st.expander("🔎 Debug — risposta grezza API quote"):
        if raw_sample:
            st.json(raw_sample[0])
        else:
            st.info("Nessuna risposta quote ricevuta: controlla chiave API e quota disponibile.")

else:
    # ============================================================
    # SCHERMATA INIZIALE
    # ============================================================
    st.markdown("""
    ### 👋 Benvenuto nel Football Phase 1 Analyzer

    Questa app automatizza la **Fase 1** della tua strategia di trading sportivo, applicando 5 filtri numerici alle partite del giorno:

    | # | Filtro | Significato |
    |---|--------|-------------|
    | 1 | Over 2.5 ≤ 1.80 | I bookmaker si aspettano partita aperta |
    | 2 | Freq. 0-0 < 10% | Entrambe evitano lo 0-0 |
    | 3 | Gol 1°T ≥ 70% | Partite con ritmo alto dall'inizio |
    | 4 | Casa favorita 1.40-1.85 | Favorita chiara ma non imbattibile |
    | 5 | Pareggio 3.40-4.30 | Finestra d'oro per il Lay the Draw |

    **Come iniziare:**
    1. Configura i parametri nella sidebar a sinistra
    2. Clicca su **"🔍 Avvia scansione"**
    3. Ricevi le partite qualificate qui e su Telegram

    ⚠️ *Ricorda: questa è solo la Fase 1. Le partite qualificate vanno poi verificate con le formazioni (Fase 2) e monitorate in live (Fase 3).*
    """)

    # --- Status credenziali ---
    st.divider()
    st.subheader("🔐 Status configurazione")

    col1, col2, col3 = st.columns(3)
    with col1:
        if get_secret("API_FOOTBALL_KEY"):
            st.success("✅ API-Football configurata")
        else:
            st.error("❌ API-Football mancante")

    with col2:
        if get_secret("TELEGRAM_BOT_TOKEN"):
            st.success("✅ Telegram Bot configurato")
        else:
            st.warning("⚠️ Telegram Bot non configurato")

    with col3:
        if get_secret("TELEGRAM_CHAT_ID"):
            st.success("✅ Telegram Chat ID configurato")
        else:
            st.warning("⚠️ Telegram Chat ID mancante")
