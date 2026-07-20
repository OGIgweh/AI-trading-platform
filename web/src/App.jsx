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
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import {
  getPortfolio,
  analyze,
  quote,
  options,
  recommendations,
} from './lib/api';
import './style.css';

const perf = [
  { d: 'Mon', v: 10000 },
  { d: 'Tue', v: 10080 },
  { d: 'Wed', v: 9940 },
  { d: 'Thu', v: 10110 },
  { d: 'Fri', v: 10126 },
];

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
          <span>{order.action.replaceAll('_', ' ')}</span>
          <span>{order.quantity} × {order.underlying_symbol}</span>
          <span>{formatDate(order.expiration)}</span>
          <span>{money(order.strike)} {order.option_type}</span>
          <span>Limit {money(order.limit_price)}</span>
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
    strategy: rec.recommendation === 'CALL' ? 'Long Call' : 'Long Put',
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

  if (!order) {
    return (
      <div className="noOrderTicket">
        <AlertTriangle size={22} />
        <div>
          <b>No broker order ticket generated</b>
          <p>
            The engine only creates entry fields after all evidence, liquidity, market-context,
            confidence, and risk rules qualify. Do not enter an options order from this analysis.
          </p>
        </div>
      </div>
    );
  }

  const actionDisplay = order.action.replaceAll('_', ' ');
  const ticketText = [
    `Underlying: ${order.underlying_symbol}`,
    `Action: ${actionDisplay}`,
    `Quantity: ${order.quantity}`,
    `Expiration: ${formatDate(order.expiration)}`,
    `Strike: ${money(order.strike)}`,
    `Call / Put: ${order.option_type}`,
    `Order Type: ${order.order_type}`,
    `Limit Price: ${money(order.limit_price)}`,
    `Timing: ${order.timing === 'DAY' ? 'Day only' : order.timing}`,
    `Special Instructions: ${order.special_instructions}`,
    `Contract: ${order.contract_symbol}`,
  ].join('\n');

  return (
    <section className="orderTicket" aria-label="Suggested options order ticket">
      <div className="orderTicketTop">
        <div>
          <span className="eyebrow">BROKER ENTRY FORMAT</span>
          <h3>Suggested Options Order</h3>
          <p>Fields are arranged to match a standard Charles Schwab options ticket.</p>
        </div>
        <span className="paperOnlyBadge">Review required</span>
      </div>

      <div className="underlyingStrip">
        <div>
          <span>Underlying</span>
          <strong>{order.underlying_symbol}</strong>
        </div>
        <div>
          <span>Market price</span>
          <strong>{money(order.underlying_price)}</strong>
        </div>
        <div>
          <span>Strategy</span>
          <strong>{order.strategy}</strong>
        </div>
        <div>
          <span>Holding period</span>
          <strong>{rec.expected_holding_period}</strong>
        </div>
      </div>

      <div className="legPanel">
        <div className="legHeader">
          <div><ChevronDown size={22} /><b>Leg 1</b></div>
          <span><Layers3 size={15} /> One-leg order</span>
        </div>

        <TicketRow
          label="Action"
          value={actionDisplay}
          copyValue={actionDisplay}
          onCopy={copyValue}
          copied={copied}
        />
        <TicketRow
          label="Quantity"
          value={order.quantity}
          help="Number of option contracts"
          copyValue={order.quantity}
          onCopy={copyValue}
          copied={copied}
        />
        <TicketRow
          label="Expiration"
          value={`${formatDate(order.expiration)}${order.days_to_expiration != null ? ` · ${order.days_to_expiration} DTE` : ''}`}
          copyValue={order.expiration}
          onCopy={copyValue}
          copied={copied}
        />
        <TicketRow
          label="Strike"
          value={money(order.strike)}
          copyValue={Number(order.strike).toFixed(2)}
          onCopy={copyValue}
          copied={copied}
        />

        <div className="ticketRow optionTypeRow">
          <div className="ticketLabel"><span>Call / Put</span></div>
          <div className="optionToggle" aria-label={`${order.option_type} selected`}>
            <span className={order.option_type === 'CALL' ? 'selected' : ''}>Call</span>
            <span className={order.option_type === 'PUT' ? 'selected' : ''}>Put</span>
          </div>
        </div>

        <div className="quoteStrip">
          <div><span>Bid</span><b>{money(order.bid)}</b></div>
          <div><span>Mid</span><b>{money(order.mid)}</b></div>
          <div><span>Ask</span><b>{money(order.ask)}</b></div>
        </div>
      </div>

      <div className="orderSettings">
        <TicketRow label="Order Type" value="Limit" />
        <TicketRow
          label="Price"
          value={money(order.limit_price)}
          help={order.price_basis}
          copyValue={Number(order.limit_price).toFixed(2)}
          onCopy={copyValue}
          copied={copied}
        />
        <TicketRow label="Timing" value="Day only" />
        <TicketRow label="Special Instructions" value="None" />
        <TicketRow
          label="Contract Symbol"
          value={order.contract_symbol}
          copyValue={order.contract_symbol}
          onCopy={copyValue}
          copied={copied}
        />
      </div>

      <div className="exitPlan">
        <div>
          <span>Suggested stop</span>
          <strong>{money(rec.stop_loss)}</strong>
        </div>
        <div>
          <span>Profit target 1</span>
          <strong>{money(rec.profit_targets?.[0])}</strong>
        </div>
        <div>
          <span>Profit target 2</span>
          <strong>{money(rec.profit_targets?.[1])}</strong>
        </div>
        <div>
          <span>Maximum modeled risk</span>
          <strong>{money(rec.max_risk_dollars || order.estimated_max_loss)}</strong>
        </div>
      </div>

      <div className="estimatedAmount">
        <div>
          <span>Estimated Amount</span>
          <strong>{money(order.estimated_amount)}</strong>
          <small>Based on limit price × 100 shares per contract; excludes commissions and fees.</small>
        </div>
        <button
          className="copyTicketButton"
          onClick={() => copyValue(ticketText, 'Full ticket')}
        >
          {copied === 'Full ticket' ? <Check size={18} /> : <Clipboard size={18} />}
          {copied === 'Full ticket' ? 'Copied' : 'Copy order ticket'}
        </button>
      </div>

      <div className="ticketWarning">
        <ShieldCheck size={20} />
        <p>
          <b>Verify before submitting:</b> confirm the underlying quote, contract expiration,
          strike, bid/ask, buying power, and estimated amount directly in Schwab. This platform
          does not submit the order and cannot guarantee execution at the midpoint.
        </p>
      </div>
    </section>
  );
}

