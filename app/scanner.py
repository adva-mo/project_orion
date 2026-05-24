import logging
from dataclasses import dataclass

from app.data import fetch_spy_returns, fetch_ticker
from app.fibonacci import detect_swing_low_confluence, get_best_fib
from app.indicators import (
    classify_volume_price_scenario,
    compute_atr,
    compute_ema,
    compute_ma200_weekly,
    compute_market_structure,
    compute_relative_strength,
    compute_volume_profile,
    compute_vwap,
    filter_hvn,
)
from app.models import ScanResult, VolumeProfile
from app.setups import detect_setup

logger = logging.getLogger(__name__)


@dataclass
class ScanDetail:
    result: ScanResult
    atr: float
    vwap: float
    ema_20: float
    volume_profile: VolumeProfile
    vp_from_date: str
    vp_to_date: str
    ma200_weekly: float
    market_structure: str
    vp_scenario: str
    relative_strength: float


def scan_ticker(ticker: str, min_rr: float = 2.0) -> ScanResult:
    return scan_ticker_detail(ticker, min_rr).result


def scan_ticker_detail(
    ticker: str,
    min_rr: float = 2.0,
    spy_returns: "pd.Series | None" = None,
) -> ScanDetail:
    import pandas as pd

    data = fetch_ticker(ticker)

    current_price = float(data.daily["Close"].iloc[-1])
    atr = compute_atr(data.daily)
    vwap = compute_vwap(data.hourly)
    ema_20 = compute_ema(data.daily)
    ma200_weekly = compute_ma200_weekly(data.weekly)
    price_above_ma200 = current_price > ma200_weekly
    market_structure = compute_market_structure(data.daily)
    vp_scenario = classify_volume_price_scenario(data.daily)
    vp = filter_hvn(compute_volume_profile(data.hourly), atr)
    fib_info = get_best_fib(data.daily, atr, current_price)

    if spy_returns is None:
        try:
            spy_returns = fetch_spy_returns()
        except Exception:
            spy_returns = pd.Series(dtype=float)
    relative_strength = compute_relative_strength(data.daily, spy_returns)

    hourly_closes = data.hourly["Close"].iloc[-5:]
    hourly_lows = data.hourly["Low"].iloc[-5:]
    hourly_volume = data.hourly["Volume"].iloc[-5:]

    vsl = detect_swing_low_confluence(
        daily=data.daily,
        atr=atr,
        current_price=current_price,
        vp=vp,
        hourly_lows=hourly_lows,
        hourly_closes=hourly_closes,
    )

    result = detect_setup(
        ticker=ticker,
        current_price=current_price,
        atr=atr,
        vwap=vwap,
        volume_profile=vp,
        fib_info=fib_info,
        hourly_closes=hourly_closes,
        hourly_lows=hourly_lows,
        hourly_volume=hourly_volume,
        ema_20=ema_20,
        vsl=vsl,
        min_rr=min_rr,
        price_above_ma200=price_above_ma200,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
        daily=data.daily,
    )
    vp_from_date = data.hourly.index[0].strftime("%Y-%m-%d")
    vp_to_date = data.hourly.index[-1].strftime("%Y-%m-%d")
    return ScanDetail(
        result=result,
        atr=atr,
        vwap=vwap,
        ema_20=ema_20,
        volume_profile=vp,
        vp_from_date=vp_from_date,
        vp_to_date=vp_to_date,
        ma200_weekly=ma200_weekly,
        market_structure=market_structure,
        vp_scenario=vp_scenario,
        relative_strength=relative_strength,
    )


def scan_tickers(
    tickers: list[str],
    min_rr: float = 2.0,
    verbose: bool = False,
) -> tuple[list[ScanResult], dict[str, str], list[ScanDetail]]:
    import pandas as pd

    results: list[ScanResult] = []
    details: list[ScanDetail] = []
    errors: dict[str, str] = {}

    try:
        spy_returns: pd.Series = fetch_spy_returns()
    except Exception:
        spy_returns = pd.Series(dtype=float)

    for ticker in tickers:
        try:
            detail = scan_ticker_detail(ticker, min_rr, spy_returns=spy_returns)
            results.append(detail.result)
            details.append(detail)
            logger.info("Scanned %s -> %s", ticker, detail.result.setup_type)
        except Exception as e:
            logger.warning("Skipping %s: %s", ticker, e)
            errors[ticker] = str(e)

    return results, errors, details
