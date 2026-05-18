import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"tickers": [], "min_rr": 2.0}
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}
