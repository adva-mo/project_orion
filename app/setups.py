import pandas as pd

from app.models import FibonacciInfo, ScanResult, VolumeProfile, VolumeSupportedSwingLow

SETUP_FIB_CONFLUENCE = "Fib 61.8 Confluence Buy Zone"
SETUP_SWING_VOLUME = "Swing Low + Volume Support Buy Zone"
SETUP_LIQUIDITY_TRAP = "Liquidity Trap Buy Zone"
SETUP_VWAP_RECLAIM = "VWAP Reclaim Setup"
SETUP_NO_TRADE = "No Trade"

# Consistent ATR-based proximity thresholds used everywhere
_VOL_PROX = 0.5   # price vs volume level (POC / VAL / HVN)
_FLOW_PROX = 0.3  # price vs VWAP
_STRUCT_PROX = 0.3  # price vs swing low


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
) -> ScanResult:
    vp = volume_profile
    in_value_area = vp.val < current_price < vp.vah
    price_above_ema = current_price > ema_20
    sweep_at_val = _detect_sweep(hourly_lows, hourly_closes, vp.val)

    if fib_info is not None:
        result = _try_fib_confluence(
            ticker, current_price, atr, vwap, vp, fib_info,
            in_value_area, price_above_ema, sweep_at_val, vsl, min_rr,
        )
        if result:
            return result

    result = _try_swing_volume(
        ticker, current_price, atr, vwap, vp, fib_info,
        in_value_area, price_above_ema, vsl, min_rr,
    )
    if result:
        return result

    result = _try_liquidity_trap(
        ticker, current_price, atr, vwap, vp, fib_info,
        in_value_area, price_above_ema, sweep_at_val, vsl, min_rr,
    )
    if result:
        return result

    result = _try_vwap_reclaim(
        ticker, current_price, atr, vwap, vp, fib_info,
        hourly_closes, hourly_volume,
        in_value_area, price_above_ema, sweep_at_val, min_rr,
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
) -> float:
    """
    Unified scorer with three non-overlapping confluence categories.

    Category caps prevent the same level being credited twice:
      Volume   (max 15): single best of POC / VAL / HVN
      Structure (max 20): single best of fib 61.8% proximity OR swing-low proximity
      Flow      (max 10): VWAP proximity

    Sweep bonus is capped at 15 across both sweep signals to avoid inflation.
    """
    score = 0.0

    # --- Volume category (max 15, single best) ---
    vol_pts = 0.0
    if abs(current_price - vp.poc) <= _VOL_PROX * atr:
        vol_pts = 15.0
    elif abs(current_price - vp.val) <= _VOL_PROX * atr:
        vol_pts = 10.0
    else:
        for hvn in vp.hvn:
            if abs(current_price - hvn) <= _VOL_PROX * atr:
                vol_pts = 8.0
                break
    score += vol_pts

    # --- Structure category (max 20, single best of fib vs swing low) ---
    struct_pts = 0.0
    if fib_618 is not None:
        dist = abs(current_price - fib_618)
        struct_pts = max(0.0, (1.0 - dist / atr) * 20.0)
    if vsl is not None and vsl.is_valid and vsl.price_near:
        struct_pts = max(struct_pts, 15.0)
    score += struct_pts

    # --- Flow category (max 10) ---
    if abs(current_price - vwap) <= _FLOW_PROX * atr:
        score += 10.0

    # --- R/R score (max 25, weighted 70/30 for scoring only) ---
    weighted_rr = 0.7 * rr1 + 0.3 * rr2
    score += min(25.0, max(0.0, (weighted_rr - 2.0) / (4.0 - 2.0) * 25.0))

    # --- Bonuses ---
    if volume_confirmed:
        score += 15.0

    # Sweep bonus capped at 15 across both sweep signals
    sweep_pts = (10.0 if sweep_at_val else 0.0) + (
        10.0 if (vsl is not None and vsl.is_valid and vsl.sweep_detected) else 0.0
    )
    score += min(15.0, sweep_pts)

    # --- Trend filter ---
    score += 10.0 if price_above_ema else -15.0

    # --- Penalties ---
    if in_value_area:
        score -= 20.0
    if vsl is not None and vsl.is_valid and vsl.accepted_below:
        score -= 20.0

    return score


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

    entry = fib.zone[0]
    stop_loss = fib.fib_786 - 0.1 * atr
    target_1 = vwap if vwap > entry else fib.fib_500
    target_2 = max(vp.vah, fib.swing_high)

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = min(100, max(0, int(round(_score_setup(
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
    )))))

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

    score = min(100, max(0, int(round(_score_setup(
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
    )))))

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
) -> ScanResult | None:
    below_val = vp.val - 1.0 * atr <= current_price < vp.val
    near_poc = abs(current_price - vp.poc) <= _VOL_PROX * atr

    if not (below_val and near_poc):
        return None

    entry = current_price
    sweep_low = current_price - 1.5 * atr
    stop_loss = min(fib.fib_786, sweep_low) if fib is not None else sweep_low
    target_1 = vp.val
    target_2 = vp.vah

    rr1, rr2 = _split_rr(entry, stop_loss, target_1, target_2)
    if max(rr1, rr2) < min_rr:
        return None

    score = min(100, max(0, int(round(_score_setup(
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
    )))))

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

    score = min(100, max(0, int(round(_score_setup(
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
    )))))

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
