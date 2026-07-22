# Indicator History Fix

The previous build requested `period="9mo"` from yfinance. That value is not a supported provider period, so quote retrieval could succeed while historical OHLCV retrieval failed for every ticker. The recommendation engine then had no usable EMA/RSI/MACD/VWAP/ATR/Bollinger evidence and returned a generic 0% `NO_TRADE`.

This build uses the supported `1y` period, validates future period values, reports the number of historical bars used, and distinguishes a true mixed-indicator `NO_TRADE` from missing historical data.
