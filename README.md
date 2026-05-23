# Project Orion — Swing Trade Scanner

Scans a watchlist of US stock tickers and identifies high-probability swing trade setups based on technical confluence. Designed for part-time traders who cannot watch charts live — all output is structured for pre-planned limit orders.

**Detects only objective technical setups. No news, no narratives, no direction prediction.**

---

## Strategy Overview

The scanner is built around a **liquidity-first** approach to price action:

1. **Mark** — identify where significant liquidity concentrates (volume nodes, Fibonacci levels, swing lows, value area boundaries)
2. **Wipe** — detect when price briefly sweeps below a level, triggering stop orders (false breakdown)
3. **Release** — confirm the sweep was absorbed: price closes back above the level, often on volume
4. **Entry** — position at the reclaimed level with a defined stop and two targets
5. **Context** — filter setups against multi-timeframe trend (weekly MA200, daily market structure) and relative strength vs. the broader market

Setups are ranked by a normalized score [0.0 – 1.0] that rewards confluence, sweep confirmation, trend alignment, and R/R quality, and penalizes counter-trend and structurally compromised conditions.

---

## Setup Types

Evaluated in priority order — first match wins.

| Priority | Setup | Core Condition |
|---|---|---|
| 1 | **Fib 61.8 Confluence Buy Zone** | Price inside 61.8% retracement zone + at least one of: POC, VAL, VWAP. Bonus when zone was swept below and reclaimed. |
| 2 | **Breakout + Retest** | Price broke above a prior resistance (swing high) on above-average volume; now retesting that level as support. |
| 3 | **Swing Low + Volume Support** | Recent pivot low overlaps with POC / VAL / HVN; price near or has swept-and-reclaimed the level. |
| 4 | **Liquidity Trap** | Price swept below VAL near a high-volume POC (stop-hunt zone). Higher conviction when VAL is subsequently reclaimed. |
| 5 | **VWAP Reclaim** | Price was below session VWAP, now reclaiming with volume confirmation. |
| — | **No Trade** | No clean confluence or poor risk/reward. |

---

## Output (per ticker)

```json
{
  "ticker": "LMT",
  "setup_type": "Fib 61.8 Confluence Buy Zone",
  "score": 0.71,
  "current_price": 513.45,
  "buy_zone": [510.00, 519.01],
  "stop_loss": 477.72,
  "target_1": 510.49,
  "target_2": 645.31,
  "risk_reward": 4.19,
  "reason": "Price at 61.8% fib retracement (514.51) with confluence at VAL, VWAP...",
  "fibonacci": { ... },
  "volume_supported_swing_low": { ... },
  "breakout_retest": null
}
```

Score is a normalised value between **0.0** (no confluence) and **1.0** (maximum confluence across all signals).

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
  XLE  —  No Trade  (score: 0.00)
============================================================
  Price      : 59.49
  ATR (14)   : 1.38
  VWAP (sess): 59.27  ↑ price above
  EMA (20)   : 58.62  above EMA (+8)
  MA200 (wk) : 42.16  above MA200 (+10)
  Mkt Struct : ranging (0)
  VP Scenario: price↓ vol↑  -10 (strong decline — avoid)
  Rel Str/SPY: 1.08×  in-line (0)

  Volume Profile  (2026-04-13 – 2026-05-22)
    POC      : 55.89
    VAH      : 60.32
    VAL      : 53.87  ← price inside value area (-20)

  Fibonacci  : swing 53.41 (2026-04-17) → 59.84 (2026-04-30)  (range 6.43)
    38.2%    : 57.38
    50.0%    : 56.62
    61.8%    : 55.87  ← zone 55.52 – 56.21  ✗ price outside zone
    78.6%    : 54.79

  Swing Low + Volume Confluence
    Swing low: 53.77 (2026-02-26)  ←→  VAL 53.87  (dist 0.07 ATR)
    Flags    :

  Reason: No clean technical setup detected. Price in middle of value area or poor risk/reward.
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

---

## How It Works

### Data

| Timeframe | Window | Used For |
|---|---|---|
| Daily (1d) | 6 months | ATR, EMA, Fibonacci, swing detection, market structure |
| Hourly (1h) | 30 days | Session VWAP, volume profile, sweep detection (hourly) |
| Weekly (1wk) | 5 years | MA200 — bull/bear market context |
| Daily SPY | 3 months | Relative strength calculation |

Weekly data and SPY are fetched alongside each ticker scan. SPY is fetched once per batch run to avoid redundant requests.

---

### Indicators

**ATR (14-period)** — Wilder's ATR on daily data. Used for zone sizing, stop placement, and all proximity tolerances throughout the scanner.

**Session VWAP** — True VWAP that resets at the start of each trading day: `Σ(TP × Volume) / Σ(Volume)` where `TP = (H+L+C)/3`. Reflects the intraday institutional reference level.

**EMA (20-period)** — 20-period EMA on daily closes. Short-term trend filter. Bonus when price is above; penalty when below.

**MA200 Weekly** — 200-period simple moving average on weekly closes. Determines the primary bull/bear market regime. A strong bonus for price above (institutional buying zone) and a significant penalty below (structural headwind for long setups).

**Volume Profile** — Hourly close prices binned into 50 equal-width buckets over the 30-day window:
- **POC** (Point of Control) — midpoint of the bin with the highest cumulative volume
- **VAH / VAL** (Value Area High/Low) — outer boundaries of bins that together contain 70% of total volume
- **HVN** (High-Volume Nodes) — up to 3 secondary bins with volume ≥ 60% of POC, filtered to exclude nodes too close to POC

