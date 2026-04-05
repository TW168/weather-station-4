"""
rain_predictor.py  –  Local heuristic rain prediction using PWS sensor data.

Analyzes the last 3-6 hours of observations to estimate rain probability
in the next 4 hours. Uses pressure trends, humidity, dew point spread,
current precipitation, absolute pressure, and solar radiation changes.
"""

from datetime import datetime, timezone, timedelta


def predict(observations: list[dict]) -> dict:
    """
    Predict rain probability for the next 4 hours.

    Args:
        observations: list of dicts sorted by observed_at ASC, each with keys:
            observed_at (datetime), temp_f, humidity, pressure_in,
            precip_rate_in, dewpt_f (optional), solar_radiation (optional)

    Returns:
        dict with probability (0-100), label, confidence, factors, calculated_at
    """
    now = datetime.now(timezone.utc)
    n = len(observations)

    if n == 0:
        return _empty_result(now)

    latest = observations[-1]
    factors = []
    score = 0

    # Factor 1: Pressure trend (max 30 pts)
    pts, factor = _score_pressure_trend(observations)
    score += pts
    if factor:
        factors.append(factor)

    # Factor 2: Humidity (max 20 pts)
    pts, factor = _score_humidity(latest)
    score += pts
    if factor:
        factors.append(factor)

    # Factor 3: Dew point spread (max 20 pts)
    pts, factor = _score_dewpoint_spread(latest)
    score += pts
    if factor:
        factors.append(factor)

    # Factor 4: Current precipitation (max 15 pts)
    pts, factor = _score_precipitation(latest)
    score += pts
    if factor:
        factors.append(factor)

    # Factor 5: Absolute pressure (max 10 pts)
    pts, factor = _score_absolute_pressure(latest)
    score += pts
    if factor:
        factors.append(factor)

    # Factor 6: Solar radiation drop (max 5 pts)
    pts, factor = _score_solar_drop(observations)
    score += pts
    if factor:
        factors.append(factor)

    score = max(0, min(100, score))

    if score <= 20:
        label = "Unlikely"
    elif score <= 45:
        label = "Possible"
    elif score <= 70:
        label = "Likely"
    else:
        label = "Very Likely"

    if n < 6:
        confidence = "low"
    elif n < 19:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "probability": score,
        "label": label,
        "confidence": confidence,
        "factors": factors,
        "calculated_at": now.isoformat(),
    }


def _empty_result(now: datetime) -> dict:
    return {
        "probability": 0,
        "label": "Unlikely",
        "confidence": "low",
        "factors": [
            _missing_factor("Pressure Trend"),
            _missing_factor("Humidity"),
            _missing_factor("Dew Point Spread"),
            _missing_factor("Current Precipitation"),
            _missing_factor("Absolute Pressure"),
            _missing_factor("Solar Radiation Drop"),
        ],
        "calculated_at": now.isoformat(),
    }


def _score_pressure_trend(observations: list[dict]) -> tuple[int, dict | None]:
    pressures = [
        (o["observed_at"], o["pressure_in"])
        for o in observations
        if o.get("pressure_in") is not None
    ]
    if len(pressures) < 2:
        return 0, _missing_factor("Pressure Trend")

    now = pressures[-1][0]
    three_hrs_ago = now - timedelta(hours=3)

    # Find the oldest reading within ~3 hour window
    window = [(t, p) for t, p in pressures if t >= three_hrs_ago]
    if len(window) < 2:
        window = pressures[-2:]

    oldest_p = window[0][1]
    newest_p = window[-1][1]
    drop = oldest_p - newest_p  # positive = pressure fell

    if drop >= 0.12:
        pts = 30
    elif drop >= 0.08:
        pts = 24
    elif drop >= 0.05:
        pts = 18
    elif drop >= 0.03:
        pts = 12
    elif drop >= 0.01:
        pts = 5
    else:
        pts = 0

    contribution = _contribution_label(pts, 30)
    return pts, {
        "name": "Pressure Trend",
        "value": f"{-drop:+.3f} inHg/3hr",
        "contribution": contribution,
    }


