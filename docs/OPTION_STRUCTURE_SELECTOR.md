# Option Trade Structure Selector

The AI Trading Assistant now separates **asset mode** from **option structure**.

## Recommendation type
- **Options**: options-only; never substitutes stock.
- **Stock**: shares-only.
- **Auto**: options first, stock fallback only when verified options data is unavailable.

## Option trade structure
This control is shown whenever Recommendation Type is Options or Auto.

- **Single Leg**: strict. Only Charles Schwab **Call** or **Put** suggestions may qualify. A Vertical Call/Put is never substituted.
- **Multi Leg**: strict. The current engine supports qualified two-leg Charles Schwab **Vertical Call** and **Vertical Put** debit spreads. A single Call/Put is never substituted.
- **Best Fit**: the engine prefers a qualifying single leg when it fits the configured risk budget and otherwise may choose a defined-risk vertical spread.

The engine returns **NO TRADE** if the requested structure cannot satisfy verified-data, liquidity, confidence, and risk gates.

Multi Leg does not claim support for calendar, diagonal, butterfly, condor, iron condor, ratio, or other structures until dedicated selection, pricing, risk, and leg-validation logic is implemented.
