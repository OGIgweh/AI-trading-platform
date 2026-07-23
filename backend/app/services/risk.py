from __future__ import annotations


def bid_ask_spread_pct(bid: float, ask: float) -> float:
    if ask <= 0 or bid <= 0:
        return 100.0
    mid = (ask + bid) / 2
    return round(((ask - bid) / mid) * 100, 2)


def planned_loss_per_contract(
    premium: float,
    stop_loss_fraction: float = 0.25,
) -> float:
    """Estimated loss per long-option contract at the planned stop.

    A long option can still lose 100% of its premium. This value is used only
    for *planned* position sizing and is always shown separately from the
    absolute maximum loss.
    """

    if premium <= 0:
        return 0.0
    fraction = min(max(float(stop_loss_fraction), 0.05), 1.0)
    return premium * 100 * fraction


def position_contracts(
    account_value: float,
    premium: float,
    max_risk_pct: float = 1.0,
    *,
    stop_loss_fraction: float = 0.25,
    max_premium_exposure_pct: float = 10.0,
    max_contracts: int = 10,
) -> int:
    """Size long options using both planned-stop risk and premium exposure.

    The previous implementation sized against the full premium while also
    using a 25% premium stop. On a $10,000 default account that made almost
    every liquid option unaffordable and forced NO_TRADE for nearly every
    ticker. This function keeps capital-preservation constraints but avoids
    that universal false-negative:

    * planned-stop loss must fit the configured risk budget;
    * total premium paid must remain below an explicit exposure cap;
    * the absolute maximum loss remains the full premium and is shown in UI.
    """

    if account_value <= 0 or premium <= 0 or max_risk_pct <= 0:
        return 0

    risk_budget = account_value * (max_risk_pct / 100)
    planned_loss = planned_loss_per_contract(premium, stop_loss_fraction)
    premium_cost = premium * 100
    premium_cap = account_value * (max_premium_exposure_pct / 100)

    if planned_loss <= 0 or premium_cost <= 0:
        return 0

    by_planned_risk = int(risk_budget // planned_loss)
    by_premium_exposure = int(premium_cap // premium_cost)
    return max(0, min(by_planned_risk, by_premium_exposure, max_contracts))


def spread_contracts(
    account_value: float,
    net_debit: float,
    max_risk_pct: float = 1.0,
    *,
    max_contracts: int = 10,
) -> int:
    """Size a debit spread by its true maximum loss (the net debit)."""

    if account_value <= 0 or net_debit <= 0 or max_risk_pct <= 0:
        return 0
    risk_budget = account_value * (max_risk_pct / 100)
    max_loss_per_spread = net_debit * 100
    return max(0, min(int(risk_budget // max_loss_per_spread), max_contracts))
