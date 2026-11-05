#!/usr/bin/env python3
"""
Binance 9/15 EMA Web Dashboard & Performance Monitor
Lightweight real-time web interface for monitoring bot state, live EMA 9 vs 15 chart,
portfolio balance, open positions, PnL, trade history, and logs.
"""

import os
import sys
import json
import time
import argparse
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import state_manager

# Dashboard Configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5001


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server for handling concurrent browser requests smoothly."""
    daemon_threads = True
    allow_reuse_address = True


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Binance 9/15 EMA Bot | Live Performance Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <!-- Lightweight Charts by TradingView -->
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {
      --bg-dark: #07090e;
      --bg-card: #0e131f;
      --bg-card-header: #141b2d;
      --bg-card-sub: #121826;
      --border-color: #1e293b;
      --border-light: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --accent-cyan: #00f0ff;
      --accent-orange: #f59e0b;
      --accent-green: #10b981;
      --accent-green-bg: rgba(16, 185, 129, 0.12);
      --accent-red: #ef4444;
      --accent-red-bg: rgba(239, 68, 68, 0.12);
      --accent-blue: #3b82f6;
      --accent-purple: #8b5cf6;
      --shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.5);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-dark);
      color: var(--text-main);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
    }

    .mono {
      font-family: 'JetBrains Mono', monospace;
      font-feature-settings: "tnum" 1;
    }

    /* Header Bar */
    header {
      background-color: var(--bg-card);
      border-bottom: 1px solid var(--border-color);
      padding: 0.85rem 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 50;
      backdrop-filter: blur(12px);
    }

    .brand-wrap {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .logo-badge {
      background: linear-gradient(135deg, #00f0ff, #3b82f6);
      width: 38px;
      height: 38px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #07090e;
      font-weight: 900;
      font-size: 1.25rem;
      box-shadow: 0 0 15px rgba(0, 240, 255, 0.4);
    }

    .brand-title h1 {
      font-size: 1.05rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .brand-title p {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.2rem 0.6rem;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .badge-pair {
      background: rgba(0, 240, 255, 0.1);
      color: var(--accent-cyan);
      border: 1px solid rgba(0, 240, 255, 0.3);
    }

    .badge-dryrun {
      background: rgba(245, 158, 11, 0.12);
      color: var(--accent-orange);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }

    .badge-status-active {
      background: var(--accent-green-bg);
      color: var(--accent-green);
      border: 1px solid rgba(16, 185, 129, 0.4);
    }

    .badge-status-standby {
      background: rgba(245, 158, 11, 0.12);
      color: var(--accent-orange);
      border: 1px solid rgba(245, 158, 11, 0.3);
    }

    .pulse-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: currentColor;
      box-shadow: 0 0 8px currentColor;
      animation: pulse 1.8s infinite;
    }

    @keyframes pulse {
      0% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
      100% { opacity: 1; transform: scale(1); }
    }

    .controls-wrap {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      background-color: var(--bg-card-header);
      color: var(--text-main);
      border: 1px solid var(--border-color);
      padding: 0.45rem 0.85rem;
      border-radius: 8px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.18s ease;
      text-decoration: none;
    }

    .btn:hover {
      background-color: #1e293b;
      border-color: var(--border-light);
      transform: translateY(-1px);
    }

    .btn-primary {
      background: linear-gradient(135deg, #00f0ff, #0284c7);
      color: #07090e;
      border: none;
      font-weight: 700;
    }

    .btn-primary:hover {
      background: linear-gradient(135deg, #38bdf8, #0ea5e9);
      box-shadow: 0 0 12px rgba(0, 240, 255, 0.4);
    }

    .btn-sim {
      background: rgba(139, 92, 246, 0.15);
      border: 1px solid rgba(139, 92, 246, 0.4);
      color: #c4b5fd;
    }

    .btn-sim:hover {
      background: rgba(139, 92, 246, 0.3);
      color: #fff;
    }

    /* Container Layout */
    main {
      padding: 1.25rem 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
      max-width: 1680px;
      margin: 0 auto;
      width: 100%;
      flex: 1;
    }

    /* Cards Grid (KPI Metrics) */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
    }

    .card {
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 1rem 1.15rem;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
      overflow: hidden;
      transition: border-color 0.2s ease;
    }

    .card:hover {
      border-color: var(--border-light);
    }

    .card-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 0.6rem;
    }

    .card-title {
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    .card-value {
      font-size: 1.45rem;
      font-weight: 800;
      color: var(--text-main);
      line-height: 1.1;
      margin-bottom: 0.4rem;
    }

    .card-sub {
      font-size: 0.72rem;
      color: var(--text-dim);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .val-up {
      color: var(--accent-green) !important;
    }

    .val-down {
      color: var(--accent-red) !important;
    }

    .pill-trend {
      font-size: 0.68rem;
      font-weight: 700;
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
    }

    .pill-up {
      background: var(--accent-green-bg);
      color: var(--accent-green);
    }

    .pill-down {
      background: var(--accent-red-bg);
      color: var(--accent-red);
    }

    /* Indicator Highlight Strip */
    .indicator-strip {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-size: 0.75rem;
      margin-top: 0.2rem;
    }

    .tag-ema9 {
      color: var(--accent-cyan);
      font-weight: 700;
    }

    .tag-ema15 {
      color: var(--accent-orange);
      font-weight: 700;
    }

    /* Main Chart Section */
    .chart-container-card {
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      box-shadow: var(--shadow);
    }

    .chart-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.75rem;
      border-bottom: 1px solid var(--border-color);
      padding-bottom: 0.75rem;
    }

    .chart-info-left {
      display: flex;
      align-items: center;
      gap: 1.25rem;
      flex-wrap: wrap;
    }

    .chart-symbol-price {
      display: flex;
      align-items: baseline;
      gap: 0.5rem;
    }

    .chart-symbol-price .symbol-name {
      font-size: 1.15rem;
      font-weight: 800;
    }

    .chart-symbol-price .price-live {
      font-size: 1.25rem;
      font-weight: 800;
      color: var(--text-main);
    }

    .chart-legend {
      display: flex;
      align-items: center;
      gap: 1rem;
      font-size: 0.75rem;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }

    .legend-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    #tradingview-chart-box {
      width: 100%;
      height: 420px;
      position: relative;
      border-radius: 8px;
      overflow: hidden;
      background: #090c14;
    }

    /* Canvas Fallback if CDN blocked */
    #chart-canvas-fallback {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      display: none;
    }

    /* Bottom Grid: Trades, Signals, Logs */
    .bottom-grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 1.25rem;
    }

    @media (max-width: 1080px) {
      .bottom-grid {
        grid-template-columns: 1fr;
      }
    }

    .table-card {
      background-color: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow);
      max-height: 380px;
    }

    .table-header-box {
      padding: 0.85rem 1.15rem;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background-color: var(--bg-card-header);
      border-radius: 12px 12px 0 0;
    }

    .table-header-box h3 {
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 0.45rem;
    }

    .table-scroll {
      overflow-y: auto;
      flex: 1;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.76rem;
    }

    th {
      background-color: var(--bg-card-sub);
      color: var(--text-muted);
      font-weight: 600;
      padding: 0.6rem 0.9rem;
      border-bottom: 1px solid var(--border-color);
      position: sticky;
      top: 0;
      z-index: 10;
      text-transform: uppercase;
      font-size: 0.68rem;
      letter-spacing: 0.04em;
    }

    td {
      padding: 0.65rem 0.9rem;
      border-bottom: 1px solid rgba(30, 41, 59, 0.6);
      color: var(--text-main);
    }

    tr:hover td {
      background-color: rgba(255, 255, 255, 0.02);
    }

    .badge-buy {
      background: var(--accent-green-bg);
      color: var(--accent-green);
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      font-weight: 700;
    }

    .badge-sell {
      background: var(--accent-red-bg);
      color: var(--accent-red);
      padding: 0.15rem 0.45rem;
      border-radius: 4px;
      font-weight: 700;
    }

    /* Terminal Log Viewer */
    .terminal-card {
      background-color: #07090f;
      border: 1px solid var(--border-color);
      border-radius: 12px;
      overflow: hidden;
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
    }

    .terminal-bar {
      background-color: #0e1320;
      padding: 0.65rem 1rem;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .terminal-dots {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .term-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }

    .term-dot-red { background: #ef4444; }
    .term-dot-yellow { background: #f59e0b; }
    .term-dot-green { background: #10b981; }

    .terminal-content {
      padding: 0.85rem 1rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.74rem;
      color: #cbd5e1;
      height: 160px;
      overflow-y: auto;
      line-height: 1.5;
      display: flex;
      flex-direction: column-reverse; /* latest at bottom */
    }

    .log-row {
      display: flex;
      gap: 0.65rem;
      margin-bottom: 0.25rem;
    }

    .log-time {
      color: var(--text-dim);
      flex-shrink: 0;
    }

    .log-lvl-info { color: #38bdf8; font-weight: 600; flex-shrink: 0; }
    .log-lvl-warn { color: #fbbf24; font-weight: 600; flex-shrink: 0; }
    .log-lvl-error { color: #f87171; font-weight: 700; flex-shrink: 0; }
    .log-msg { color: #e2e8f0; word-break: break-all; }

    /* Footer */
    footer {
      border-top: 1px solid var(--border-color);
      padding: 0.75rem 1.5rem;
      font-size: 0.72rem;
      color: var(--text-dim);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--bg-card);
      margin-top: 1rem;
    }

    /* Modal Toast Notifications */
    #toast-msg {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      border: 1px solid var(--accent-cyan);
      color: #fff;
      padding: 0.65rem 1.15rem;
      border-radius: 8px;
      font-size: 0.8rem;
      font-weight: 600;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      z-index: 1000;
      opacity: 0;
      transform: translateY(10px);
      transition: all 0.25s ease;
      pointer-events: none;
    }

    #toast-msg.show {
      opacity: 1;
      transform: translateY(0);
    }
  </style>
</head>
<body>

  <!-- Top Header Navigation -->
  <header>
    <div class="brand-wrap">
      <div class="logo-badge">9/15</div>
      <div class="brand-title">
        <h1>Binance 9/15 EMA Bot <span id="header-symbol-badge" class="badge badge-pair">BTC/USDT 5m</span></h1>
        <p>Real-Time Strategy Monitor & Performance Dashboard</p>
      </div>
    </div>

    <div class="controls-wrap">
      <span id="bot-mode-badge" class="badge badge-dryrun">DRY RUN (TESTNET)</span>
      <span id="bot-status-badge" class="badge badge-status-standby">
        <span class="pulse-dot"></span>
        <span id="bot-status-text">CONNECTING</span>
      </span>
      <button class="btn btn-sim" onclick="simulateTick()" title="Trigger a simulated candle tick & crossover calculation">
        ⚡ Sim Tick
      </button>
      <button class="btn" onclick="fetchData(true)" title="Force reload data">
        🔄 Refresh
      </button>
    </div>
  </header>

  <!-- Main Container -->
  <main>

    <!-- Top KPI Metrics Grid -->
    <section class="metrics-grid">
      <!-- Balance Card -->
      <div class="card">
        <div class="card-top">
          <span class="card-title">💰 Account / Sim Balance</span>
          <span id="kpi-balance-pnl-pill" class="pill-trend pill-up mono">+0.00%</span>
        </div>
        <div id="kpi-balance" class="card-value mono">$20.00</div>
        <div class="card-sub">
          <span>Initial Budget: <strong class="mono" id="kpi-initial-balance">$20.00</strong></span>
          <span class="mono">USDT</span>
        </div>
      </div>

      <!-- Total PnL Card -->
      <div class="card">
        <div class="card-top">
          <span class="card-title">📈 Total Net PnL</span>
          <span id="kpi-pnl-status" class="pill-trend pill-up">PROFIT</span>
        </div>
        <div id="kpi-total-pnl" class="card-value mono val-up">+$0.0000</div>
        <div class="card-sub">
          <span>Realized: <strong class="mono" id="kpi-realized-pnl">$0.00</strong></span>
          <span>Floating: <strong class="mono" id="kpi-unrealized-pnl">$0.00</strong></span>
        </div>
      </div>

      <!-- Open Position Card -->
      <div class="card">
        <div class="card-top">
          <span class="card-title">🎯 Position Status</span>
          <span id="kpi-position-badge" class="badge badge-pair">FLAT</span>
        </div>
        <div id="kpi-position-side" class="card-value mono">NO POSITION</div>
        <div class="card-sub">
          <span>Entry: <strong class="mono" id="kpi-pos-entry">-</strong></span>
          <span>Size: <strong class="mono" id="kpi-pos-qty">0.0000 BTC</strong></span>
        </div>
      </div>

      <!-- EMA Indicators Card -->
      <div class="card">
        <div class="card-top">
          <span class="card-title">⚡ 9 / 15 EMA Crossover</span>
          <span id="kpi-signal-pill" class="pill-trend pill-up">BUY</span>
        </div>
        <div id="kpi-ema-spread" class="card-value mono tag-ema9">+0.00</div>
        <div class="card-sub indicator-strip">
          <span>EMA9: <strong class="mono tag-ema9" id="kpi-val-ema9">0.00</strong></span>
          <span>EMA15: <strong class="mono tag-ema15" id="kpi-val-ema15">0.00</strong></span>
        </div>
      </div>

      <!-- Win Rate Card -->
      <div class="card">
        <div class="card-top">
          <span class="card-title">🏆 Strategy Stats</span>
          <span id="kpi-trades-count" class="badge badge-pair">0 TRADES</span>
        </div>
        <div id="kpi-win-rate" class="card-value mono">0.0%</div>
        <div class="card-sub">
          <span>W/L: <strong class="mono" id="kpi-wl-ratio">0 W / 0 L</strong></span>
          <span>Vol: <strong class="mono" id="kpi-volume">$0.00</strong></span>
        </div>
      </div>
    </section>

    <!-- Main Live Interactive Chart Card -->
    <section class="chart-container-card">
      <div class="chart-header">
        <div class="chart-info-left">
          <div class="chart-symbol-price">
            <span class="symbol-name" id="chart-symbol-title">BTC/USDT</span>
            <span class="price-live mono" id="chart-last-price">$0.00</span>
          </div>
          <div class="chart-legend">
            <div class="legend-item">
              <span class="legend-dot" style="background:#00f0ff;"></span>
              <span>Fast EMA 9: <strong class="mono tag-ema9" id="legend-ema9">-</strong></span>
            </div>
            <div class="legend-item">
              <span class="legend-dot" style="background:#f59e0b;"></span>
              <span>Slow EMA 15: <strong class="mono tag-ema15" id="legend-ema15">-</strong></span>
            </div>
          </div>
        </div>
        <div>
          <span class="badge badge-pair mono" id="chart-timeframe-tag">5M CANDLES</span>
        </div>
      </div>

      <!-- Chart Display Area -->
      <div id="tradingview-chart-box">
        <canvas id="chart-canvas-fallback"></canvas>
      </div>
    </section>

    <!-- Bottom Split View: Trade History & Recent Signals -->
    <section class="bottom-grid">
      <!-- Trade History Table -->
      <div class="table-card">
        <div class="table-header-box">
          <h3>📊 Trade Execution History</h3>
          <span class="mono" style="font-size: 0.72rem; color: var(--text-dim);" id="table-trades-subtitle">0 trades recorded</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Price</th>
                <th>Qty</th>
                <th>Cost (USDT)</th>
                <th>Realized PnL</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="trades-table-body">
              <tr>
                <td colspan="7" style="text-align:center; color:var(--text-dim); padding: 2rem;">
                  No trade executions recorded yet.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Signals & Crossover Feed -->
      <div class="table-card">
        <div class="table-header-box">
          <h3>⚡ Crossover Signals</h3>
          <span class="mono" style="font-size: 0.72rem; color: var(--text-dim);" id="table-signals-subtitle">Live Strategy Feed</span>
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Signal</th>
                <th>Price</th>
                <th>EMA 9</th>
                <th>EMA 15</th>
                <th>Spread</th>
              </tr>
            </thead>
            <tbody id="signals-table-body">
              <tr>
                <td colspan="6" style="text-align:center; color:var(--text-dim); padding: 2rem;">
                  Waiting for strategy crossover signals...
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Bot Log Terminal Viewer -->
    <section class="terminal-card">
      <div class="terminal-bar">
        <div class="terminal-dots">
          <span class="term-dot term-dot-red"></span>
          <span class="term-dot term-dot-yellow"></span>
          <span class="term-dot term-dot-green"></span>
          <span style="margin-left: 8px; font-size: 0.72rem; font-weight: 700; color: var(--text-muted); font-family: monospace;">bot.log (Live Stream)</span>
        </div>
        <div style="font-size: 0.7rem; color: var(--text-dim);">
          Auto-refreshing every 3s
        </div>
      </div>
      <div class="terminal-content mono" id="terminal-logs">
        <div class="log-row"><span class="log-msg">Connecting to bot.log stream...</span></div>
      </div>
    </section>

  </main>

  <!-- Footer -->
  <footer>
    <div>
      Binance 9/15 EMA Automated Trader & Dashboard &bull; CCXT Engine
    </div>
    <div class="mono" id="footer-heartbeat">
      Last Sync: Never
    </div>
  </footer>

  <div id="toast-msg">Simulated tick executed!</div>

  <script>
    // State & Chart Globals
    let tvChart = null;
    let candleSeries = null;
    let ema9Series = null;
    let ema15Series = null;
    let volumeSeries = null;
    let chartFallbackActive = false;
    let latestCandlesData = [];

    // Initialize Chart
    function initChart() {
      const container = document.getElementById('tradingview-chart-box');
      
      if (typeof LightweightCharts !== 'undefined') {
        try {
          tvChart = LightweightCharts.createChart(container, {
            layout: {
              background: { color: '#090c14' },
              textColor: '#94a3b8',
              fontSize: 11,
              fontFamily: 'JetBrains Mono, monospace',
            },
            grid: {
              vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
              horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
            },
            crosshair: {
              mode: LightweightCharts.CrosshairMode.Normal,
              vertLine: { color: 'rgba(148, 163, 184, 0.4)', width: 1, style: 3 },
              horzLine: { color: 'rgba(148, 163, 184, 0.4)', width: 1, style: 3 },
            },
            rightPriceScale: {
              borderColor: '#1e293b',
              scaleMargins: { top: 0.1, bottom: 0.2 },
            },
            timeScale: {
              borderColor: '#1e293b',
              timeVisible: true,
              secondsVisible: false,
            },
          });

          // Volume Series
          volumeSeries = tvChart.addHistogramSeries({
            color: 'rgba(59, 130, 246, 0.25)',
            priceFormat: { type: 'volume' },
            priceScaleId: '',
            scaleMargins: { top: 0.8, bottom: 0 },
          });

          // Candlestick Series
          candleSeries = tvChart.addCandlestickSeries({
            upColor: '#10b981',
            downColor: '#ef4444',
            borderVisible: false,
            wickUpColor: '#10b981',
            wickDownColor: '#ef4444',
          });

          // EMA 9 Line (Cyan)
          ema9Series = tvChart.addLineSeries({
            color: '#00f0ff',
            lineWidth: 2,
            title: 'EMA 9',
            priceLineVisible: false,
          });

          // EMA 15 Line (Amber/Orange)
          ema15Series = tvChart.addLineSeries({
            color: '#f59e0b',
            lineWidth: 2,
            title: 'EMA 15',
            priceLineVisible: false,
          });

          window.addEventListener('resize', () => {
            if (tvChart && container) {
              tvChart.applyOptions({
                width: container.clientWidth,
                height: container.clientHeight,
              });
            }
          });
          return;
        } catch (e) {
          console.warn("Could not initialize LightweightCharts, falling back to Canvas renderer", e);
        }
      }
      
      // Fallback renderer
      chartFallbackActive = true;
      document.getElementById('chart-canvas-fallback').style.display = 'block';
    }

    // Canvas fallback drawing if offline
    function renderCanvasFallback(candles) {
      const canvas = document.getElementById('chart-canvas-fallback');
      const box = document.getElementById('tradingview-chart-box');
      canvas.width = box.clientWidth;
      canvas.height = box.clientHeight;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!candles || candles.length === 0) return;

      const w = canvas.width;
      const h = canvas.height;
      const paddingBottom = 40;
      const paddingTop = 30;
      const chartH = h - paddingBottom - paddingTop;

      // Find min/max price
      let minP = Infinity, maxP = -Infinity;
      candles.forEach(c => {
        minP = Math.min(minP, c.low, c.ema_9 || c.low, c.ema_15 || c.low);
        maxP = Math.max(maxP, c.high, c.ema_9 || c.high, c.ema_15 || c.high);
      });
      const range = maxP - minP || 1;
      const getY = (val) => paddingTop + chartH - ((val - minP) / range) * chartH;

      const candleW = Math.max(3, (w - 80) / candles.length);
      const gap = candleW * 0.25;

      // Draw Grid
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = paddingTop + (chartH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(40, y);
        ctx.lineTo(w - 20, y);
        ctx.stroke();

        const pVal = maxP - (range / 4) * i;
        ctx.fillStyle = '#64748b';
        ctx.font = '10px JetBrains Mono';
        ctx.fillText(pVal.toFixed(2), w - 65, y - 4);
      }

      // Draw Candlesticks
      candles.forEach((c, idx) => {
        const x = 50 + idx * candleW;
        const yOpen = getY(c.open);
        const yClose = getY(c.close);
        const yHigh = getY(c.high);
        const yLow = getY(c.low);
        const isUp = c.close >= c.open;

        ctx.strokeStyle = isUp ? '#10b981' : '#ef4444';
        ctx.fillStyle = isUp ? '#10b981' : '#ef4444';

        // Wick
        ctx.beginPath();
        ctx.moveTo(x + (candleW - gap)/2, yHigh);
        ctx.lineTo(x + (candleW - gap)/2, yLow);
        ctx.stroke();

        // Body
        const topY = Math.min(yOpen, yClose);
        const bodyH = Math.max(2, Math.abs(yClose - yOpen));
        ctx.fillRect(x, topY, candleW - gap, bodyH);
      });

      // Draw EMA 9 (Cyan)
      ctx.strokeStyle = '#00f0ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      candles.forEach((c, idx) => {
        const x = 50 + idx * candleW + (candleW - gap)/2;
        const y = getY(c.ema_9);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Draw EMA 15 (Amber)
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.beginPath();
      candles.forEach((c, idx) => {
        const x = 50 + idx * candleW + (candleW - gap)/2;
        const y = getY(c.ema_15);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    // Update Chart with Candles & Indicators
    function updateChartData(candles, signals) {
      if (!candles || candles.length === 0) return;
      latestCandlesData = candles;

      if (chartFallbackActive || !tvChart) {
        renderCanvasFallback(candles);
        return;
      }

      try {
        const candleFormatted = [];
        const ema9Formatted = [];
        const ema15Formatted = [];
        const volFormatted = [];

        candles.forEach(c => {
          const t = c.time;
          candleFormatted.push({
            time: t,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          });
          ema9Formatted.push({
            time: t,
            value: c.ema_9,
          });
          ema15Formatted.push({
            time: t,
            value: c.ema_15,
          });
          volFormatted.push({
            time: t,
            value: c.volume || 1.0,
            color: c.close >= c.open ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)',
          });
        });

        candleSeries.setData(candleFormatted);
        ema9Series.setData(ema9Formatted);
        ema15Series.setData(ema15Formatted);
        volumeSeries.setData(volFormatted);

        // Add markers for BUY/SELL signals
        if (signals && signals.length > 0 && candleSeries.setMarkers) {
          const markers = [];
          signals.forEach(sig => {
            const sigUnix = sig.timestamp ? Math.floor(new Date(sig.timestamp).getTime() / 1000) : 0;
            // Match with candle time
            const nearestCandle = candles.find(c => Math.abs(c.time - sigUnix) < 300);
            if (nearestCandle) {
              if (sig.type === 'BUY') {
                markers.push({
                  time: nearestCandle.time,
                  position: 'belowBar',
                  color: '#10b981',
                  shape: 'arrowUp',
                  text: 'BUY',
                });
              } else if (sig.type === 'SELL') {
                markers.push({
                  time: nearestCandle.time,
                  position: 'aboveBar',
                  color: '#ef4444',
                  shape: 'arrowDown',
                  text: 'SELL',
                });
              }
            }
          });
          candleSeries.setMarkers(markers);
        }

      } catch (err) {
        console.warn("Chart data update fallback:", err);
        renderCanvasFallback(candles);
      }
    }

    // Fetch and Update Dashboard State
    async function fetchData(manual = false) {
      try {
        const res = await fetch('/api/state');
        if (!res.ok) throw new Error('API network response not ok');
        const state = await res.json();
        renderDashboard(state);
        
        // Also fetch logs
        fetchLogs();

        if (manual) showToast("Dashboard synced with bot!");
      } catch (err) {
        console.error("Error fetching state:", err);
        document.getElementById('bot-status-text').innerText = "DISCONNECTED";
        const badge = document.getElementById('bot-status-badge');
        badge.className = "badge badge-status-standby";
      }
    }

    // Fetch Logs
    async function fetchLogs() {
      try {
        const res = await fetch('/api/logs');
        if (!res.ok) return;
        const data = await res.json();
        renderLogs(data.logs || []);
      } catch (e) {
        // silent fail on logs
      }
    }

    // Render Dashboard UI from State
    function renderDashboard(st) {
      // 1. Header Badges
      const sym = st.symbol || 'BTC/USDT';
      const tf = st.timeframe || '5m';
      document.getElementById('header-symbol-badge').innerText = `${sym} ${tf}`;
      document.getElementById('chart-symbol-title').innerText = sym;
      document.getElementById('chart-timeframe-tag').innerText = `${tf.toUpperCase()} CANDLES`;

      const modeText = (st.dry_run ? 'DRY RUN' : 'LIVE') + (st.testnet ? ' (TESTNET)' : '');
      document.getElementById('bot-mode-badge').innerText = modeText;

      // Status check (check if updated within last 45 seconds)
      const lastUpdateStr = st.last_updated;
      let isLive = false;
      if (lastUpdateStr) {
        const diffSec = (Date.now() - new Date(lastUpdateStr).getTime()) / 1000;
        isLive = diffSec < 60;
      }
      
      const statusBadge = document.getElementById('bot-status-badge');
      const statusText = document.getElementById('bot-status-text');
      if (st.status === 'RUNNING' || st.status === 'ACTIVE' || isLive) {
        statusBadge.className = 'badge badge-status-active';
        statusText.innerText = 'BOT ACTIVE';
      } else {
        statusBadge.className = 'badge badge-status-standby';
        statusText.innerText = 'STANDBY';
      }

      // 2. Balance & PnL
      const bal = st.balance || {};
      const curBal = Number(bal.current || 20.0);
      const initBal = Number(bal.initial || 20.0);
      const totPnl = Number(bal.total_pnl || 0.0);
      const pnlPct = Number(bal.total_pnl_pct || 0.0);

      document.getElementById('kpi-balance').innerText = `$${curBal.toFixed(2)}`;
      document.getElementById('kpi-initial-balance').innerText = `$${initBal.toFixed(2)}`;

      const balPnlPill = document.getElementById('kpi-balance-pnl-pill');
      balPnlPill.innerText = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
      balPnlPill.className = `pill-trend mono ${pnlPct >= 0 ? 'pill-up' : 'pill-down'}`;

      const pnlEl = document.getElementById('kpi-total-pnl');
      pnlEl.innerText = `${totPnl >= 0 ? '+' : ''}$${totPnl.toFixed(4)}`;
      pnlEl.className = `card-value mono ${totPnl >= 0 ? 'val-up' : 'val-down'}`;

      document.getElementById('kpi-realized-pnl').innerText = `$${Number(bal.realized_pnl || 0).toFixed(4)}`;
      document.getElementById('kpi-unrealized-pnl').innerText = `$${Number(bal.unrealized_pnl || 0).toFixed(4)}`;

      const pnlStatus = document.getElementById('kpi-pnl-status');
      pnlStatus.innerText = totPnl >= 0 ? 'PROFIT' : 'DRAWDOWN';
      pnlStatus.className = `pill-trend ${totPnl >= 0 ? 'pill-up' : 'pill-down'}`;

      // 3. Position Status
      const pos = st.position || {};
      const inPos = pos.in_position;
      const posBadge = document.getElementById('kpi-position-badge');
      const posSide = document.getElementById('kpi-position-side');

      if (inPos) {
        posBadge.className = 'badge badge-buy';
        posBadge.innerText = 'IN POSITION';
        posSide.innerText = `${pos.side || 'LONG'} ${sym.split('/')[0]}`;
        posSide.className = 'card-value mono val-up';
        document.getElementById('kpi-pos-entry').innerText = `$${Number(pos.entry_price || 0).toFixed(2)}`;
        document.getElementById('kpi-pos-qty').innerText = `${Number(pos.qty || 0).toFixed(6)} ${sym.split('/')[0]}`;
      } else {
        posBadge.className = 'badge badge-pair';
        posBadge.innerText = 'FLAT';
        posSide.innerText = 'NO POSITION';
        posSide.className = 'card-value mono';
        document.getElementById('kpi-pos-entry').innerText = '-';
        document.getElementById('kpi-pos-qty').innerText = `0.000000 ${sym.split('/')[0]}`;
      }

      // 4. EMA 9 vs 15 Engine
      const ind = st.indicators || {};
      const ema9 = Number(ind.ema_9 || 0);
      const ema15 = Number(ind.ema_15 || 0);
      const spread = Number(ind.spread || (ema9 - ema15));
      const latestClose = Number(ind.latest_close || 0);

      document.getElementById('kpi-val-ema9').innerText = ema9 ? ema9.toFixed(2) : '-';
      document.getElementById('kpi-val-ema15').innerText = ema15 ? ema15.toFixed(2) : '-';
      document.getElementById('legend-ema9').innerText = ema9 ? `$${ema9.toFixed(2)}` : '-';
      document.getElementById('legend-ema15').innerText = ema15 ? `$${ema15.toFixed(2)}` : '-';
      document.getElementById('chart-last-price').innerText = latestClose ? `$${latestClose.toFixed(2)}` : '-';

      const spreadEl = document.getElementById('kpi-ema-spread');
      spreadEl.innerText = `${spread >= 0 ? '+' : ''}${spread.toFixed(2)}`;
      spreadEl.className = `card-value mono ${spread >= 0 ? 'tag-ema9' : 'tag-ema15'}`;

      const sigPill = document.getElementById('kpi-signal-pill');
      const lastSig = ind.last_signal || (spread > 0 ? 'BUY' : 'SELL');
      sigPill.innerText = lastSig;
      sigPill.className = `pill-trend ${lastSig === 'BUY' ? 'pill-up' : (lastSig === 'SELL' ? 'pill-down' : 'pill-trend')}`;

      // 5. Strategy Stats
      const stats = st.stats || {};
      const totalTrades = stats.total_trades || (st.trades ? st.trades.length : 0);
      const winRate = Number(stats.win_rate || 0);
      document.getElementById('kpi-trades-count').innerText = `${totalTrades} TRADES`;
      document.getElementById('kpi-win-rate').innerText = `${winRate.toFixed(1)}%`;
      document.getElementById('kpi-wl-ratio').innerText = `${stats.winning_trades || 0} W / ${stats.losing_trades || 0} L`;
      document.getElementById('kpi-volume').innerText = `$${Number(stats.total_volume_usdt || 0).toFixed(2)}`;

      // 6. Update Chart
      updateChartData(st.candles || [], st.signals || []);

      // 7. Update Trades Table
      renderTradesTable(st.trades || []);

      // 8. Update Signals Table
      renderSignalsTable(st.signals || []);

      // 9. Footer Heartbeat
      document.getElementById('footer-heartbeat').innerText = `Last Sync: ${new Date().toLocaleTimeString()} (UTC)`;
    }

    // Render Trades Table
    function renderTradesTable(trades) {
      const tbody = document.getElementById('trades-table-body');
      const subtitle = document.getElementById('table-trades-subtitle');
      subtitle.innerText = `${trades.length} trade${trades.length === 1 ? '' : 's'} recorded`;

      if (!trades || trades.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-dim); padding: 1.5rem;">No trades recorded yet.</td></tr>`;
        return;
      }

      let html = '';
      trades.slice(0, 50).forEach(t => {
        const isBuy = t.action === 'BUY';
        const pnl = Number(t.pnl || 0);
        const pnlPct = Number(t.pnl_pct || 0);
        const dateStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : '-';

        html += `
          <tr>
            <td class="mono" style="color:var(--text-dim);">${dateStr}</td>
            <td><span class="${isBuy ? 'badge-buy' : 'badge-sell'}">${t.action}</span></td>
            <td class="mono font-bold">$${Number(t.price).toFixed(2)}</td>
            <td class="mono">${Number(t.qty).toFixed(6)}</td>
            <td class="mono">$${Number(t.cost || (t.price * t.qty)).toFixed(2)}</td>
            <td class="mono ${pnl > 0 ? 'val-up' : (pnl < 0 ? 'val-down' : '')}">
              ${isBuy ? '-' : (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(4) + ' (' + pnlPct.toFixed(2) + '%)'}
            </td>
            <td><span class="badge badge-pair" style="font-size:0.65rem;">${t.status || 'CLOSED'}</span></td>
          </tr>
        `;
      });
      tbody.innerHTML = html;
    }

    // Render Signals Table
    function renderSignalsTable(signals) {
      const tbody = document.getElementById('signals-table-body');
      const subtitle = document.getElementById('table-signals-subtitle');
      subtitle.innerText = `${signals.length} signal${signals.length === 1 ? '' : 's'} triggered`;

      if (!signals || signals.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-dim); padding: 1.5rem;">No crossover signals triggered yet.</td></tr>`;
        return;
      }

      let html = '';
      signals.slice(0, 50).forEach(s => {
        const isBuy = s.type === 'BUY';
        const dateStr = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '-';
        const spread = Number(s.spread || (s.ema_9 - s.ema_15));

        html += `
          <tr>
            <td class="mono" style="color:var(--text-dim);">${dateStr}</td>
            <td><span class="${isBuy ? 'badge-buy' : 'badge-sell'}">${s.type} CROSS</span></td>
            <td class="mono font-bold">$${Number(s.price).toFixed(2)}</td>
            <td class="mono tag-ema9">${Number(s.ema_9).toFixed(2)}</td>
            <td class="mono tag-ema15">${Number(s.ema_15).toFixed(2)}</td>
            <td class="mono ${spread >= 0 ? 'tag-ema9' : 'tag-ema15'}">${spread >= 0 ? '+' : ''}${spread.toFixed(2)}</td>
          </tr>
        `;
      });
      tbody.innerHTML = html;
    }

    // Render Logs
    function renderLogs(logs) {
      const term = document.getElementById('terminal-logs');
      if (!logs || logs.length === 0) {
        term.innerHTML = `<div class="log-row"><span class="log-msg">No log entries found.</span></div>`;
        return;
      }

      let html = '';
      logs.slice(0, 60).forEach(l => {
        let lvlClass = 'log-lvl-info';
        if (l.level === 'WARNING' || l.level === 'WARN') lvlClass = 'log-lvl-warn';
        if (l.level === 'ERROR' || l.level === 'CRITICAL') lvlClass = 'log-lvl-error';

        html += `
          <div class="log-row">
            <span class="log-time">${l.timestamp || ''}</span>
            <span class="${lvlClass}">[${l.level || 'INFO'}]</span>
            <span class="log-msg">${escapeHtml(l.message || l.raw || '')}</span>
          </div>
        `;
      });
      term.innerHTML = html;
    }

    function escapeHtml(text) {
      return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    // Trigger Simulation Tick
    async function simulateTick() {
      try {
        const res = await fetch('/api/simulate_tick', { method: 'POST' });
        if (res.ok) {
          const updated = await res.json();
          renderDashboard(updated);
          showToast("Simulated 5m tick & EMA calculated!");
        }
      } catch (e) {
        console.error("Sim error:", e);
      }
    }

    // Show temporary toast message
    function showToast(text) {
      const el = document.getElementById('toast-msg');
      el.innerText = text;
      el.classList.add('show');
      setTimeout(() => el.classList.remove('show'), 2400);
    }

    // Startup & Polling
    window.addEventListener('DOMContentLoaded', () => {
      initChart();
      fetchData();
      // Poll every 3 seconds for continuous live updates
      setInterval(fetchData, 3000);
    });
  </script>
</body>
</html>
"""


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Handles REST API and serves Web Dashboard frontend."""

    def log_message(self, format, *args):
        """Suppress default stdout access logs for quiet, clean terminal operation."""
        return

    def send_json_response(self, data: dict, status_code: int = HTTPStatus.OK):
        """Sends JSON formatted response."""
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Route GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            content = DASHBOARD_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/api/state":
            state = state_manager.load_state()
            self.send_json_response(state)
            return

        elif path == "/api/candles":
            state = state_manager.load_state()
            self.send_json_response({
                "symbol": state.get("symbol", "BTC/USDT"),
                "timeframe": state.get("timeframe", "5m"),
                "candles": state.get("candles", []),
            })
            return

        elif path == "/api/trades":
            state = state_manager.load_state()
            self.send_json_response({
                "trades": state.get("trades", []),
                "stats": state.get("stats", {}),
            })
            return

        elif path == "/api/signals":
            state = state_manager.load_state()
            self.send_json_response({
                "signals": state.get("signals", []),
                "indicators": state.get("indicators", {}),
            })
            return

        elif path == "/api/logs":
            logs = state_manager.parse_bot_logs(80)
            self.send_json_response({"logs": logs})
            return

        elif path == "/api/scanner":
            signals_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "signals.json"))
            if os.path.exists(signals_file):
                try:
                    with open(signals_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.send_json_response(data)
                    return
                except Exception:
                    pass
            self.send_json_response({"summary": {"total_scanned": 0}, "active_crossovers": []})
            return

        elif path == "/api/forecast":
            try:
                import ccxt
                import pandas as pd
                from hybrid_forecaster import HybridTradingForecaster
                ex = ccxt.binance()
                state = state_manager.load_state()
                sym = state.get("symbol", "BTC/USDT")
                tf = state.get("timeframe", "1h")
                candles = ex.fetch_ohlcv(sym, timeframe=tf, limit=100)
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                forecaster = HybridTradingForecaster()
                result = forecaster.predict_ensemble(df)
                self.send_json_response(result)
            except Exception as e:
                self.send_json_response({"error": f"Forecast failed: {e}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Resource Not Found")

    def do_POST(self):
        """Route POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/simulate_tick":
            # Read optional body
            content_length = int(self.headers.get("Content-Length", 0))
            force_action = None
            if content_length > 0:
                body = self.rfile.read(content_length).decode("utf-8", errors="ignore")
                try:
                    payload = json.loads(body)
                    force_action = payload.get("action")
                except Exception:
                    pass

            state = state_manager.load_state()
            updated_state = state_manager.simulate_tick(state, force_action=force_action)
            self.send_json_response(updated_state)
            return

        elif path == "/api/reset":
            default_state = state_manager.get_default_state()
            default_state = state_manager.seed_initial_candles_if_empty(default_state)
            state_manager.save_state(default_state)
            self.send_json_response({"status": "reset_completed", "state": default_state})
            return

        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown POST Action")


