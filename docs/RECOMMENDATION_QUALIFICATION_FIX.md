# Recommendation Qualification Fix

## Problem corrected

The prior engine used a hard-coded $10,000 account and 1% risk limit, then sized long options against the entire premium. That created a $100 maximum premium budget. Most liquid directional options cost more than $1.00 per contract, so position size became zero and every otherwise-valid setup was blocked.

The confidence formula also assigned 25% of the score to this zero-position result, which pushed many technically valid setups into the low 60s.

## Changes

- Single long options are sized by planned stop loss while also enforcing a separate premium-exposure cap.
- The full premium remains displayed as the absolute maximum loss.
- If a single long option does not fit the configured risk budget, the engine attempts a defined-risk bull-call or bear-put debit spread.
- Debit spreads are sized by their true maximum loss, the net debit.
- Preferred option volume, open interest, and spread thresholds now reduce confidence when missed; only critically illiquid contracts are hard failures.
- Broad-market scoring is directional. Bullish context no longer increases confidence for a put, and bearish context no longer increases confidence for a call.
- User-facing controls now allow account value, maximum risk percentage, and minimum confidence to be configured.
- Blocking reasons are displayed directly when a trade does not qualify.
- The summary AI confidence card now displays the current ticker's analysis rather than a hard-coded placeholder.

## Safety behavior

A recommendation still requires verified quote, history, options, market context, confidence, and position sizing. The engine returns NO_TRADE when critical evidence is missing, confidence is below the configured threshold, or neither a single option nor a defined-risk spread fits the risk budget.
