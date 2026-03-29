
# PWS Weather Dashboard
# weather-station-4

Weather-themed FastAPI dashboard for your personal weather station (KTXSPRIN829, Spring TX). This app provides a live, interactive web dashboard with real-time and historical weather data, local rain prediction, and beautiful animated sky visuals. The UI uses a light, sky-inspired theme.


## Project Structure

```
weather-station-4/
├── app/
│   ├── main.py           # FastAPI backend (serves API & dashboard)
│   └── rain_predictor.py # Local rain prediction logic
├── templates/
│   └── dashboard.html    # Light, animated weather dashboard UI (Chart.js)
├── pws_fetcher.py        # Cron job script (fetches WU API → Postgres)
├── requirements.txt      # Python dependencies
├── .env                  # Secrets: DATABASE_URL, STATION_ID, WU_API_KEY
└── run.sh                # Launch script
```


## Setup

### 1. Configure environment
Edit `.env`:
```env
DATABASE_URL=postgresql://youruser:yourpassword@db.example.com:5432/weatherdb
STATION_ID=KTXSPRIN829
WU_API_KEY=your_weather_underground_api_key
```
Get your WU API key from: https://www.wunderground.com/member/api-keys

### 2. Install & run
```bash
chmod +x run.sh
./run.sh
```
Dashboard is at: **http://localhost:8000**

### 3. Set up cron job (every 15 minutes)
```bash
crontab -e
```
Add:
```
*/15 * * * * /usr/bin/python3 /path/to/weather-station-4/pws_fetcher.py >> /var/log/pws_fetcher.log 2>&1
```


## API Endpoints

| Endpoint                    | Description                                 |
|-----------------------------|---------------------------------------------|
| `GET /`                     | Dashboard UI (HTML)                         |
| `GET /api/latest`           | Most recent observation (all metrics)       |
| `GET /api/history?hours=24` | Time series for past N hours (1–168)        |
| `GET /api/stats?hours=24`   | Min/max/avg stats for past N hours          |
| `GET /api/rain-prediction`  | Local rain probability & contributing factors|


## Dashboard Features

- 🌤️ **Live Weather Dashboard** — See current temperature, feels like, dew point, humidity, wind (speed, gust, direction), pressure (with trend), precipitation (rate & total), UV index, and solar radiation. All metrics update automatically every 60 seconds.
- 📊 **Interactive Charts** — Visualize trends for temperature & dew point, humidity, wind & gust, pressure, precipitation, and solar radiation. Select time ranges (24h, 48h, 7d) for historical analysis.
- 🧠 **Rain Prediction** — Uses recent local weather data and heuristics to estimate rain probability for the next 4 hours. Explains the main contributing factors (pressure trend, humidity, dew point spread, etc.).
- 📋 **Stats Bar** — Shows min, max, and average values for temperature, humidity, wind, pressure, and precipitation over the selected period.
- 🌈 **Animated Sky UI** — Light, sky-inspired theme with animated clouds and a modern, responsive layout.
- 🔄 **Auto-refresh** — All data and charts refresh every 60 seconds for real-time updates.

## How It Works

1. **Data Collection:**
	- `pws_fetcher.py` runs every 15 minutes (via cron), fetching data from the Weather Underground API and storing it in a PostgreSQL database.
2. **Backend API:**
	- FastAPI app (`app/main.py`) provides REST endpoints for latest data, history, stats, and rain prediction. It also serves the dashboard UI.
3. **Frontend Dashboard:**
	- `dashboard.html` (Jinja2 template) uses Chart.js and custom JavaScript to fetch data, render charts, and update the UI. The design is light-themed with animated backgrounds.
4. **Rain Prediction:**
	- The `/api/rain-prediction` endpoint uses recent weather trends and local heuristics (in `rain_predictor.py`) to estimate rain probability and explain the reasoning.

## Deployment Notes

- The app can be run locally or deployed using Docker. For production, use a process manager (e.g., Docker, systemd) and a reverse proxy (e.g., Nginx) for HTTPS.
- Environment variables are loaded from `.env` for secrets and configuration.
- PostgreSQL is required for data storage.

## Example Screenshots

> ![Dashboard Example](screenshot.png)

---

**Made for personal weather station enthusiasts.**
