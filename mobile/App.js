import React, { useEffect, useState } from 'react';
import { SafeAreaView, View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, ActivityIndicator } from 'react-native';
import * as LocalAuthentication from 'expo-local-authentication';
import Constants from 'expo-constants';

const API = Constants.expoConfig?.extra?.apiUrl || 'https://ai-trading-platform-vdm6.onrender.com/api';

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

async function postAnalyze(symbol) {
  const r = await fetch(`${API}/ai/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, account_value: 10000, strategy: 'long_call', min_confidence: 75 }),
  });
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

async function getPortfolio() {
  const r = await fetch(`${API}/portfolio/summary`);
  if (!r.ok) throw new Error(await apiError(r));
  return r.json();
}

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [symbol, setSymbol] = useState('AAPL');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [rec, setRec] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

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
      setSymbol(clean);
      setSearchResults([]);
      setRec(await postAnalyze(clean));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
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
          <View style={styles.card}><Text style={styles.label}>Portfolio</Text><Text style={styles.big}>${portfolio?.total_value?.toLocaleString() || '10,000'}</Text><Text style={styles.muted}>Daily P/L ${portfolio?.daily_pl ?? '—'}</Text></View>
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
              style={styles.btn}
            ><Text style={styles.btnText}>Analyze</Text></TouchableOpacity>
          </View>
          {searching ? <ActivityIndicator style={{ marginTop: 10 }} /> : null}
          {searchResults.length > 0 ? (
            <View style={styles.searchResults}>
              {searchResults.map((item) => (
                <TouchableOpacity key={`${item.symbol}-${item.exchange}`} style={styles.searchResult} onPress={() => analyze(item.symbol)}>
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
            <Text style={styles.text}>Confidence {rec.confidence}% / {rec.threshold}%</Text>
            <Text style={styles.text}>{rec.explanation}</Text>
            {rec.risks?.map((r, i) => <Text key={i} style={styles.text}>• {r}</Text>)}
          </View>}
        </View>
        <View style={styles.card}><Text style={styles.label}>Risk Center</Text><Text style={styles.text}>Max risk per trade: 1%</Text><Text style={styles.text}>Emergency stop: ready</Text><Text style={styles.text}>Broker execution: disabled</Text></View>
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
  noTrade: { borderLeftColor: '#f59e0b', borderLeftWidth: 5, backgroundColor: '#1f2937', borderRadius: 12, padding: 14, marginTop: 14 },
  trade: { borderLeftColor: '#22c55e', borderLeftWidth: 5, backgroundColor: '#13251b', borderRadius: 12, padding: 14, marginTop: 14 },
  result: { color: '#fff', fontWeight: '900', fontSize: 18 },
  text: { color: '#dbeafe', marginTop: 6 },
});