**Fibonacci Retracement** — Objective, data-driven impulse detection:
1. Pivot highs/lows: a candle must be strictly higher/lower than the 5 candles on each side
2. Valid bullish impulse: `swing_low → swing_high` where move ≥ 2× ATR
3. Ranked by recency (60%) + magnitude (40%) — top 2 impulses evaluated
4. Levels: 38.2%, 50%, 61.8%, 78.6% retracements
5. Zone: `61.8% ± 0.25 × ATR`
6. **Sweep detection**: the zone is checked for a prior wick-below + close-above pattern on both hourly and daily bars. A swept-and-reclaimed zone scores significantly higher than simple proximity — this is the preferred entry signal.

**Swing Low + Volume Confluence** — Structural support zones where price pivots and volume align:
1. Takes the 3 most recent pivot lows from valid impulse structures
2. Matches each against POC, VAL, then HVN (within 0.25 × ATR tolerance)
3. Flags: `price_near` (within 0.3 × ATR), `sweep_detected` (wick below + close above, on hourly or daily bars), `accepted_below` (price broke below and has not reclaimed)

**Market Structure** — Analyses the sequence of recent daily pivot highs and lows:
- `uptrend` — higher highs and higher lows (HH + HL)
- `downtrend` — lower highs and lower lows (LH + LL)
- `ranging` — mixed sequence

**Volume-Price Scenario** — Classifies the last 5 daily bars vs. the prior 5 into one of four states:

| Scenario | Interpretation | Score Impact |
|---|---|---|
| Price↑ Volume↑ | Strong trend — institutional participation | +8 |
| Price↑ Volume↓ | Weak upside — potential false breakout | 0 |
| Price↓ Volume↓ | Fading decline — selling pressure waning | +8 |
| Price↓ Volume↑ | Strong decline — institutional selling | −10 |

**Relative Strength vs. SPY** — Compares the ticker's 20-day return to SPY's over the same window. `RS > 1.3` indicates a stock outperforming the broader market (institutional accumulation signal). `RS < 0.7` flags significant underperformance.

---

### Sweep Detection Logic

Sweeps (false breakdowns) are detected identically on both hourly and daily bars: a candle's **low** pierces below the support level while the **close** is back above it. A sweep confirmed on daily bars earns an additional bonus over an hourly-only sweep, as the higher-timeframe signal carries more weight.

---

### Risk Parameters

| Field | Source |
|---|---|
| Entry | Lower bound of buy zone (aggressive limit order) |
| Stop loss | Below fib 78.6%, below sweep low, or below swing low (setup-dependent) |
| Target 1 | Session VWAP, fib 50%, or 1:1 extension above resistance (setup-dependent) |
| Target 2 | VAH or recent swing high |
| R/R | `max((T1 − entry), (T2 − entry)) / (entry − stop)` — uses the better target |

---

### Scoring System

Score is normalized to **[0.0, 1.0]** by dividing the raw signal sum by the theoretical maximum (248 points). Penalties can push raw scores negative — these are clamped to 0.0 before normalization.

**Positive signals (add to raw score)**

| Signal | Points |
|---|---|
| Sweep-and-reclaim (hourly) | +30 |
| POC confluence | +25 |
| Fib 61.8% proximity (linear, 0 at 1× ATR) | 0 – 20 |
| Fib OTE zone swept + reclaimed | +20 |
| R/R quality (linear, 2× → 4×) | 0 – 20 |
| VAL reclaim after sweep | +15 |
| Breakout candle volume ≥ 1.5× avg | +15 |
| Market structure: uptrend (HH+HL) | +12 |
| VAL confluence | +12 |
| Volume confirmation (VWAP reclaim setup) | +12 |
| MA200 weekly — price above | +10 |
| Relative strength vs. SPY > 1.3× | +10 |
| Swing low proximity | +10 |
| Volume-price scenario bonus (↑↑ or ↓↓) | +8 |
| HVN confluence | +8 |
| VWAP proximity | +8 |
| EMA 20 — price above | +8 |
| Daily timeframe sweep bonus | +5 |

**Penalties (subtract from raw score)**

| Condition | Points |
|---|---|
| MA200 weekly — price below | −25 |
| Market structure: downtrend (LH+LL) | −20 |
| Price inside value area | −20 |
| Price accepted below swing low | −20 |
| EMA 20 — price below | −15 |
| Volume-price scenario: price↓ vol↑ | −10 |
| Relative strength vs. SPY < 0.7× | −8 |

---

## Project Structure

```
app/
├── __main__.py     CLI entrypoint
├── main.py         FastAPI app
├── models.py       Pydantic types (FibonacciInfo, VolumeProfile, VolumeSupportedSwingLow,
│                                   BreakoutRetestInfo, ScanResult)
├── config.py       config.yaml loader
├── scanner.py      Orchestrator — wires all indicators and routes to setups
├── data.py         yfinance fetch + validation (daily, hourly, weekly, SPY)
├── indicators.py   ATR, session VWAP, EMA20, MA200 weekly, volume profile,
│                   market structure, volume-price scenario, relative strength
├── fibonacci.py    Pivot detection, impulse ranking, fib levels, swing-low confluence
└── setups.py       Setup detection + unified scoring
config.yaml         Watchlist and settings
Dockerfile          Multi-stage Docker build
```
