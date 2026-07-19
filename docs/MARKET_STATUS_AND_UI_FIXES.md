# Market Status and UI Feedback Fixes

## Market status fix

The app no longer uses a UTC approximation or hard-coded `CLOSED` value for portfolio status.

The backend now uses `app/services/market_clock.py` to calculate NYSE regular-session status in `America/New_York`.

Priority order:
1. `pandas_market_calendars` NYSE schedule when installed.
2. Fallback ET-based regular session logic with weekend, holiday, and early-close handling.

New endpoint:

```text
GET /api/market/status
```

Example response:

```json
{
  "status": "OPEN",
  "reason": "NYSE regular session open until 4:00 PM EDT.",
  "timezone": "America/New_York",
  "session": "NYSE regular session"
}
```

## UI hover/click feedback

The web dashboard now applies hover, active/click, focus-visible, disabled, and pointer states to clickable controls.

Updated elements include:
- Analyze button
- Refresh button
- Recommendation cards
- Details/summary expanders
- Links
- Any future button elements

## Deployment note

After pushing this version, redeploy:

- Backend: Clear build cache & deploy latest commit
- Web: Deploy latest commit
