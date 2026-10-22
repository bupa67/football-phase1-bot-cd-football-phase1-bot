"""Football Phase 1 Analyzer - Versione con session_state per debug persistente."""
from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date
from dotenv import load_dotenv

from config import FilterConfig
from api_client import (
    get_fixtures_today,
    get_odds,
    get_available_leagues,
    search_leagues,
    debug_api_response,
    ApiError,
    QuotaExceeded,
    test_api_connection,
)
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
# INIZIALIZZAZIONE SESSION STATE
# ============================================================
if "last_fixtures" not in st.session_state:
    st.session_state.last_fixtures = None
if "last_results" not in st.session_state:
    st.session_state.last_results = None
if "last_scan_date" not in st.session_state:
    st.session_state.last_scan_date = None
if "scan_in_progress" not in st.session_state:
    st.session_state.scan_in_progress = False

# ============================================================
# SIDEBAR: configurazione filtri
# ============================================================
with st.sidebar:
    st.title("⚙️ Parametri Filtri")
    st.caption("Modifica i valori per adattare la strategia")

    # --- Verifica credenziali ---
    api_key = get_secret("API_FOOTBALL_KEY")
    if not api_key:
        st.error(
            "⚠️ **API_FOOTBALL_KEY** non configurata.\n\n"
            "Configura `.env` (locale) o **Settings → Secrets** (Streamlit Cloud)."
        )
    else:
        st.success(f"✅ API Key caricata: `{api_key[:6]}...{api_key[-4:]}`")

    # --- Diagnostica API ---
    st.divider()
    st.subheader("🔧 Diagnostica")

    if st.button("🔌 Testa Connessione API", use_container_width=True, key="test_api_btn"):
        with st.spinner("Testo la chiave API..."):
            result = test_api_connection()
        if result.startswith("✅"):
            st.success(result)
        else:
            st.error(result)

    st.divider()

    # --- Data e stagione ---
    scan_date = st.date_input("📅 Data partite", value=date.today(), key="scan_date")
    season = st.number_input(
        "🗓️ Stagione API-Football", 2020, 2035, value=2026, step=1, key="season"
    )

    # --- Campionati ---
    cfg_temp = FilterConfig()
    league_options = list(cfg_temp.LEAGUES_NAMES.values())
    selected_leagues = st.multiselect(
        "🏆 Campionati monitorati",
        league_options,
        default=league_options,
        key="selected_leagues",
        help="Seleziona i campionati da analizzare.",
    )

    if not selected_leagues:
        st.error("❌ Seleziona almeno un campionato.")
        st.stop()

    name_to_id = {v: k for k, v in cfg_temp.LEAGUES_NAMES.items()}
    selected_league_ids = [name_to_id[n] for n in selected_leagues]

    st.caption(
        f"ℹ️ **Piano free ≈ 100 req/giorno**: con {len(selected_leagues)} leghe, "
        "una scan completa può esaurire la quota giornaliera."
    )

    st.divider()

    # --- Filtro 1: Over 2.5 ---
    st.subheader("📊 Filtro 1 - Over 2.5")
    over25_max = st.number_input("Quota max Over 2.5", 1.20, 2.50, 1.80, 0.05, key="over25_max")
    use_avg = st.checkbox("Accetta anche Media Gol > soglia", value=True, key="use_avg")
    avg_goals_min = st.number_input("Media gol minima (alternativa)", 2.0, 3.5, 2.6, 0.1, key="avg_goals_min")

    # --- Filtro 2: 0-0 storici ---
    st.subheader("🚫 Filtro 2 - 0-0 storici")
    zero_zero_pct = st.slider("Frequenza max 0-0 (%)", 0, 30, 10, key="zero_zero_pct")
    zero_zero_n = st.number_input("Campione partite (Filtro 2)", 10, 30, 20, key="zero_zero_n")

    # --- Filtro 3: Gol 1° Tempo ---
    st.subheader("⚽ Filtro 3 - Gol 1° Tempo")
    ht_pct = st.slider("Min % Over 0.5 1HT", 50, 90, 70, key="ht_pct")
    ht_n = st.number_input("Campione partite (Filtro 3)", 10, 30, 20, key="ht_n")

    # --- Filtro 4: Favorita in casa ---
    st.subheader("🏠 Filtro 4 - Favorita in casa")
    home_min = st.number_input("Quota min casa", 1.10, 2.00, 1.40, 0.05, key="home_min")
    home_max = st.number_input("Quota max casa", 1.20, 2.50, 1.85, 0.05, key="home_max")

    if home_min >= home_max:
        st.error("❌ Il limite minimo deve essere inferiore al massimo.")
        st.stop()

    # --- Filtro 5: Pareggio ---
    st.subheader("🤝 Filtro 5 - Pareggio")
    draw_min = st.number_input("Quota min pareggio", 2.50, 4.00, 3.40, 0.05, key="draw_min")
    draw_max = st.number_input("Quota max pareggio", 3.50, 5.00, 4.30, 0.05, key="draw_max")

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
st.title(" Football Phase 1 Analyzer")
st.caption(
    f"📅 Analisi del **{scan_date.strftime('%d/%m/%Y')}** • "
    "Strategia Lay the Draw / Over 2.5"
)