def _score_humidity(latest: dict) -> tuple[int, dict | None]:
    hum = latest.get("humidity")
    if hum is None:
        return 0, _missing_factor("Humidity")

    if hum >= 95:
        pts = 20
    elif hum >= 90:
        pts = 16
    elif hum >= 85:
        pts = 12
    elif hum >= 80:
        pts = 8
    elif hum >= 70:
        pts = 4
    else:
        pts = 0

    return pts, {
        "name": "Humidity",
        "value": f"{hum:.0f}%",
        "contribution": _contribution_label(pts, 20),
    }


def _score_dewpoint_spread(latest: dict) -> tuple[int, dict | None]:
    temp = latest.get("temp_f")
    dewpt = latest.get("dewpt_f")
    if temp is None or dewpt is None:
        return 0, _missing_factor("Dew Point Spread")

    spread = temp - dewpt

    if spread <= 2:
        pts = 20
    elif spread <= 4:
        pts = 16
    elif spread <= 6:
        pts = 12
    elif spread <= 10:
        pts = 6
    elif spread <= 15:
        pts = 2
    else:
        pts = 0

    return pts, {
        "name": "Dew Point Spread",
        "value": f"{spread:.1f}°F",
        "contribution": _contribution_label(pts, 20),
    }


def _score_precipitation(latest: dict) -> tuple[int, dict | None]:
    rate = latest.get("precip_rate_in")
    if rate is None:
        return 0, _missing_factor("Current Precipitation")

    if rate >= 0.10:
        pts = 15
    elif rate >= 0.01:
        pts = 12
    elif rate > 0:
        pts = 8
    else:
        pts = 0

    return pts, {
        "name": "Current Precipitation",
        "value": f"{rate:.2f} in/hr",
        "contribution": _contribution_label(pts, 15),
    }


def _score_absolute_pressure(latest: dict) -> tuple[int, dict | None]:
    pres = latest.get("pressure_in")
    if pres is None:
        return 0, _missing_factor("Absolute Pressure")

    if pres < 29.70:
        pts = 10
    elif pres < 29.85:
        pts = 7
    elif pres < 29.95:
        pts = 3
    else:
        pts = 0

    return pts, {
        "name": "Absolute Pressure",
        "value": f"{pres:.2f} inHg",
        "contribution": _contribution_label(pts, 10),
    }


def _score_solar_drop(observations: list[dict]) -> tuple[int, dict | None]:
    now = observations[-1]["observed_at"]
    one_hr_ago = now - timedelta(hours=1)
    three_hrs_ago = now - timedelta(hours=3)

    recent = [
        o["solar_radiation"]
        for o in observations
        if o.get("solar_radiation") is not None and o["observed_at"] >= one_hr_ago
    ]
    earlier = [
        o["solar_radiation"]
        for o in observations
        if o.get("solar_radiation") is not None
        and three_hrs_ago <= o["observed_at"] < one_hr_ago
    ]

    if not recent or not earlier:
        return 0, _missing_factor("Solar Radiation Drop")

    avg_recent = sum(recent) / len(recent)
    avg_earlier = sum(earlier) / len(earlier)

    # Only evaluate during daytime
    if avg_earlier < 50:
        return 0, {
            "name": "Solar Radiation Drop",
            "value": "N/A (nighttime)",
            "contribution": "none",
        }

    drop_pct = ((avg_earlier - avg_recent) / avg_earlier) * 100

    if drop_pct >= 70:
        pts = 5
    elif drop_pct >= 50:
        pts = 3
    elif drop_pct >= 30:
        pts = 1
    else:
        pts = 0

    return pts, {
        "name": "Solar Radiation Drop",
        "value": f"{drop_pct:.0f}%",
        "contribution": _contribution_label(pts, 5),
    }


def _contribution_label(pts: int, max_pts: int) -> str:
    ratio = pts / max_pts if max_pts > 0 else 0
    if ratio >= 0.75:
        return "strong"
    elif ratio >= 0.4:
        return "moderate"
    elif ratio > 0:
        return "slight"
    return "none"


def _missing_factor(name: str) -> dict:
    return {
        "name": name,
        "value": "N/A (insufficient data)",
        "contribution": "none",
    }
