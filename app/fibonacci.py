import numpy as np
import pandas as pd

from app.models import FibonacciInfo, VolumeProfile, VolumeSupportedSwingLow


def find_pivot_highs(daily: pd.DataFrame, n: int = 5) -> pd.Series:
    arr = daily["High"].to_numpy()
    pivot = np.zeros(len(arr), dtype=bool)
    for i in range(n, len(arr) - n):
        if arr[i] > arr[i - n : i].max() and arr[i] > arr[i + 1 : i + n + 1].max():
            pivot[i] = True
    return pd.Series(pivot, index=daily.index)


def find_pivot_lows(daily: pd.DataFrame, n: int = 5) -> pd.Series:
    arr = daily["Low"].to_numpy()
    pivot = np.zeros(len(arr), dtype=bool)
    for i in range(n, len(arr) - n):
        if arr[i] < arr[i - n : i].min() and arr[i] < arr[i + 1 : i + n + 1].min():
            pivot[i] = True
    return pd.Series(pivot, index=daily.index)


def build_impulse_moves(
    daily: pd.DataFrame,
    pivot_highs: pd.Series,
    pivot_lows: pd.Series,
    atr: float,
    min_atr_multiplier: float = 2.0,
) -> list[dict]:
    low_times = daily.index[pivot_lows].sort_values()
    high_times = daily.index[pivot_highs].sort_values()

    if len(low_times) == 0 or len(high_times) == 0:
        return []

    impulses = []
    for low_t in low_times:
        next_highs = high_times[high_times > low_t]
        if len(next_highs) == 0:
            continue
        high_t = next_highs[0]

        swing_low = float(daily.loc[low_t, "Low"])
        swing_high = float(daily.loc[high_t, "High"])
        move_size = swing_high - swing_low

        if move_size >= min_atr_multiplier * atr:
            impulses.append(
                {
                    "swing_low": swing_low,
                    "swing_high": swing_high,
                    "low_idx": low_t,
                    "high_idx": high_t,
                    "move_size": move_size,
                }
            )

    return impulses


