"""
main.py  –  FastAPI backend for PWS Weather Dashboard
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from .rain_predictor import predict as predict_rain

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
STATION_ID = os.getenv("STATION_ID", "KTXSPRIN829")

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")

_pool: Optional[asyncpg.Pool] = None


def _build_dsn() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    if "sslmode=" in DATABASE_URL:
        return DATABASE_URL
    if "?" in DATABASE_URL:
        return f"{DATABASE_URL}&sslmode=disable"
    return f"{DATABASE_URL}?sslmode=disable"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(_build_dsn(), min_size=1, max_size=5)
    return _pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await get_pool()
    except Exception as exc:
        log.warning("Database not reachable at startup: %s", exc)
    try:
        yield
    finally:
        if _pool:
            await _pool.close()


app = FastAPI(title="PWS Weather Dashboard", lifespan=lifespan)


def _serialize_row(row: asyncpg.Record) -> dict:
    data = dict(row)
    for key in ("observed_at", "fetched_at"):
        if isinstance(data.get(key), datetime):
            data[key] = data[key].isoformat()
    return data


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "station_id": STATION_ID})


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.get("/api/observations/latest-10")
async def latest_10_observations() -> list[dict]:
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT id, station_id, observed_at, fetched_at, raw_json,
                   temp_f, humidity, wind_speed_mph, wind_gust_mph,
                   pressure_in, precip_rate_in
            FROM public.pws_observations
            ORDER BY observed_at DESC
            LIMIT 10
            """
        )
        return [_serialize_row(r) for r in rows]
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        raise HTTPException(
            status_code=503,
            detail=f"Database query failed ({exc.__class__.__name__}): {msg}",
        ) from exc


@app.get("/api/latest")
async def api_latest():
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT observed_at, temp_f, humidity, wind_speed_mph, wind_gust_mph,
               pressure_in, precip_rate_in, raw_json
         FROM public.pws_observations
        WHERE station_id = $1
        ORDER BY observed_at DESC
        LIMIT 1
        """,
        STATION_ID,
    )
    if not row:
        return JSONResponse({"error": "No data yet"}, status_code=404)

    raw = json.loads(row["raw_json"])
    imp = raw.get("imperial", {})

    return {
        "observed_at": row["observed_at"].isoformat(),
        "temp_f": row["temp_f"],
        "feels_like": imp.get("heatIndex") or imp.get("windChill") or row["temp_f"],
        "dewpt_f": imp.get("dewpt"),
        "humidity": row["humidity"],
        "wind_speed_mph": row["wind_speed_mph"],
        "wind_gust_mph": row["wind_gust_mph"],
        "wind_dir": raw.get("winddir"),
        "pressure_in": row["pressure_in"],
        "precip_rate_in": row["precip_rate_in"],
        "precip_total_in": imp.get("precipTotal"),
        "uv": raw.get("uv"),
        "solar_radiation": raw.get("solarRadiation"),
        "neighborhood": raw.get("neighborhood", "Spring, TX"),
    }


@app.get("/api/history")
async def api_history(hours: int = Query(default=24, ge=1, le=168)):
    pool = await get_pool()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = await pool.fetch(
        """
        SELECT observed_at, temp_f, humidity, wind_speed_mph,
               wind_gust_mph, pressure_in, precip_rate_in, raw_json
                FROM public.pws_observations
        WHERE station_id = $1
          AND observed_at >= $2
        ORDER BY observed_at ASC
        """,
        STATION_ID,
        since,
    )

    result = []
    for r in rows:
        raw = json.loads(r["raw_json"])
        imp = raw.get("imperial", {})
        result.append(
            {
                "t": r["observed_at"].isoformat(),
                "temp_f": r["temp_f"],
                "dewpt_f": imp.get("dewpt"),
                "humidity": r["humidity"],
                "wind_speed": r["wind_speed_mph"],
                "wind_gust": r["wind_gust_mph"],
                "pressure": r["pressure_in"],
                "precip_rate": r["precip_rate_in"],
                "solar": raw.get("solarRadiation"),
                "uv": raw.get("uv"),
            }
        )
    return result


@app.get("/api/stats")
async def api_stats(hours: int = Query(default=24, ge=1, le=168)):
    pool = await get_pool()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    row = await pool.fetchrow(
        """
        SELECT
            MIN(temp_f)         AS temp_min,
            MAX(temp_f)         AS temp_max,
            AVG(temp_f)         AS temp_avg,
            MIN(humidity)       AS hum_min,
            MAX(humidity)       AS hum_max,
            AVG(humidity)       AS hum_avg,
            MAX(wind_gust_mph)  AS gust_max,
            AVG(wind_speed_mph) AS wind_avg,
            MIN(pressure_in)    AS pres_min,
            MAX(pressure_in)    AS pres_max,
            SUM(precip_rate_in) AS precip_sum,
            COUNT(*)            AS obs_count
                FROM public.pws_observations
        WHERE station_id = $1
          AND observed_at >= $2
        """,
        STATION_ID,
        since,
    )
    return dict(row)


@app.get("/api/rain-prediction")
async def api_rain_prediction():
    pool = await get_pool()
    since = datetime.now(timezone.utc) - timedelta(hours=6)

    rows = await pool.fetch(
        """
        SELECT observed_at, temp_f, humidity, pressure_in,
               precip_rate_in, raw_json
                FROM public.pws_observations
        WHERE station_id = $1
          AND observed_at >= $2
        ORDER BY observed_at ASC
        """,
        STATION_ID,
        since,
    )

    observations = []
    for r in rows:
        raw = json.loads(r["raw_json"])
        imp = raw.get("imperial", {})
        observations.append(
            {
                "observed_at": r["observed_at"],
                "temp_f": r["temp_f"],
                "humidity": r["humidity"],
                "pressure_in": r["pressure_in"],
                "precip_rate_in": r["precip_rate_in"],
                "dewpt_f": imp.get("dewpt"),
                "solar_radiation": raw.get("solarRadiation"),
            }
        )

    return predict_rain(observations)
