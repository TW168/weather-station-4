# PWS Weather Dashboard

Dark weather-themed FastAPI dashboard for your personal weather station (KTXSPRIN829, Spring TX).

## Project Structure

```
pws_dashboard/
├── app/
│   └── main.py          ← FastAPI backend (API + serves dashboard)
├── templates/
│   └── dashboard.html   ← Dark weather UI (Chart.js, animated sky)
├── pws_fetcher.py        ← Cron job script (fetches WU API → Postgres)
├── requirements.txt
├── .env                  ← DATABASE_URL, STATION_ID, WU_API_KEY
└── run.sh
```

## Setup

### 1. Configure environment
Edit `.env`:
```env
DATABASE_URL=postgresql://db_user:3XQvlcXS7gjwAy3@45.82.72.128:5432/db
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
*/15 * * * * /usr/bin/python3 /path/to/pws_dashboard/pws_fetcher.py >> /var/log/pws_fetcher.log 2>&1
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard UI |
| `GET /api/latest` | Current observation (all metrics) |
| `GET /api/history?hours=24` | Time series (1–168h) |
| `GET /api/stats?hours=24` | Min/max/avg statistics |

## Dashboard Features

- 🌡 **Temperature** — current, feels like, dew point, 24H high/low/avg
- 💧 **Humidity** — current + gauge bar
- 💨 **Wind** — speed, gust, live compass rose
- 🌀 **Pressure** — with ↑↓ trend indicator
- 🌧 **Precipitation** — rate + daily total
- ☀️ **UV Index** — with label (Low → Extreme) + solar radiation
- 📊 **6 Charts** — temp/dew, humidity, wind/gust, pressure, precip, solar
- 📋 **Stats Bar** — 24H/48H/7D summaries
- 🔄 **Auto-refresh** every 60 seconds