def rank_impulses(
    impulses: list[dict],
    last_date: pd.Timestamp,
    top_n: int = 2,
) -> list[dict]:
    if not impulses:
        return []

    recency_scores = [1.0 / ((last_date - imp["high_idx"]).days + 1) for imp in impulses]
    max_recency = max(recency_scores)
    norm_recency = [s / max_recency for s in recency_scores]

    sizes = [imp["move_size"] for imp in impulses]
    max_size = max(sizes)
    norm_size = [s / max_size for s in sizes]

    scored = [
        (0.6 * norm_recency[i] + 0.4 * norm_size[i], impulses[i])
        for i in range(len(impulses))
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [imp for _, imp in scored[:top_n]]


def compute_fib_levels(
    impulse: dict,
    atr: float,
    current_price: float,
) -> FibonacciInfo:
    lo = impulse["swing_low"]
    hi = impulse["swing_high"]
    rng = hi - lo

    fib_382 = hi - 0.382 * rng
    fib_500 = hi - 0.500 * rng
    fib_618 = hi - 0.618 * rng
    fib_786 = hi - 0.786 * rng

    zone_low = fib_618 - 0.25 * atr
    zone_high = fib_618 + 0.25 * atr
    is_near = zone_low <= current_price <= zone_high

    return FibonacciInfo(
        swing_low=lo,
        swing_low_date=impulse["low_idx"].strftime("%Y-%m-%d"),
        swing_high=hi,
        swing_high_date=impulse["high_idx"].strftime("%Y-%m-%d"),
        fib_382=round(fib_382, 4),
        fib_500=round(fib_500, 4),
        fib_618=round(fib_618, 4),
        fib_786=round(fib_786, 4),
        zone=(round(zone_low, 4), round(zone_high, 4)),
        is_near=is_near,
    )


def get_best_fib(
    daily: pd.DataFrame,
    atr: float,
    current_price: float,
    pivot_n: int = 5,
) -> FibonacciInfo | None:
    ph = find_pivot_highs(daily, pivot_n)
    pl = find_pivot_lows(daily, pivot_n)
    impulses = build_impulse_moves(daily, ph, pl, atr)
    if not impulses:
        return None
    ranked = rank_impulses(impulses, daily.index[-1], top_n=2)
    if not ranked:
        return None

    fibs = [compute_fib_levels(imp, atr, current_price) for imp in ranked]

    # If price is inside any zone, return the one with closest 61.8% level
    near = [f for f in fibs if f.is_near]
    if near:
        return min(near, key=lambda f: abs(current_price - f.fib_618))

    return fibs[0]


def detect_swing_low_confluence(
    daily: pd.DataFrame,
    atr: float,
    current_price: float,
    vp: VolumeProfile,
    hourly_lows: pd.Series,
    hourly_closes: pd.Series,
    pivot_n: int = 5,
    n_recent: int = 3,
    daily_sweep_lookback: int = 10,
) -> VolumeSupportedSwingLow | None:
    """
    Returns a VolumeSupportedSwingLow when a recent pivot low from a valid
    impulse overlaps with a meaningful volume level (POC / VAL / HVN).
    Returns None when no such confluence exists.
    """
    ph = find_pivot_highs(daily, pivot_n)
    pl = find_pivot_lows(daily, pivot_n)
    impulses = build_impulse_moves(daily, ph, pl, atr)

    if not impulses:
        return None

    # Most-recent swing lows from valid impulse structures
    sorted_impulses = sorted(impulses, key=lambda x: x["low_idx"], reverse=True)
    recent_impulses = sorted_impulses[:n_recent]

    tolerance = 0.25 * atr

    # Find the first (most recent) swing low that overlaps with a volume level
    match: tuple[dict, str, float] | None = None
    for imp in recent_impulses:
        swing_low = imp["swing_low"]
        if abs(swing_low - vp.poc) <= tolerance:
            match = (imp, "POC", vp.poc)
            break
        if abs(swing_low - vp.val) <= tolerance:
            match = (imp, "VAL", vp.val)
            break
        for hvn_level in vp.hvn:
            if abs(swing_low - hvn_level) <= tolerance:
                match = (imp, "HVN", hvn_level)
                break
        if match:
            break

    if match is None:
        return None

    matched_imp, volume_type, volume_level = match
    swing_low = matched_imp["swing_low"]
    swing_low_date = matched_imp["low_idx"].strftime("%Y-%m-%d")
    distance_atr = abs(swing_low - volume_level) / atr if atr > 0 else 0.0

    price_near = abs(current_price - swing_low) <= 0.3 * atr

    # Sweep: hourly candle wicked below swing_low but closed back above
    sweep_hourly = any(
        float(hourly_lows.iloc[i]) < swing_low and float(hourly_closes.iloc[i]) > swing_low
        for i in range(len(hourly_lows))
    )
    # Also check daily bars (higher timeframe confirmation)
    daily_start = max(0, len(daily) - daily_sweep_lookback)
    sweep_daily = any(
        float(daily["Low"].iloc[i]) < swing_low and float(daily["Close"].iloc[i]) > swing_low
        for i in range(daily_start, len(daily))
    )
    sweep_detected = sweep_hourly or sweep_daily

    # Accepted below: price is clearly below swing_low with no reclaim
    accepted_below = (current_price < swing_low - 0.1 * atr) and not sweep_detected

    return VolumeSupportedSwingLow(
        swing_low=round(swing_low, 4),
        swing_low_date=swing_low_date,
        volume_level=round(volume_level, 4),
        volume_type=volume_type,
        distance_atr=round(distance_atr, 4),
        is_valid=True,
        price_near=price_near,
        sweep_detected=sweep_detected,
        accepted_below=accepted_below,
    )