col1, col2, col3 = st.columns(3)
with col1:
    scan_btn = st.button(
        "🔍 Avvia scansione", type="primary", use_container_width=True, key="scan_btn"
    )
with col2:
    total_placeholder = st.empty()
    if st.session_state.last_fixtures is not None:
        total_placeholder.metric("Partite totali", len(st.session_state.last_fixtures))
    else:
        total_placeholder.metric("Partite totali", "-")
with col3:
    passed_placeholder = st.empty()
    if st.session_state.last_results is not None:
        passed_count = sum(1 for r in st.session_state.last_results if r.passed)
        passed_placeholder.metric("✅ Qualificate", passed_count)
    else:
        passed_placeholder.metric("✅ Qualificate", "-")

# ============================================================
# LOGICA SCANSIONE (usa session_state)
# ============================================================
if scan_btn:
    st.session_state.scan_in_progress = True
    st.session_state.last_scan_date = scan_date.isoformat()
    
    try:
        with st.spinner("Recupero partite in corso..."):
            fixtures = get_fixtures_today(cfg, scan_date.isoformat())
    except ApiError as exc:
        st.error(f"❌ **Errore API**: {exc}")
        st.session_state.scan_in_progress = False
        st.stop()

    st.session_state.last_fixtures = fixtures
    st.session_state.scan_in_progress = False

# ============================================================
# PANNELLO DEBUG (SEMPRE VISIBILE, indipendente dalla scansione)
# ============================================================
st.divider()
with st.expander(" DEBUG API - Testa una lega specifica", expanded=True):
    st.markdown("""
    **Istruzioni:**
    1. Seleziona una lega
    2. Imposta una data (es. 25/10/2026 o una data passata come 18/10/2026)
    3. Clicca "Testa API" per vedere la risposta grezza
    """)
    
    debug_col1, debug_col2, debug_col3 = st.columns([2, 2, 1])
    
    with debug_col1:
        debug_league = st.selectbox(
            "Lega da testare:",
            options=selected_league_ids,
            format_func=lambda x: cfg_temp.LEAGUES_NAMES.get(x, str(x)),
            key="debug_league_select"
        )
    
    with debug_col2:
        debug_date = st.date_input("Data da testare:", value=date(2026, 10, 25), key="debug_date_select")
    
    with debug_col3:
        debug_btn = st.button("🔍 Testa API", use_container_width=True, key="debug_api_btn_main")
    
        if debug_btn:
        with st.spinner("Chiamo l'API in due modalità..."):
            debug_result = debug_api_response(debug_date.isoformat(), debug_league)
        
        st.subheader("Risultato del Test:")
        
        # Mostra risultato CON league_id
        st.markdown("#### 1️⃣ Test CON league_id")
        res_with = debug_result.get("CON league_id", {})
        if res_with.get("status_code") == 200 and isinstance(res_with.get("parsed_data_count"), int) and res_with["parsed_data_count"] > 0:
            st.success(f"✅ Funziona! Trovate {res_with['parsed_data_count']} partite.")
        else:
            st.error(f"❌ Fallito. Risposta: `{res_with.get('raw_error', res_with.get('raw_response', 'Errore sconosciuto'))}`")
            
        # Mostra risultato SENZA league_id
        st.markdown("#### 2️⃣ Test SENZA league_id (solo data)")
        res_without = debug_result.get("SENZA league_id", {})
        if res_without.get("status_code") == 200 and isinstance(res_without.get("parsed_data_count"), int) and res_without["parsed_data_count"] > 0:
            st.success(f"✅ Funziona! Trovate {res_without['parsed_data_count']} partite in totale quel giorno.")
            st.info("💡 **Conclusione**: Il tuo piano API non supporta il filtro `league_id` insieme alle date, oppure l'ID è sbagliato. Dobbiamo filtrare i dati in Python dopo averli scaricati tutti.")
        else:
            st.warning(f"⚠️ Anche questo ha fallito. Risposta: `{res_without.get('raw_error', res_without.get('raw_response', 'Errore sconosciuto'))}`")
            st.info("💡 **Conclusione**: Probabilmente la data **{debug_date.strftime('%d-%m-%Y')}** non ha partite nel database. Prova con una data passata come **18-10-2023** o **18-10-2024**.")
        
        with st.expander("📄 Risposta grezza JSON completa"):
            st.json(debug_result)

