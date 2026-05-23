import pandas as pd

from app.fibonacci import find_pivot_highs
from app.models import BreakoutRetestInfo, FibonacciInfo, ScanResult, VolumeProfile, VolumeSupportedSwingLow

SETUP_FIB_CONFLUENCE = "Fib 61.8 Confluence Buy Zone"
SETUP_BREAKOUT_RETEST = "Breakout + Retest"
SETUP_SWING_VOLUME = "Swing Low + Volume Support Buy Zone"
SETUP_LIQUIDITY_TRAP = "Liquidity Trap Buy Zone"
SETUP_VWAP_RECLAIM = "VWAP Reclaim Setup"
SETUP_NO_TRADE = "No Trade"

# Consistent ATR-based proximity thresholds used everywhere
_VOL_PROX = 0.5   # price vs volume level (POC / VAL / HVN)
_FLOW_PROX = 0.3  # price vs VWAP
_STRUCT_PROX = 0.3  # price vs swing low

# Signal weights (tiered by predictive strength)
_W_SWEEP      = 30   # tier 1: sweep-and-reclaim anywhere
_W_POC        = 25   # tier 1: POC confluence
_W_FIB618_MAX = 20   # tier 2: fib 61.8% proximity (linear, 0–20)
_W_FIB_SWEEP  = 20   # tier 2: fib zone swept below then reclaimed (ICT OTE confirmation)
_W_RR_MAX     = 20   # tier 2: R/R quality (linear, 0–20)
_W_VAL_RECLAIM = 15  # tier 2: price reclaimed VAL after sweep (CIIDB Release signal)
_W_VAL        = 12   # tier 3
_W_VOL_CONF   = 12   # tier 3: volume-confirmed VWAP reclaim
_W_SWING_PROX = 10   # tier 3
_W_HVN        = 8    # tier 3
_W_VWAP       = 8    # tier 3
_W_EMA_ABOVE  = 8    # tier 3
_W_EMA_BELOW  = -15  # penalty
_W_MA200_ABOVE = 10   # tier 3: price above weekly MA200 (bull market context)
_W_MA200_BELOW = -25  # penalty: price below weekly MA200 (bear market)
_W_MARKET_UPTREND   = 12   # tier 3: HH+HL sequence on daily pivots
_W_MARKET_DOWNTREND = -20  # penalty: LH+LL sequence
_W_VP_SCENARIO_BONUS   = 8   # price_up_vol_up or price_down_vol_down
_W_VP_SCENARIO_PENALTY = -10 # price_down_vol_up (strong institutional selling)
_W_RS_STRONG = 10   # relative strength vs SPY > 1.3
_W_RS_WEAK   = -8   # relative strength vs SPY < 0.7
_W_SWEEP_DAILY_BONUS = 5  # extra when sweep confirmed on daily timeframe
_W_BREAKOUT_VOL = 15   # breakout candle volume >= 1.5x 20-day average
_W_IN_VA      = -20  # penalty
_W_ACCEPTED   = -20  # penalty
_MAX_SCORE = (
    _W_SWEEP + _W_POC + _W_FIB618_MAX + _W_FIB_SWEEP + _W_RR_MAX + _W_VAL_RECLAIM
    + _W_VAL + _W_VOL_CONF + _W_SWING_PROX + _W_HVN + _W_VWAP + _W_EMA_ABOVE
    + _W_MA200_ABOVE + _W_MARKET_UPTREND + _W_VP_SCENARIO_BONUS + _W_RS_STRONG
    + _W_SWEEP_DAILY_BONUS + _W_BREAKOUT_VOL
)  # = 248


