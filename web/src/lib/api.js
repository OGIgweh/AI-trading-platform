const API = import.meta.env.VITE_API_URL || 'https://ai-trading-platform-vdm6.onrender.com/api';

async function request(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export function getPortfolio() { return request('/portfolio/summary'); }
export function quote(symbol) { return request(`/market/quote/${encodeURIComponent(symbol)}`); }
export function options(symbol) { return request(`/market/options/${encodeURIComponent(symbol)}`); }
export function analyze(symbol, strategy = 'long_call') {
  return request('/ai/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, account_value: 10000, strategy, min_confidence: 75, max_risk_percent: 1 })
  });
}
export function recommendations(symbols = ['AAPL','MSFT','NVDA','SPY','QQQ']) {
  return request('/ai/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols, account_value: 10000, min_confidence: 75, max_risk_percent: 1, include_no_trade: true })
  });
}
