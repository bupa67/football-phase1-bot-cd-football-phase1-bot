"""Lettura credenziali: ambiente locale (.env) e Streamlit Cloud (secrets)."""
from __future__ import annotations

import os


def get_secret(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value

    try:
        import streamlit as st
        raw = st.secrets.get(name, default)
    except Exception:
        # Localmente secrets.toml puo' non esistere: si usa .env
        return default

    return str(raw).strip() if raw is not None else default
