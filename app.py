"""Football Phase 1 Analyzer - Interfaccia Streamlit."""
import streamlit as st
import pandas as pd
from datetime import date
from dotenv import load_dotenv

from config import FilterConfig
from api_client import get_fixtures_today, get_odds
from filters import analyze_fixture, FilterResult
from telegram_bot import send_telegram, build_message

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

    st.subheader("📊 Filtro 1 - Over 2.5")
    over25_max = st.number_input("Quota max Over 2.5", 1.20, 2.50, 1.80, 0.05)

    st.subheader("🚫 Filtro 2 - 0-0 storici")
    zero_zero_pct = st.slider("Frequenza max 0-0 (%)", 0, 30, 10)
    zero_zero_n = st.number_input("Campione partite", 10, 30, 20)

    st.subheader("⚽ Filtro 3 - Gol 1° Tempo")
    ht_pct = st.slider("Min % Over 0.5 1HT", 50, 90, 70)
    ht_n = st.number_input("Campione partite", 10, 30, 20)

    st.subheader("🏠 Filtro 4 - Favorita in casa")
    home_min = st.number_input("Quota min casa", 1.10, 2.00, 1.40, 0.05)
    home_max = st.number_input("Quota max casa", 1.20, 2.50, 1.85, 0.05)

    st.subheader("🤝 Filtro 5 - Pareggio")
    draw_min = st.number_input("Quota min pareggio", 2.50, 4.00, 3.40, 0.05)
    draw_max = st.number_input("Quota max pareggio", 3.50, 5.00, 4.30, 0.05)

    cfg = FilterConfig(
        over25_max_odds=over25_max,
        zero_zero_max_pct=zero_zero_pct,
        zero_zero_sample_size=int(zero_zero_n),
        ht_over05_min_pct=ht_pct,
        ht_sample_size=int(ht_n),
        home_fav_min_odds=home_min,
        home_fav_max_odds=home_max,
        draw_min_odds=draw_min,
        draw_max_odds=draw_max,
    )

    st.divider()
    st.caption("💡 Le modifiche si applicano al prossimo scan")

# ============================================================
# HEADER
# ============================================================
st.title("⚽ Football Phase 1 Analyzer")
st.caption(f"📅 Analisi del {date.today().strftime('%d/%m/%Y')} • Strategia Lay the Draw / Over 2.5")

col1, col2, col3 = st.columns(3)
with col1:
    scan_btn = st.button("🔍 Avvia scansione", type="primary", use_container_width=True)
with col2:
    st.metric("Partite totali oggi", "-")
with col3:
    st.metric("Qualificate", "-")

# ============================================================
# MAIN LOGIC
# ============================================================
if scan_btn:
    with st.spinner("Recupero partite in corso..."):
        fixtures = get_fixtures_today(cfg)

    if not fixtures:
        st.warning("⚠️ Nessuna partita trovata oggi nei campionati monitorati.")
        st.stop()

    col2.metric("Partite totali oggi", len(fixtures))

    st.info(f"🔄 Analisi di {len(fixtures)} partite in corso... (richiede ~2-3 minuti)")
    progress = st.progress(0)
    status = st.empty()

    results: list[FilterResult] = []
    for i, fx in enumerate(fixtures):
        status.write(f"Analisi {i+1}/{len(fixtures)}: **{fx['teams']['home']['name']} vs {fx['teams']['away']['name']}**")
        progress.progress((i + 1) / len(fixtures))

        odds_data = get_odds(fx["fixture"]["id"])
        if not odds_data:
            continue

        result = analyze_fixture(fx, odds_data, cfg)
        results.append(result)

    status.empty()
    progress.empty()

    # ============================================================
    # RISULTATI
    # ============================================================
    passed = [r for r in results if r.passed]
    col3.metric("✅ Qualificate", len(passed))

    st.divider()

    if passed:
        st.success(f"🎯 **{len(passed)} partite superano TUTTI i 5 filtri!**")

        # Tabella riassuntiva
        df = pd.DataFrame([r.to_dict() for r in passed])
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Dettaglio espandibile
        with st.expander(f"📋 Dettaglio completo ({len(passed)} partite)"):
            for r in passed:
                with st.container(border=True):
                    st.subheader(f"⚽ {r.home} vs {r.away}")
                    st.caption(f"{r.league} • {r.kickoff[:16]}")
                    cols = st.columns(5)
                    for (k, v), col in zip(r.filters.items(), cols):
                        icon = "✅" if v["pass"] else "❌"
                        col.metric(k, v["value"], icon)

        # Invio Telegram
        st.divider()
        if st.button("📱 Invia qualificate su Telegram", type="primary"):
            msg = build_message(passed)
            if send_telegram(msg):
                st.success("✅ Messaggio inviato su Telegram!")
            else:
                st.error("❌ Errore invio. Controlla le credenziali Telegram.")
    else:
        st.warning("❌ Nessuna partita supera tutti i 5 filtri oggi.")

        # Mostra comunque le "quasi qualificate" (4/5 filtri)
        almost = [r for r in results if r.passed_count == 4]
        if almost:
            st.info(f"💡 {len(almost)} partite hanno superato 4 filtri su 5 (quasi qualificate):")
            for r in almost:
                failed = [k for k, v in r.filters.items() if not v["pass"]]
                st.write(f"• **{r.home} vs {r.away}** — fallisce: {', '.join(failed)}")

    # Mostra tutte le partite analizzate
    with st.expander(f"📊 Tutte le partite analizzate ({len(results)})"):
        df_all = pd.DataFrame([r.to_dict() for r in results])
        st.dataframe(df_all, use_container_width=True, hide_index=True)

else:
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
