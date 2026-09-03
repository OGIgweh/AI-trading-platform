# Probability-Sensitive Option Qualification

This update prevents a high technical/options evidence score from automatically becoming a short-dated, far-out-of-the-money option recommendation.

The engine now evaluates the selected long option's moneyness, days to expiration, directional delta, IV-implied expected move, expiration break-even distance, and time-decay exposure before a trade may qualify.

Key safety gates:
- Short-dated (21 DTE or less) contracts more than 4% out of the money are blocked.
- Break-even requirements greater than 1.35x the IV-implied expected move are blocked.
- Short-dated single-leg contracts with absolute directional delta below 0.30 are blocked.
- Warnings apply before those hard limits.
- Confidence is explicitly an evidence-alignment score, not a probability of profit.
- Short-dated or low-delta contracts cannot receive an extreme confidence label.

The order ticket now displays:
- Out-of-the-money percentage
- Move required to break even at expiration
- IV-implied expected move in dollars and percent
- Break-even / expected-move multiple
- Directional delta with a non-probability disclaimer
- Provider theta when available
- Time-decay risk based on DTE when exact theta is unavailable

The expected move is an estimate based on underlying price, implied volatility, and square-root-of-time. It is not a guaranteed trading range.