def detect_setup(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    volume_profile: VolumeProfile,
    fib_info: FibonacciInfo | None,
    hourly_closes: "pd.Series",
    hourly_lows: "pd.Series",
    hourly_volume: "pd.Series",
    ema_20: float,
    vsl: VolumeSupportedSwingLow | None,
    min_rr: float = 2.0,
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    daily: "pd.DataFrame | None" = None,
) -> ScanResult:
    vp = volume_profile
    in_value_area = vp.val < current_price < vp.vah
    price_above_ema = current_price > ema_20
    sweep_at_val_hourly = _detect_sweep(hourly_lows, hourly_closes, vp.val)
    sweep_at_val_daily = (
        _detect_sweep_daily(daily["Low"], daily["Close"], vp.val)
        if daily is not None else False
    )
    sweep_at_val = sweep_at_val_hourly or sweep_at_val_daily

    if fib_info is not None:
        result = _try_fib_confluence(
            ticker, current_price, atr, vwap, vp, fib_info,
            in_value_area, price_above_ema, sweep_at_val, vsl, min_rr,
            hourly_lows, hourly_closes, price_above_ma200, market_structure,
            vp_scenario, relative_strength, sweep_at_val_daily,
            daily=daily,
        )
        if result:
            return result

    result = _try_breakout_retest(
        ticker, current_price, atr, vwap, vp, fib_info, daily,
        in_value_area, price_above_ema, price_above_ma200,
        market_structure, vp_scenario, relative_strength, vsl, min_rr,
    )
    if result:
        return result

    result = _try_swing_volume(
        ticker, current_price, atr, vwap, vp, fib_info,
        in_value_area, price_above_ema, vsl, min_rr, price_above_ma200,
        market_structure, vp_scenario, relative_strength, sweep_at_val_daily,
    )
    if result:
        return result

    result = _try_liquidity_trap(
        ticker, current_price, atr, vwap, vp, fib_info,
        in_value_area, price_above_ema, sweep_at_val, vsl, min_rr, price_above_ma200,
        market_structure, vp_scenario, relative_strength, sweep_at_val_daily,
    )
    if result:
        return result

    result = _try_vwap_reclaim(
        ticker, current_price, atr, vwap, vp, fib_info,
        hourly_closes, hourly_volume,
        in_value_area, price_above_ema, sweep_at_val, min_rr, price_above_ma200,
        market_structure, vp_scenario, relative_strength, sweep_at_val_daily,
    )
    if result:
        return result

    return _no_trade(ticker, current_price, fib_info, vsl)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_sweep(
    hourly_lows: "pd.Series",
    hourly_closes: "pd.Series",
    support: float,
) -> bool:
    for i in range(len(hourly_lows)):
        if float(hourly_lows.iloc[i]) < support and float(hourly_closes.iloc[i]) > support:
            return True
    return False


def _detect_sweep_daily(
    daily_lows: "pd.Series",
    daily_closes: "pd.Series",
    support: float,
    lookback: int = 10,
) -> bool:
    """Check last `lookback` daily candles for wick-below, close-above pattern."""
    lows = daily_lows.iloc[-lookback:]
    closes = daily_closes.iloc[-lookback:]
    for i in range(len(lows)):
        if float(lows.iloc[i]) < support and float(closes.iloc[i]) > support:
            return True
    return False


def _split_rr(
    entry: float,
    stop_loss: float,
    target_1: float,
    target_2: float = 0.0,
) -> tuple[float, float]:
    """Returns (rr1, rr2) as individual R/R ratios for each target."""
    denom = entry - stop_loss
    if denom <= 0:
        return 0.0, 0.0
    rr1 = (target_1 - entry) / denom if target_1 > entry else 0.0
    rr2 = (target_2 - entry) / denom if target_2 > entry else 0.0
    return rr1, rr2


def _compute_rr(entry: float, stop_loss: float, target_1: float, target_2: float = 0.0) -> float:
    """Output R/R: best of the two targets (used in the result field)."""
    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    return max(rr1, rr2)


