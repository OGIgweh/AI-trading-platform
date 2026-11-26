import React, { useEffect, useState } from 'react';
import { SafeAreaView, View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import Constants from 'expo-constants';

const API = process.env.EXPO_PUBLIC_API_URL || Constants.expoConfig?.extra?.apiUrl || 'https://ai-trading-platform-vdm6.onrender.com/api';

async function apiError(response) {
  try {
    const payload = await response.json();
    return payload.detail || payload.message || `API error ${response.status}`;
  } catch {
    return `API error ${response.status}`;
  }
}

async function searchStocks(query) {
  const r = await fetch(`${API}/market/search?q=${encodeURIComponent(query)}&limit=8`);
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

async function postAnalyze(symbol, assetMode, optionStructure) {
  const r = await fetch(`${API}/ai/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, account_value: 10000, asset_mode: assetMode, option_structure: optionStructure, strategy: 'auto', min_confidence: 75 }),
  });
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

async function getPortfolio() {
  const r = await fetch(`${API}/portfolio/summary`);
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

async function getSocialIntelligence(symbol = 'BTC') {
  const r = await fetch(`${API}/social/intelligence/${encodeURIComponent(symbol)}`);
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

async function getVerifiedStrategyIntelligence(symbol) {
  const r = await fetch(`${API}/verified-strategy/intelligence/${encodeURIComponent(symbol)}`);
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [symbol, setSymbol] = useState('AAPL');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [rec, setRec] = useState(null);
  const [assetMode, setAssetMode] = useState('options');
  const [optionStructure, setOptionStructure] = useState('auto');
  const [portfolio, setPortfolio] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [socialAsset, setSocialAsset] = useState('BTC');
  const [socialData, setSocialData] = useState(null);
  const [socialLoading, setSocialLoading] = useState(false);
  const [verifiedStrategyData, setVerifiedStrategyData] = useState(null);
  const [verifiedStrategyLoading, setVerifiedStrategyLoading] = useState(false);

  useEffect(() => {
    async function init() {
      try {
        const hasHardware = await LocalAuthentication.hasHardwareAsync();
        if (hasHardware) {
          const r = await LocalAuthentication.authenticateAsync({ promptMessage: 'Unlock AI Trading Platform' });
          setAuthed(r.success);
        } else {
          setAuthed(true);
        }
        const p = await getPortfolio();
        setPortfolio(p);
        setSocialData(await getSocialIntelligence('BTC'));
        setVerifiedStrategyData(await getVerifiedStrategyIntelligence('AAPL'));
      } catch (e) {
        setError(e.message);
        setAuthed(true);
      }
    }
    init();
  }, []);

  useEffect(() => {
    const query = symbol.trim();
    if (!query) {
      setSearchResults([]);
      return undefined;
    }
    const timer = setTimeout(async () => {
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
    return () => clearTimeout(timer);
  }, [symbol]);

  async function analyze(requestedSymbol = symbol) {
    try {
      setLoading(true);
      setError('');
      const clean = requestedSymbol.trim().toUpperCase();
      setRec(null);
      setSymbol(clean);
      setSearchResults([]);
      setRec(await postAnalyze(clean, assetMode, optionStructure));
      await loadVerifiedStrategy(clean);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadSocial(asset) {
    setSocialAsset(asset);
    setSocialLoading(true);
    try {
      setSocialData(await getSocialIntelligence(asset));
    } catch (e) {
      setSocialData({ consensus: 'UNAVAILABLE', score: 50, confidence: 0, qualified_traders: 0, message: e.message, top_traders: [] });
    } finally {
      setSocialLoading(false);
    }
  }

  async function loadVerifiedStrategy(requestedSymbol) {
    const clean = String(requestedSymbol || '').trim().toUpperCase();
    if (!clean) return;
    setVerifiedStrategyLoading(true);
    try {
      setVerifiedStrategyData(await getVerifiedStrategyIntelligence(clean));
    } catch (e) {
      setVerifiedStrategyData({ symbol: clean, consensus: 'N/A', quality_score: 0, matched_strategies: 0, message: e.message, top_strategies: [] });
    } finally {
      setVerifiedStrategyLoading(false);
    }
  }

  if (!authed) {
    return <SafeAreaView style={styles.wrap}><Text style={styles.title}>Locked</Text><Text style={styles.muted}>Use Face ID / fingerprint to continue.</Text></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.wrap}>
      <ScrollView>
        <Text style={styles.title}>AI Trading Platform</Text>
        <Text style={styles.muted}>Paper mode · live trading locked · capital preservation first</Text>
        {error ? <Text style={styles.error}>Error: {error}</Text> : null}
        <View style={styles.grid}>
          <View style={styles.card}><Text style={styles.label}>Demo Portfolio</Text><Text style={styles.big}>{portfolio ? `$${portfolio.total_value.toLocaleString()}` : 'Unavailable'}</Text><Text style={styles.muted}>Daily P/L ${portfolio?.daily_pl ?? '—'}</Text></View>
          <View style={styles.card}><Text style={styles.label}>Market</Text><Text style={styles.big}>{portfolio?.market_status || '—'}</Text><Text style={styles.muted}>{portfolio?.market_sentiment || 'Neutral'}</Text></View>
        </View>
        <View style={styles.card}>
          <Text style={styles.label}>AI Trading Assistant</Text>
          <View style={styles.row}>
            <TextInput
              value={symbol}
              onChangeText={setSymbol}
              style={styles.input}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="Ticker or company name"
              placeholderTextColor="#64748b"
              onSubmitEditing={() => {
                const exact = searchResults.find((item) => item.symbol === symbol.trim().toUpperCase());
                analyze(exact?.symbol || searchResults[0]?.symbol || symbol);
              }}
            />
            <TouchableOpacity
              onPress={() => {
                const exact = searchResults.find((item) => item.symbol === symbol.trim().toUpperCase());
                analyze(exact?.symbol || searchResults[0]?.symbol || symbol);
              }}
              disabled={loading}
              style={styles.btn}
            ><Text style={styles.btnText}>Analyze</Text></TouchableOpacity>
          </View>
          <Text style={[styles.label, { marginTop: 16 }]}>Recommendation type</Text>
          <View style={styles.modeRow}>
            {[['options', 'Options'], ['stock', 'Stock'], ['auto', 'Auto']].map(([value, label]) => (
              <TouchableOpacity
                key={value}
                style={[styles.modeButton, assetMode === value && styles.modeButtonActive]}
                disabled={loading}
                onPress={() => { setAssetMode(value); setRec(null); }}
              >
                <Text style={[styles.modeButtonText, assetMode === value && styles.modeButtonTextActive]}>{label}</Text>
              </TouchableOpacity>
            ))}
          </View>
          <Text style={styles.modeHelp}>
            {assetMode === 'options'
              ? 'Options-only: no stock substitute when an option chain is unavailable.'
              : assetMode === 'stock'
                ? 'Shares-only: option contracts are not evaluated.'
                : 'Auto: options first, with stock fallback only when options data is unavailable.'}
          </Text>
          {assetMode !== 'stock' ? (
            <>
              <Text style={[styles.label, { marginTop: 16 }]}>Option trade structure</Text>
              <View style={styles.modeRow}>
                {[['single', 'Single Leg'], ['multi', 'Multi Leg'], ['auto', 'Best Fit']].map(([value, label]) => (
                  <TouchableOpacity
                    key={value}
                    style={[styles.modeButton, optionStructure === value && styles.modeButtonActive]}
                    disabled={loading}
                    onPress={() => { setOptionStructure(value); setRec(null); }}
                  >
                    <Text style={[styles.modeButtonText, optionStructure === value && styles.modeButtonTextActive]}>{label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.modeHelp}>
                {optionStructure === 'single'
                  ? 'Single Leg: Call or Put only; no vertical spread substitution.'
                  : optionStructure === 'multi'
                    ? 'Multi Leg: defined-risk Vertical Call or Vertical Put only in the current engine.'
                    : 'Best Fit: the engine may choose a single leg or vertical spread based on verified evidence and risk.'}
              </Text>
            </>
          ) : null}
          {searching ? <ActivityIndicator style={{ marginTop: 10 }} /> : null}
          {searchResults.length > 0 ? (
            <View style={styles.searchResults}>
              {searchResults.map((item) => (
                <TouchableOpacity key={`${item.symbol}-${item.exchange}`} style={styles.searchResult} disabled={loading} onPress={() => analyze(item.symbol)}>
                  <Text style={styles.searchSymbol}>{item.symbol}</Text>
                  <View style={{ flex: 1 }}>
                    <Text numberOfLines={1} style={styles.searchName}>{item.name}</Text>
                    <Text style={styles.searchMeta}>{item.exchange} · {item.quote_type}</Text>
                  </View>
                </TouchableOpacity>
              ))}
            </View>
          ) : null}
          {loading ? <ActivityIndicator style={{ marginTop: 20 }} /> : null}
          {rec && <View style={rec.recommendation === 'NO_TRADE' ? styles.noTrade : styles.trade}>
            <Text style={styles.result}>{rec.recommendation === 'NO_TRADE' ? 'NO TRADE RECOMMENDED' : `${rec.recommendation} SETUP`}</Text>
            <Text style={styles.text}>Evidence score {rec.confidence}/100 · Threshold {rec.threshold}/100</Text>
            <Text style={styles.text}>{rec.explanation}</Text>
            {rec.risks?.map((r, i) => <Text key={i} style={styles.text}>• {r}</Text>)}
          </View>}
        </View>
        <View style={styles.card}>
          <Text style={styles.label}>Social / Whale Intelligence</Text>
          <View style={styles.modeRow}>
            {['BTC', 'ETH', 'SOL', 'HYPE', 'ARB'].map((asset) => (
              <TouchableOpacity key={asset} style={[styles.socialAssetButton, socialAsset === asset && styles.modeButtonActive]} onPress={() => loadSocial(asset)}>
                <Text style={[styles.modeButtonText, socialAsset === asset && styles.modeButtonTextActive]}>{asset}</Text>
              </TouchableOpacity>
            ))}
          </View>
          {socialLoading ? <ActivityIndicator style={{ marginTop: 12 }} /> : (
            <>
              <Text style={styles.socialConsensus}>{socialData?.consensus || 'UNAVAILABLE'} · {socialData?.score ?? 50}/100</Text>
              <Text style={styles.text}>Coverage confidence: {socialData?.confidence ?? 0}% · Qualified traders: {socialData?.qualified_traders ?? 0}</Text>
              <Text style={styles.muted}>{socialData?.message || 'Configure an authorized Invo endpoint or explicit Hyperliquid wallets to populate this signal.'}</Text>
            </>
          )}
        </View>
        <View style={styles.card}>
          <Text style={styles.label}>Verified Strategy Intelligence</Text>
          {verifiedStrategyLoading ? <ActivityIndicator style={{ marginTop: 12 }} /> : (
            <>
              <Text style={styles.socialConsensus}>{verifiedStrategyData?.consensus || 'N/A'} · Quality {verifiedStrategyData?.quality_score ?? 0}/100</Text>
              <Text style={styles.text}>Matched strategies: {verifiedStrategyData?.matched_strategies ?? 0} · Reviewed: {verifiedStrategyData?.strategies_reviewed ?? 0}</Text>
              <Text style={styles.muted}>{verifiedStrategyData?.message || 'Configure an authorized AlphaLedger JSON endpoint to populate verified strategy intelligence.'}</Text>
              {(verifiedStrategyData?.top_strategies || []).slice(0, 3).map((strategy, index) => (
                <View key={`${strategy.alphaledger_id || strategy.strategy_name}-${index}`} style={styles.strategyMiniRow}>
                  <Text style={styles.text}>{strategy.strategy_name}</Text>
                  <Text style={styles.muted}>Alpha {Number(strategy.alpha_score || 0).toFixed(0)} · Sharpe {Number(strategy.sharpe_ratio || 0).toFixed(2)} · Max DD {Number(strategy.max_drawdown_percent || 0).toFixed(1)}%</Text>
                </View>
              ))}
            </>
          )}
        </View>
        <View style={styles.card}><Text style={styles.label}>Risk Center</Text><Text style={styles.text}>Max risk per trade: 1%</Text><Text style={styles.text}>Broker execution: disabled</Text></View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: '#0b1020', padding: 20 },
  title: { fontSize: 31, fontWeight: '800', color: '#fff', marginTop: 24 },
  muted: { color: '#94a3b8', marginTop: 4 },
  error: { color: '#fecaca', backgroundColor: '#7f1d1d', padding: 10, borderRadius: 10, marginTop: 12 },
  grid: { flexDirection: 'row', gap: 12, marginTop: 20 },
  card: { backgroundColor: '#111827', borderRadius: 20, padding: 18, marginTop: 16, flex: 1, borderColor: '#25314d', borderWidth: 1 },
  label: { color: '#cbd5e1', fontWeight: '700' },
  big: { fontSize: 25, color: '#fff', fontWeight: '900', marginTop: 8 },
  row: { flexDirection: 'row', gap: 10, marginTop: 12 },
  input: { flex: 1, backgroundColor: '#0b1020', color: '#fff', borderRadius: 12, padding: 12, borderColor: '#334155', borderWidth: 1 },
  searchResults: { marginTop: 8, borderColor: '#334155', borderWidth: 1, borderRadius: 12, overflow: 'hidden', backgroundColor: '#0b1020' },
  searchResult: { flexDirection: 'row', gap: 10, alignItems: 'center', padding: 12, borderBottomColor: '#1e293b', borderBottomWidth: 1 },
  searchSymbol: { color: '#38bdf8', fontWeight: '900', width: 68 },
  searchName: { color: '#f8fafc', fontWeight: '700' },
  searchMeta: { color: '#94a3b8', fontSize: 12, marginTop: 2 },
  btn: { backgroundColor: '#e5e7eb', padding: 12, borderRadius: 12 },
  btnText: { fontWeight: '800' },
  modeRow: { flexDirection: 'row', gap: 8, marginTop: 8 },
  modeButton: { flex: 1, paddingVertical: 10, paddingHorizontal: 8, borderRadius: 10, borderColor: '#334155', borderWidth: 1, backgroundColor: '#0b1020', alignItems: 'center' },
  modeButtonActive: { backgroundColor: '#075985', borderColor: '#38bdf8' },
  modeButtonText: { color: '#cbd5e1', fontWeight: '800' },
  modeButtonTextActive: { color: '#ffffff' },
  modeHelp: { color: '#94a3b8', fontSize: 12, lineHeight: 17, marginTop: 8 },
  socialAssetButton: { flex: 1, minWidth: 52, paddingVertical: 9, paddingHorizontal: 6, borderRadius: 10, borderColor: '#334155', borderWidth: 1, backgroundColor: '#0b1020', alignItems: 'center' },
  socialConsensus: { color: '#fff', fontWeight: '900', fontSize: 19, marginTop: 14 },
  strategyMiniRow: { marginTop: 10, paddingTop: 10, borderTopColor: '#25314d', borderTopWidth: 1 },
  noTrade: { borderLeftColor: '#f59e0b', borderLeftWidth: 5, backgroundColor: '#1f2937', borderRadius: 12, padding: 14, marginTop: 14 },
  trade: { borderLeftColor: '#22c55e', borderLeftWidth: 5, backgroundColor: '#13251b', borderRadius: 12, padding: 14, marginTop: 14 },
  result: { color: '#fff', fontWeight: '900', fontSize: 18 },
  text: { color: '#dbeafe', marginTop: 6 },
});