def start_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Initializes and runs the web dashboard server."""
    # Ensure state file and initial values exist
    initial_state = state_manager.load_state()

    server_address = (host, port)
    try:
        httpd = ThreadedHTTPServer(server_address, DashboardRequestHandler)
    except OSError as e:
        if "Address already in use" in str(e):
            alt_port = port + 1
            print(f"[!] Port {port} is occupied. Trying fallback port {alt_port}...")
            server_address = (host, alt_port)
            httpd = ThreadedHTTPServer(server_address, DashboardRequestHandler)
            port = alt_port
        else:
            raise e

    print("=" * 64)
    print(" 🚀 BINANCE 9/15 EMA BOT - WEB DASHBOARD MONITOR")
    print("=" * 64)
    print(f" ▶ Local Web Interface:  http://{host}:{port}")
    print(f" ▶ Active Trading Pair:  {initial_state.get('symbol', 'BTC/USDT')} ({initial_state.get('timeframe', '5m')})")
    print(f" ▶ Bot Operating Mode:   {'DRY RUN' if initial_state.get('dry_run') else 'LIVE'} | {'TESTNET' if initial_state.get('testnet') else 'PRODUCTION'}")
    print(f" ▶ Initial Sim Balance:  ${initial_state.get('balance', {}).get('initial', 20.0):.2f} USDT")
    print(f" ▶ State File:           {state_manager.STATE_FILE}")
    print(f" ▶ Bot Log File:         {state_manager.LOG_FILE}")
    print("=" * 64)
    print(" Press Ctrl+C to stop the dashboard server.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down Web Dashboard server gracefully...")
    finally:
        httpd.server_close()
        print("[✓] Server stopped.")


def main():
    parser = argparse.ArgumentParser(description="Binance 9/15 EMA Web Dashboard Monitor")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host address to bind (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    start_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
