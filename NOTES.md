# NOTES

Work log for the flight trajectory prediction project: what I tried, what I found, and why I made each decision.
Newest phase at the bottom. Numbers marked **TODO** still need to be filled in or re-checked.

---

## Phase 0: Python foundations (2026-11-15 → 2026-11-17)

Exercises done on the WeatherAPI forecast endpoint (Paris, 3 days, hourly).

- Flattened nested JSON (`forecast → forecastday → hour`) into one row per hour (72 rows).
- Converted Unix timestamps with `pd.to_datetime(..., unit="s", utc=True)`.
- Daily min / mean / max temperature with `groupby` + `agg`; rainy-hours count with filter + `groupby` + `size`.
- CSV round trip: a CSV doesn't keep data types. Datetimes come back as text unless `parse_dates` is used.
  This is why the project uses **Parquet** for data files.

Lessons I keep relying on:
- Prefer whole-column (vectorised) operations over loops and `apply`.
- `df.filter()` selects by label, not by condition. Use boolean indexing: `df[condition]`.
- Combine conditions with `&`, `|`, `~` and parentheses around each condition.
- Don't reuse built-in names as variables (`map`, `sorted`, `id`).

---

## Phase 1: First contact with OpenSky (2026-11-17)

### Setup
- Endpoint: `/states/all` with a bounding box (`/states/own` is only for data from my own receivers).
- Paris bounding box: lat 48.5–49.5, lon 1.8–3.3.
- `extended=1` adds an 18th field (`category`), so `STATE_COLUMNS` has 18 names.
- `data["states"]` is `None` when the box is empty. `pd.DataFrame(None, columns=...)` returns an empty DataFrame, so no special case is needed.
- Credentials are loaded from `.env` (git-ignored).

### State vector fields used

| Field | Meaning | Unit |
| --- | --- | --- |
| `icao24` | Transponder ID: identifies the aircraft, not the flight | hex |
| `callsign` | Flight identifier (e.g. `AFR369Y`) | text |
| `time_position` | Time of the last position update | Unix s |
| `last_contact` | Time of the last message of any kind | Unix s |
| `latitude`, `longitude` | Position | degrees |
| `baro_altitude` | Pressure altitude | m |
| `geo_altitude` | GPS altitude | m |
| `on_ground` | On the ground or not | bool |
| `velocity` | Ground speed reported by the aircraft | m/s |
| `true_track` | Direction of travel, 0° = north | degrees |
| `vertical_rate` | Climb (+) / descent (−) | m/s |
| `position_source` | Where the position came from (see OpenSky docs for codes) | int |
| `category` | Aircraft category (only with `extended=1`) | int |

Added by me: `snapshot_time` = the response's top-level `time` (UTC datetime), the same for every row of a snapshot.

### Findings
- **Altitude nulls** (snapshot of 47 aircraft): 11 aircraft (23.4%) had no altitude. **All 11 were on the ground**, and the same 11 for both `geo_altitude` and `baro_altitude`. Airborne aircraft: 0% missing for both.
- **Altitude choice: `geo_altitude`.** Equally available for airborne aircraft, and unlike `baro_altitude` it doesn't drift with weather and air pressure. That matters most near the ground, on final approach.
- **15-minute polling test:** 58 snapshots, 2,276 rows (15 s interval). Fewer than 60 rounds because each round = 15 s sleep + request time.
- **Finding arrivals (step 7):** filter per aircraft, not per row. Filtering rows only keeps the tail of each approach; finding the aircraft IDs and then using `isin` keeps the whole track.
- `haversine_km` (in `src/geo.py`) checked: Paris → London ≈ 343.5 km, point to itself = 0.

---

## Data collection (since 2026-11-20)

- `src/collect.py`: `StateCollector` class polls `/states/all` for the Paris box **every 25 s** and saves **one Parquet file per hour** to `data/raw/states_paris_YYYY-MM-DD_HH-MM.parquet`.
- Budget: 4,000 API credits/day; the Paris box costs 1 credit per call, so 25 s ≈ 3,450 calls/day.
- Runs on the VPS as a **systemd service** (`flight-collector`), as a dedicated user `flightcollector`, in `/opt/flight-collector/app`.
  - `Restart=always`: restarts automatically after a crash.
  - `KillSignal=SIGINT`: stopping the service acts like Ctrl+C, so the current hour is saved first.
- Logs: `logs/` on the VPS, and `journalctl -u flight-collector`.
- Data copied to my computer with `scp` / `rsync`.
- OpenSky historical (Trino) access is limited to university-affiliated researchers, by application. Not needed: the collector is the main data source.
- Free alternative if more variety is needed later: ADS-B Exchange publishes full data for the 1st of each month.

---

## Phase 2: Cleaning

Pipeline (each step takes a DataFrame and returns a new one; the input is never modified):

```
load_raw → remove_missing_positions → remove_duplicates → split_flights → keep_arrivals → remove_implausible_flights
```

Data used: **235,323 raw rows** (≈ 2 days of VPS collection + earlier local tests).

