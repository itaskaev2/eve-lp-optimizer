"""Command line interface for the EVE LP -> ISK optimizer."""

from __future__ import annotations

import argparse
import csv
import os
import sys

from .esi import EsiClient, EsiError, DEFAULT_USER_AGENT
from .market import JitaMarket, JITA_STATION_ID, TRADE_HUBS, MarketError
from .optimizer import FeeSettings, evaluate_offers, rank


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------
def fmt_isk(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1e9:
        return f"{value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"{value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"{value / 1e3:.1f}k"
    return f"{value:.0f}"


def render_table(headers, rows, aligns=None) -> str:
    aligns = aligns or ["l"] * len(headers)
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def line(cells):
        out = []
        for i, cell in enumerate(cells):
            text = str(cell)
            out.append(text.rjust(widths[i]) if aligns[i] == "r" else text.ljust(widths[i]))
        return "  ".join(out).rstrip()

    parts = [line(headers), line(["-" * w for w in widths])]
    parts.extend(line(r) for r in rows)
    return "\n".join(parts)


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def parse_corp_arg(value: str):
    """Parse ``NAME[:LP]`` or ``ID[:LP]``. Returns (name_or_id, lp_or_None)."""
    if ":" in value:
        head, tail = value.rsplit(":", 1)
        cleaned = tail.strip().replace(",", "").replace("_", "")
        if cleaned.isdigit():
            return head.strip(), int(cleaned)
    return value.strip(), None


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eve-lp-optimizer",
        description="Rank EVE Online LP store offers by ISK profit per Loyalty "
                    "Point, valuing the rewards at Jita market prices.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--corp", "-c", action="append", required=True, metavar="NAME[:LP]",
        help='Corporation to evaluate, e.g. "Caldari Navy:169675" or an id '
             '"1000035:169675". Repeat for multiple corps.',
    )
    parser.add_argument("--top", "-n", type=int, default=20,
                        help="How many offers to show per corporation.")
    parser.add_argument("--strategy", choices=["sell", "buy"], default="sell",
                        help='"sell" = list a Jita sell order; "buy" = dump to buy orders.')
    parser.add_argument("--price-field", default="percentile",
                        choices=["percentile", "weightedAverage", "median", "min", "max"],
                        help="Fuzzwork price field used for valuation.")
    parser.add_argument("--sales-tax", type=float, default=3.37,
                        help="Sales tax %% (Accounting V ~= 3.37).")
    parser.add_argument("--broker-fee", type=float, default=1.5,
                        help="Broker fee %% for sell orders (Broker Relations V ~= 1.5).")
    parser.add_argument("--min-isk-per-lp", type=float, default=None,
                        help="Only show offers at or above this ISK/LP.")
    parser.add_argument("--include-unpriced", action="store_true",
                        help="Also include offers with no/illiquid Jita market data.")
    parser.add_argument("--hub", choices=[h.lower() for h in TRADE_HUBS], default="jita",
                        help="Trade hub to value rewards at.")
    parser.add_argument("--station", type=int, default=None,
                        help="Raw market station id (overrides --hub).")
    parser.add_argument("--csv", metavar="PATH", default=None,
                        help="Also write the full ranked results to a CSV file.")
    parser.add_argument("--datasource", default="tranquility",
                        help="ESI datasource (tranquility / singularity).")
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("EVE_LP_USER_AGENT", DEFAULT_USER_AGENT),
        help="HTTP User-Agent. CCP asks that this identify you (set an email).",
    )
    return parser


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    # Item names can contain non-ASCII characters; emit UTF-8 regardless of the
    # host console's default code page (notably on Windows).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    fees = FeeSettings(
        sales_tax_pct=args.sales_tax,
        broker_fee_pct=args.broker_fee,
        output_strategy=args.strategy,
        price_field=args.price_field,
    )

    # Resolve which market to value at: explicit --station wins, else the --hub.
    hub_by_lower = {h.lower(): (h, sid) for h, sid in TRADE_HUBS.items()}
    if args.station is not None:
        station = args.station
        hub_label = f"station {station}"
    else:
        hub_name, station = hub_by_lower[args.hub]
        hub_label = hub_name

    esi = EsiClient(user_agent=args.user_agent, datasource=args.datasource)
    market = JitaMarket(station_id=station, user_agent=args.user_agent)

    # 1. Resolve corps and fetch their offers.
    corps = []  # list of dicts: {id, name, lp, offers}
    type_ids: set[int] = set()
    for raw in args.corp:
        name_or_id, lp = parse_corp_arg(raw)
        try:
            corp_id, corp_name = esi.resolve_corporation(name_or_id)
            offers = esi.loyalty_offers(corp_id)
        except EsiError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        for offer in offers:
            type_ids.add(int(offer["type_id"]))
            for req in offer.get("required_items", []) or []:
                type_ids.add(int(req["type_id"]))
        corps.append({"id": corp_id, "name": corp_name, "lp": lp, "offers": offers})
        lp_text = f"{lp:,} LP" if lp is not None else "LP not specified"
        print(f"Loaded {len(offers)} offers for {corp_name} (id {corp_id}) - {lp_text}")

    # 2. One batch of name + price lookups for everything.
    print(f"Resolving {len(type_ids)} item names and {hub_label} prices...")
    try:
        names = esi.names_for_ids(type_ids)
    except EsiError as exc:
        print(f"error resolving names: {exc}", file=sys.stderr)
        return 2
    try:
        prices = market.prices(type_ids)
    except MarketError as exc:
        print(f"error fetching market prices: {exc}", file=sys.stderr)
        return 2

    strat_label = "list sell order" if args.strategy == "sell" else "instant sell to buy orders"
    print(
        f"\nValuation: {strat_label} @ {hub_label}, "
        f"price={args.price_field}, sales tax {args.sales_tax}%, "
        f"broker {args.broker_fee}%\n"
    )

    all_rows_for_csv = []

    # 3. Evaluate and print per corporation.
    for corp in corps:
        results = evaluate_offers(corp["offers"], prices, names, fees, corp["lp"])
        ranked = rank(results, include_unpriced=args.include_unpriced)
        if args.min_isk_per_lp is not None:
            ranked = [r for r in ranked if r.isk_per_lp >= args.min_isk_per_lp]

        header_lp = f"{corp['lp']:,} LP available" if corp["lp"] is not None else "LP not set"
        bar = "=" * 78
        print(bar)
        print(f" {corp['name']} - {header_lp}")
        print(bar)

        if not ranked:
            print(" No priced offers matched your filters.\n")
            continue

        show_runs = corp["lp"] is not None
        headers = ["#", "Item", "LP cost", "ISK/LP", "Mkt units", "Profit/run", "Cost/run"]
        aligns = ["r", "l", "r", "r", "r", "r", "r"]
        if show_runs:
            headers += ["Max runs", "Total profit"]
            aligns += ["r", "r"]

        rows = []
        for i, r in enumerate(ranked[: args.top], start=1):
            label = f"{r.quantity}x {r.item_name}" if r.quantity > 1 else r.item_name
            if r.required_items:
                label += " (+items)"
            if not r.priced:
                label += " [unpriced]"
            row = [
                i,
                truncate(label, 46),
                f"{r.lp_cost:,}",
                f"{r.isk_per_lp:,.0f}",
                fmt_isk(r.depth_volume(args.strategy)),
                fmt_isk(r.profit),
                fmt_isk(r.total_cost),
            ]
            if show_runs:
                row += [f"{r.max_runs:,}", fmt_isk(r.total_profit)]
            rows.append(row)

        print(render_table(headers, rows, aligns))

        best = ranked[0]
        if show_runs and best.max_runs > 0:
            print(
                f"\n Best play: {best.max_runs:,}x \"{truncate(best.item_name, 40)}\" "
                f"using all {corp['lp']:,} LP -> ~{fmt_isk(best.total_profit)} ISK profit "
                f"(needs ~{fmt_isk(best.max_runs * best.total_cost)} ISK upfront)."
            )
        print()

        for r in ranked:  # full results for CSV (not just top N)
            all_rows_for_csv.append((corp["name"], r))

    # 4. Optional CSV export.
    if args.csv:
        _write_csv(args.csv, all_rows_for_csv)
        print(f"Wrote {len(all_rows_for_csv)} rows to {args.csv}")

    print(
        "Note: prices are Fuzzwork order-book aggregates and move constantly. "
        "'Mkt units' is the current order-book depth on the valuation side - a "
        "tiny number means the headline ISK/LP is likely a thin-market mirage "
        "you can't actually sell into. Sanity-check before committing LP."
    )
    return 0


def _write_csv(path: str, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "corporation", "offer_id", "item", "quantity", "lp_cost", "isk_cost",
            "required_cost", "total_cost", "net_value", "profit", "isk_per_lp",
            "priced", "max_runs", "total_profit",
            "sell_orders", "sell_volume", "buy_orders", "buy_volume",
        ])
        for corp_name, r in rows:
            writer.writerow([
                corp_name, r.offer_id, r.item_name, r.quantity, r.lp_cost,
                f"{r.isk_cost:.2f}", f"{r.required_cost:.2f}", f"{r.total_cost:.2f}",
                f"{r.net_value:.2f}", f"{r.profit:.2f}", f"{r.isk_per_lp:.2f}",
                r.priced, r.max_runs, f"{r.total_profit:.2f}",
                r.out_sell_orders, f"{r.out_sell_volume:.0f}",
                r.out_buy_orders, f"{r.out_buy_volume:.0f}",
            ])


if __name__ == "__main__":
    raise SystemExit(main())
