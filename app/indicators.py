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


def filter_hvn(vp: VolumeProfile, atr: float) -> VolumeProfile:
    """Remove HVN entries within 0.2 × ATR of POC (they are not distinct nodes)."""
    filtered = [h for h in vp.hvn if abs(h - vp.poc) > 0.2 * atr]
    return VolumeProfile(poc=vp.poc, vah=vp.vah, val=vp.val, hvn=filtered)
