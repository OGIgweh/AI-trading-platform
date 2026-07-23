const API = import.meta.env.VITE_API_URL || 'https://ai-trading-platform-vdm6.onrender.com/api';

async function request(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) {
    let message = `API error ${res.status}`;
    try {
      const payload = await res.json();
      message = payload.detail || payload.message || message;
    } catch {
      // Keep status fallback for non-JSON responses.
    }
    throw new Error(message);
  }
  return res.json();
}

const DEFAULT_ANALYSIS_SETTINGS = {
  accountValue: 10000,
  minConfidence: 75,
  maxRiskPercent: 1,
};

function normalizeSettings(settings = {}) {
  return {
    accountValue: Number(settings.accountValue) > 0
      ? Number(settings.accountValue)
      : DEFAULT_ANALYSIS_SETTINGS.accountValue,
    minConfidence: Number(settings.minConfidence) >= 1
      ? Number(settings.minConfidence)
      : DEFAULT_ANALYSIS_SETTINGS.minConfidence,
    maxRiskPercent: Number(settings.maxRiskPercent) > 0
      ? Number(settings.maxRiskPercent)
      : DEFAULT_ANALYSIS_SETTINGS.maxRiskPercent,
  };
}

export function getPortfolio() { return request('/portfolio/summary'); }
export function searchStocks(query, limit = 8) { return request(`/market/search?q=${encodeURIComponent(query)}&limit=${limit}`); }
export function quote(symbol) { return request(`/market/quote/${encodeURIComponent(symbol)}`); }
export function options(symbol) { return request(`/market/options/${encodeURIComponent(symbol)}`); }
export function history(symbol, period = '1y') {
  return request(`/market/history/${encodeURIComponent(symbol)}?period=${encodeURIComponent(period)}`);
}

export function analyze(symbol, strategy = 'auto', settings = DEFAULT_ANALYSIS_SETTINGS) {
  const normalized = normalizeSettings(settings);
  return request('/ai/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      symbol,
      account_value: normalized.accountValue,
      strategy,
      min_confidence: normalized.minConfidence,
      max_risk_percent: normalized.maxRiskPercent,
    }),
  });
}

export function recommendations(symbols = ['AAPL', 'MSFT', 'NVDA', 'SPY', 'QQQ'], settings = DEFAULT_ANALYSIS_SETTINGS) {
  const normalized = normalizeSettings(settings);
  return request('/ai/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      symbols,
      account_value: normalized.accountValue,
      min_confidence: normalized.minConfidence,
      max_risk_percent: normalized.maxRiskPercent,
      include_no_trade: true,
    }),
  });
}
