import logging
import warnings
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DAILY_PERIOD = "6mo"
HOURLY_PERIOD = "30d"
MIN_DAILY_ROWS = 60
MIN_HOURLY_ROWS = 100


@dataclass
class TickerData:
    ticker: str
    daily: pd.DataFrame
    hourly: pd.DataFrame


def fetch_ticker(ticker: str) -> TickerData:
    daily = _fetch_frame(ticker, "1d", DAILY_PERIOD)
    daily = _validate_frame(daily, ticker, "1d", MIN_DAILY_ROWS)

    hourly = _fetch_frame(ticker, "1h", HOURLY_PERIOD)
    hourly = _validate_frame(hourly, ticker, "1h", MIN_HOURLY_ROWS)

    return TickerData(ticker=ticker, daily=daily, hourly=hourly)


def _fetch_frame(ticker: str, interval: str, period: str) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        raise ValueError(f"{ticker}: no data returned for interval={interval}")

    df = df.rename(columns=str.title)
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")

    df = df.dropna(subset=["Close"])

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    return df


def _validate_frame(df: pd.DataFrame, ticker: str, interval: str, min_rows: int) -> pd.DataFrame:
    if len(df) < min_rows:
        raise ValueError(
            f"{ticker}: only {len(df)} rows for interval={interval}, need at least {min_rows}"
        )
    return df
