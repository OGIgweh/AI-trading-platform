import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  LineChart,
  Line,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import {
  AlertTriangle,
  Brain,
  Check,
  ChevronDown,
  Clipboard,
  Copy,
  DollarSign,
  Layers3,
  RefreshCw,
  Search as SearchIcon,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import {
  getPortfolio,
  analyze,
  options,
  history,
  searchStocks,
} from './lib/api';
import './style.css';

const DEFAULT_SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'SPY', 'QQQ'];
const WATCHLIST_STORAGE_KEY = 'ai-trading-platform-symbols';
const ANALYSIS_SETTINGS_STORAGE_KEY = 'ai-trading-platform-analysis-settings';
const DEFAULT_ANALYSIS_SETTINGS = { accountValue: 10000, minConfidence: 75, maxRiskPercent: 1, analysisMode: 'options', optionStructure: 'auto' };

const CHART_PERIODS = ['1mo', '3mo', '6mo', '1y', '5y'];
const VERIFIED_DATA_SOURCES = new Set(['tradier_realtime', 'tradier_delayed', 'yahoo_chart_delayed', 'yfinance_delayed', 'stooq_eod', 'mixed_verified_providers']);
const isVerifiedSource = (source) => VERIFIED_DATA_SOURCES.has(String(source || '').toLowerCase());
const hasVerifiedQuote = (quote) => isVerifiedSource(quote?.data_source) && Number(quote?.price) > 0;
const quoteMoney = (value, quote) => hasVerifiedQuote(quote) && Number(value) > 0 ? money(value) : 'Unavailable';

const money = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { style: 'currency', currency: 'USD' })
    : '—';
};