def _score_setup(
    current_price: float,
    atr: float,
    vp: VolumeProfile,
    vwap: float,
    fib_618: float | None,
    vsl: VolumeSupportedSwingLow | None,
    rr1: float,
    rr2: float,
    volume_confirmed: bool = False,
    in_value_area: bool = False,
    sweep_at_val: bool = False,
    price_above_ema: bool = True,
    fib_zone_swept: bool = False,
    val_reclaimed: bool = False,
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    sweep_at_val_daily: bool = False,
    breakout_vol_confirmed: bool = False,
) -> float:
    """Returns a score in [0.0, 1.0] normalised against _MAX_SCORE."""
    raw = 0.0

    # --- Volume (best of POC / VAL / HVN) ---
    if abs(current_price - vp.poc) <= _VOL_PROX * atr:
        raw += _W_POC
    elif abs(current_price - vp.val) <= _VOL_PROX * atr:
        raw += _W_VAL
    else:
        for hvn in vp.hvn:
            if abs(current_price - hvn) <= _VOL_PROX * atr:
                raw += _W_HVN
                break

    # --- Structure (best of fib 61.8% proximity vs swing-low proximity) ---
    struct_pts = 0.0
    if fib_618 is not None:
        dist = abs(current_price - fib_618)
        struct_pts = max(0.0, (1.0 - dist / atr) * _W_FIB618_MAX)
    if vsl is not None and vsl.is_valid and vsl.price_near:
        struct_pts = max(struct_pts, float(_W_SWING_PROX))
    raw += struct_pts

    # --- Flow ---
    if abs(current_price - vwap) <= _FLOW_PROX * atr:
        raw += _W_VWAP

    # --- R/R (linear 0→20 over range 2×→4×) ---
    weighted_rr = 0.7 * rr1 + 0.3 * rr2
    raw += min(_W_RR_MAX, max(0.0, (weighted_rr - 2.0) / (4.0 - 2.0) * _W_RR_MAX))

    # --- Volume confirmation (VWAP reclaim) ---
    if volume_confirmed:
        raw += _W_VOL_CONF

    # --- Sweep-and-reclaim (capped at _W_SWEEP even when both locations fire) ---
    any_sweep = sweep_at_val or (vsl is not None and vsl.is_valid and vsl.sweep_detected)
    if any_sweep:
        raw += _W_SWEEP
        if sweep_at_val_daily:
            raw += _W_SWEEP_DAILY_BONUS

    # --- Fib OTE zone swept + reclaimed (ICT/CIIDB confirmation) ---
    if fib_zone_swept:
        raw += _W_FIB_SWEEP

    # --- Breakout candle confirmed by volume ---
    if breakout_vol_confirmed:
        raw += _W_BREAKOUT_VOL

    # --- VAL reclaim after sweep (CIIDB Release signal for Liquidity Trap) ---
    if val_reclaimed:
        raw += _W_VAL_RECLAIM

    # --- Trend filter ---
    raw += _W_EMA_ABOVE if price_above_ema else _W_EMA_BELOW

    # --- Weekly MA200 (bull/bear market context) ---
    raw += _W_MA200_ABOVE if price_above_ma200 else _W_MA200_BELOW

    # --- Market structure (HH/HL = uptrend, LH/LL = downtrend) ---
    if market_structure == "uptrend":
        raw += _W_MARKET_UPTREND
    elif market_structure == "downtrend":
        raw += _W_MARKET_DOWNTREND

    # --- Volume-price scenario (CIIDB 4-type classification) ---
    if vp_scenario in ("price_up_vol_up", "price_down_vol_down"):
        raw += _W_VP_SCENARIO_BONUS
    elif vp_scenario == "price_down_vol_up":
        raw += _W_VP_SCENARIO_PENALTY

    # --- Relative strength vs SPY ---
    if relative_strength > 1.3:
        raw += _W_RS_STRONG
    elif relative_strength < 0.7:
        raw += _W_RS_WEAK

    # --- Penalties ---
    if in_value_area:
        raw += _W_IN_VA
    if vsl is not None and vsl.is_valid and vsl.accepted_below:
        raw += _W_ACCEPTED

    return max(0.0, min(raw, _MAX_SCORE)) / _MAX_SCORE


