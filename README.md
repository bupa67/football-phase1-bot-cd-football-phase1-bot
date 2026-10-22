# ⚽ Football Phase 1 Analyzer

Automazione della **Fase 1** di una strategia di trading sportivo basata su 5 filtri statistici pre-match.

## 🎯 Cosa fa

Analizza le partite dei principali campionati europei e identifica quelle che soddisfano **tutti** questi criteri:

| Filtro | Parametro |
|--------|-----------|
| 1 | Quota Over 2.5 ≤ 1.80 |
| 2 | Frequenza 0-0 storici < 10% |
| 3 | Gol 1° Tempo ≥ 70% |
| 4 | Favorita in casa tra 1.40 e 1.85 |
| 5 | Quota Pareggio tra 3.40 e 4.30 |

Le partite qualificate vengono mostrate in una dashboard web e possono essere inviate su **Telegram**.

## 🚀 Setup locale

```bash
git clone https://github.com/TUO_USERNAME/football-phase1-bot.git
cd football-phase1-bot
pip install -r requirements.txt
cp .env.example .env   # poi inserisci le tue chiavi
streamlit run app.py
```

## 🔑 Credenziali necessarie

1. **API-Football** (gratuita fino a 100 req/giorno): https://rapidapi.com/api-sports/api/api-football
2. **Telegram Bot**: crea con @BotFather su Telegram
3. **Chat ID**: ottienilo da @userinfobot

## ☁️ Deploy gratuito su Streamlit Cloud

1. Push del repo su GitHub
2. Vai su https://share.streamlit.io
3. Collega il repo e seleziona `app.py`
4. In **Settings → Secrets** aggiungi:
   ```toml
   API_FOOTBALL_KEY = "..."
   TELEGRAM_BOT_TOKEN = "..."
   TELEGRAM_CHAT_ID = "..."
   ```
5. Deploy! Avrai un URL pubblico tipo `https://football-phase1-bot.streamlit.app`

## 📁 Struttura

```
app.py            → Interfaccia Streamlit
config.py         → Parametri filtri (dataclass)
api_client.py     → Chiamate API-Football con cache
filters.py        → Logica dei 5 filtri
telegram_bot.py   → Notifiche Telegram
```

## ⚠️ Disclaimer

Questo strumento è a scopo educativo e di analisi statistica. Il betting comporta rischi finanziari. Gestisci sempre il bankroll in modo responsabile.
