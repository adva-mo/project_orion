# Project Orion — Swing Trade Scanner

Scans a watchlist of US stock tickers and identifies high-probability swing trade setups based on technical confluence. Designed for part-time traders who cannot watch charts live — all output is structured for pre-planned limit orders.

**Detects only objective technical setups. No news, no narratives, no direction prediction.**

---

## Setup Types

Evaluated in priority order — first match wins.

| Priority | Setup | Core Condition |
|---|---|---|
| 1 | **Fib 61.8 Confluence Buy Zone** | Price inside 61.8% retracement zone + at least one of: POC, VAL, VWAP |
| 2 | **Swing Low + Volume Support Buy Zone** | Recent pivot low overlaps with POC / VAL / HVN; price near or has swept-and-reclaimed |
| 3 | **Liquidity Trap Buy Zone** | Price swept below VAL near a high-volume POC (stop-hunt zone) |
| 4 | **VWAP Reclaim Setup** | Price was below session VWAP, now reclaiming with volume confirmation |
| 5 | **No Trade** | No clean confluence or poor risk/reward |

---

## Output (per ticker)

```json
{
  "ticker": "LMT",
  "setup_type": "Fib 61.8 Confluence Buy Zone",
  "score": 44,
  "current_price": 513.45,
  "buy_zone": [510.00, 519.01],
  "stop_loss": 477.72,
  "target_1": 510.49,
  "target_2": 645.31,
  "risk_reward": 4.19,
  "reason": "Price at 61.8% fib retracement (514.51) with confluence at VAL, VWAP...",
  "fibonacci": {
    "swing_low": 434.96,
    "swing_high": 643.20,
    "fib_382": 563.65,
    "fib_500": 539.08,
    "fib_618": 514.51,
    "fib_786": 479.52,
    "zone": [510.00, 519.01],
    "is_near": true
  },
  "volume_supported_swing_low": {
    "swing_low": 630.72,
    "volume_level": 629.14,
    "volume_type": "HVN",
    "distance_atr": 0.09,
    "is_valid": true,
    "price_near": false,
    "sweep_detected": false,
    "accepted_below": true
  }
}
```

---

## Installation

**Requirements:** Python 3.11+

```bash
git clone <repo>
cd project_orion

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
```

---

## Configuration

Edit `config.yaml` to set your watchlist and minimum risk/reward:

```yaml
tickers:
  - LMT
  - RTX
  - NOC

min_rr: 2.0
```

CLI arguments always override the config file.

---

## Usage

### CLI

```bash
# Scan tickers from config.yaml
python -m app scan

# Scan specific tickers
python -m app scan LMT RTX NOC

# Override minimum R/R
python -m app scan --min-rr 1.5

# Verbose mode — shows all indicator values for comparison with charts
python -m app scan --verbose
python -m app scan LMT --verbose

# JSON output
python -m app scan --json
```

**Verbose output example:**
```
============================================================
  LMT  —  Fib 61.8 Confluence Buy Zone  (score: 44/100)
============================================================
  Price      : 513.45
  ATR (14)   : 18.02
  VWAP (sess): 510.49  ↑ price above
  EMA (20)   : 590.42  below EMA (-15)

  Volume Profile
    POC      : 626.20
    VAH      : 645.31
    VAL      : 507.13  ← price inside value area (-20)

  Fibonacci  : swing 434.96 → 643.20  (range 208.24)
    38.2%    : 563.65
    50.0%    : 539.08
    61.8%    : 514.51  ← zone 510.00 – 519.01  ✓ PRICE IN ZONE
    78.6%    : 479.52

  Swing Low + Volume Confluence
    Swing low: 630.72  ←→  HVN 629.14  (dist 0.09 ATR)
    Flags    :  ✗ accepted below (-20)

  Setup
    Buy zone : 510.00 – 519.01
    Stop     : 477.72  (32.28 risk from zone low)
    Target 1 : 510.49
    Target 2 : 645.31
    R/R      : 4.19x

  Reason: Price at 61.8% fib retracement (514.51)...
```

### API

```bash
uvicorn app.main:app --reload --port 8000
```

**POST /scan**
```bash
curl -X POST http://localhost:8000/scan \
  -H "Content-Type: application/json" \
  -d '{"tickers": ["LMT", "RTX"], "min_rr": 2.0}'
```

**GET /config** — view active config.yaml contents

**GET /health** — health check

---

## Docker

