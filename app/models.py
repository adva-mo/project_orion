from pydantic import BaseModel, Field


class FibonacciInfo(BaseModel):
    swing_low: float
    swing_low_date: str       # YYYY-MM-DD
    swing_high: float
    swing_high_date: str      # YYYY-MM-DD
    fib_382: float
    fib_500: float
    fib_618: float
    fib_786: float
    zone: tuple[float, float]
    is_near: bool


class VolumeProfile(BaseModel):
    poc: float
    vah: float
    val: float
    hvn: list[float] = []  # high-volume nodes (bin midpoints with vol > 60% of POC)


class VolumeSupportedSwingLow(BaseModel):
    swing_low: float
    swing_low_date: str       # YYYY-MM-DD
    volume_level: float
    volume_type: str          # "POC" | "VAL" | "HVN"
    distance_atr: float       # abs(swing_low - volume_level) / ATR
    is_valid: bool
    price_near: bool          # current price within 0.3 ATR of swing_low
    sweep_detected: bool      # candle wicked below swing_low, closed back above
    accepted_below: bool      # price broke below and stayed below


class BreakoutRetestInfo(BaseModel):
    resistance_level: float
    resistance_date: str          # YYYY-MM-DD
    breakout_date: str            # YYYY-MM-DD
    breakout_volume_ratio: float  # breakout candle vol / 20-day avg vol
    is_holding: bool              # price >= resistance_level - 0.5 * ATR


class ScanResult(BaseModel):
    ticker: str
    setup_type: str
    score: float = Field(ge=0.0, le=1.0)
    current_price: float
    buy_zone: tuple[float, float]
    stop_loss: float
    target_1: float
    target_2: float
    risk_reward: float
    reason: str
    fibonacci: FibonacciInfo | None = None
    volume_supported_swing_low: VolumeSupportedSwingLow | None = None
    breakout_retest: BreakoutRetestInfo | None = None


class ScanRequest(BaseModel):
    tickers: list[str] = Field(min_length=1)
    min_rr: float = Field(default=2.0, gt=0)


class ScanResponse(BaseModel):
    results: list[ScanResult]
    errors: dict[str, str] = {}
