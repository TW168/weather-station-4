# Dokploy Cron Setup for `pws_fetcher.py`

This guide documents the working setup to run the weather fetcher every 15 minutes and keep Telegram alerts working.

## Final cron line

Use this exact entry in `crontab -e`:

```cron
*/15 * * * * sudo /usr/bin/docker exec myweatherstation-my-station-ygoxes.1.7j3320yxewfx5s4pyippnu8x2 python /app/pws_fetcher.py >> /home/newguy/fetch-pws/weather_cron.log 2>&1
```

## Why this works

- The script with Telegram logic is inside the app container at `/app/pws_fetcher.py`.
- Running host script `/home/newguy/fetch-pws/fetch_weather_data.py` only fetches weather data and does not send Telegram alerts.
- Cron must call Docker to execute the container script.

## Required sudoers rule

Cron cannot type a sudo password. Add a narrow NOPASSWD rule:

```sudoers
newguy ALL=(root) NOPASSWD: /usr/bin/docker exec myweatherstation-my-station-ygoxes.1.7j3320yxewfx5s4pyippnu8x2 python /app/pws_fetcher.py
```

Created via:

```bash
sudo visudo -f /etc/sudoers.d/newguy-docker-cron
```

## Verification commands

1. Confirm current cron entry:

```bash
crontab -l | tail -n 5
```

2. Test no-password sudo path:

```bash
sudo -n /usr/bin/docker exec myweatherstation-my-station-ygoxes.1.7j3320yxewfx5s4pyippnu8x2 python /app/pws_fetcher.py
```

3. Check logs:

```bash
tail -n 20 /home/newguy/fetch-pws/weather_cron.log
```

## How to test cron job end-to-end

1. Confirm the active cron line includes `pws_fetcher.py`:

```bash
crontab -l | grep pws_fetcher.py
```

2. Confirm non-interactive execution works (same behavior cron uses):

```bash
sudo -n /usr/bin/docker exec myweatherstation-my-station-ygoxes.1.7j3320yxewfx5s4pyippnu8x2 python /app/pws_fetcher.py
```

3. Check current UTC time:

```bash
date -u
```

Cron schedule `*/15 * * * *` fires at minute `00`, `15`, `30`, and `45`.

4. After the next scheduled minute passes, inspect log tail:

```bash
tail -n 30 /home/newguy/fetch-pws/weather_cron.log
```

Expected result:

- New entries around the expected schedule minute.
- At least one line like `Saved observation for ...`.
- No new `sudo: a terminal is required` or `sudo: a password is required` errors.
- No new `can't open file '/Users/tony/weather-station-4/pws_fetcher.py'` errors.

5. Optional DB confirmation: latest observation timestamp should be recent (about 15-20 minutes from now or newer).

## Important operational note

If Dokploy redeploys or recreates the service, the container name can change.
If cron stops working, update the container name in:

- crontab entry
- sudoers rule

Find current container name with:

```bash
sudo docker ps --format '{{.Names}}' | grep myweatherstation
```