# ---------------------------------------------------------------------------
# Setup detectors
# ---------------------------------------------------------------------------

def _try_fib_confluence(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    vp: VolumeProfile,
    fib: FibonacciInfo,
    in_value_area: bool,
    price_above_ema: bool,
    sweep_at_val: bool,
    vsl: VolumeSupportedSwingLow | None,
    min_rr: float,
    hourly_lows: "pd.Series",
    hourly_closes: "pd.Series",
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    sweep_at_val_daily: bool = False,
    daily: "pd.DataFrame | None" = None,
) -> ScanResult | None:
    if not fib.is_near:
        return None

    # Detect which confluences are present (needed for trigger + reason text)
    reasons = []
    if abs(current_price - vp.poc) <= _VOL_PROX * atr:
        reasons.append("POC")
    if abs(current_price - vp.val) <= _VOL_PROX * atr:
        reasons.append("VAL")
    if abs(current_price - vwap) <= _FLOW_PROX * atr:
        reasons.append("VWAP")

    if not reasons:
        return None

    # ICT OTE: check if fib zone was swept below then reclaimed (Release signal)
    fib_zone_swept = _detect_sweep(hourly_lows, hourly_closes, fib.zone[0]) or (
        daily is not None and _detect_sweep_daily(daily["Low"], daily["Close"], fib.zone[0])
    )

    entry = fib.zone[0]
    stop_loss = fib.fib_786 - 0.1 * atr
    target_1 = vwap if vwap > entry else fib.fib_500
    target_2 = max(vp.vah, fib.swing_high)

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = _score_setup(
        current_price=current_price,
        atr=atr,
        vp=vp,
        vwap=vwap,
        fib_618=fib.fib_618,
        vsl=vsl,
        rr1=rr1,
        rr2=rr2,
        in_value_area=in_value_area,
        sweep_at_val=sweep_at_val,
        price_above_ema=price_above_ema,
        fib_zone_swept=fib_zone_swept,
        price_above_ma200=price_above_ma200,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
        sweep_at_val_daily=sweep_at_val_daily,
    )

    vsl_note = (
        f" Structural confluence: swing low at {vsl.swing_low:.2f} aligns with {vsl.volume_type} ({vsl.volume_level:.2f})."
        if vsl and vsl.is_valid else ""
    )
    reason = (
        f"Price at 61.8% fib retracement ({fib.fib_618:.2f}) with confluence at {', '.join(reasons)}."
        f" Entry at zone low {entry:.2f}, stop below fib 78.6% at {stop_loss:.2f}.{vsl_note}"
    )

    return ScanResult(
        ticker=ticker,
        setup_type=SETUP_FIB_CONFLUENCE,
        score=score,
        current_price=round(current_price, 4),
        buy_zone=(round(fib.zone[0], 4), round(fib.zone[1], 4)),
        stop_loss=round(stop_loss, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        risk_reward=round(max(rr1, rr2), 2),
        reason=reason,
        fibonacci=fib,
        volume_supported_swing_low=vsl,
    )


def _try_breakout_retest(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    vp: VolumeProfile,
    fib: FibonacciInfo | None,
    daily: "pd.DataFrame",
    in_value_area: bool,
    price_above_ema: bool,
    price_above_ma200: bool,
    market_structure: str,
    vp_scenario: str,
    relative_strength: float,
    vsl: VolumeSupportedSwingLow | None,
    min_rr: float,
) -> ScanResult | None:
    if daily is None or len(daily) < 30:
        return None

    ph = find_pivot_highs(daily, n=5)
    pivot_high_dates = daily.index[ph]

    # Only consider swing highs in the last 60 bars
    recent_cutoff = daily.index[-60]
    pivot_high_dates = pivot_high_dates[pivot_high_dates >= recent_cutoff]
    if len(pivot_high_dates) == 0:
        return None

    closes = daily["Close"]
    volumes = daily["Volume"]

    for resistance_date in reversed(pivot_high_dates.tolist()):
        resistance_level = float(daily.loc[resistance_date, "High"])
        res_iloc = daily.index.get_loc(resistance_date)

        # Find the first close above resistance_level after the swing high
        breakout_iloc = None
        for i in range(res_iloc + 1, len(daily)):
            if float(closes.iloc[i]) > resistance_level:
                breakout_iloc = i
                break

        if breakout_iloc is None:
            continue

        # Volume check: breakout candle vol >= 1.5x prior 20-day avg
        prior_start = max(0, breakout_iloc - 20)
        avg_vol = float(volumes.iloc[prior_start:breakout_iloc].mean())
        breakout_vol = float(volumes.iloc[breakout_iloc])
        breakout_vol_ratio = breakout_vol / avg_vol if avg_vol > 0 else 1.0
        breakout_vol_confirmed = breakout_vol_ratio >= 1.5

        # Current price must be in the retest zone
        retest_low = resistance_level - 1.0 * atr
        retest_high = resistance_level + 0.5 * atr
        if not (retest_low <= current_price <= retest_high):
            continue

        # Structure not broken: no close below resistance - 1.5 * ATR after breakout
        invalidation_level = resistance_level - 1.5 * atr
        post_breakout_closes = closes.iloc[breakout_iloc + 1:]
        if (post_breakout_closes < invalidation_level).any():
            continue

        # Valid setup — compute trade parameters
        entry = current_price
        stop_loss = resistance_level - 1.5 * atr
        target_1 = resistance_level + (resistance_level - stop_loss)
        target_2 = max(vp.vah, fib.swing_high if fib else 0.0)

        rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
        if max(rr1, rr2) < min_rr:
            continue

        score = _score_setup(
            current_price=current_price,
            atr=atr,
            vp=vp,
            vwap=vwap,
            fib_618=fib.fib_618 if fib else None,
            vsl=vsl,
            rr1=rr1,
            rr2=rr2,
            in_value_area=in_value_area,
            price_above_ema=price_above_ema,
            price_above_ma200=price_above_ma200,
            market_structure=market_structure,
            vp_scenario=vp_scenario,
            relative_strength=relative_strength,
            breakout_vol_confirmed=breakout_vol_confirmed,
        )

        breakout_date_str = daily.index[breakout_iloc].strftime("%Y-%m-%d")
        is_holding = current_price >= resistance_level - 0.5 * atr

        reason = (
            f"Price ({current_price:.2f}) retesting broken resistance ({resistance_level:.2f}) as support. "
            f"Breakout on {breakout_date_str} with {breakout_vol_ratio:.1f}× avg volume. "
            f"{'Volume confirmed breakout. ' if breakout_vol_confirmed else ''}"
            f"Entry at {entry:.2f}, stop at {stop_loss:.2f}."
        )

        return ScanResult(
            ticker=ticker,
            setup_type=SETUP_BREAKOUT_RETEST,
            score=score,
            current_price=round(current_price, 4),
            buy_zone=(round(retest_low, 4), round(resistance_level, 4)),
            stop_loss=round(stop_loss, 4),
            target_1=round(target_1, 4),
            target_2=round(target_2, 4),
            risk_reward=round(max(rr1, rr2), 2),
            reason=reason,
            fibonacci=fib,
            volume_supported_swing_low=vsl,
            breakout_retest=BreakoutRetestInfo(
                resistance_level=round(resistance_level, 4),
                resistance_date=resistance_date.strftime("%Y-%m-%d"),
                breakout_date=breakout_date_str,
                breakout_volume_ratio=round(breakout_vol_ratio, 2),
                is_holding=is_holding,
            ),
        )

    return None


def _try_swing_volume(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    vp: VolumeProfile,
    fib: FibonacciInfo | None,
    in_value_area: bool,
    price_above_ema: bool,
    vsl: VolumeSupportedSwingLow | None,
    min_rr: float,
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    sweep_at_val_daily: bool = False,
) -> ScanResult | None:
    if vsl is None or not vsl.is_valid:
        return None
    if not (vsl.price_near or vsl.sweep_detected):
        return None
    if vsl.accepted_below:
        return None

    entry = vsl.swing_low
    stop_loss = vsl.swing_low - 1.5 * atr
    target_1 = vwap if vwap > entry else entry + 1.5 * atr
    target_2 = vp.vah

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = _score_setup(
        current_price=current_price,
        atr=atr,
        vp=vp,
        vwap=vwap,
        fib_618=fib.fib_618 if fib else None,
        vsl=vsl,
        rr1=rr1,
        rr2=rr2,
        in_value_area=in_value_area,
        sweep_at_val=vsl.sweep_detected,
        price_above_ema=price_above_ema,
        price_above_ma200=price_above_ma200,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
        sweep_at_val_daily=sweep_at_val_daily,
    )

    sweep_note = " Liquidity sweep below swing low detected — wick and reclaim." if vsl.sweep_detected else ""
    reason = (
        f"Price is pulling into a recent swing-low support ({vsl.swing_low:.2f}) that overlaps with a "
        f"high-volume area ({vsl.volume_type} at {vsl.volume_level:.2f}), creating structural + volume confluence."
        f"{sweep_note} Stop below {stop_loss:.2f}."
    )

    return ScanResult(
        ticker=ticker,
        setup_type=SETUP_SWING_VOLUME,
        score=score,
        current_price=round(current_price, 4),
        buy_zone=(round(entry - _STRUCT_PROX * atr, 4), round(entry + _VOL_PROX * atr, 4)),
        stop_loss=round(stop_loss, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        risk_reward=round(max(rr1, rr2), 2),
        reason=reason,
        fibonacci=fib,
        volume_supported_swing_low=vsl,
    )


def _try_liquidity_trap(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    vp: VolumeProfile,
    fib: FibonacciInfo | None,
    in_value_area: bool,
    price_above_ema: bool,
    sweep_at_val: bool,
    vsl: VolumeSupportedSwingLow | None,
    min_rr: float,
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    sweep_at_val_daily: bool = False,
) -> ScanResult | None:
    near_poc = abs(current_price - vp.poc) <= _VOL_PROX * atr

    # Tier 1: swept below VAL and reclaimed (CIIDB Release signal — higher conviction)
    val_swept_and_reclaimed = sweep_at_val and current_price >= vp.val
    # Tier 2: price currently below VAL near POC (wipe in progress — lower conviction)
    below_val_near_poc = (vp.val - 1.0 * atr <= current_price < vp.val) and near_poc

    if not (val_swept_and_reclaimed or below_val_near_poc):
        return None

    entry = current_price
    sweep_low = current_price - 1.5 * atr
    stop_loss = min(fib.fib_786, sweep_low) if fib is not None else sweep_low
    target_1 = vp.val if not val_swept_and_reclaimed else vp.vah
    target_2 = vp.vah

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = _score_setup(
        current_price=current_price,
        atr=atr,
        vp=vp,
        vwap=vwap,
        fib_618=fib.fib_618 if fib else None,
        vsl=vsl,
        rr1=rr1,
        rr2=rr2,
        in_value_area=in_value_area,
        sweep_at_val=sweep_at_val,
        price_above_ema=price_above_ema,
        val_reclaimed=val_swept_and_reclaimed,
        price_above_ma200=price_above_ma200,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
        sweep_at_val_daily=sweep_at_val_daily,
    )

    if val_swept_and_reclaimed:
        reason = (
            f"Price ({current_price:.2f}) swept below VAL ({vp.val:.2f}) and reclaimed it — liquidity trap confirmed. "
            f"POC at {vp.poc:.2f} provides structural support. Entry at {entry:.2f}, stop at {stop_loss:.2f}."
        )
    else:
        reason = (
            f"Price ({current_price:.2f}) swept below VAL ({vp.val:.2f}) near high-volume POC ({vp.poc:.2f}). "
            f"{'Sweep candle detected (wick below, close above support). ' if sweep_at_val else ''}"
            f"Entry at {entry:.2f}, stop at {stop_loss:.2f}."
        )

    return ScanResult(
        ticker=ticker,
        setup_type=SETUP_LIQUIDITY_TRAP,
        score=score,
        current_price=round(current_price, 4),
        buy_zone=(round(entry - 0.1 * atr, 4), round(entry + 0.1 * atr, 4)),
        stop_loss=round(stop_loss, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        risk_reward=round(max(rr1, rr2), 2),
        reason=reason,
        fibonacci=fib,
        volume_supported_swing_low=vsl,
    )


def _try_vwap_reclaim(
    ticker: str,
    current_price: float,
    atr: float,
    vwap: float,
    vp: VolumeProfile,
    fib: FibonacciInfo | None,
    hourly_closes: "pd.Series",
    hourly_volume: "pd.Series",
    in_value_area: bool,
    price_above_ema: bool,
    sweep_at_val: bool,
    min_rr: float,
    price_above_ma200: bool = True,
    market_structure: str = "ranging",
    vp_scenario: str = "price_down_vol_up",
    relative_strength: float = 1.0,
    sweep_at_val_daily: bool = False,
) -> ScanResult | None:
    recent_closes = hourly_closes.iloc[-5:-1]
    was_below_vwap = (recent_closes < vwap).any()
    near_vwap = abs(current_price - vwap) <= _FLOW_PROX * atr

    if len(hourly_volume) >= 2:
        volume_not_decreasing = float(hourly_volume.iloc[-1]) >= float(hourly_volume.iloc[-2])
    else:
        volume_not_decreasing = True

    if not (was_below_vwap and near_vwap and volume_not_decreasing):
        return None

    entry = current_price
    stop_loss = current_price - 1.0 * atr
    if fib is not None:
        stop_loss = min(fib.fib_786, stop_loss)

    target_1 = vwap + 0.5 * atr
    target_2 = vp.vah

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = _score_setup(
        current_price=current_price,
        atr=atr,
        vp=vp,
        vwap=vwap,
        fib_618=fib.fib_618 if fib else None,
        vsl=None,
        rr1=rr1,
        rr2=rr2,
        volume_confirmed=True,
        in_value_area=in_value_area,
        sweep_at_val=sweep_at_val,
        price_above_ema=price_above_ema,
        price_above_ma200=price_above_ma200,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
        sweep_at_val_daily=sweep_at_val_daily,
    )

    reason = (
        f"Price ({current_price:.2f}) reclaiming VWAP ({vwap:.2f}) after trading below it. "
        f"Volume confirming. Entry at {entry:.2f}, stop at {stop_loss:.2f}."
    )

    return ScanResult(
        ticker=ticker,
        setup_type=SETUP_VWAP_RECLAIM,
        score=score,
        current_price=round(current_price, 4),
        buy_zone=(round(entry - _FLOW_PROX * atr, 4), round(entry + _FLOW_PROX * atr, 4)),
        stop_loss=round(stop_loss, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        risk_reward=round(max(rr1, rr2), 2),
        reason=reason,
        fibonacci=fib,
        volume_supported_swing_low=None,
    )


def _no_trade(
    ticker: str,
    current_price: float,
    fib_info: FibonacciInfo | None = None,
    vsl: VolumeSupportedSwingLow | None = None,
) -> ScanResult:
    return ScanResult(
        ticker=ticker,
        setup_type=SETUP_NO_TRADE,
        score=0,
        current_price=round(current_price, 4),
        buy_zone=(0.0, 0.0),
        stop_loss=0.0,
        target_1=0.0,
        target_2=0.0,
        risk_reward=0.0,
        reason="No clean technical setup detected. Price in middle of value area or poor risk/reward.",
        fibonacci=fib_info,
        volume_supported_swing_low=vsl,
    )
