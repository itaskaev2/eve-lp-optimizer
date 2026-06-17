"""Turn raw LP store offers + Jita prices into a ranked profit table.

For each offer we compute:

    proceeds  = (Jita value of the rewarded item) minus selling fees
    cost      = isk_cost  +  Jita cost of any required input items
    profit    = proceeds - cost
    isk/LP    = profit / lp_cost            <-- the metric we rank by

Selling strategies:
    * "sell"  -> you list a sell order in Jita. Value = sell-side price,
                 reduced by both sales tax and broker fee.
    * "buy"   -> you dump to the highest buy order. Value = buy-side price,
                 reduced by sales tax only (no broker fee).

Required input items are always valued at the cheapest Jita sell order (what
you would actually pay to buy them); buying from a sell order incurs no fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeeSettings:
    # Defaults assume a well-skilled trader (Accounting V, Broker Relations V).
    sales_tax_pct: float = 3.37     # base 7.5%, -11%/level Accounting
    broker_fee_pct: float = 1.5     # base 3.0%, -0.3%/level Broker Relations
    output_strategy: str = "sell"   # "sell" (list order) or "buy" (instant dump)
    price_field: str = "percentile"  # Fuzzwork field used for valuation


@dataclass
class RequiredItem:
    type_id: int
    name: str
    quantity: int
    unit_cost: float
    total_cost: float
    priced: bool


@dataclass
class OfferResult:
    offer_id: int
    type_id: int
    item_name: str
    quantity: int
    lp_cost: int
    isk_cost: float
    ak_cost: int
    required_items: list[RequiredItem] = field(default_factory=list)
    required_cost: float = 0.0
    unit_price: float = 0.0
    gross_value: float = 0.0   # before fees
    net_value: float = 0.0     # after fees
    total_cost: float = 0.0    # isk_cost + required_cost
    profit: float = 0.0
    isk_per_lp: float = 0.0
    priced: bool = False
    max_runs: int = 0          # how many times you can run it with available LP
    total_profit: float = 0.0  # profit * max_runs
    # reward item order-book depth at the chosen hub (liquidity sanity check)
    out_sell_orders: int = 0
    out_sell_volume: float = 0.0
    out_buy_orders: int = 0
    out_buy_volume: float = 0.0

    def depth_orders(self, strategy: str) -> int:
        """Order count on the side the reward is valued at."""
        return self.out_sell_orders if strategy == "sell" else self.out_buy_orders

    def depth_volume(self, strategy: str) -> float:
        """Units listed on the side the reward is valued at."""
        return self.out_sell_volume if strategy == "sell" else self.out_buy_volume


def _price(prices: dict, type_id: int, side: str, fieldname: str):
    entry = prices.get(int(type_id))
    if not entry:
        return None
    value = entry.get(side, {}).get(fieldname, 0.0)
    return value if value and value > 0 else None


def _output_unit_price(prices, type_id, strategy, preferred):
    """Price one unit of the rewarded item, with sensible fallbacks."""
    side = "sell" if strategy == "sell" else "buy"
    extreme = "min" if side == "sell" else "max"
    for fieldname in (preferred, "percentile", "weightedAverage", "median", extreme):
        value = _price(prices, type_id, side, fieldname)
        if value:
            return value
    return None


def _buy_unit_cost(prices, type_id, preferred):
    """Cost to acquire one unit (cheapest available Jita sell order)."""
    for fieldname in ("min", preferred, "percentile", "weightedAverage", "median"):
        value = _price(prices, type_id, "sell", fieldname)
        if value:
            return value
    return None


def evaluate_offer(offer: dict, prices: dict, names: dict, fees: FeeSettings,
                   available_lp: int | None = None) -> OfferResult:
    tax = fees.sales_tax_pct / 100.0
    broker = fees.broker_fee_pct / 100.0
    proceeds_mult = (1.0 - tax - broker) if fees.output_strategy == "sell" else (1.0 - tax)

    type_id = int(offer["type_id"])
    quantity = int(offer.get("quantity", 1) or 1)
    lp_cost = int(offer.get("lp_cost", 0) or 0)
    isk_cost = float(offer.get("isk_cost", 0) or 0)
    ak_cost = int(offer.get("ak_cost", 0) or 0)

    result = OfferResult(
        offer_id=int(offer.get("offer_id", 0)),
        type_id=type_id,
        item_name=names.get(type_id, f"type#{type_id}"),
        quantity=quantity,
        lp_cost=lp_cost,
        isk_cost=isk_cost,
        ak_cost=ak_cost,
    )

    unit_price = _output_unit_price(prices, type_id, fees.output_strategy, fees.price_field)
    output_priced = unit_price is not None
    result.unit_price = unit_price or 0.0

    # capture reward-item market depth (order-book units + order counts)
    entry = prices.get(type_id) or {}
    sell, buy = entry.get("sell", {}) or {}, entry.get("buy", {}) or {}
    result.out_sell_orders = int(sell.get("orderCount", 0) or 0)
    result.out_sell_volume = float(sell.get("volume", 0.0) or 0.0)
    result.out_buy_orders = int(buy.get("orderCount", 0) or 0)
    result.out_buy_volume = float(buy.get("volume", 0.0) or 0.0)

    required_priced = True
    for raw in offer.get("required_items", []) or []:
        rtid = int(raw["type_id"])
        rqty = int(raw["quantity"])
        unit_cost = _buy_unit_cost(prices, rtid, fees.price_field)
        if unit_cost is None:
            required_priced = False
            total = 0.0
        else:
            total = unit_cost * rqty
        result.required_cost += total
        result.required_items.append(
            RequiredItem(
                type_id=rtid,
                name=names.get(rtid, f"type#{rtid}"),
                quantity=rqty,
                unit_cost=unit_cost or 0.0,
                total_cost=total,
                priced=unit_cost is not None,
            )
        )

    result.gross_value = result.unit_price * quantity
    result.net_value = result.gross_value * proceeds_mult
    result.total_cost = isk_cost + result.required_cost
    result.profit = result.net_value - result.total_cost
    result.priced = output_priced and required_priced
    result.isk_per_lp = (result.profit / lp_cost) if lp_cost else 0.0

    if available_lp is not None and lp_cost:
        result.max_runs = int(available_lp // lp_cost)
        result.total_profit = result.max_runs * result.profit

    return result


def evaluate_offers(offers, prices, names, fees: FeeSettings,
                    available_lp: int | None = None) -> list[OfferResult]:
    return [evaluate_offer(o, prices, names, fees, available_lp) for o in offers]


def rank(results: list[OfferResult], include_unpriced: bool = False) -> list[OfferResult]:
    """Sort by ISK/LP (highest first). Unpriced offers are dropped by default."""
    usable = [r for r in results if r.lp_cost > 0 and (include_unpriced or r.priced)]
    return sorted(usable, key=lambda r: r.isk_per_lp, reverse=True)