const formatDate = (value) => {
  if (!value || value === 'Unavailable') return value || 'Unavailable';
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const formatAsOf = (value) => {
  if (!value) return 'Unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  });
};

const compactDate = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

function Card({ title, children, icon, className = '' }) {
  return (
    <div className={`card ${className}`}>
      <div className="cardTitle">{icon}{title}</div>
      {children}
    </div>
  );
}

function Badge({ rec }) {
  const cls = rec === 'NO_TRADE' ? 'badge warn' : 'badge good';
  return <span className={cls}>{rec === 'NO_TRADE' ? 'NO TRADE' : rec}</span>;
}

function RecommendationCard({ r, onSelect }) {
  const order = r.suggested_order;
  const equityOrder = r.suggested_equity_order;
  return (
    <button className="recCard" onClick={() => onSelect(r.symbol)}>
      <div className="recTop">
        <b>{r.symbol}</b>
        <Badge rec={r.recommendation} />
      </div>
      <div className="confidence">
        <span style={{ width: `${r.confidence}%` }} />
      </div>
      <p>
        <strong>{r.confidence}%</strong> confidence · {r.trade_type || 'analysis'} · {r.risk_level}
      </p>
      {order ? (
        <div className="compactOrder">
          <span>{order.strategy}</span>
          <span>{order.leg_count || 1} leg{(order.leg_count || 1) > 1 ? 's' : ''}</span>
          <span>{order.quantity} × {order.underlying_symbol}</span>
          <span>{formatDate(order.expiration)}</span>
          <span>{(order.leg_count || 1) > 1 ? 'Net debit' : 'Limit'} {money(order.limit_price)}</span>
        </div>
      ) : equityOrder ? (
        <div className="compactOrder">
          <span>{equityOrder.strategy}</span>
          <span>{equityOrder.quantity} shares</span>
          <span>{equityOrder.action.replaceAll('_', ' ')}</span>
          <span>Limit {money(equityOrder.limit_price)}</span>
        </div>
      ) : (
        <p>{r.explanation}</p>
      )}
    </button>
  );
}

function EvidenceList({ items = [] }) {
  if (!items.length) return <p>No structured evidence returned by the backend.</p>;
  const groups = items.reduce((acc, item) => {
    const key = item.category || 'Other';
    acc[key] = acc[key] || [];
    acc[key].push(item);
    return acc;
  }, {});

  return (
    <div className="evidenceGrid">
      {Object.entries(groups).map(([category, rows]) => (
        <div className="evidenceGroup" key={category}>
          <h4>{category}</h4>
          {rows.map((evidence, index) => (
            <div
              className={`evidenceItem ${evidence.signal || ''}`}
              key={`${category}-${index}`}
            >
              <div className="evidenceHead">
                <b>{evidence.name}</b>
                <span>{evidence.passed ? 'PASS' : 'CHECK'}</span>
              </div>
              <p>
                <b>Value:</b>{' '}
                {typeof evidence.value === 'object'
                  ? JSON.stringify(evidence.value)
                  : String(evidence.value)}
              </p>
              <p>{evidence.explanation}</p>
              <small>
                Signal: {evidence.signal} · Score: {evidence.score} · Weight: {evidence.weight} · Source: {evidence.data_source}
              </small>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ScoreBreakdown({ score }) {
  if (!score) return null;
  return (
    <div className="scoreGrid">
      <span>Technical <b>{score.technical_score}</b></span>
      <span>Options <b>{score.options_score}</b></span>
      <span>Market <b>{score.market_score}</b></span>
      <span>Risk <b>{score.risk_score}</b></span>
      <span>Final <b>{score.final_confidence}</b></span>
      <span>Threshold <b>{score.threshold}</b></span>
    </div>
  );
}

function fallbackOrder(rec, currentQuote) {
  if (rec?.suggested_order) return rec.suggested_order;
  const contract = rec?.raw_data?.selected_contract;
  if (!contract || !rec?.entry_price || rec?.recommendation === 'NO_TRADE') return null;
  const quantity = rec.position_size || 1;
  const mid = Number(rec.entry_price);
  return {
    strategy: rec.recommendation === 'CALL' ? 'Call' : 'Put',
    underlying_symbol: rec.symbol,
    underlying_price: currentQuote?.price || rec.raw_data?.quote?.price,
    action: 'BUY_TO_OPEN',
    quantity,
    expiration: contract.expiration || 'Unavailable',
    days_to_expiration: contract.days_to_expiration,
    strike: contract.strike,
    option_type: rec.recommendation,
    contract_symbol: contract.symbol,
    bid: contract.bid,
    mid,
    ask: contract.ask,
    order_type: 'LIMIT',
    limit_price: mid,
    timing: 'DAY',
    special_instructions: 'NONE',
    estimated_amount: quantity * mid * 100,
    estimated_max_loss: quantity * mid * 100,
    price_basis: 'Midpoint of current bid/ask',
    review_required: true,
    live_submission_enabled: false,
  };
}

function TicketRow({ label, value, help, copyValue, onCopy, copied }) {
  return (
    <div className="ticketRow">
      <div className="ticketLabel">
        <span>{label}</span>
        {help && <small>{help}</small>}
      </div>
      <div className="ticketValueWrap">
        <strong>{value}</strong>
        {copyValue !== undefined && (
          <button
            className="iconButton subtleButton"
            onClick={() => onCopy(copyValue, label)}
            aria-label={`Copy ${label}`}
            title={`Copy ${label}`}
          >
            {copied === label ? <Check size={16} /> : <Copy size={16} />}
          </button>
        )}
      </div>
    </div>
  );
}

function SuggestedOrderTicket({ rec, currentQuote }) {
  const [copied, setCopied] = useState('');
  const order = useMemo(() => fallbackOrder(rec, currentQuote), [rec, currentQuote]);

  async function copyValue(value, label) {
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(label);
      window.setTimeout(() => setCopied(''), 1600);
    } catch {
      setCopied('');
    }
  }

  const equityOrder = rec?.suggested_equity_order;
  if (equityOrder) {
    const actionDisplay = equityOrder.action.replaceAll('_', ' ');
    const equityTicketText = [
      `Symbol: ${equityOrder.symbol}`,
      `Action: ${actionDisplay}`,
      `Quantity: ${equityOrder.quantity} shares`,
      `Order Type: ${equityOrder.order_type}`,
      `Limit Price: ${money(equityOrder.limit_price)}`,
      `Timing: Day only`,
      `Stop Loss: ${money(equityOrder.stop_loss)}`,
      `Profit Target 1: ${money(equityOrder.profit_targets?.[0])}`,
      `Profit Target 2: ${money(equityOrder.profit_targets?.[1])}`,
    ].join('\n');
    return (
      <section className="orderTicket" aria-label="Suggested stock order ticket">
        <div className="orderTicketTop">
          <div>
            <span className="eyebrow">BROKER ENTRY FORMAT</span>
            <h3>Suggested Stock Order</h3>
            <p>Generated because verified stock data qualified but a verified options chain was unavailable.</p>
          </div>
          <span className="paperOnlyBadge">Review required</span>
        </div>
        <div className="underlyingStrip">
          <div><span>Symbol</span><strong>{equityOrder.symbol}</strong></div>
          <div><span>Strategy</span><strong>{equityOrder.strategy}</strong></div>
          <div><span>Market price</span><strong>{money(currentQuote?.price || equityOrder.limit_price)}</strong></div>
          <div><span>Holding period</span><strong>{rec.expected_holding_period}</strong></div>
        </div>
        <div className="orderSettings">
          <TicketRow label="Action" value={actionDisplay} copyValue={actionDisplay} onCopy={copyValue} copied={copied} />
          <TicketRow label="Quantity" value={`${equityOrder.quantity} shares`} copyValue={equityOrder.quantity} onCopy={copyValue} copied={copied} />
          <TicketRow label="Order Type" value="Limit" />
          <TicketRow label="Limit Price" value={money(equityOrder.limit_price)} help={equityOrder.price_basis} copyValue={Number(equityOrder.limit_price).toFixed(2)} onCopy={copyValue} copied={copied} />
          <TicketRow label="Timing" value="Day only" />
        </div>
        <div className="exitPlan">
          <div><span>Suggested stop</span><strong>{money(equityOrder.stop_loss)}</strong></div>
          <div><span>Profit target 1</span><strong>{money(equityOrder.profit_targets?.[0])}</strong></div>
          <div><span>Profit target 2</span><strong>{money(equityOrder.profit_targets?.[1])}</strong></div>
          <div><span>Planned risk</span><strong>{money(equityOrder.planned_risk)}</strong></div>
        </div>
        <div className="estimatedAmount">
          <div>
            <span>Estimated Amount</span>
            <strong>{money(equityOrder.estimated_amount)}</strong>
            <small>Verify the current quote, buying power, and short availability in your broker before submitting.</small>
          </div>
          <button className="copyTicketButton" onClick={() => copyValue(equityTicketText, 'Full ticket')}>
            {copied === 'Full ticket' ? <Check size={18} /> : <Clipboard size={18} />}
            {copied === 'Full ticket' ? 'Copied' : 'Copy order ticket'}
          </button>
        </div>
        <div className="ticketWarning">
          <ShieldCheck size={20} />
          <p><b>Verify before submitting:</b> this platform does not place orders. End-of-day fallback prices are not intraday executable quotes.</p>
        </div>
      </section>
    );
  }

  if (!order) {
    const blockers = rec?.raw_data?.blocking_failures || rec?.risks || [];
    return (
      <div className="noOrderTicket">
        <AlertTriangle size={22} />
        <div>
          <b>No broker order ticket generated</b>
          <p>The setup did not pass every critical evidence, execution, confidence, and risk gate.</p>
          {blockers.length > 0 && (
            <ul className="blockingReasons">
              {blockers.slice(0, 6).map((reason, index) => <li key={index}>{reason}</li>)}
            </ul>
          )}
        </div>
      </div>
    );
  }

  const legs = order.legs?.length ? order.legs : [{
    action: order.action,
    quantity: order.quantity,
    expiration: order.expiration,
    days_to_expiration: order.days_to_expiration,
    strike: order.strike,
    option_type: order.option_type,
    contract_symbol: order.contract_symbol,
    bid: order.bid,
    mid: order.mid,
    ask: order.ask,
  }];

  const ticketLines = [
    `Underlying: ${order.underlying_symbol}`,
    `Strategy: ${order.strategy}`,
    ...legs.flatMap((leg, index) => [
      `Leg ${index + 1} Action: ${leg.action.replaceAll('_', ' ')}`,
      `Leg ${index + 1} Quantity: ${leg.quantity}`,
      `Leg ${index + 1} Expiration: ${formatDate(leg.expiration)}`,
      `Leg ${index + 1} Strike: ${money(leg.strike)} ${leg.option_type}`,
      `Leg ${index + 1} Contract: ${leg.contract_symbol}`,
    ]),
    `Order Type: ${order.order_type}`,
    `Net Limit Price: ${money(order.limit_price)}`,
    `Timing: ${order.timing === 'DAY' ? 'Day only' : order.timing}`,
    `Estimated Max Loss: ${money(order.estimated_max_loss)}`,
  ];
  const ticketText = ticketLines.join('\n');

  return (
    <section className="orderTicket" aria-label="Suggested options order ticket">
      <div className="orderTicketTop">
        <div>
          <span className="eyebrow">BROKER ENTRY FORMAT</span>
          <h3>Suggested Options Order</h3>
          <p>Use Schwab’s strategy name shown below, then enter each leg in the displayed sequence.</p>
        </div>
        <span className="paperOnlyBadge">Review required</span>
      </div>

      <div className="underlyingStrip">
        <div><span>Underlying</span><strong>{order.underlying_symbol}</strong></div>
        <div><span>Market price</span><strong>{money(order.underlying_price)}</strong></div>
        <div><span>Schwab strategy</span><strong>{order.strategy}</strong></div>
        <div><span>Holding period</span><strong>{rec.expected_holding_period}</strong></div>
      </div>

      {legs.map((leg, index) => {
        const actionDisplay = leg.action.replaceAll('_', ' ');
        return (
          <div className="legPanel" key={`${leg.contract_symbol}-${index}`}>
            <div className="legHeader">
              <div><ChevronDown size={22} /><b>Leg {index + 1}</b></div>
              <span><Layers3 size={15} /> {order.leg_count > 1 ? `${order.leg_count}-leg order` : 'One-leg order'}</span>
            </div>
            <TicketRow label="Action" value={actionDisplay} copyValue={actionDisplay} onCopy={copyValue} copied={copied} />
            <TicketRow label="Quantity" value={leg.quantity} help="Number of option contracts" copyValue={leg.quantity} onCopy={copyValue} copied={copied} />
            <TicketRow
              label="Expiration"
              value={`${formatDate(leg.expiration)}${leg.days_to_expiration != null ? ` · ${leg.days_to_expiration} DTE` : ''}`}
              copyValue={leg.expiration}
              onCopy={copyValue}
              copied={copied}
            />
            <TicketRow label="Strike" value={money(leg.strike)} copyValue={Number(leg.strike).toFixed(2)} onCopy={copyValue} copied={copied} />
            <div className="ticketRow optionTypeRow">
              <div className="ticketLabel"><span>Call / Put</span></div>
              <div className="optionToggle" aria-label={`${leg.option_type} selected`}>
                <span className={leg.option_type === 'CALL' ? 'selected' : ''}>Call</span>
                <span className={leg.option_type === 'PUT' ? 'selected' : ''}>Put</span>
              </div>
            </div>
            <div className="quoteStrip">
              <div><span>Bid</span><b>{money(leg.bid)}</b></div>
              <div><span>Mid</span><b>{money(leg.mid)}</b></div>
              <div><span>Ask</span><b>{money(leg.ask)}</b></div>
            </div>
            <TicketRow label="Contract Symbol" value={leg.contract_symbol} copyValue={leg.contract_symbol} onCopy={copyValue} copied={copied} />
          </div>
        );
      })}

      <div className="orderSettings">
        <TicketRow label="Order Type" value="Limit" />
        <TicketRow
          label={order.leg_count > 1 ? 'Net debit price' : 'Price'}
          value={money(order.limit_price)}
          help={order.price_basis}
          copyValue={Number(order.limit_price).toFixed(2)}
          onCopy={copyValue}
          copied={copied}
        />
        <TicketRow label="Timing" value="Day only" />
        <TicketRow label="Special Instructions" value="None" />
        {order.break_even != null && <TicketRow label="Break-even at expiration" value={money(order.break_even)} />}
      </div>

      <div className="probabilityPanel">
        <div className="probabilityPanelHeader">
          <div>
            <span className="eyebrow">EXPIRATION & PROBABILITY CHECK</span>
            <b>Move required vs. time remaining</b>
          </div>
          <small>Evidence estimates · not a probability of profit</small>
        </div>
        <div className="probabilityGrid">
          <div><span>Out of the money</span><strong>{order.moneyness_percent != null ? `${order.moneyness_percent}%` : '—'}</strong></div>
          <div><span>Move to break-even</span><strong>{order.required_move_percent != null ? `${order.required_move_percent}%` : '—'}</strong></div>
          <div><span>IV expected move</span><strong>{order.expected_move_percent != null ? `${order.expected_move_percent}% (${money(order.expected_move_dollars)})` : '—'}</strong></div>
          <div><span>Break-even / expected move</span><strong>{order.break_even_expected_move_multiple != null ? `${order.break_even_expected_move_multiple}×` : '—'}</strong></div>
          <div><span>Directional delta</span><strong>{order.directional_delta != null ? order.directional_delta : '—'}</strong><small>Not probability of profit</small></div>
          <div><span>Time-decay risk</span><strong>{order.time_decay_risk || '—'}</strong><small>{order.theta_per_day != null ? `Theta ${order.theta_per_day}/day` : 'Exact theta unavailable'}</small></div>
        </div>
        <p className="probabilityNote">
          {order.delta_interpretation || 'Delta measures directional sensitivity; it is not a guaranteed probability.'} {' '}
          {order.theta_interpretation || ''}
        </p>
      </div>

      <div className="exitPlan">
        <div><span>Suggested stop</span><strong>{money(rec.stop_loss)}</strong></div>
        <div><span>Profit target 1</span><strong>{money(rec.profit_targets?.[0])}</strong></div>
        <div><span>Profit target 2</span><strong>{money(rec.profit_targets?.[1])}</strong></div>
        <div><span>Maximum possible loss</span><strong>{money(order.estimated_max_loss)}</strong></div>
        {order.max_profit != null && <div><span>Maximum profit at expiration</span><strong>{money(order.max_profit)}</strong></div>}
      </div>

      <div className="estimatedAmount">
        <div>
          <span>{order.leg_count > 1 ? 'Estimated Net Debit' : 'Estimated Amount'}</span>
          <strong>{money(order.estimated_amount)}</strong>
          <small>Excludes commissions and fees. Verify all legs, prices, and buying-power effects in the broker.</small>
        </div>
        <button className="copyTicketButton" onClick={() => copyValue(ticketText, 'Full ticket')}>
          {copied === 'Full ticket' ? <Check size={18} /> : <Clipboard size={18} />}
          {copied === 'Full ticket' ? 'Copied' : 'Copy order ticket'}
        </button>
      </div>

      <div className="ticketWarning">
        <ShieldCheck size={20} />
        <p><b>Verify before submitting:</b> confirm every leg, expiration, strike, net debit, buying power, and maximum loss directly in Schwab. This platform does not submit orders or guarantee fills.</p>
      </div>
    </section>
  );
}

function App() {
  const [portfolio, setPortfolio] = useState(null);
  const [symbol, setSymbol] = useState('AAPL');
  const [searchTerm, setSearchTerm] = useState('AAPL');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [watchSymbols, setWatchSymbols] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(WATCHLIST_STORAGE_KEY) || '[]');
      return Array.isArray(saved) && saved.length ? saved.slice(0, 20) : DEFAULT_SYMBOLS;
    } catch {
      return DEFAULT_SYMBOLS;
    }
  });
  const [rec, setRec] = useState(null);
  const [currentQuote, setCurrentQuote] = useState(null);
  const [chain, setChain] = useState([]);
  const [chartData, setChartData] = useState(null);
  const [chartPeriod, setChartPeriod] = useState('1y');
  const [chartLoading, setChartLoading] = useState(false);
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [analysisSettings, setAnalysisSettings] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(ANALYSIS_SETTINGS_STORAGE_KEY) || '{}');
      return {
        accountValue: Number(saved.accountValue) > 0 ? Number(saved.accountValue) : DEFAULT_ANALYSIS_SETTINGS.accountValue,
        minConfidence: Number(saved.minConfidence) >= 50 ? Number(saved.minConfidence) : DEFAULT_ANALYSIS_SETTINGS.minConfidence,
        maxRiskPercent: Number(saved.maxRiskPercent) > 0 ? Number(saved.maxRiskPercent) : DEFAULT_ANALYSIS_SETTINGS.maxRiskPercent,
        analysisMode: ['options', 'stock', 'auto'].includes(String(saved.analysisMode || '').toLowerCase())
          ? String(saved.analysisMode).toLowerCase()
          : DEFAULT_ANALYSIS_SETTINGS.analysisMode,
        optionStructure: ['auto', 'single', 'multi'].includes(String(saved.optionStructure || '').toLowerCase())
          ? String(saved.optionStructure).toLowerCase()
          : DEFAULT_ANALYSIS_SETTINGS.optionStructure,
      };
    } catch {
      return DEFAULT_ANALYSIS_SETTINGS;
    }
  });

  useEffect(() => {
    getPortfolio().then(setPortfolio).catch(() => setError('Unable to load portfolio summary.'));
    refreshAll();
  }, []);

  useEffect(() => {
    localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(watchSymbols));
  }, [watchSymbols]);

  useEffect(() => {
    localStorage.setItem(ANALYSIS_SETTINGS_STORAGE_KEY, JSON.stringify(analysisSettings));
  }, [analysisSettings]);

  useEffect(() => {
    const query = searchTerm.trim();
    if (!query) {
      setSearchResults([]);
      setSearching(false);
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const data = await searchStocks(query);
        setSearchResults(data.results || []);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [searchTerm]);

  async function refreshAll() {
    setLoading(true);
    setError('');
    try {
      // Refresh only the selected ticker. Automatically analyzing every saved
      // symbol on page load can trigger free-provider rate limits and make
      // valid tickers appear unavailable.
      await run(searchTerm || symbol || DEFAULT_SYMBOLS[0], false);
    } catch (err) {
      setError(err.message || 'Unable to refresh the current analysis.');
    } finally {
      setLoading(false);
    }
  }

  function rememberSymbol(clean) {
    setWatchSymbols((previous) => [clean, ...previous.filter((item) => item !== clean)].slice(0, 20));
  }

  async function loadHistory(requestedSymbol, period = chartPeriod) {
    if (!requestedSymbol) return;
    setChartLoading(true);
    try {
      const data = await history(requestedSymbol, period);
      setChartData(data);
    } catch (err) {
      setChartData({
        symbol: requestedSymbol,
        period,
        status: 'provider_unavailable',
        points: [],
        summary: {},
        message: err.message,
      });
    } finally {
      setChartLoading(false);
    }
  }

  async function run(requestedSymbol = searchTerm || symbol, manageLoading = true) {
    const clean = String(requestedSymbol || '').toUpperCase().trim();
    if (!clean) return;
    if (manageLoading) setLoading(true);
    setSymbol(clean);
    setSearchTerm(clean);
    setSearchOpen(false);
    setError('');
    try {
      // Analyze first. The analysis response already contains the verified quote,
      // which avoids three simultaneous Yahoo requests for the same ticker.
      const recommendationData = await analyze(clean, 'auto', analysisSettings);
      const quoteData = recommendationData?.raw_data?.quote || null;
      let chainData = [];

      // Always load the latest completed daily bars. This remains useful when
      // the regular market is closed because it shows the last available close.
      await loadHistory(recommendationData.symbol || clean, chartPeriod);

      // Fetch the table after analysis so a temporary options-chain failure does
      // not erase a valid quote or the engine's transparent NO_TRADE decision.
      if (Number(quoteData?.price) > 0 && analysisSettings.analysisMode !== 'stock') {
        try {
          chainData = await options(recommendationData.symbol || clean);
        } catch {
          chainData = [];
        }
      }

      setCurrentQuote(quoteData);
      setChain(chainData);
      setRec(recommendationData);
      if (Number(quoteData?.price) > 0) rememberSymbol(recommendationData.symbol || clean);
      setRecs((previous) => [
        recommendationData,
        ...previous.filter((item) => item.symbol !== recommendationData.symbol),
      ].slice(0, 20));
    } catch (err) {
      setCurrentQuote(null);
      setChain([]);
      setChartData(null);
      setRec(null);
      setError(err.message || `Unable to analyze ${clean}.`);
    } finally {
      if (manageLoading) setLoading(false);
    }
  }

  function chooseSearchResult(result) {
    setSearchTerm(result.symbol);
    setSearchOpen(false);
    run(result.symbol);
  }

  function changeAnalysisMode(nextMode) {
    setAnalysisSettings((previous) => ({ ...previous, analysisMode: nextMode }));
    // Clear mode-dependent results so an options result is never mistaken for
    // a stock/auto result (or vice versa) after the selector changes.
    setRec(null);
    setRecs([]);
    setChain([]);
    setError('');
  }

  function changeOptionStructure(nextStructure) {
    setAnalysisSettings((previous) => ({ ...previous, optionStructure: nextStructure }));
    // Clear the old ticket so a single-leg recommendation cannot remain visible
    // after switching to Multi Leg (or vice versa).
    setRec(null);
    setRecs([]);
    setChain([]);
    setError('');
  }

  async function analyzeSearchTerm() {
    const raw = searchTerm.trim();
    const typed = raw.toUpperCase();
    if (!raw) return;

    let candidates = searchResults;
    if (!candidates.length) {
      try {
        setSearching(true);
        const data = await searchStocks(raw);
        candidates = data.results || [];
        setSearchResults(candidates);
      } catch {
        candidates = [];
      } finally {
        setSearching(false);
      }
    }

    const exact = candidates.find((item) => item.symbol === typed);
    if (exact) {
      chooseSearchResult(exact);
      return;
    }

    // An uppercase/punctuated value is treated as an intentional ticker even
    // when autocomplete returns a different company. Lowercase company-name
    // searches continue to select the best provider result.
    const tickerShape = /^[A-Z0-9^][A-Z0-9.^=\/-]{0,23}$/;
    const explicitTicker = tickerShape.test(typed)
      && (raw === raw.toUpperCase() || /[.^=\/-]/.test(raw));
    if (explicitTicker) {
      run(typed);
      return;
    }

    if (candidates.length) {
      chooseSearchResult(candidates[0]);
      return;
    }
    run(typed);
  }

  return (
    <main>
      <header>
        <div>
          <h1>AI Trading Platform</h1>
          <p>Evidence-based trading assistant · paper decision support · live trading locked</p>
        </div>
        <span className={`pill ${(portfolio?.market_status || 'CLOSED').toLowerCase()}`}>
          {portfolio?.market_status || 'CLOSED'}
        </span>
      </header>

      {error && <div className="errorBanner"><AlertTriangle size={18} />{error}</div>}

      <section className="grid metrics">
        <Card title="Portfolio Value" icon={<TrendingUp />}>
          <b>{money(portfolio?.total_value)}</b>
          <span>Daily P/L {money(portfolio?.daily_pl || 0)}</span>
        </Card>
        <Card title="Buying Power" icon={<ShieldCheck />}>
          <b>{money(portfolio?.buying_power)}</b>
          <span>Open positions {portfolio?.open_positions || 0}</span>
        </Card>
        <Card title="AI Confidence" icon={<Brain />}>
          <b>{rec ? `${rec.confidence}%` : '—'}</b>
          <span>{rec ? `${rec.symbol} · ${rec.recommendation === 'NO_TRADE' ? 'No trade' : rec.recommendation}` : 'Run an analysis'}</span>
          <small className="confidenceClarifier">Evidence alignment · not probability of profit</small>
        </Card>
        <Card title="Risk Mode" icon={<AlertTriangle />}>
          <b>Capital First</b>
          <span>NO TRADE unless verified evidence aligns</span>
        </Card>
      </section>

      <section className="grid two primaryGrid">
        <Card title={`${chartData?.symbol || symbol} Price Chart`} className="priceChartCard">
          <div className="chartHeader">
            <div>
              <strong>{Number(chartData?.summary?.last_price) > 0 ? money(chartData.summary.last_price) : quoteMoney(currentQuote?.price, currentQuote)}</strong>
              {Number(chartData?.summary?.last_price) > 0 ? (
                <span className={(chartData?.summary?.period_change || 0) >= 0 ? 'positive' : 'negative'}>
                  {(chartData?.summary?.period_change || 0) >= 0 ? '+' : ''}
                  {money(chartData?.summary?.period_change || 0)}
                  {' '}({chartData?.summary?.period_change_percent ?? 0}%)
                </span>
              ) : <span className="dataUnavailableText">Verified price unavailable</span>}
            </div>
            <span className={`marketState ${(currentQuote?.market_status || portfolio?.market_status || 'CLOSED').toLowerCase()}`}>
              {currentQuote?.market_status || portfolio?.market_status || 'CLOSED'}
            </span>
          </div>

          {(currentQuote?.market_status || portfolio?.market_status) !== 'OPEN' && (
            <div className="marketClosedNotice">
              Market closed · showing the latest available completed price data
              {chartData?.as_of ? ` as of ${formatAsOf(chartData.as_of)}` : ''}.
            </div>
          )}

          <div className="chartPeriods" aria-label="Chart time range">
            {CHART_PERIODS.map((period) => (
              <button
                key={period}
                className={chartPeriod === period ? 'active' : ''}
                disabled={chartLoading || !symbol}
                onClick={() => {
                  setChartPeriod(period);
                  loadHistory(symbol, period);
                }}
              >
                {period === '1mo' ? '1 Mo' : period === '3mo' ? '3 Mo' : period === '6mo' ? '6 Mo' : period === '1y' ? '1 Yr' : '5 Yrs'}
              </button>
            ))}
          </div>

          {chartLoading && <p className="chartStatus">Loading price history…</p>}
          {!chartLoading && chartData?.points?.length > 0 && (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData.points}>
                <XAxis dataKey="date" tickFormatter={compactDate} minTickGap={30} />
                <YAxis domain={['auto', 'auto']} width={58} tickFormatter={(value) => `$${Number(value).toFixed(0)}`} />
                <Tooltip
                  labelFormatter={(value) => formatAsOf(value)}
                  formatter={(value) => [money(value), 'Close']}
                />
                <Line type="monotone" dataKey="close" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
          {!chartLoading && !chartData?.points?.length && (
            <p className="chartStatus">Price history is currently unavailable. The recommendation remains NO TRADE until verified history is restored.</p>
          )}

          <div className="rangeGrid">
            <div><span>Period low</span><b>{money(chartData?.summary?.period_low)}</b></div>
            <div><span>Period high</span><b>{money(chartData?.summary?.period_high)}</b></div>
            <div><span>52-week low</span><b>{money(chartData?.summary?.fifty_two_week_low || currentQuote?.fifty_two_week_low)}</b></div>
            <div><span>52-week high</span><b>{money(chartData?.summary?.fifty_two_week_high || currentQuote?.fifty_two_week_high)}</b></div>
          </div>
        </Card>

        <Card title="AI Trading Assistant" className="assistantCard">
          <div className="symbolSearchArea">
            <div className="search">
              <div className="searchInputWrap">
                <SearchIcon size={18} aria-hidden="true" />
                <input
                  value={searchTerm}
                  onChange={(event) => {
                    setSearchTerm(event.target.value);
                    setSearchResults([]);
                    setSearchOpen(true);
                  }}
                  onFocus={() => setSearchOpen(true)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      analyzeSearchTerm();
                    }
                    if (event.key === 'Escape') setSearchOpen(false);
                  }}
                  placeholder="Search ticker or company name"
                  aria-label="Search any stock or ETF by ticker or company name"
                  aria-autocomplete="list"
                  aria-expanded={searchOpen}
                />
                {searching && <RefreshCw size={16} className="spin searchSpinner" aria-label="Searching" />}
              </div>
              <button onClick={analyzeSearchTerm} disabled={loading || !searchTerm.trim()}>Analyze</button>
              <button
                className="iconButton"
                onClick={refreshAll}
                title="Refresh current analysis"
                disabled={loading}
              >
                <RefreshCw size={16} className={loading ? 'spin' : ''} />
              </button>
            </div>

            {searchOpen && searchTerm.trim() && (
              <div className="searchResults" role="listbox" aria-label="Stock search results">
                {searching && !searchResults.length && <div className="searchStatus">Searching market symbols…</div>}
                {!searching && !searchResults.length && (
                  <div className="searchStatus">Autocomplete found no company match. Exact ticker entry still works and will be verified independently.</div>
                )}
                {searchResults.map((result) => (
                  <button
                    type="button"
                    className="searchResult"
                    key={`${result.symbol}-${result.exchange}`}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => chooseSearchResult(result)}
                    role="option"
                  >
                    <span className="searchSymbol">{result.symbol}</span>
                    <span className="searchCompany">{result.name}</span>
                    <span className="searchMeta">{result.exchange} · {result.quote_type}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="symbolChips" aria-label="Recently analyzed symbols">
            <span>Saved:</span>
            {watchSymbols.slice(0, 10).map((item) => (
              <button key={item} onClick={() => run(item)} className={item === symbol ? 'active' : ''}>
                {item}
              </button>
            ))}
          </div>
          <p className="searchHelp">Search by ticker (such as TSLA or BRK-B) or by company name. Valid symbols are analyzed with the same technical, options, market-context, and risk rules.</p>

          <div className="assetModeSection" aria-label="Recommendation type selector">
            <div className="assetModeHeader">
              <div>
                <span className="controlLabel">Recommendation type</span>
                <p>Choose whether the engine may recommend options, shares, or either.</p>
              </div>
              <strong>{analysisSettings.analysisMode.toUpperCase()}</strong>
            </div>
            <div className="assetModeSelector" role="radiogroup" aria-label="Options, Stock, or Auto">
              {[
                { value: 'options', label: 'Options', description: 'Options-only. No stock substitute.' },
                { value: 'stock', label: 'Stock', description: 'Shares-only. No options chain used.' },
                { value: 'auto', label: 'Auto', description: 'Prefer options; use stock only if options data is unavailable.' },
              ].map((mode) => (
                <button
                  key={mode.value}
                  type="button"
                  role="radio"
                  aria-checked={analysisSettings.analysisMode === mode.value}
                  className={analysisSettings.analysisMode === mode.value ? 'active' : ''}
                  onClick={() => changeAnalysisMode(mode.value)}
                >
                  <b>{mode.label}</b>
                  <small>{mode.description}</small>
                </button>
              ))}
            </div>
            <p className="assetModeNotice">
              {analysisSettings.analysisMode === 'options'
                ? 'Options mode is strict: if a verified option chain is unavailable, the result is NO TRADE—not a stock buy or short.'
                : analysisSettings.analysisMode === 'stock'
                  ? 'Stock mode analyzes shares only and will not generate Call, Put, Vertical Call, or Vertical Put tickets.'
                  : 'Auto mode evaluates options first and may produce a defined-risk stock setup only when verified options data is unavailable.'}
            </p>
          </div>

          {analysisSettings.analysisMode !== 'stock' && (
            <div className="assetModeSection optionStructureSection" aria-label="Option structure selector">
              <div className="assetModeHeader">
                <div>
                  <span className="controlLabel">Option trade structure</span>
                  <p>Choose whether options suggestions must be one leg, multiple legs, or whichever structure best fits the verified setup and risk budget.</p>
                </div>
                <strong>{analysisSettings.optionStructure === 'auto' ? 'BEST FIT' : analysisSettings.optionStructure === 'single' ? 'SINGLE LEG' : 'MULTI LEG'}</strong>
              </div>
              <div className="assetModeSelector" role="radiogroup" aria-label="Single Leg, Multi Leg, or Best Fit">
                {[
                  { value: 'single', label: 'Single Leg', description: 'Call or Put only. No spread substitution.' },
                  { value: 'multi', label: 'Multi Leg', description: 'Defined-risk Vertical Call or Vertical Put only.' },
                  { value: 'auto', label: 'Best Fit', description: 'Use a single leg when it fits; otherwise consider a vertical spread.' },
                ].map((structure) => (
                  <button
                    key={structure.value}
                    type="button"
                    role="radio"
                    aria-checked={analysisSettings.optionStructure === structure.value}
                    className={analysisSettings.optionStructure === structure.value ? 'active' : ''}
                    onClick={() => changeOptionStructure(structure.value)}
                  >
                    <b>{structure.label}</b>
                    <small>{structure.description}</small>
                  </button>
                ))}
              </div>
              <p className="assetModeNotice">
                {analysisSettings.optionStructure === 'single'
                  ? 'Single Leg is strict: the engine may recommend only Schwab Call or Put. If the contract cannot satisfy risk and execution rules, the result is NO TRADE.'
                  : analysisSettings.optionStructure === 'multi'
                    ? 'Multi Leg is strict: the current engine may recommend only Schwab Vertical Call or Vertical Put. It will not substitute a single-leg Call/Put.'
                    : 'Best Fit allows the engine to choose between a single Call/Put and a defined-risk Vertical Call/Put based on evidence, liquidity, and your configured risk budget.'}
              </p>
            </div>
          )}

          <div className="analysisControls" aria-label="Analysis and risk controls">
            <label>
              <span>Account value</span>
              <input
                type="number"
                min="1000"
                step="1000"
                value={analysisSettings.accountValue}
                onChange={(event) => setAnalysisSettings((previous) => ({
                  ...previous,
                  accountValue: Math.max(1000, Number(event.target.value) || 1000),
                }))}
              />
            </label>
            <label>
              <span>Risk per trade</span>
              <select
                value={analysisSettings.maxRiskPercent}
                onChange={(event) => setAnalysisSettings((previous) => ({
                  ...previous,
                  maxRiskPercent: Number(event.target.value),
                }))}
              >
                <option value="0.5">0.5%</option>
                <option value="1">1%</option>
                <option value="1.5">1.5%</option>
                <option value="2">2%</option>
                <option value="3">3%</option>
              </select>
            </label>
            <label>
              <span>Minimum confidence</span>
              <select
                value={analysisSettings.minConfidence}
                onChange={(event) => setAnalysisSettings((previous) => ({
                  ...previous,
                  minConfidence: Number(event.target.value),
                }))}
              >
                <option value="65">65%</option>
                <option value="70">70%</option>
                <option value="75">75%</option>
                <option value="80">80%</option>
                <option value="85">85%</option>
              </select>
            </label>
            <div className="riskBudgetSummary">
              <span>Configured risk budget</span>
              <strong>{money(analysisSettings.accountValue * analysisSettings.maxRiskPercent / 100)}</strong>
              <small>Used for position sizing. Enter values that reflect your real account and limits.</small>
            </div>
          </div>

          {currentQuote && (
            <div className="quoteSummary detailedQuote">
              <div className="quotePrimary">
                <div>
                  <strong>{currentQuote.symbol}</strong>
                  <span className="lastPrice">{quoteMoney(currentQuote.price, currentQuote)}</span>
                </div>
                {hasVerifiedQuote(currentQuote) ? (
                  <span className={currentQuote.change >= 0 ? 'positive' : 'negative'}>
                    {currentQuote.change >= 0 ? '+' : ''}{money(currentQuote.change)} ({currentQuote.change_percent}%)
                  </span>
                ) : <span className="dataUnavailableText">Provider temporarily unavailable</span>}
              </div>
              <div className="quoteFacts">
                <span><small>Status</small><b>{currentQuote.market_status}</b></span>
                <span><small>As of</small><b>{formatAsOf(currentQuote.as_of || chartData?.as_of)}</b></span>
                <span><small>Previous close</small><b>{hasVerifiedQuote(currentQuote) ? money(currentQuote.previous_close) : 'Unavailable'}</b></span>
                <span><small>Day range</small><b>{hasVerifiedQuote(currentQuote) ? `${money(currentQuote.day_low)} – ${money(currentQuote.day_high)}` : 'Unavailable'}</b></span>
                <span><small>Volume</small><b>{hasVerifiedQuote(currentQuote) ? currentQuote.volume?.toLocaleString() : 'Unavailable'}</b></span>
                <span><small>Data source</small><b>{currentQuote.data_source}</b></span>
              </div>
              {currentQuote.data_source === 'stooq_eod' ? (
                <p className="lastAvailableMessage">
                  Independent fallback active: this is the latest completed daily price, not a live intraday quote. Verify the current broker quote before entry.
                </p>
              ) : currentQuote.market_status !== 'OPEN' && (
                <p className="lastAvailableMessage">
                  The regular market is closed. Price, change, volume, ranges, and chart use the latest available completed market data.
                </p>
              )}
            </div>
          )}

          {rec && (
            <div className={rec.recommendation === 'NO_TRADE' ? 'noTrade' : 'trade'}>
              <div className="recommendationHeader">
                <div>
                  <span className="eyebrow">AI DECISION</span>
                  <h2>
                    {rec.recommendation === 'NO_TRADE'
                      ? 'NO TRADE RECOMMENDED'
                      : `${rec.recommendation} SETUP`}
                  </h2>
                </div>
                <div className="confidenceBadge">
                  <strong>{rec.confidence}%</strong>
                  <small>Evidence alignment</small>
                  <small>Threshold {rec.threshold}% · not win probability</small>
                </div>
              </div>

              <p>{rec.explanation}</p>
              <div className="analysisHealth" aria-label="Analysis data status">
                <span className="verified">Mode: {(rec.raw_data?.analysis_settings?.asset_mode || analysisSettings.analysisMode).toUpperCase()}</span>
                <span className={isVerifiedSource(rec.raw_data?.technical?.data_source) ? 'verified' : 'unavailable'}>
                  Technical data: {rec.raw_data?.technical?.data_source || 'unavailable'}
                </span>
                <span>History: {rec.raw_data?.technical?.history_bars ?? 0} daily bars</span>
                <span>Period: {rec.raw_data?.technical?.history_period || '—'}</span>
                <span>Options contracts: {rec.raw_data?.options_contract_count ?? 0}</span>
                <span>Quote source: {currentQuote?.data_source || rec.raw_data?.quote?.data_source || 'unavailable'}</span>
              </div>
              <SuggestedOrderTicket rec={rec} currentQuote={currentQuote} />

              {rec.risks?.length > 0 && (
                <details className="analysisDetails">
                  <summary>Risks and cautions</summary>
                  <ul>{rec.risks.map((risk, index) => <li key={index}>{risk}</li>)}</ul>
                </details>
              )}

              <details className="analysisDetails">
                <summary>Confidence score breakdown</summary>
                <ScoreBreakdown score={rec.score_breakdown} />
              </details>

              <details className="analysisDetails">
                <summary>Supporting evidence</summary>
                <EvidenceList items={rec.evidence} />
              </details>

              <details className="analysisDetails">
                <summary>Raw data used</summary>
                <pre>{JSON.stringify(rec.raw_data, null, 2)}</pre>
              </details>
            </div>
          )}
        </Card>
      </section>

      <section className="grid two">
        <Card title="Saved & Recent AI Recommendations">
          <div className="recList">
            {loading && <p>Loading recommendations...</p>}
            {recs.map((recommendation) => (
              <RecommendationCard
                key={recommendation.symbol}
                r={recommendation}
                onSelect={run}
              />
            ))}
          </div>
        </Card>

        <Card title={analysisSettings.analysisMode === 'stock' ? 'Options Chain (not used in Stock mode)' : 'Options Chain'}>
          <div className="tableScroll">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Expiration</th>
                  <th>Strike</th>
                  <th>Bid</th>
                  <th>Ask</th>
                  <th>Vol</th>
                  <th>OI</th>
                  <th>IV</th>
                  <th>Δ</th>
                </tr>
              </thead>
              <tbody>
                {!chain.length && (
                  <tr><td colSpan="9">{analysisSettings.analysisMode === 'options'
                    ? 'No verified option chain is available. Options mode remains options-only and returns NO TRADE.'
                    : analysisSettings.analysisMode === 'stock'
                      ? 'Stock mode is selected, so the option chain is not requested or used.'
                      : 'No verified option chain is available. Auto mode may evaluate a stock setup from verified price data.'}</td></tr>
                )}
                {chain.map((contract) => (
                  <tr key={contract.symbol}>
                    <td>{contract.contract_type}</td>
                    <td>{formatDate(contract.expiration)}</td>
                    <td>{contract.strike}</td>
                    <td>{contract.bid}</td>
                    <td>{contract.ask}</td>
                    <td>{contract.volume}</td>
                    <td>{contract.open_interest}</td>
                    <td>{Math.round(contract.implied_volatility * 100)}%</td>
                    <td>{contract.delta}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </section>

      <section className="grid two">
        <Card title="Risk Center">
          <p>Portfolio risk score: <b>Medium</b></p>
          <p>Max risk per trade: <b>1%</b></p>
          <p>Live execution: <b>Disabled</b></p>
          <p>Market data: <b>Tradier when configured; independent completed-daily fallback otherwise</b></p>
          <p>Emergency stop: <b>Ready</b></p>
        </Card>
        <Card title="Implementation Notice" icon={<DollarSign />}>
          <p>
            Options mode produces only options tickets and returns NO TRADE when a verified chain is unavailable. The Option Trade Structure selector can force Single Leg (Call/Put), Multi Leg (currently Vertical Call/Vertical Put), or Best Fit. Stock mode produces only share orders. The platform never invents contracts or places an order with Charles Schwab.
          </p>
        </Card>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