### Step 1: missing positions
- Rule: drop rows where `time_position`, `latitude` or `longitude` is null (they can't be placed on a trajectory).
- Test data: 0 removed. Full data: **TODO**.
- Runs **before** duplicate removal, because `drop_duplicates` treats nulls as equal to each other.

### Step 2: duplicates
- Rule: same `icao24` + `time_position` = OpenSky had no new position between two snapshots. Keep the first.
- Test data: 823 of 3,630 rows removed (22.7%). Full data: **TODO**.

### Step 3: splitting into flights
- One `icao24` = one aircraft, which can fly several flights a day.
- Rule: a new flight starts at an aircraft's first point, or after a gap of more than **10 minutes**.
  `flight_id` = `<icao24>_<n>`.

Gap analysis (full data):

| Gaps above | Count |
| --- | --- |
| 1 min | 8,102 |
| 5 min | 4,782 |
| 10 min | 4,555 |
| 15 min | 4,466 |
| 20 min | 4,408 |
| 60 min | 4,082 |

- Normal tracking: 10–50 s (peak at 25–30 s = the collector interval).
- 1–5 min: short coverage dropouts (same flight).
- Bump at ~3 h: the same aircraft coming back on its next rotation.
- Between 10 and 20 min the count barely changes, so 10 min is a stable choice.
- ~700 gaps between 5 and 60 min are ambiguous (left the box and came back, or a quick turnaround).
  Accepted for now: if an arrival gets split, the later part still ends at CDG and is kept.
- Result: **7,280 flights**.

### Step 4: keeping CDG arrivals
Rule: a flight is a CDG arrival if
1. its **last point** is within **7 km** of CDG (49.01, 2.55),
2. that point is **on the ground or below 500 m**,
3. and the flight was **above 1,000 m at some point** (rules out aircraft that only moved on the ground).

Why these thresholds (histogram of last-point distance to CDG):
- 0–4 km: aircraft ending on the ground at CDG.
- 5–6.5 km: descending aircraft lost just before touchdown, so 5 km was too tight.
- 8–10 km: probably **Le Bourget**, excluded by 7 km.
- ~21–22 km and ~26–27 km clusters: **TODO**, not yet explained (plot them).

| Step | Flights |
| --- | --- |
| All flights | 7,280 |
| Ending within 7 km of CDG | 1,249 |
| …and on the ground or below 500 m | 1,244 |
| …and airborne above 1,000 m at some point | **1,156** |

- The airborne check removed **88 ground-only "flights"** (parked or taxiing aircraft).
- 44,430 points in arrival tracks, ≈ 38 points per flight (≈ 16 min in the box).
- 1,156 arrivals in ~2 days fits CDG's roughly 650–700 arrivals per day, minus coverage losses.

### Step 5: implausible speeds (in progress)
Computed between consecutive points of each flight: distance (`haversine_km` with `shift()`), time (`diff()`), implied speed, vertical speed.

- Implied speed: median ≈ 393 km/h; 25–75% = 272–499 km/h; max ≈ 1,640 km/h.
- Vertical speed: median ≈ −4 m/s; range −38 to +18 m/s.
- The speed histogram has a smooth tail, with no clean gap: only ~50 points above 1,000 km/h.

What the outliers turned out to be:
- **Whole flights with wrong positions or timestamps, not single-point glitches.** Implied speed is consistently 1.4–2.8× the speed the aircraft itself reports (`velocity`), for the entire track:
  - `347308_1` (SWT5614): ratio 2.4–2.8
  - `440d93_1` (TAY5AD): ratio 1.4–1.9
  - `44a6e4_1` (TAY7CA): ratio 1.6–2.0
  - Normal flight for comparison, `398579_6` (HOP61QR): ratio ≈ 1.0 (0.93–1.10)
  - SWT and TAY are both cargo-operator callsigns. Check `position_source` for these: **TODO**.
- **Steep descents (< −20 m/s) at touchdown are rounding noise:** `step_s` = 1 s and altitude steps of exactly 30.48 m (100 ft) or 38.1 m (125 ft). Altitude is broadcast in 25 ft steps, so rates over very short time steps are unreliable. These rows are real and are kept.
- **The strongest "climb" was not a go-around:** `392ae6_6` (AFR369Y) starts on the ground at **Orly** and lands at CDG (a short repositioning flight). It's a valid arrival that starts on the ground inside the box.
- Ratio artefact at touchdown: braking makes the current reported speed much lower than the average over the last step, so single-point ratios are high there. Hence the **median per flight**, ignoring points with a reported speed below ~50 km/h.

Planned rule: drop flights whose **median ratio implied / reported speed** is above ~**1.3**.
To do: histogram of the per-flight median ratio → confirm the threshold → count the flights removed → `remove_implausible_flights`.

---

## Open questions / ideas
- Should a callsign change start a new flight, even without a gap?
- A better split rule for the ambiguous 5–60 min gaps: split on a long gap only if the aircraft was low or on the ground before it?
- Re-check all thresholds when more data has been collected.
- Later: traffic context features (aircraft ahead in the arrival queue), and airport-agnostic features (distance to runway threshold).