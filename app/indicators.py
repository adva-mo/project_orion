import numpy as np
import pandas as pd

from app.models import VolumeProfile


def compute_atr(daily: pd.DataFrame, period: int = 14) -> float:
    if len(daily) < period + 1:
        raise ValueError(f"Need at least {period + 1} daily rows for ATR, got {len(daily)}")
    tr = _true_range(daily)
    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()
    return float(atr_series.iloc[-1])


def _true_range(daily: pd.DataFrame) -> pd.Series:
    prev_close = daily["Close"].shift(1)
    tr = pd.concat(
        [
            daily["High"] - daily["Low"],
            (daily["High"] - prev_close).abs(),
            (daily["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.dropna()


def compute_vwap(hourly: pd.DataFrame) -> float:
    """True session VWAP — resets at the start of each trading day."""
    tp = (hourly["High"] + hourly["Low"] + hourly["Close"]) / 3
    dates = hourly.index.normalize()
    last_date = dates[-1]
    mask = dates == last_date

    today_tp = tp[mask]
    today_vol = hourly["Volume"][mask]

    cum_vol = today_vol.cumsum()
    if cum_vol.iloc[-1] == 0:
        return float(hourly["Close"].iloc[-1])

    return float((today_tp * today_vol).cumsum().iloc[-1] / cum_vol.iloc[-1])


def compute_ema(daily: pd.DataFrame, period: int = 20) -> float:
    if len(daily) < period:
        raise ValueError(f"Need at least {period} daily rows for EMA, got {len(daily)}")
    return float(daily["Close"].ewm(span=period, adjust=False).mean().iloc[-1])


def compute_volume_profile(hourly: pd.DataFrame, n_buckets: int = 50) -> VolumeProfile:
    lo = hourly["Close"].min()
    hi = hourly["Close"].max()

    if hi == lo:
        mid = float((hi + lo) / 2)
        return VolumeProfile(poc=mid, vah=mid, val=mid)

    counts, edges = np.histogram(hourly["Close"], bins=n_buckets, weights=hourly["Volume"])
    bin_mids = (edges[:-1] + edges[1:]) / 2

    poc_idx = int(np.argmax(counts))
    poc = float(bin_mids[poc_idx])

    total_volume = counts.sum()
    if total_volume == 0:
        mid = float((hi + lo) / 2)
        return VolumeProfile(poc=mid, vah=mid, val=mid)

    sorted_idx = np.argsort(counts)[::-1]
    accumulated = 0.0
    selected = []
    for idx in sorted_idx:
        accumulated += counts[idx]
        selected.append(idx)
        if accumulated >= 0.70 * total_volume:
            break

    vah = float(edges[max(selected) + 1])
    val = float(edges[min(selected)])

    # High-volume nodes: bins with vol > 60% of POC, excluding POC itself, top 3
    poc_vol = counts[poc_idx]
    hvn_indices = [
        i for i in range(len(counts))
        if i != poc_idx and counts[i] >= 0.60 * poc_vol
    ]
    hvn_indices.sort(key=lambda i: counts[i], reverse=True)
    hvn = [float(bin_mids[i]) for i in hvn_indices[:3]]

    return VolumeProfile(poc=poc, vah=vah, val=val, hvn=hvn)


def classify_volume_price_scenario(daily: pd.DataFrame, n_bars: int = 5) -> str:
    """CIIDB 4-scenario classifier based on last n_bars vs prior n_bars."""
    if len(daily) < n_bars * 2:
        return "price_down_vol_up"  # neutral/conservative default
    recent = daily.iloc[-n_bars:]
    prior = daily.iloc[-(n_bars * 2):-n_bars]
    price_up = float(recent["Close"].iloc[-1]) > float(recent["Close"].iloc[0])
    vol_up = float(recent["Volume"].mean()) > float(prior["Volume"].mean())
    if price_up and vol_up:
        return "price_up_vol_up"
    if price_up and not vol_up:
        return "price_up_vol_down"
    if not price_up and not vol_up:
        return "price_down_vol_down"
    return "price_down_vol_up"


def compute_market_structure(daily: pd.DataFrame, n_pivots: int = 5) -> str:
    """Returns 'uptrend', 'downtrend', or 'ranging' based on recent daily pivot sequence."""
    from app.fibonacci import find_pivot_highs, find_pivot_lows

    ph = find_pivot_highs(daily, n_pivots)
    pl = find_pivot_lows(daily, n_pivots)

    high_vals = daily["High"][ph].values
    low_vals = daily["Low"][pl].values

    if len(high_vals) < 2 or len(low_vals) < 2:
        return "ranging"

    hh = high_vals[-1] > high_vals[-2]
    hl = low_vals[-1] > low_vals[-2]
    lh = high_vals[-1] < high_vals[-2]
    ll = low_vals[-1] < low_vals[-2]

    if hh and hl:
        return "uptrend"
    if lh and ll:
        return "downtrend"
    return "ranging"


def compute_relative_strength(
    ticker_daily: pd.DataFrame,
    spy_returns: "pd.Series",
    n_days: int = 20,
) -> float:
    """Returns ticker 20-day return / SPY 20-day return. >1.0 = outperforming."""
    if len(ticker_daily) < n_days or len(spy_returns) == 0:
        return 1.0
    ticker_ret = float(ticker_daily["Close"].iloc[-1] / ticker_daily["Close"].iloc[-n_days] - 1)
    common = spy_returns.index.intersection(ticker_daily.index[-n_days:])
    if len(common) == 0:
        return 1.0
    spy_ret = float((1 + spy_returns.loc[common]).prod() - 1)
    if spy_ret == 0:
        return 1.0
    return ticker_ret / spy_ret


def compute_ma200_weekly(weekly: pd.DataFrame) -> float:
    if len(weekly) < 200:
        raise ValueError(f"Need at least 200 weekly rows for MA200, got {len(weekly)}")
    return float(weekly["Close"].rolling(200).mean().iloc[-1])


def filter_hvn(vp: VolumeProfile, atr: float) -> VolumeProfile:
    """Remove HVN entries within 0.2 × ATR of POC (they are not distinct nodes)."""
    filtered = [h for h in vp.hvn if abs(h - vp.poc) > 0.2 * atr]
    return VolumeProfile(poc=vp.poc, vah=vp.vah, val=vp.val, hvn=filtered)
