#!/usr/bin/env python3
"""
backtest.py  –  Evaluate rain predictor accuracy against historical observations.

For each evaluation point in the database, builds the same 6-hour observation
window the predictor uses at runtime, runs predict(), then checks whether it
actually rained in the following 4 hours.

Usage:
    python backtest.py                  # last 30 days, step every 30 min
    python backtest.py --days 90        # last 90 days
    python backtest.py --step 60        # step every 60 min
    python backtest.py --threshold 46   # treat >= 46% as a "rain predicted" call
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(dotenv_path=BASE_DIR / ".env")

from app.rain_predictor import predict

DATABASE_URL = os.getenv("DATABASE_URL")
STATION_ID   = os.getenv("STATION_ID", "KTXSPRIN829")

PREDICT_HORIZON = timedelta(hours=4)
OBS_WINDOW      = timedelta(hours=6)


def fetch_all_observations(conn, since: datetime) -> list[dict]:
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

    result = []
    for observed_at, temp_f, humidity, pressure_in, precip_rate_in, raw in rows:
        raw_data = json.loads(raw) if isinstance(raw, str) else raw
        imp = raw_data.get("imperial", {})
        result.append({
            "observed_at":     observed_at,
            "temp_f":          temp_f,
            "humidity":        humidity,
            "pressure_in":     pressure_in,
            "precip_rate_in":  precip_rate_in,
            "dewpt_f":         imp.get("dewpt"),
            "solar_radiation": raw_data.get("solarRadiation"),
        })
    return result


def build_window(all_obs: list[dict], t: datetime) -> list[dict]:
    start = t - OBS_WINDOW
    return [o for o in all_obs if start <= o["observed_at"] <= t]


def rained_after(all_obs: list[dict], t: datetime) -> bool:
    end = t + PREDICT_HORIZON
    return any(
        o["precip_rate_in"] and o["precip_rate_in"] > 0
        for o in all_obs
        if t < o["observed_at"] <= end
    )


def calibration_table(rows: list[dict], bucket_width: int = 10) -> list[dict]:
    buckets: dict[int, dict] = {}
    for r in rows:
        b = (r["probability"] // bucket_width) * bucket_width
        if b not in buckets:
            buckets[b] = {"count": 0, "actual_rain": 0}
        buckets[b]["count"] += 1
        if r["actual_rain"]:
            buckets[b]["actual_rain"] += 1

    table = []
    for b in sorted(buckets):
        cnt = buckets[b]["count"]
        actual = buckets[b]["actual_rain"]
        table.append({
            "bucket":       f"{b}–{b+bucket_width-1}%",
            "predictions":  cnt,
            "actual_rain":  actual,
            "actual_rate":  round(actual / cnt * 100, 1) if cnt else 0,
        })
    return table


def print_results(rows: list[dict], threshold: int) -> None:
    total = len(rows)
    if total == 0:
        print("No evaluation points found.")
        return

    rain_events    = sum(1 for r in rows if r["actual_rain"])
    no_rain_events = total - rain_events

    predicted_rain    = [r for r in rows if r["probability"] >= threshold]
    predicted_no_rain = [r for r in rows if r["probability"] <  threshold]

    tp = sum(1 for r in predicted_rain    if     r["actual_rain"])
    fp = sum(1 for r in predicted_rain    if not r["actual_rain"])
    fn = sum(1 for r in predicted_no_rain if     r["actual_rain"])
    tn = sum(1 for r in predicted_no_rain if not r["actual_rain"])

    precision = tp / (tp + fp) if (tp + fp) else 0
    recall    = tp / (tp + fn) if (tp + fn) else 0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    accuracy  = (tp + tn) / total if total else 0

    print(f"\n{'='*55}")
    print(f"  Rain Predictor Backtest  —  {total} evaluation points")
    print(f"  Station: {STATION_ID}   Threshold: {threshold}%")
    print(f"{'='*55}")
    print(f"\n  Dataset")
    print(f"    Total eval points : {total}")
    print(f"    Rain events (4hr) : {rain_events}  ({rain_events/total*100:.1f}%)")
    print(f"    No-rain events    : {no_rain_events}  ({no_rain_events/total*100:.1f}%)")

    print(f"\n  Confusion Matrix  (threshold ≥ {threshold}%)")
    print(f"    True Positives    : {tp}   (predicted rain, it rained)")
    print(f"    False Positives   : {fp}   (predicted rain, it didn't)")
    print(f"    False Negatives   : {fn}   (missed rain events)")
    print(f"    True Negatives    : {tn}   (correctly predicted no rain)")

    print(f"\n  Metrics")
    print(f"    Accuracy          : {accuracy*100:.1f}%")
    print(f"    Precision         : {precision*100:.1f}%  (of rain alerts, how many verified)")
    print(f"    Recall            : {recall*100:.1f}%  (of rain events, how many caught)")
    print(f"    F1 Score          : {f1*100:.1f}%")

    print(f"\n  Calibration  (does stated probability match actual rain rate?)")
    print(f"  {'Predicted':>14}  {'# Preds':>8}  {'# Rained':>9}  {'Actual %':>9}")
    print(f"  {'-'*46}")
    for b in calibration_table(rows):
        bar_len = int(b["actual_rate"] / 2)
        bar = "█" * bar_len
        print(f"  {b['bucket']:>14}  {b['predictions']:>8}  {b['actual_rain']:>9}  {b['actual_rate']:>8.1f}%  {bar}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest rain predictor accuracy.")
    parser.add_argument("--days",      type=int, default=30,  help="Days of history to evaluate (default 30)")
    parser.add_argument("--step",      type=int, default=30,  help="Minutes between evaluation points (default 30)")
    parser.add_argument("--threshold", type=int, default=46,  help="Probability %% to call as 'rain predicted' (default 46)")
    args = parser.parse_args()

    step_td = timedelta(minutes=args.step)
    since   = datetime.now(timezone.utc) - timedelta(days=args.days)

    print(f"Fetching observations since {since.strftime('%Y-%m-%d %H:%M UTC')} …")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        all_obs = fetch_all_observations(conn, since)
    finally:
        conn.close()

    if not all_obs:
        print("No observations found. Check DATABASE_URL and STATION_ID.")
        sys.exit(1)

    print(f"Loaded {len(all_obs)} observations. Running backtest …")

    # Build evaluation timestamps: from first obs + OBS_WINDOW up to last obs - PREDICT_HORIZON
    first_t = all_obs[0]["observed_at"]
    last_t  = all_obs[-1]["observed_at"]
    eval_start = first_t + OBS_WINDOW
    eval_end   = last_t  - PREDICT_HORIZON

    if eval_start >= eval_end:
        print(f"Not enough history to evaluate. Need at least {OBS_WINDOW + PREDICT_HORIZON}.")
        sys.exit(1)

    results = []
    t = eval_start
    while t <= eval_end:
        window = build_window(all_obs, t)
        if len(window) >= 2:
            pred = predict(window)
            results.append({
                "t":           t,
                "probability": pred["probability"],
                "label":       pred["label"],
                "confidence":  pred["confidence"],
                "actual_rain": rained_after(all_obs, t),
            })
        t += step_td

    print_results(results, args.threshold)


if __name__ == "__main__":
    main()
