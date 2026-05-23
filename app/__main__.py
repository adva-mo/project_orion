"""
Usage:
  python -m app scan                          # reads tickers from config.yaml
  python -m app scan LMT RTX NOC             # explicit tickers
  python -m app scan --min-rr 1.5            # override min RR
  python -m app scan --verbose               # show all indicator values
  python -m app scan --json                  # raw JSON output
"""

import argparse
import json
import sys

from app.config import load_config
from app.models import ScanResult
from app.scanner import ScanDetail, scan_tickers
from app.setups import SETUP_BREAKOUT_RETEST


def main() -> None:
    parser = argparse.ArgumentParser(prog="app", description="Project Orion — swing trade scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan", help="Scan tickers for swing trade setups")
    scan_cmd.add_argument("tickers", nargs="*", help="Ticker symbols (default: from config.yaml)")
    scan_cmd.add_argument("--min-rr", type=float, default=None, help="Minimum risk/reward ratio")
    scan_cmd.add_argument("--verbose", "-v", action="store_true", help="Show all indicator values")
    scan_cmd.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    if args.command == "scan":
        cfg = load_config()

        tickers = [t.upper() for t in args.tickers] if args.tickers else [t.upper() for t in cfg.get("tickers", [])]
        min_rr = args.min_rr if args.min_rr is not None else float(cfg.get("min_rr", 2.0))

        if not tickers:
            print("Error: no tickers provided and config.yaml is empty.", file=sys.stderr)
            sys.exit(1)

        print(f"Scanning {len(tickers)} ticker(s): {', '.join(tickers)}  |  min_rr={min_rr}", file=sys.stderr)
        results, errors, details = scan_tickers(tickers, min_rr=min_rr)

        if args.json:
            output = {
                "results": [r.model_dump() for r in results],
                "errors": errors,
            }
            print(json.dumps(output, indent=2))
        elif args.verbose:
            _print_verbose(details, errors)
        else:
            _print_table(results, errors)


def _print_verbose(details: list[ScanDetail], errors: dict[str, str]) -> None:
    for d in details:
        r = d.result
        vp = d.volume_profile
        fib = r.fibonacci
        price = r.current_price
        in_value_area = vp.val < price < vp.vah
        ema_tag = "above EMA (+8)" if price > d.ema_20 else "below EMA (-15)"
        sep = "=" * 60

        print(sep)
        print(f"  {r.ticker}  —  {r.setup_type}  (score: {r.score:.2f})")
        print(sep)

        ma200_tag = f"above MA200 (+10)" if price > d.ma200_weekly else "BELOW MA200 (-25)"
        struct_scores = {"uptrend": "+12", "downtrend": "-20", "ranging": "0"}
        struct_tag = f"{d.market_structure} ({struct_scores.get(d.market_structure, '0')})"
        vp_scenario_tags = {
            "price_up_vol_up": "price↑ vol↑  +8 (bullish confirmation)",
            "price_up_vol_down": "price↑ vol↓  0  (weak upside)",
            "price_down_vol_down": "price↓ vol↓  +8 (fading decline — bottom approaching)",
            "price_down_vol_up": "price↓ vol↑  -10 (strong decline — avoid)",
        }
        vp_tag = vp_scenario_tags.get(d.vp_scenario, d.vp_scenario)
        rs = d.relative_strength
        if rs > 1.3:
            rs_tag = f"{rs:.2f}×  outperforming (+10)"
        elif rs < 0.7:
            rs_tag = f"{rs:.2f}×  underperforming (-8)"
        else:
            rs_tag = f"{rs:.2f}×  in-line (0)"

        print(f"  Price      : {price:.2f}")
        print(f"  ATR (14)   : {d.atr:.2f}")
        print(f"  VWAP (sess): {d.vwap:.2f}  {'↑ price above' if price > d.vwap else '↓ price below'}")
        print(f"  EMA (20)   : {d.ema_20:.2f}  {ema_tag}")
        print(f"  MA200 (wk) : {d.ma200_weekly:.2f}  {ma200_tag}")
        print(f"  Mkt Struct : {struct_tag}")
        print(f"  VP Scenario: {vp_tag}")
        print(f"  Rel Str/SPY: {rs_tag}")
        print()

        in_va_tag = "  ← price inside value area (-20)" if in_value_area else ""
        print(f"  Volume Profile  ({d.vp_from_date} – {d.vp_to_date})")
        print(f"    POC      : {vp.poc:.2f}")
        print(f"    VAH      : {vp.vah:.2f}")
        print(f"    VAL      : {vp.val:.2f}{in_va_tag}")
        print()

        if fib:
            print(f"  Fibonacci  : swing {fib.swing_low:.2f} ({fib.swing_low_date}) → {fib.swing_high:.2f} ({fib.swing_high_date})  (range {fib.swing_high - fib.swing_low:.2f})")
            print(f"    38.2%    : {fib.fib_382:.2f}")
            print(f"    50.0%    : {fib.fib_500:.2f}")
            print(f"    61.8%    : {fib.fib_618:.2f}  ← zone {fib.zone[0]:.2f} – {fib.zone[1]:.2f}  {'✓ PRICE IN ZONE' if fib.is_near else '✗ price outside zone'}")
            print(f"    78.6%    : {fib.fib_786:.2f}")
        else:
            print(f"  Fibonacci  : no valid impulse found")
        print()

        vsl = r.volume_supported_swing_low
        if vsl and vsl.is_valid:
            near_tag = "  ✓ price near" if vsl.price_near else ""
            sweep_tag = "  ✓ sweep detected" if vsl.sweep_detected else ""
            fail_tag = "  ✗ accepted below (-20)" if vsl.accepted_below else ""
            print(f"  Swing Low + Volume Confluence")
            print(f"    Swing low: {vsl.swing_low:.2f} ({vsl.swing_low_date})  ←→  {vsl.volume_type} {vsl.volume_level:.2f}  (dist {vsl.distance_atr:.2f} ATR)")
            print(f"    Flags    :{near_tag}{sweep_tag}{fail_tag}")
            print()

        br = r.breakout_retest
        if br is not None:
            holding_tag = "✓ price holding above retest level" if br.is_holding else "✗ price slipping below retest level"
            print(f"  Breakout + Retest")
            print(f"    Resistance : {br.resistance_level:.2f}  ({br.resistance_date})")
            print(f"    Breakout   : {br.breakout_date}  (vol {br.breakout_volume_ratio:.1f}× avg)")
            print(f"    Holding    : {holding_tag}")
            print()

        if r.setup_type != "No Trade":
            print(f"  Setup")
            print(f"    Buy zone : {r.buy_zone[0]:.2f} – {r.buy_zone[1]:.2f}")
            print(f"    Stop     : {r.stop_loss:.2f}  ({r.buy_zone[0] - r.stop_loss:.2f} risk from zone low)")
            print(f"    Target 1 : {r.target_1:.2f}")
            print(f"    Target 2 : {r.target_2:.2f}")
            print(f"    R/R      : {r.risk_reward:.2f}x")
            print()

        print(f"  Reason: {r.reason}")
        print()

    if errors:
        print("Skipped (data errors):", file=sys.stderr)
        for ticker, msg in errors.items():
            print(f"  {ticker}: {msg}", file=sys.stderr)


