#!/usr/bin/env python3
"""
pws_fetcher.py
Fetches Weather Underground PWS observations every 15 min and saves to PostgreSQL.
Run via cron:  */15 * * * * /usr/bin/python3 /path/to/pws_fetcher.py
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

DATABASE_URL        = os.getenv("DATABASE_URL")
STATION_ID          = os.getenv("STATION_ID", "KTXSPRIN829")
WU_API_KEY          = os.getenv("WU_API_KEY")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "")
RAIN_ALERT_THRESHOLD = int(os.getenv("RAIN_ALERT_THRESHOLD", "46"))

STATE_FILE = Path(__file__).parent / "rain_alert_state.json"

WU_URL = (
    "https://api.weather.com/v2/pws/observations/current"
    "?stationId={station_id}&format=json&units=e&apiKey={api_key}&numericPrecision=decimal"
)


def fetch_observation() -> dict:
    url = WU_URL.format(station_id=STATION_ID, api_key=WU_API_KEY)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    observations = data.get("observations", [])
    if not observations:
        raise ValueError("No observations returned from Weather Underground API")
    return observations[0]


def save_observation(obs: dict) -> None:
    imp      = obs.get("imperial", {})
    raw_json = json.dumps(obs)

    # Parse ISO timestamp from API
    obs_time_str = obs.get("obsTimeUtc", "")
    try:
        observed_at = datetime.strptime(obs_time_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        observed_at = datetime.now(timezone.utc)

    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            # Ensure table exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pws_observations (
                    id              BIGSERIAL PRIMARY KEY,
                    station_id      TEXT NOT NULL,
                    observed_at     TIMESTAMP WITH TIME ZONE NOT NULL,
                    fetched_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    raw_json        JSONB NOT NULL,
                    temp_f          REAL,
                    humidity        REAL,
                    wind_speed_mph  REAL,
                    wind_gust_mph   REAL,
                    pressure_in     REAL,
                    precip_rate_in  REAL
                );
                CREATE INDEX IF NOT EXISTS idx_pws_obs_station_time
                    ON pws_observations (station_id, observed_at DESC);
            """)

            # Avoid duplicate inserts for the same observation timestamp
            cur.execute(
                "SELECT 1 FROM pws_observations WHERE station_id=%s AND observed_at=%s",
                (STATION_ID, observed_at),
            )
            if cur.fetchone():
                log.info("Observation at %s already stored — skipping.", observed_at)
                return

            cur.execute(
                """
                INSERT INTO pws_observations
                    (station_id, observed_at, raw_json,
                     temp_f, humidity, wind_speed_mph, wind_gust_mph,
                     pressure_in, precip_rate_in)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                """,
                (
                    obs.get("stationID", STATION_ID),
                    observed_at,
                    raw_json,
                    imp.get("temp"),
                    obs.get("humidity"),
                    imp.get("windSpeed"),
                    imp.get("windGust"),
                    imp.get("pressure"),
                    imp.get("precipRate"),
                ),
            )
        log.info("Saved observation for %s at %s", STATION_ID, observed_at)
    finally:
        conn.close()


def send_telegram(text: str) -> None:
    """Send a message via the Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials not set — skipping notification.")
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
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"alerted": False}


def save_alert_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def fetch_recent_observations() -> list[dict]:
    """Query the last 6 hours of observations from the DB."""
    since = datetime.now(timezone.utc) - timedelta(hours=6)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT observed_at, temp_f, humidity, pressure_in,
                       precip_rate_in, raw_json
                FROM pws_observations
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
    """Run rain prediction and send a Telegram alert if needed."""
    from app.rain_predictor import predict

    observations = fetch_recent_observations()
    result = predict(observations)
    probability = result["probability"]
    label       = result["label"]
    confidence  = result["confidence"]
    factors     = result["factors"]

    state = load_alert_state()
    log.info("Rain prediction: %d%% (%s) — alerted=%s", probability, label, state["alerted"])

    if probability >= RAIN_ALERT_THRESHOLD and not state["alerted"]:
        # Build factor summary lines
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
        state["alerted"] = True
        save_alert_state(state)

    elif probability < RAIN_ALERT_THRESHOLD and state["alerted"]:
        # Conditions cleared — reset so the next event triggers a fresh alert
        log.info("Prediction dropped below threshold — resetting alert state.")
        state["alerted"] = False
        save_alert_state(state)


if __name__ == "__main__":
    try:
        obs = fetch_observation()
        save_observation(obs)
        check_and_alert_rain()
    except Exception as exc:
        log.error("Fetch/save failed: %s", exc)
        raise