function App() {
  const [portfolio, setPortfolio] = useState(null);
  const [symbol, setSymbol] = useState('AAPL');
  const [rec, setRec] = useState(null);
  const [currentQuote, setCurrentQuote] = useState(null);
  const [chain, setChain] = useState([]);
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getPortfolio().then(setPortfolio).catch(() => setError('Unable to load portfolio summary.'));
    refreshAll();
  }, []);

  async function refreshAll() {
    setLoading(true);
    setError('');
    try {
      await run('AAPL');
      const data = await recommendations();
      setRecs(data.recommendations || []);
    } catch (err) {
      setError(err.message || 'Unable to refresh recommendations.');
    } finally {
      setLoading(false);
    }
  }

  async function run(requestedSymbol = symbol) {
    const clean = requestedSymbol.toUpperCase().trim();
    if (!clean) return;
    setSymbol(clean);
    setError('');
    try {
      const [quoteData, chainData, recommendationData] = await Promise.all([
        quote(clean),
        options(clean),
        analyze(clean, 'auto'),
      ]);
      setCurrentQuote(quoteData);
      setChain(chainData);
      setRec(recommendationData);
    } catch (err) {
      setError(err.message || `Unable to analyze ${clean}.`);
    }
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
          <b>{portfolio?.ai_confidence_level || 0}%</b>
          <span>{portfolio?.market_sentiment}</span>
        </Card>
        <Card title="Risk Mode" icon={<AlertTriangle />}>
          <b>Capital First</b>
          <span>NO TRADE unless verified evidence aligns</span>
        </Card>
      </section>

      <section className="grid two primaryGrid">
        <Card title="Performance Chart">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={perf}>
              <XAxis dataKey="d" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="v" strokeWidth={3} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card title="AI Trading Assistant" className="assistantCard">
          <div className="search">
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
              onKeyDown={(event) => event.key === 'Enter' && run()}
              aria-label="Ticker symbol"
            />
            <button onClick={() => run()} disabled={loading}>Analyze</button>
            <button
              className="iconButton"
              onClick={refreshAll}
              title="Refresh recommendations"
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? 'spin' : ''} />
            </button>
          </div>

          {currentQuote && (
            <div className="quoteSummary">
              <strong>{currentQuote.symbol}</strong>
              <span>{money(currentQuote.price)}</span>
              <span className={currentQuote.change >= 0 ? 'positive' : 'negative'}>
                {currentQuote.change >= 0 ? '+' : ''}{money(currentQuote.change)} ({currentQuote.change_percent}%)
              </span>
              <span>Vol {currentQuote.volume?.toLocaleString()}</span>
              <span>{currentQuote.market_status}</span>
              <small>Source: {currentQuote.data_source}</small>
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
                  <small>Threshold {rec.threshold}%</small>
                </div>
              </div>

              <p>{rec.explanation}</p>
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
        <Card title="Recent AI Recommendations">
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

        <Card title="Options Chain">
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
          <p>Market data: <b>Live delayed yfinance required for recommendations</b></p>
          <p>Emergency stop: <b>Ready</b></p>
        </Card>
        <Card title="Implementation Notice" icon={<DollarSign />}>
          <p>
            The order ticket is generated only for a qualified recommendation. It translates the
            selected contract into broker-entry fields; it does not connect to or place an order
            with Charles Schwab.
          </p>
        </Card>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
