# Broker-Entry Options Ticket

The AI Trading Assistant translates a qualified one-leg long CALL or PUT recommendation into fields that map to a standard Charles Schwab options order ticket:

- Action: Buy to Open
- Quantity
- Expiration and DTE
- Strike
- Call or Put
- Bid, midpoint, and ask
- Order type: Limit
- Suggested limit price
- Timing: Day only
- Special instructions: None
- Contract symbol
- Estimated amount and modeled maximum premium risk
- Stop and profit targets as a separate exit plan

The ticket provides copy buttons for individual values and the complete ticket. It does not connect to Schwab or submit an order. The user must confirm all values against the live brokerage ticket before submitting.

The backend returns this structure in `Recommendation.suggested_order`. When the engine returns `NO_TRADE`, `suggested_order` is null and the UI explicitly states that no broker ticket was generated.