# ============================================================
# MOSTRA RISULTATI SCANSIONE (da session_state)
# ============================================================
if st.session_state.last_fixtures is not None:
    fixtures = st.session_state.last_fixtures
    
    if not fixtures:
        st.warning(
            f"⚠️ Nessuna partita trovata per il **{st.session_state.last_scan_date}**.\n\n"
            "Usa il pannello DEBUG qui sopra per testare singole leghe."
        )
    else:
        st.success(f"✅ Trovate **{len(fixtures)} partite**! Avvia l'analisi...")
        
        # Esegui analisi se non è già stata fatta
        if st.session_state.last_results is None:
            with st.spinner(f"Analisi di {len(fixtures)} partite in corso..."):
                progress = st.progress(0)
                results = []
                raw_sample = None
                
                for i, fx in enumerate(fixtures):
                    progress.progress((i + 1) / len(fixtures))
                    try:
                        odds_data = get_odds(fx["fixture"]["id"])
                        if not odds_data:
                            continue
                        if raw_sample is None:
                            raw_sample = odds_data
                        result = analyze_fixture(fx, odds_data, cfg)
                        results.append(result)
                    except Exception as e:
                        continue
                
                progress.empty()
                st.session_state.last_results = results
        
        # Mostra risultati
        results = st.session_state.last_results
        passed = [r for r in results if r.passed]
        
        st.divider()
        
        if passed:
            st.success(f"🎯 **{len(passed)} partite superano TUTTI i 5 filtri!**")
            df = pd.DataFrame([r.to_dict() for r in passed])
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            with st.expander(f"📋 Dettaglio completo ({len(passed)} partite)"):
                for r in passed:
                    with st.container(border=True):
                        st.subheader(f"⚽ {r.home} vs {r.away}")
                        st.caption(f"{r.league} • {r.kickoff[:16]}")
                        cols = st.columns(5)
                        for (k, v), col in zip(r.filters.items(), cols):
                            icon = "✅" if v["pass"] else ("⏭️" if v.get("skipped") else "❌")
                            col.markdown(f"**{icon} {k}**\n\n{v['value']}")
            
            st.divider()
            if st.button("📱 Invia su Telegram", type="primary", key="send_tg_btn"):
                if not get_secret("TELEGRAM_BOT_TOKEN") or not get_secret("TELEGRAM_CHAT_ID"):
                    st.error("️ Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
                else:
                    msg = build_message(passed)
                    if send_telegram(msg):
                        st.success("✅ Messaggio inviato!")
                    else:
                        st.error("❌ Errore invio.")
        else:
            st.warning("❌ Nessuna partita supera tutti i 5 filtri.")
            almost = [r for r in results if r.passed_count == 4]
            if almost:
                st.info(f" **{len(almost)} partite** con 4/5 filtri:")
                for r in almost:
                    failed = [k for k, v in r.filters.items() if not v["pass"] and not v.get("skipped")]
                    st.write(f"• **{r.home} vs {r.away}** — fallisce: {', '.join(failed)}")
        
        # Reset button
        st.divider()
        if st.button("🔄 Nuova scansione (reset)", key="reset_btn"):
            st.session_state.last_fixtures = None
            st.session_state.last_results = None
            st.rerun()

else:
    # Schermata iniziale
    st.markdown("""
    ### 👋 Benvenuto nel Football Phase 1 Analyzer
    
    **Come usare il DEBUG:**
    1. Espandi il pannello "🐛 DEBUG API" qui sopra
    2. Seleziona una lega (es. Premier League)
    3. Imposta una data (prova **18/10/2026** - domenica scorsa)
    4. Clicca "🔍 Testa API"
    5. Dimmi cosa vedi!
    
    Questo ci aiuterà a capire se l'API restituisce dati o no.
    """)
