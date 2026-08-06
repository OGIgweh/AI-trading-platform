# Analysis Mode Selector

The `/api/ai/analyze` request accepts `asset_mode`: `options`, `stock`, or `auto`.

- `options` is strict options-only mode. If no verified chain is available, the engine returns `NO_TRADE` and never creates a stock order.
- `stock` evaluates shares only and does not request an option chain.
- `auto` evaluates options first and permits the defined-risk stock fallback only when the option chain is unavailable.

The direction field remains `strategy` and defaults to `auto`; it may still accept explicit call/put direction requests.
