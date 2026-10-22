"""Invio notifiche su Telegram."""
import os
import requests
import streamlit as st
from typing import List
from filters import FilterResult


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or st.secrets.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def build_message(results: List[FilterResult]) -> str:
    from datetime import date
    msg = f"🎯 <b>FASE 1 - PARTITE QUALIFICATE</b>\n"
    msg += f"📅 {date.today().strftime('%d/%m/%Y')}\n"
    msg += f"✅ {len(results)} partite su tutti i 5 filtri:\n\n"
    for r in results:
        msg += f"⚽ <b>{r.home} vs {r.away}</b>\n"
        msg += f"🏆 {r.league} | ⏰ {r.kickoff[:16]}\n"
        for k, v in r.filters.items():
            icon = "✅" if v["pass"] else "❌"
            msg += f"  • {k}: {v['value']} {icon}\n"
        msg += "\n"
    msg += "➡️ Prossimo step: FASE 2 (formazioni tra 1h)"
    return msg
