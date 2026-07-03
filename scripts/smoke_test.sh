#!/usr/bin/env bash
set -e
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/market/quote/AAPL
curl -s -X POST http://localhost:8000/api/ai/analyze -H 'Content-Type: application/json' -d '{"symbol":"AAPL","strategy":"long_call","account_value":10000}'