```bash
docker build -t project-orion .

# CLI scan (reads config.yaml)
docker run --rm -v $(pwd)/config.yaml:/app/config.yaml project-orion

# API server
docker run --rm -p 8000:8000 -v $(pwd)/config.yaml:/app/config.yaml \
  project-orion uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Mount your own `config.yaml` to customize the watchlist without rebuilding the image.

---

## How It Works

### Data
- **Daily OHLCV** — 6 months lookback via yfinance (swing detection, ATR, EMA, Fibonacci)
- **Hourly OHLCV** — 30 days lookback (session VWAP, volume profile, sweep detection)

### Indicators

**ATR** — Wilder's 14-period ATR on daily data. Used for zone sizing, stop placement, and all confluence tolerances.

**Session VWAP** — True VWAP that resets at the start of each trading day: `cumulative(TP × Volume) / cumulative(Volume)` where `TP = (H+L+C)/3`. Reflects the actual institutional reference level.

**EMA (20)** — 20-period EMA on daily closes. Used as a trend filter: +10 pts if price is above, −15 pts if price is below. Avoids buying into strong downtrends.

**Volume Profile** — Hourly close prices binned into 50 equal-width buckets over the 30-day window:
- **POC** — Price of Control: midpoint of the bin with highest volume
- **VAH / VAL** — Value Area High/Low: outer boundaries of bins containing 70% of total volume
- **HVN** — High-Volume Nodes: up to 3 secondary bins with volume ≥ 60% of POC

**Fibonacci** — Objective, data-driven swing detection:
1. Pivot highs/lows: candle must be strictly higher/lower than the 5 candles on each side (numpy-based, no rolling window bias)
2. Valid bullish impulse: `swing_low → swing_high` where move ≥ 2× ATR and low occurs before high
3. Ranked by recency (60%) and size (40%) — top 2 impulses evaluated
4. Price is considered "near 61.8%" if it falls inside the zone of **either** top impulse
5. Levels: 38.2%, 50%, 61.8%, 78.6%
6. Zone: `fib_618 ± 0.25 × ATR`

**Swing Low + Volume Confluence** — Detects support zones where price structure and volume align:
1. Takes the 3 most recent pivot lows from valid impulse structures
2. Checks each against POC, VAL, and HVN within 0.25 × ATR tolerance
3. Returns the most recent match (POC checked first, then VAL, then HVN)
4. Detects sweep: hourly candle wicked below the swing low but closed back above
5. Detects breakdown: price currently below swing low with no reclaim

### Risk Logic

| Field | Source |
|---|---|
| Entry | Lower bound of buy zone (aggressive limit) |
| Stop loss | Below fib 78.6%, below sweep low, or below swing low (setup-dependent) |
| Target 1 | Session VWAP or 50% fib retracement (whichever is above entry) |
| Target 2 | VAH or recent swing high |
| R/R | `max((T1 − entry), (T2 − entry)) / (entry − stop)` — uses the better target |

### Scoring (0–100)

**Base score (all setups)**

| Component | Points |
|---|---|
| Confluence count (POC, VAL, VWAP) | 10 pts each, max 40 |
| Proximity to 61.8% fib | 0–20 pts (linear, 0 at 1× ATR away) |
| R/R ratio | 0–25 pts (linear, 10 pts at 2×, 25 pts at 4×) |
| Volume confirmation | +15 |
| Price above 20 EMA | +10 |
| Price below 20 EMA | −15 |
| Price inside value area | −20 |
| VAL sweep candle (wick below, close above) | +15 |

**Swing Low + Volume Confluence bonus (added on top)**

| Condition | Points |
|---|---|
| Swing low overlaps with POC | +20 |
| Swing low overlaps with VAL or HVN | +15 |
| Current price near swing low (≤ 0.5× ATR) | +10 |
| Sweep-and-reclaim detected at swing low | +10 |
| Price accepted below swing low (breakdown) | −20 |

---

## Project Structure

```
app/
├── __main__.py     CLI entrypoint
├── main.py         FastAPI app
├── models.py       Pydantic types (FibonacciInfo, VolumeProfile, VolumeSupportedSwingLow, ScanResult)
├── config.py       config.yaml loader
├── scanner.py      Orchestrator
├── data.py         yfinance fetch + validation
├── indicators.py   ATR, session VWAP, EMA, volume profile (POC/VAH/VAL/HVN)
├── fibonacci.py    Pivot detection, impulse ranking, fib levels, swing-low confluence
└── setups.py       Setup detection + scoring
config.yaml         Watchlist and settings
Dockerfile          Multi-stage Docker build
```
