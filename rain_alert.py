#!/usr/bin/env python3
"""
rain_alert.py
Checks recent PWS observations and sends Telegram alerts for rain prediction/start.
Run via cron after each fetch:  */15 * * * * /usr/bin/python3 /path/to/rain_alert.py
"""

import os
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))
load_dotenv(dotenv_path=BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

DATABASE_URL        = os.getenv("DATABASE_URL")
STATION_ID          = os.getenv("STATION_ID", "KTXSPRIN829")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
RAIN_ALERT_THRESHOLD = int(os.getenv("RAIN_ALERT_THRESHOLD", "46"))

STATE_FILE = BASE_DIR / "rain_alert_state.json"


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning(
            "Telegram credentials not set (token=%s, chat_id=%s) — skipping notification.",
            bool(TELEGRAM_BOT_TOKEN),
            bool(TELEGRAM_CHAT_ID),
        )
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }, timeout=10)
    resp.raise_for_status()
    log.info("Telegram alert sent.")


def load_alert_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            if "prediction_alerted" not in state:
                state["prediction_alerted"] = bool(state.get("alerted", False))
            if "raining_now" not in state:
                state["raining_now"] = False
            return state
        except Exception:
            pass
    return {"prediction_alerted": False, "raining_now": False}


def save_alert_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def fetch_recent_observations() -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT observed_at, temp_f, humidity, pressure_in,
                       precip_rate_in, raw_json
                  FROM public.pws_observations
                WHERE station_id = %s AND observed_at >= %s
                ORDER BY observed_at ASC
                """,
                (STATION_ID, since),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    observations = []
    for observed_at, temp_f, humidity, pressure_in, precip_rate_in, raw in rows:
        raw_data = json.loads(raw) if isinstance(raw, str) else raw
        imp = raw_data.get("imperial", {})
        observations.append({
            "observed_at":    observed_at,
            "temp_f":         temp_f,
            "humidity":       humidity,
            "pressure_in":    pressure_in,
            "precip_rate_in": precip_rate_in,
            "dewpt_f":        imp.get("dewpt"),
            "solar_radiation": raw_data.get("solarRadiation"),
        })
    return observations


def check_and_alert_rain() -> None:
    from app.rain_predictor import predict

    observations = fetch_recent_observations()
    result = predict(observations)
    probability = result["probability"]
    label       = result["label"]
    confidence  = result["confidence"]
    factors     = result["factors"]
    latest = observations[-1] if observations else {}
    precip_rate = latest.get("precip_rate_in")
    raining_now = bool(precip_rate and precip_rate > 0)

    state = load_alert_state()
    log.info(
        "Rain prediction: %d%% (%s) — prediction_alerted=%s raining_now=%s",
        probability,
        label,
        state["prediction_alerted"],
        state["raining_now"],
    )

    if raining_now and not state["raining_now"]:
        message = (
            f"🌧 <b>Rain Started — {STATION_ID}</b>\n\n"
            f"Current precip rate: <b>{(precip_rate or 0):.2f} in/hr</b>\n"
            f"Detected by your station at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        send_telegram(message)
        state["raining_now"] = True
        save_alert_state(state)
    elif not raining_now and state["raining_now"]:
        log.info("Precipitation stopped — clearing rain-start alert state.")
        state["raining_now"] = False
        save_alert_state(state)
    else:
        log.info(
            "No rain-start alert sent (raining_now=%s, prior_raining_now=%s).",
            raining_now,
            state["raining_now"],
        )

    if probability >= RAIN_ALERT_THRESHOLD and not state["prediction_alerted"]:
        factor_lines = "\n".join(
            f"  {f['name']}: {f['value']}"
            for f in factors if f["contribution"] != "none"
        )
        message = (
            f"🌧 <b>Rain Alert — {STATION_ID}</b>\n\n"
            f"Prediction: <b>{label} ({probability}%)</b>\n"
            f"Your weather station is showing signs of rain in the next 4 hours.\n\n"
            f"<b>Contributing factors:</b>\n{factor_lines}\n\n"
            f"Confidence: {confidence.title()}"
        )
        send_telegram(message)
        state["prediction_alerted"] = True
        save_alert_state(state)
    elif probability < RAIN_ALERT_THRESHOLD and state["prediction_alerted"]:
        log.info("Prediction dropped below threshold — resetting alert state.")
        state["prediction_alerted"] = False
        save_alert_state(state)
    else:
        log.info(
            "No prediction alert sent (probability=%d, threshold=%d, already_alerted=%s).",
            probability,
            RAIN_ALERT_THRESHOLD,
            state["prediction_alerted"],
        )


if __name__ == "__main__":
    try:
        check_and_alert_rain()
    except Exception as exc:
        log.exception("Rain alert check failed: %s", exc)
        raise