def _print_table(results: list[ScanResult], errors: dict[str, str]) -> None:
    col_w = [6, 32, 5, 10, 18, 10, 10, 10, 5]
    header = (
        f"{'TICKER':<{col_w[0]}}  "
        f"{'SETUP':<{col_w[1]}}  "
        f"{'SCR':>{col_w[2]}}  "
        f"{'PRICE':>{col_w[3]}}  "
        f"{'BUY ZONE':^{col_w[4]}}  "
        f"{'STOP':>{col_w[5]}}  "
        f"{'T1':>{col_w[6]}}  "
        f"{'T2':>{col_w[7]}}  "
        f"{'RR':>{col_w[8]}}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for r in results:
        buy_zone_str = f"{r.buy_zone[0]:.2f} – {r.buy_zone[1]:.2f}" if r.setup_type != "No Trade" else "—"
        stop_str = f"{r.stop_loss:.2f}" if r.setup_type != "No Trade" else "—"
        t1_str = f"{r.target_1:.2f}" if r.setup_type != "No Trade" else "—"
        t2_str = f"{r.target_2:.2f}" if r.setup_type != "No Trade" else "—"
        rr_str = f"{r.risk_reward:.1f}x" if r.setup_type != "No Trade" else "—"

        print(
            f"{r.ticker:<{col_w[0]}}  "
            f"{r.setup_type:<{col_w[1]}}  "
            f"{r.score:>{col_w[2]}.2f}  "
            f"{r.current_price:>{col_w[3]}.2f}  "
            f"{buy_zone_str:^{col_w[4]}}  "
            f"{stop_str:>{col_w[5]}}  "
            f"{t1_str:>{col_w[6]}}  "
            f"{t2_str:>{col_w[7]}}  "
            f"{rr_str:>{col_w[8]}}"
        )
        print(f"  → {r.reason}")
        print()

    print(sep)

    if errors:
        print("\nSkipped (data errors):", file=sys.stderr)
        for ticker, msg in errors.items():
            print(f"  {ticker}: {msg}", file=sys.stderr)


if __name__ == "__main__":
    main()
