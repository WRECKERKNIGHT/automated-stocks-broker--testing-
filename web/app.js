"use strict";

const state = {
  symbol: "AAPL",
  follow: true,
  autoSym: null,
  tf: "5Min",
  snap: null,
  chart: null,
  candle: null,
  volume: null,
  overlays: {},
  priceLines: [],
  vp: null,
  lastBars: null,
};

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) =>
  v == null ? "--" : "$" + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
const pct = (v) => (v == null ? "--" : (v * 100).toFixed(2) + "%");
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "muted");
const tstr = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString() : "--");
const dstr = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString() : "--");
const fmtPct = (v) => (v == null ? "--" : (v >= 0 ? "+" : "") + Number(v).toFixed(2) + "%");
const fmtVol = (v) =>
  v == null ? "--" : v >= 1e9 ? (v / 1e9).toFixed(1) + "B"
    : v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : String(v);
const ago = (ts) => (ts ? tstr(ts) : "");
const toast = (msg) => pushToast({ level: "info", msg });

/* Plain-language explainer for every label/term. Hover any label to see it.
   Keyed by the exact visible text of the element. */
const TIPS = {
  /* top bar */
  "Equity": "Your total account value right now = cash + value of open positions. This is your real score.",
  "Day": "Profit or loss since today's session opened (green = up, red = down).",
  "BP": "Buying Power: how much the broker lets you deploy. It includes borrowed money (leverage), so it is NOT your cash.",
  "Pos": "How many positions are open right now.",
  "Mkt": "Whether the US stock market is open or closed.",
  "Universe": "How many symbols the bot is watching.",
  "LLM": "Whether an AI language model helps analyse the market, or it is just rules.",
  "Start Bot": "Turn the trading bot on.",
  "Stop Bot": "Turn the trading bot off (open positions stay until closed).",
  /* chart toolbar */
  "🔎": "Research this symbol in depth.",
  "⤢ focus": "Focus mode: hide the side panels and enlarge the chart.",
  "⤢ exit": "Leave focus mode and show the panels again.",
  "◎ follow": "Chart automatically follows the bot's biggest open trade.",
  "1m": "Each candle = 1 minute of price action.",
  "5m": "Each candle = 5 minutes of price action.",
  "15m": "Each candle = 15 minutes of price action.",
  "1H": "Each candle = 1 hour of price action.",
  "1D": "Each candle = 1 day of price action.",
  /* side tabs */
  "Positions": "Your open trades and their live profit/loss.",
  "Orders": "Every order the bot has sent to the broker.",
  "Tape": "The live order book (best bid/ask) plus recent trade prints.",
  "News": "Latest headlines, each with a sentiment score (+ good, − bad).",
  "Log": "The bot's running diary of actions, trades and errors.",
  /* left rail */
  "Terminal": "Live decision log — what the bot is thinking and why.",
  "Scanner": "Find the market's biggest gainers, losers and most active names.",
  "Research": "A full dossier on one stock: trend, levels, news, thesis and risks.",
  "Ideas": "Trade candidates the bot likes right now, with entry/stop/target.",
  "Portfolio": "Risk view: exposure, concentration, correlation and sector allocation.",
  "Journal": "Your personal trade notes and lessons.",
  "Alerts": "Price/volume triggers you set; the bot pings you when they fire.",
  "Coach": "A trading playbook of principles that fit the current market.",
  "Library": "Lessons distilled from 100+ trading books.",
  "Pulse": "Market pulse: news wire, breadth and worth-watching talks.",
  "Equity": "Your account value over time (the equity curve).",
  "Trades": "All your closed (finished) trades with their results.",
  "Daily": "Day-by-day performance summary.",
  "Mind": "The bot's discipline: mood, win/loss streaks, cooldowns and guards.",
  "Today": "Today's stats at a glance.",
  "Backtest": "Test a strategy on past data to see if it would have worked.",
  "Optimize": "Walk-forward test: checks whether an edge is real or just curve-fit.",
  "Depth": "Liquidity heatmap: green = buy orders, red = sell orders, over price × time.",
  /* table headers */
  "Symbol": "Ticker of the stock.",
  "Sector": "Industry group the stock belongs to.",
  "Qty": "Number of shares. Negative = a short position.",
  "Entry": "The average price the position was opened at.",
  "Last": "The most recent traded price.",
  "Mkt Val": "Current value of the position. Negative when you are short.",
  "Mkt val": "Current value of the position. Negative when you are short.",
  "Weight": "This position as a percentage of your equity.",
  "P&L": "Profit or loss for this row (green = gain, red = loss).",
  "Realized": "Profit already locked in by closing trades (does not include open ones).",
  "%": "The profit/loss shown as a percentage.",
  "Time": "When this happened.",
  "Date": "The trading day.",
  "Start": "Account equity at the start of the day.",
  "End": "Account equity at the end of the day.",
  "Tr": "Number of trades that day.",
  "Side": "Direction of the order: buy or sell.",
  "Type": "Order type (e.g. market = fill immediately, limit = only at a set price).",
  "Status": "Whether the order filled, is pending, or was cancelled.",
  "Fill": "The average price the order actually filled at.",
  "Action": "What the bot decided: BUY, SELL or HOLD.",
  "Conf": "Confidence in the decision, from 0% to 100%.",
  "Regime": "Market state the bot sees (trend up, range, risk-off, etc.).",
  "Exec": "✓ = the decision became a real order; — = it was filtered out.",
  "Reasoning": "Why the bot made this decision.",
  "RR": "Reward-to-risk ratio: how much you stand to gain versus what you risk.",
  "Stop": "Stop price: where the trade exits automatically to limit a loss.",
  "Target": "Target price: where the trade takes profit.",
  "Signals": "Which strategy signals fired for this idea.",
  "%Chg": "Percentage change in price today.",
  "RelVol": "Relative volume: today's volume versus its normal (1.0x = average).",
  "Vol": "Number of shares traded.",
  "RSI": "Momentum gauge. Above 70 = overbought, below 30 = oversold.",
  "ADX": "Trend-strength gauge. Higher = a stronger trend.",
  "ATR%": "Average daily range as a percentage of price (how jumpy it is).",
  "Trend": "Whether price is trending up, down, or sideways.",
  "Conditions": "The rule this alert watches.",
  /* metrics */
  "Win Rate": "Percentage of trades that made money.",
  "Win rate": "Percentage of trades that made money.",
  "Win%": "Percentage of trades that made money.",
  "Profit Factor": "Total winnings ÷ total losses. Above 1 means profitable overall.",
  "Profit factor": "Total winnings ÷ total losses. Above 1 means profitable overall.",
  "PF": "Profit factor: total winnings ÷ total losses. Above 1 = profitable.",
  "Expectancy": "Average profit (or loss) you can expect per trade.",
  "Exp": "Expectancy: average profit or loss per trade.",
  "Avg Win": "The average size of your winning trades.",
  "Avg win": "The average size of your winning trades.",
  "Avg Loss": "The average size of your losing trades.",
  "Avg loss": "The average size of your losing trades.",
  "Max DD": "Max drawdown: the biggest drop from a peak in account value.",
  "MaxDD": "Max drawdown: the biggest drop from a peak in account value.",
  "Sharpe": "Return earned per unit of risk taken. Higher is better.",
  "Best": "The symbol that made the most money.",
  "Worst": "The symbol that lost the most money.",
  "Trades": "Number of trades.",
  "Cash": "Uninvested cash. It can look large when short — that money isn't really yours.",
  "Gross exp": "Total position value (longs + shorts) as a % of equity.",
  "Net exp": "Longs minus shorts as a % of equity (directional exposure).",
  "Open pos": "How many positions are open.",
  "HHI": "Concentration score. Higher = a few positions carry most of the risk.",
  "Top weight": "Your single biggest position as a % of equity.",
  "Top-3": "Your three biggest positions combined as a % of equity.",
  "Mood": "The bot's emotional state (calm, confident, frustrated, tilted...).",
  "Size mult": "How much the bot scales trade size right now (it shrinks when stressed).",
  "Trading IQ": "A combined discipline score built from the bot's recent behaviour.",
  "Discipline": "How well the bot is sticking to its rules.",
  "Trades seen": "Total trades the psychology layer has watched.",
  "Loss streak": "How many losses in a row.",
  "Win streak": "How many wins in a row.",
  "Drawdown": "How far below the peak account value you currently are.",
  "Peak profit": "Best profit level reached today.",
  "Protect floor": "The equity level the bot won't let you fall back below.",
  "Cooldown": "Time the bot is sitting out after losses.",
  "Day P&L": "The account's profit or loss for today.",
  "Universe": "How many symbols the bot is watching.",
  /* tape */
  "VWAP": "Volume-weighted average price: the average price everyone paid.",
  "Buy Vol": "Volume traded on the buy side.",
  "Sell Vol": "Volume traded on the sell side.",
  "Cum Δ": "Cumulative delta: net buying minus selling pressure.",
  /* depth */
  "ASK": "The lowest price a seller will accept right now.",
  "BID": "The highest price a buyer will offer right now.",
};

function applyTips(root) {
  const scope = root || document;
  scope.querySelectorAll("[data-tip], label, th, button, .railbtn, .tab").forEach((el) => {
    if (el.dataset.tipApplied) return;
    const key = (el.getAttribute("data-tip") || el.textContent || "").trim();
    const t = TIPS[key];
    if (t) { el.setAttribute("title", t); el.dataset.tipApplied = "1"; }
  });
}

/* surface any client error on the dashboard instead of failing silently */
window.onerror = (msg, src, line) => {
  pushToast({ level: "error", msg: "JS: " + msg + " @" + (src || "").split("/").pop() + ":" + line });
};
window.addEventListener("unhandledrejection", (e) => {
  pushToast({ level: "warn", msg: "async: " + (e.reason && e.reason.message ? e.reason.message : e.reason) });
});

/* accent tone follows the day's P&L: green when up, red when down */
function applyTone(pnl) {
  const tone = pnl == null ? "flat" : pnl > 0 ? "profit" : pnl < 0 ? "loss" : "flat";
  if (document.documentElement.dataset.tone !== tone) document.documentElement.dataset.tone = tone;
}
function fmtClock(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString([], { weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", timeZone: "America/New_York" }) + " ET";
}
function setConn(state) {
  const el = $("connState");
  if (!el) return;
  const map = { live: ["ok", "LIVE"], rest: ["ok", "LIVE · polling"],
    connecting: ["muted", "connecting…"], down: ["warn", "reconnecting…"] };
  const [k, label] = map[state] || map.connecting;
  el.className = "pill " + k;
  el.textContent = label;
}
function renderMarketState(bot) {
  const open = !!bot.market_open;
  const clock = bot.clock || {};
  const nextOpen = fmtClock(clock.next_open);
  const banner = $("mktBanner"), title = $("mktBannerTitle"), text = $("mktBannerText");
  const cc = $("chartClosed"), cct = $("chartClosedText"), mkt = $("mkt");
  if (open) {
    if (banner) banner.classList.add("hidden");
    if (cc) cc.classList.add("hidden");
    if (mkt) mkt.innerHTML = '<span class="pos">OPEN</span>';
    return;
  }
  if (banner) banner.classList.remove("hidden");
  if (title) title.textContent = "MARKET CLOSED";
  if (text) text.textContent = nextOpen ? "· reopens " + nextOpen : "· outside regular trading hours";
  if (cc) cc.classList.remove("hidden");
  if (cct) cct.textContent = nextOpen ? "Showing last session · reopens " + nextOpen : "Showing last session";
  if (mkt) mkt.innerHTML = '<span class="warn">CLOSED</span>';
}

/* ----------------------------- chart ----------------------------- */
const chartLibOk = () => typeof LightweightCharts !== "undefined";

function initChart() {
  const el = $("chart");
  if (!chartLibOk()) {
    // charts engine may still be loading: retry briefly, then show a clear fallback
    state._chartRetry = (state._chartRetry || 0) + 1;
    if (state._chartRetry <= 4) {
      if (!state._chartTimer) {
        state._chartTimer = setTimeout(() => {
          state._chartTimer = null;
          try { initChart(); } catch (e) { console.warn(e); }
        }, 700);
      }
      if (el) el.innerHTML = '<div class="chartfallback">Loading chart engine…</div>';
      return;
    }
    if (el) el.innerHTML = '<div class="chartfallback">Charts lib could not load. ' +
      'Live panels, tape, positions, news and bot are still running.</div>';
    return;
  }
  if (state.chart) return;
  try {
    state.chart = LightweightCharts.createChart(el, {
    layout: { background: { color: "#000000" }, textColor: "#8b98a9" },
    grid: { vertLines: { color: "#141418" }, horzLines: { color: "#141418" } },
    rightPriceScale: { borderColor: "#2b3444" },
    timeScale: { borderColor: "#2b3444", timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    autoSize: true,
  });
  state.candle = state.chart.addCandlestickSeries({
    upColor: "#26a69a", downColor: "#ef5350", borderVisible: false,
    wickUpColor: "#26a69a", wickDownColor: "#ef5350",
  });
  state.volume = state.chart.addHistogramSeries({
    priceFormat: { type: "volume" }, priceScaleId: "",
  });
  state.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  const line = (color, width, dashed) =>
    state.chart.addLineSeries({
      color, lineWidth: width, priceLineVisible: false, lastValueVisible: false,
      lineStyle: dashed ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
    });
  state.overlays = {
    vwap: line("#f0b90b", 2, false),
    vwap_upper: line("#5b6472", 1, true),
    vwap_lower: line("#5b6472", 1, true),
    ema9: line("#4c8dff", 1, false),
    ema21: line("#a78bfa", 1, false),
    ema50: line("#ff9800", 1, false),
  };
  state.chart.timeScale().subscribeVisibleTimeRangeChange(drawVP);
  new ResizeObserver(() => drawVP()).observe(el.parentElement);
  } catch (e) {
    console.warn("initChart failed", e);
    el.innerHTML = '<div class="chartfallback">Chart failed to initialise: ' + esc(e.message) + '</div>';
  }
}

function clearPriceLines() {
  (state.priceLines || []).forEach((pl) => {
    try { state.candle.removePriceLine(pl); } catch (e) {}
  });
  state.priceLines = [];
}

function addPriceLine(price, color, title, style) {
  if (price == null) return;
  const pl = state.candle.createPriceLine({
    price, color, lineWidth: 1,
    lineStyle: style || LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true, title: title || "",
  });
  state.priceLines.push(pl);
}

async function loadChart() {
  try {
    const tf = state.tf || "5Min";
    const r = await fetch(`/api/market/bars?symbol=${state.symbol}&timeframe=${encodeURIComponent(tf)}&limit=300`);
    const d = await r.json();
    state.lastBars = d;
    if (d.error) return;
    state.candle.setData(d.candles);
    state.volume.setData(d.volume);
    for (const [k, series] of Object.entries(state.overlays)) {
      series.setData(d.overlays[k] || []);
    }
    state.chart.timeScale().fitContent();
    state.vp = d.volume_profile;

    clearPriceLines();
    const vp = d.volume_profile || {};
    addPriceLine(vp.poc, "#f0b90b", "POC");
    addPriceLine(vp.vah, "#4c8dff", "VAH");
    addPriceLine(vp.val, "#4c8dff", "VAL");
    const an = d.analysis || {};
    addPriceLine(an.stop, "#ef5350", "Stop");
    addPriceLine(an.target, "#26a69a", "Target");

    const last = d.candles[d.candles.length - 1];
    if (last) $("chartPrice").textContent = money(last.close);
    renderSignals(an);
    $("chartLegend").textContent = `${state.symbol} · ${state.tf} · VWAP + EMA9/21/50`;
    drawVP();
  } catch (e) { console.warn("chart", e); }
}

function renderSignals(an) {
  const bar = $("signalBar");
  if (!an || !an.action) { bar.innerHTML = ""; return; }
  const dir = an.action === "BUY" ? "buy" : an.action === "SELL" ? "sell" : "hold";
  const chips = (an.signals || [])
    .map((s) => `<span class="chip" title="${esc(s.reason)}">${esc(s.name)}</span>`).join("");
  const f = an.features || {};
  bar.innerHTML =
    `<span class="chip ${dir}">${an.action} ${(an.confidence * 100).toFixed(0)}%</span>` +
    `<span class="chip regime">${esc(an.regime)}</span>` +
    `<span class="chip">RSI ${f.rsi}</span><span class="chip">ADX ${f.adx}</span>` +
    `<span class="chip">RVOL ${f.rvol}</span><span class="chip">VPIN ${f.vpin}</span>` +
    `<span class="chip">Δ ${f.delta_imbalance}%</span>` +
    `&nbsp;${chips}`;
}

/* volume profile overlay */
function drawVP() {
  const cv = $("vpCanvas");
  if (!cv || !state.vp || !state.candle) return;
  const wrap = cv.parentElement;
  const dpr = window.devicePixelRatio || 1;
  const w = wrap.clientWidth, h = wrap.clientHeight;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const hist = state.vp.hist || [];
  if (!hist.length) return;
  const maxV = Math.max(...hist.map((p) => p.volume)) || 1;
  const maxBar = Math.min(140, w * 0.35);
  const right = w - 60;
  hist.forEach((p) => {
    const y = state.candle.priceToCoordinate(p.price);
    if (y == null) return;
    const bw = (p.volume / maxV) * maxBar;
    ctx.fillStyle = p.price === state.vp.poc ? "rgba(240,185,11,0.55)" : "rgba(76,141,255,0.28)";
    ctx.fillRect(right - bw, y - 3, bw, 6);
  });
}

/* ----------------------------- snapshot ----------------------------- */
function renderSnapshot(s) {
  state.snap = s;
  const a = s.account || {}, bot = s.bot || {};
  const badge = $("modeBadge");
  badge.textContent = s.mode;
  badge.className = "badge " + s.mode.toLowerCase();
  const simBadge = $("simBadge");
  if (simBadge) {
    const fake = s.mode !== "DEMO" && s.tape && s.tape.demo;
    simBadge.style.display = fake ? "" : "none";
  }
  $("equity").textContent = money(a.equity);
  const dp = a.day_pnl || 0;
  $("daypnl").innerHTML = `<span class="${cls(dp)}">${money(dp)} (${pct(a.day_pnl_pct)})</span>`;
  $("bp").textContent = money(a.buying_power);
  $("npos").textContent = (s.positions || []).length;
  applyTone(a.day_pnl);
  renderMarketState(bot);
  setConn(_wsOk ? "live" : "rest");
  const llm = bot.llm || {};
  $("llmState").textContent = llm.enabled ? llm.provider : "rules";
  $("llmState").className = llm.enabled ? "pos" : "muted";
  if ($("uni")) $("uni").textContent = bot.universe_size != null ? bot.universe_size : "--";

  const btn = $("botToggle"), pill = $("botState");
  btn.textContent = bot.running ? "Stop Bot" : "Start Bot";
  btn.className = "btn " + (bot.running ? "" : "primary");
  pill.textContent = bot.running ? (bot.market_open ? "running" : "armed · market closed") : "stopped";
  pill.className = "pill " + (bot.running ? "on" : "");
  $("scanInterval").value = bot.scan_interval || 30;
  if (document.activeElement !== $("watchlist")) $("watchlist").value = (bot.universe || []).join(",");

  const safe = (fn, label) => { try { fn(); } catch (e) { console.warn(label, e); } };
  safe(() => renderPositions(s.positions || []), "positions");
  safe(() => followBot(s.positions || []), "follow");
  safe(() => renderOrders(s.orders || []), "orders");
  safe(() => renderNews(s.news || []), "news");
  safe(() => renderLog(s.log || []), "log");
  safe(() => renderReasoning(s.decisions || []), "reasoning");
  safe(() => renderMind(s.psyche), "mind");
  safe(() => renderToday(s), "today");
  safe(() => renderTicker(s), "ticker");
  safe(() => renderToasts(s.log || []), "toasts");
  if (s.tape) safe(() => renderTape(s.tape), "tape");
  safe(() => loadTrades(), "trades");
}

/* ----------------------------- ticker ----------------------------- */
function renderTicker(s) {
  const el = $("tickerItems");
  if (!el || !s) return;
  const book = (s.tape && s.tape.book) || {};
  const pos = {};
  (s.positions || []).forEach((p) => { pos[p.symbol] = p.unrealized_plpc; });
  const items = Object.values(book).map((b) => {
    const ch = pos[b.symbol];
    const c = ch > 0 ? "pos" : ch < 0 ? "neg" : "muted";
    return `<span class="bitem"><span class="bs">${esc(b.symbol)}</span>` +
      `<span class="bl">${money(b.last)}</span>` +
      `<span class="${c}">${ch == null ? "" : pct(ch)}</span></span>`;
  }).join("");
  if (!items) return;
  el.innerHTML = items + items;
}

/* ----------------------------- toasts ----------------------------- */
let _toastSeen = 0;
function renderToasts(log) {
  if (!log || !log.length) return;
  const fresh = log.filter((l) => l.ts > _toastSeen &&
    (l.level === "error" || l.level === "warn" || l.level === "trade")).slice(0, 3);
  _toastSeen = Math.max(_toastSeen, log[0].ts || 0);
  fresh.reverse().forEach(pushToast);
}
function pushToast(l) {
  const box = $("toasts");
  if (!box) return;
  const d = document.createElement("div");
  d.className = "toast " + esc(l.level);
  d.innerHTML = `<b>${esc((l.level || "").toUpperCase())}</b> · ${esc(l.msg)}`;
  box.appendChild(d);
  setTimeout(() => d.remove(), 9000);
}

function renderPositions(ps) {
  if (!ps.length) { $("tab-positions").innerHTML = '<p class="muted">No open positions.</p>'; return; }
  let h = "<table><thead><tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Last</th><th>Mkt Val</th><th>P&L</th><th>%</th><th></th></tr></thead><tbody>";
  for (const p of ps) {
    h += `<tr><td class="sym clickable" onclick="openResearch('${esc(p.symbol)}')">${esc(p.symbol)}</td><td>${p.qty}</td>
      <td>${money(p.avg_entry)}</td><td>${money(p.current_price)}</td>
      <td>${money(p.market_value)}</td>
      <td class="${cls(p.unrealized_pl)}">${money(p.unrealized_pl)}</td>
      <td class="${cls(p.unrealized_pl)}">${pct(p.unrealized_plpc)}</td>
      <td><button class="btn" onclick="closeSym('${esc(p.symbol)}')">Close</button></td></tr>`;
  }
  $("tab-positions").innerHTML = h + "</tbody></table>";
}

function followBot(ps) {
  if (!state.follow) return;
  let sym = null;
  if (ps && ps.length) {
    const ranked = ps.slice().sort((a, b) =>
      Math.abs(b.unrealized_pl || 0) - Math.abs(a.unrealized_pl || 0));
    sym = ranked[0] && ranked[0].symbol;
  }
  if (!sym) sym = state.autoSym;
  if (!sym) return;
  sym = String(sym).toUpperCase();
  if (sym === state.symbol) return;
  state.symbol = sym;
  const si = $("symbolInput"); if (si) si.value = sym;
  loadChart();
}

function renderOrders(os) {
  if (!os.length) { $("tab-orders").innerHTML = '<p class="muted">No orders yet.</p>'; return; }
  let h = "<table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Type</th><th>Status</th><th>Fill</th></tr></thead><tbody>";
  for (const o of os) {
    h += `<tr><td>${esc((o.submitted_at || "").slice(11, 19))}</td><td><b>${esc(o.symbol)}</b></td>
      <td class="${o.side === "buy" ? "pos" : "neg"}">${esc(o.side)}</td><td>${esc(o.filled_qty || o.qty)}</td>
      <td>${esc(o.type)}</td><td>${esc(o.status)}</td><td>${o.filled_avg_price ? money(o.filled_avg_price) : "--"}</td></tr>`;
  }
  $("tab-orders").innerHTML = h + "</tbody></table>";
}

function renderNews(news) {
  if (!news.length) { $("tab-news").innerHTML = '<p class="muted">No news yet.</p>'; return; }
  $("tab-news").innerHTML = news.map((n) => {
    const s = n.sentiment || 0;
    const sc = s > 0.1 ? "sent-pos" : s < -0.1 ? "sent-neg" : "muted";
    return `<div class="news-item"><div class="hl">${esc(n.headline)}</div>
      <div class="meta"><span class="${sc}">${s >= 0 ? "+" : ""}${s.toFixed(2)}</span>
      · ${esc(n.source || "")} · ${esc((n.symbol || ""))} · ${tstr(n.ts)}</div></div>`;
  }).join("");
}

function renderLog(log) {
  $("tab-log").innerHTML = log.map((l) =>
    `<div class="logrow ${esc(l.level)}"><span class="t">${tstr(l.ts)}</span>${esc(l.msg)}</div>`).join("");
}

function renderReasoning(decs) {
  if (!decs.length) { $("tab-reasoning").innerHTML = '<p class="muted">No decisions logged yet.</p>'; return; }
  const ex = decs.filter((d) => d.executed);
  if (ex.length) {
    ex.sort((a, b) => ((a.ts || "") < (b.ts || "") ? 1 : -1));
    state.autoSym = ex[0].symbol;
  }
  let h = "<table><thead><tr><th>Time</th><th>Sym</th><th>Action</th><th>Conf</th><th>Regime</th><th>Exec</th><th>Reasoning</th></tr></thead><tbody>";
  for (const d of decs) {
    let reasons = d.reasons;
    try { reasons = JSON.parse(d.reasons); } catch (e) {}
    const rz = Array.isArray(reasons) ? reasons.join(" · ") : reasons;
    const act = (d.action || "").toLowerCase();
    h += `<tr><td>${tstr(d.ts)}</td><td><b>${esc(d.symbol)}</b></td>
      <td><span class="chip ${act === "buy" ? "buy" : act === "sell" ? "sell" : "hold"}">${esc(d.action)}</span></td>
      <td>${((d.confidence || 0) * 100).toFixed(0)}%</td>
      <td><span class="chip regime">${esc(d.regime || "")}</span></td>
      <td>${d.executed ? '<span class="pos">✓</span>' : `<span class="muted" title="${esc(d.error || "")}">—</span>`}</td>
      <td style="white-space:normal;max-width:520px">${esc(rz)}</td></tr>`;
  }
  $("tab-reasoning").innerHTML = h + "</tbody></table>";
}

function metric(label, value, klass) {
  return `<div class="metric"><label>${label}</label><b class="${klass || ""}">${value}</b></div>`;
}

const MOOD_CLASS = {
  CONFIDENT: "pos", CALM: "muted", CAUTIOUS: "warn",
  STRESSED: "neg", FRUSTRATED: "neg", TILTED: "neg", HALTED: "neg",
};

function renderMind(p) {
  const el = $("tab-mind");
  if (!el) return;
  if (!p) { el.innerHTML = '<p class="muted">No psychology data yet.</p>'; return; }
  const mk = MOOD_CLASS[p.state] || "muted";
  const pf = p.profit_factor == null ? "∞/--" : p.profit_factor;
  let h = `<div class="mind-head"><span class="verdict ${mk}">${esc(p.state)}</span>` +
          `<span class="muted small">size ×${p.size_mult} · IQ ${p.iq} · discipline ${p.discipline}</span></div>`;
  h += '<div class="metric-grid">' +
    metric("Mood", `<span class="${mk}">${esc(p.state)}</span>`) +
    metric("Size mult", `×${p.size_mult}`) +
    metric("Trading IQ", p.iq) +
    metric("Discipline", p.discipline) +
    metric("Win rate", pct(p.win_rate)) +
    metric("Profit factor", pf) +
    metric("Expectancy", money(p.expectancy)) +
    metric("Trades seen", p.trades_seen) +
    metric("Loss streak", p.loss_streak) +
    metric("Win streak", p.win_streak) +
    metric("Drawdown", pct(-Math.abs(p.drawdown))) +
    metric("Peak profit", money(p.peak_profit)) +
    metric("Protect floor", p.protect_floor == null ? "--" : money(p.protect_floor)) +
    metric("Cooldown", p.cooldown_remaining > 0 ? Math.round(p.cooldown_remaining) + "s" : "--") +
    "</div>";
  if (!p.can_trade) {
    h += `<div class="verdict neg">Sitting out: ${esc(p.block_reason || "risk governor")}</div>`;
    h += '<button class="btn primary" onclick="resumeMind()">Resume desk</button>';
  } else {
    h += `<div class="verdict pos">Clear to trade — ${esc(p.state.toLowerCase())}, sizing ×${p.size_mult}</div>`;
  }
  const v = p.violations || {};
  h += `<p class="muted small">Guards — cooldowns ${v.cooldown_hits || 0} · tilt ${v.tilt_events || 0} · ` +
       `overtrade ${v.overtrade_hits || 0} · profit-floor ${v.profit_floor_hits || 0} · daily-stop ${v.daily_stop_hits || 0}</p>`;
  if ((p.events || []).length) {
    h += '<table><thead><tr><th>Time</th><th>Kind</th><th>Note</th></tr></thead><tbody>';
    for (const e of p.events) {
      h += `<tr><td>${tstr(e.ts)}</td><td>${esc(e.kind)}</td><td style="white-space:normal">${esc(e.msg)}</td></tr>`;
    }
    h += "</tbody></table>";
  }
  el.innerHTML = h;
}

function renderToday(s) {
  const today = (s.daily_stats || [])[0];
  if (!today) { $("tab-today").innerHTML = '<p class="muted">No stats for today yet.</p>'; return; }
  $("tab-today").innerHTML =
    '<div class="metric-grid">' +
    metric("Day P&L", `<span class="${cls(today.pnl)}">${money(today.pnl)} (${pct(today.pnl_pct)})</span>`) +
    metric("Realized", `<span class="${cls(today.realized_pnl)}">${money(today.realized_pnl)}</span>`) +
    metric("Trades", today.num_trades) +
    metric("Win Rate", pct(today.win_rate)) +
    metric("Profit Factor", today.profit_factor) +
    metric("Expectancy", money(today.expectancy)) +
    metric("Avg Win", money(today.avg_win)) +
    metric("Avg Loss", money(today.avg_loss)) +
    metric("Max DD", money(today.max_drawdown)) +
    metric("Sharpe", today.sharpe) +
    metric("Best", today.best_symbol || "--") +
    metric("Worst", today.worst_symbol || "--") +
    "</div>";
}

async function loadTrades() {
  const r = await fetch("/api/trades?limit=200");
  const ts = await r.json();
  if (!ts.length) { $("tab-trades").innerHTML = '<p class="muted">No closed trades yet.</p>'; return; }
  let h = "<table><thead><tr><th>Time</th><th>Sym</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th><th>%</th><th>Reason</th></tr></thead><tbody>";
  for (const t of ts) {
    h += `<tr><td>${tstr(t.ts)}</td><td><b>${esc(t.symbol)}</b></td><td>${esc(t.side)}</td>
      <td>${t.qty}</td><td>${money(t.entry_price)}</td><td>${money(t.exit_price)}</td>
      <td class="${cls(t.pnl)}">${money(t.pnl)}</td>
      <td class="${cls(t.pnl)}">${pct(t.pnl_pct)}</td><td>${esc(t.reason || "")}</td></tr>`;
  }
  $("tab-trades").innerHTML = h + "</tbody></table>";
}

async function loadDaily() {
  const r = await fetch("/api/stats/daily?limit=90");
  const ds = await r.json();
  if (!ds.length) { $("tab-daily").innerHTML = '<p class="muted">No daily history yet.</p>'; return; }
  let h = "<table><thead><tr><th>Date</th><th>Start</th><th>End</th><th>P&L</th><th>Realized</th><th>%</th><th>Tr</th><th>Win%</th><th>PF</th><th>Exp</th><th>MaxDD</th><th>Sharpe</th><th>Best</th><th>Worst</th></tr></thead><tbody>";
  for (const d of ds) {
    h += `<tr><td>${esc(d.date)}</td><td>${money(d.start_equity)}</td><td>${money(d.end_equity)}</td>
      <td class="${cls(d.pnl)}">${money(d.pnl)}</td>
      <td class="${cls(d.realized_pnl)}">${d.realized_pnl == null ? "--" : money(d.realized_pnl)}</td>
      <td class="${cls(d.pnl)}">${pct(d.pnl_pct)}</td>
      <td>${d.num_trades}</td><td>${pct(d.win_rate)}</td><td>${d.profit_factor}</td>
      <td>${money(d.expectancy)}</td><td>${money(d.max_drawdown)}</td><td>${d.sharpe}</td>
      <td>${esc(d.best_symbol || "")}</td><td>${esc(d.worst_symbol || "")}</td></tr>`;
  }
  $("tab-daily").innerHTML = h + "</tbody></table>";
}

/* ----------------------------- tape / L2 ----------------------------- */
function fmtSize(v) {
  if (v == null) return "--";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "k";
  return String(Math.round(v));
}

function updateBBO(sym, t) {
  if (sym !== state.symbol || !t || !t.bid || !t.ask) return;
  const style = LightweightCharts.LineStyle.Dotted;
  if (!state.bbo) {
    state.bbo = {
      bid: state.candle.createPriceLine({ price: t.bid, color: "#26a69a", lineWidth: 1, lineStyle: style, axisLabelVisible: true, title: "BID" }),
      ask: state.candle.createPriceLine({ price: t.ask, color: "#ef5350", lineWidth: 1, lineStyle: style, axisLabelVisible: true, title: "ASK" }),
    };
  } else {
    state.bbo.bid.applyOptions({ price: t.bid });
    state.bbo.ask.applyOptions({ price: t.ask });
  }
}

function renderTape(tape) {
  state.tape = tape;
  const book = (tape && tape.book) || {};
  const sel = book[state.symbol] || Object.values(book)[0];
  const panel = $("tab-tape");
  if (!sel) { panel.innerHTML = '<p class="muted">Waiting for tape...</p>'; return; }
  updateBBO(sel.symbol, sel);

  const imb = sel.imbalance || 0;
  const imbPct = Math.round((imb + 1) / 2 * 100);
  const src = tape.demo ? '<span class="chip">demo tape</span>' : '<span class="chip">IEX live</span>';

  const ts = (sel.trades || []).slice(0, 16).map((t) =>
    `<div class="tsrow ${t.side}"><span>${tstr(t.ts)}</span><span>${money(t.price)}</span><span>${fmtSize(t.size)}</span></div>`).join("");

  const picker = Object.values(book).map((b) =>
    `<button class="chip ${b.symbol === sel.symbol ? "buy" : ""}" onclick="pickTape('${esc(b.symbol)}')">${esc(b.symbol)}</button>`).join("");

  panel.innerHTML =
    `<div class="tapeHead">${src} <span class="muted">top-of-book NBBO</span> <span class="mono">${money(sel.last)}</span></div>
     <div class="ladder">
       <div class="lrow ask"><span class="side">ASK</span><b>${money(sel.ask)}</b><span class="sz">${fmtSize(sel.ask_size)}</span></div>
       <div class="mid"><span class="muted">spread ${sel.spread}</span><b>${esc(sel.symbol)}</b><span>${money(sel.last)}</span></div>
       <div class="lrow bid"><span class="side">BID</span><b>${money(sel.bid)}</b><span class="sz">${fmtSize(sel.bid_size)}</span></div>
     </div>
     <div class="imbwrap"><div class="imbbar" style="width:${imbPct}%"></div></div>
     <div class="muted small">book imbalance ${(imb * 100).toFixed(1)}% bid-heavy</div>
     <div class="metric-grid tapeMetrics">
       ${metric("Cum Δ", `<span class="${cls(sel.cum_delta)}">${fmtSize(sel.cum_delta)}</span>`)}
       ${metric("VWAP", money(sel.vwap))}
       ${metric("Buy Vol", fmtSize(sel.buy_vol))}
       ${metric("Sell Vol", fmtSize(sel.sell_vol))}
     </div>
     <div class="tapePicker">${picker}</div>
     <h4>Time &amp; Sales</h4>
     <div class="tape">${ts || '<span class="muted">no prints</span>'}</div>`;
}

function pickTape(sym) {
  state.symbol = sym;
  $("symbolInput").value = sym;
  loadChart();
}

/* ----------------------------- equity curve ----------------------------- */
function initEquityChart() {
  const el = $("equityChart");
  if (!chartLibOk()) {
    if (!state._eqRetry) {
      state._eqRetry = setTimeout(() => { try { initEquityChart(); } catch (e) {} }, 700);
    }
    return;
  }
  if (state.eqChart) return;
  try {
    state.eqChart = LightweightCharts.createChart(el, {
      layout: { background: { color: "#000000" }, textColor: "#8b98a9" },
      grid: { vertLines: { color: "#111114" }, horzLines: { color: "#111114" } },
      rightPriceScale: { borderColor: "#2b3444" },
      timeScale: { borderColor: "#2b3444", timeVisible: true, secondsVisible: false },
      autoSize: true,
    });
    state.eqSeries = state.eqChart.addAreaSeries({
      lineColor: "#4c8dff", topColor: "rgba(76,141,255,0.35)", bottomColor: "rgba(76,141,255,0.02)",
      lineWidth: 2,
    });
    new ResizeObserver(() => state.eqChart && state.eqChart.applyOptions({})).observe(el);
  } catch (e) {
    console.warn("initEquityChart failed", e);
    el.innerHTML = '<div class="chartfallback">Equity chart failed: ' + esc(e.message) + '</div>';
  }
}

async function loadEquity() {
  try {
    const [eq, ov] = await Promise.all([
      fetch("/api/stats/equity?limit=20000").then((r) => r.json()),
      fetch("/api/stats/overall").then((r) => r.json()),
    ]);
    if (state.eqSeries && eq.length) {
      const seen = new Set();
      const data = eq.filter((p) => {
        if (p.equity == null || seen.has(p.ts)) return false;
        seen.add(p.ts); return true;
      }).map((p) => ({ time: Math.floor(p.ts), value: p.equity }));
      state.eqSeries.setData(data);
      state.eqChart.timeScale().fitContent();
    }
    const el = $("tab-equity");
    el.querySelectorAll(".eqstats").forEach((n) => n.remove());
    const div = document.createElement("div");
    div.className = "metric-grid eqstats";
    div.innerHTML =
      metric("Net P&L", `<span class="${cls(ov.total_pnl)}">${money(ov.total_pnl)} (${pct(ov.total_pnl_pct)})</span>`) +
      metric("Trades", ov.num_trades) + metric("Win Rate", pct(ov.win_rate)) +
      metric("Profit Factor", ov.profit_factor) + metric("Expectancy", money(ov.expectancy)) +
      metric("Max DD", money(ov.max_drawdown)) + metric("Sharpe", ov.sharpe);
    el.prepend(div);
  } catch (e) { console.warn("equity", e); }
}

/* ----------------------------- controls ----------------------------- */
async function botToggle() {
  const running = state.snap && state.snap.bot && state.snap.bot.running;
  await fetch(`/api/bot/${running ? "stop" : "start"}`, { method: "POST" });
}
async function closeSym(sym) {
  await fetch(`/api/bot/close/${sym}`, { method: "POST" });
}
async function resumeMind() {
  try {
    await fetch("/api/mind/resume", { method: "POST" });
    toast("Desk resumed - halts and cooldowns cleared");
  } catch (e) { toast("Resume failed"); }
}
window.resumeMind = resumeMind;
async function applyCfg() {
  const universe = $("watchlist").value.split(",").map((s) => s.trim()).filter(Boolean);
  const scan_interval = parseInt($("scanInterval").value) || 30;
  await fetch("/api/bot/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ universe, scan_interval }),
  });
}
async function runBacktest() {
  const symbol = $("btSymbol").value.toUpperCase();
  const timeframe = $("btTf").value;
  const limit = parseInt($("btLimit").value) || 600;
  const rr = parseFloat($("btRr").value) || 2;
  const atr_mult = parseFloat($("btAtr").value) || 1.5;
  const min_conf = parseFloat($("btConf").value) || 0.55;
  $("btStatus").textContent = "running...";
  const r = await fetch("/api/backtest", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, timeframe, limit, rr, atr_mult, min_conf }),
  });
  const d = await r.json();
  $("btStatus").textContent = "";
  const s = d.stats || {};
  $("btResult").innerHTML =
    '<div class="metric-grid">' +
    metric("Trades", s.num_trades) + metric("Win Rate", pct(s.win_rate)) +
    metric("Net P&L", `<span class="${cls(s.total_pnl)}">${money(s.total_pnl)}</span>`) +
    metric("Profit Factor", s.profit_factor) + metric("Expectancy", money(s.expectancy)) +
    metric("Max DD", money(s.max_drawdown)) + metric("Sharpe", s.sharpe) +
    metric("Avg Win", money(s.avg_win)) + metric("Avg Loss", money(s.avg_loss)) +
    '</div>';
}

/* ----------------------------- depth heatmap ----------------------------- */
async function loadDepth() {
  const sym = ($("depthSymbol").value || state.symbol).toUpperCase();
  try {
    const d = await fetch(`/api/market/depth?symbol=${sym}&frames=90`).then((r) => r.json());
    drawDepth(d);
    $("depthMeta").textContent =
      `${sym} · ${(d.cells || []).length} price levels · ${(d.times || []).length} frames${
        d.demo ? " · demo depth" : " · live BBO"}`;
  } catch (e) { /* ignore */ }
}

function drawDepth(d) {
  const cv = $("depthCanvas");
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(320, cv.parentElement.clientWidth - 4);
  const h = 260;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + "px"; cv.style.height = h + "px";
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const cells = d.cells || [];
  const nR = cells.length;
  const nC = nR ? cells[0].length : 0;
  if (!nR || !nC) {
    ctx.fillStyle = "#5b6472"; ctx.font = "12px monospace";
    ctx.fillText("collecting tape...", 10, 20);
    return;
  }
  const padL = 64, padT = 6, padB = 16;
  const cw = (w - padL) / nC, ch = (h - padT - padB) / nR;
  const mx = d.max_abs || 1;
  for (let r = 0; r < nR; r++) {
    const row = cells[r];
    for (let c = 0; c < nC; c++) {
      const v = row[c];
      if (!v) continue;
      const a = Math.min(0.92, (Math.abs(v) / mx) * 0.92);
      ctx.fillStyle = v > 0 ? `rgba(38,166,154,${a})` : `rgba(239,83,80,${a})`;
      ctx.fillRect(padL + c * cw, padT + r * ch, Math.ceil(cw), Math.ceil(ch));
    }
  }
  ctx.fillStyle = "#8b98a9"; ctx.font = "10px monospace";
  const prices = d.prices || [];
  const step = Math.max(1, Math.floor(nR / 9));
  for (let r = 0; r < nR; r += step) {
    const y = padT + r * ch + 8;
    ctx.fillText(Number(prices[r]).toFixed(2), 4, y);
  }
  const times = d.times || [];
  if (times.length) {
    ctx.fillText(new Date(times[0] * 1000).toLocaleTimeString(), padL + 2, h - 4);
    ctx.fillText(new Date(times[times.length - 1] * 1000).toLocaleTimeString(), w - 64, h - 4);
  }
}

/* ----------------------------- walk-forward ----------------------------- */
let wfoTimer = null;

async function runWFO() {
  const symbol = $("wfoSymbol").value.toUpperCase();
  const timeframe = $("wfoTf").value;
  const limit = parseInt($("wfoLimit").value) || 500;
  const stride = parseInt($("wfoStride").value) || 12;
  const regime_method = $("wfoMethod").value;
  $("wfoStatus").textContent = "running...";
  $("wfoResult").innerHTML = "";
  try {
    const j = await fetch("/api/optimize", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, timeframe, limit, stride, regime_method }),
    }).then((r) => r.json());
    if (j.error) { $("wfoStatus").textContent = j.error; return; }
    if (wfoTimer) clearTimeout(wfoTimer);
    pollWFO(j.job_id);
  } catch (e) { $("wfoStatus").textContent = "request failed"; }
}

async function pollWFO(id) {
  try {
    const j = await fetch(`/api/optimize/${id}`).then((r) => r.json());
    if (j.status === "running") {
      $("wfoStatus").textContent = "running (job " + id + ")...";
      wfoTimer = setTimeout(() => pollWFO(id), 2000);
      return;
    }
    if (j.status === "error") { $("wfoStatus").textContent = "error: " + j.error; return; }
    $("wfoStatus").textContent = "done";
    renderWFO(j.result);
    loadWfoRuns();
  } catch (e) { $("wfoStatus").textContent = "poll failed"; }
}

function renderWFO(res) {
  const s = res.summary || {};
  const v = s.verdict || "";
  const vk = v.startsWith("OVERFIT") || v.startsWith("NO OUT") ? "neg"
    : v.startsWith("PROMISING") ? "pos" : "muted";
  let h =
    '<div class="metric-grid">' +
    metric("WFE (OOS/IS)", s.walk_forward_efficiency == null ? "--" : s.walk_forward_efficiency) +
    metric("Mean IS Exp", money(s.mean_is_expectancy)) +
    metric("Mean OOS Exp", `<span class="${cls(s.mean_oos_expectancy)}">${money(s.mean_oos_expectancy)}</span>`) +
    metric("OOS Total P&L", `<span class="${cls(s.oos_total_pnl)}">${money(s.oos_total_pnl)}</span>`) +
    metric("PBO (approx)", s.pbo == null ? "--" : s.pbo) +
    metric("Grid size", res.grid_size) +
    "</div>";
  h += `<div class="verdict ${vk}">${esc(v)}</div>`;
  h += '<table><thead><tr><th>Fold</th><th>Bars (train→test)</th><th>Best params RR/ATR/Conf</th>' +
       '<th>IS Exp</th><th>IS P&L</th><th>OOS Exp</th><th>OOS P&L</th><th>OOS Tr</th></tr></thead><tbody>';
  for (const f of res.folds || []) {
    const p = f.best_params || {};
    h += `<tr><td>${f.fold}</td><td>${f.train_bars}→${f.test_bars}</td>
      <td class="mono">${p.rr} / ${p.atr_mult} / ${p.min_conf}</td>
      <td class="${cls(f.is_expectancy)}">${money(f.is_expectancy)}</td>
      <td class="${cls(f.is_pnl)}">${money(f.is_pnl)}</td>
      <td class="${cls(f.oos_expectancy)}">${money(f.oos_expectancy)}</td>
      <td class="${cls(f.oos_pnl)}">${money(f.oos_pnl)}</td>
      <td>${f.oos_trades}</td></tr>`;
  }
  h += "</tbody></table>";
  h += `<p class="muted small">Best full-sample params: <span class="mono">${
    esc(JSON.stringify(s.best_full_sample_params))}</span> · expectancy ${money(s.best_full_sample_expectancy)}.
    WFE near 1 means the edge holds out-of-sample; ≤ 0 means pure overfit. PBO ≥ 0.6 = high overfitting risk
    (approximate, and noisy on sparse-signal demo data).</p>`;
  h += `<div class="fld"><button id="wfoApply" class="btn">Apply best params to bot</button>` +
       `<span id="wfoApplyMsg" class="muted small"></span></div>`;
  $("wfoResult").innerHTML = h;
  state.lastWfoParams = s.best_full_sample_params || null;
  const ab = $("wfoApply");
  if (ab) ab.onclick = applyWfoParams;
}

async function applyWfoParams() {
  const p = state.lastWfoParams;
  if (!p) { $("wfoApplyMsg").textContent = "no params"; return; }
  const body = { rr: p.rr, atr_mult: p.atr_mult, min_confidence: p.min_conf };
  if (p.risk_pct != null) body.risk_per_trade = p.risk_pct;
  $("wfoApplyMsg").textContent = "applying...";
  try {
    await fetch("/api/bot/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    $("wfoApplyMsg").textContent = "applied to bot limits";
  } catch (e) { $("wfoApplyMsg").textContent = "apply failed"; }
}

async function loadWfoRuns() {
  const el = $("wfoRuns");
  if (!el) return;
  try {
    const runs = await fetch("/api/optimize/runs?limit=20").then((r) => r.json());
    if (!runs || !runs.length) { el.innerHTML = '<p class="muted small">No saved runs yet.</p>'; return; }
    let h = '<table><thead><tr><th>When</th><th>Symbol</th><th>TF</th><th>Method</th>' +
            '<th>Folds</th><th>WFE</th><th>PBO</th><th>OOS P&L</th><th>Verdict</th><th></th></tr></thead><tbody>';
    for (const r of runs) {
      const v = r.verdict || "";
      const vk = v.startsWith("OVERFIT") || v.startsWith("NO OUT") ? "neg"
        : v.startsWith("PROMISING") ? "pos" : "muted";
      const bp = r.best_params || {};
      h += `<tr><td>${new Date(r.ts * 1000).toLocaleString()}</td><td>${esc(r.symbol)}</td>` +
           `<td>${esc(r.timeframe)}</td><td>${esc(r.method)}</td><td>${r.folds}</td>` +
           `<td>${r.wfe == null ? "--" : r.wfe}</td><td>${r.pbo == null ? "--" : r.pbo}</td>` +
           `<td class="${cls(r.oos_pnl)}">${money(r.oos_pnl)}</td>` +
           `<td><span class="verdict ${vk}">${esc(v.split(" - ")[0])}</span></td>` +
           `<td><button class="btn mini" onclick="useRun(${r.id})">Use</button></td></tr>`;
    }
    h += "</tbody></table>";
    el.innerHTML = h;
    el._runs = runs;
  } catch (e) { el.innerHTML = '<p class="muted small">Could not load runs.</p>'; }
}

function useRun(id) {
  const el = $("wfoRuns");
  const r = (el && el._runs || []).find((x) => x.id === id);
  if (!r) return;
  const bp = r.best_params || {};
  $("wfoSymbol").value = r.symbol || "";
  $("wfoTf").value = r.timeframe || "5Min";
  $("wfoMethod").value = r.method || "hybrid";
  state.lastWfoParams = bp;
  $("wfoStatus").textContent = `loaded run #${id}`;
  $("wfoResult").innerHTML = `<p class="muted small">Loaded saved run #${id} (${esc(r.symbol)} ${esc(r.timeframe)}). ` +
    `Params RR/ATR/Conf: <span class="mono">${bp.rr} / ${bp.atr_mult} / ${bp.min_conf}</span>. ` +
    `<button id="wfoApply" class="btn">Apply best params to bot</button> <span id="wfoApplyMsg" class="muted small"></span></p>`;
  const ab = $("wfoApply");
  if (ab) ab.onclick = applyWfoParams;
}

/* ----------------------------- market rail + toolkit ----------------------------- */
const SECTIONS = {
  reasoning: { title: "Terminal · decision log" },
  scanner: { title: "Market scanner", live: loadScanner },
  research: { title: "Stock research", live: () => loadResearch(state.researchSym || state.symbol) },
  ideas: { title: "Ideas & tips", live: loadIdeas },
  portfolio: { title: "Portfolio & risk", live: loadPortfolio },
  journal: { title: "Trade journal", live: loadJournal },
  alerts: { title: "Alerts", live: loadAlerts },
  coach: { title: "Coach · playbook for right now", live: loadCoach },
  library: { title: "Trading library · 100+ books", live: loadLibrary },
  pulse: { title: "Pulse · tips, talks & live wire", live: loadPulse },
  equity: { title: "Equity curve", live: loadEquity },
  trades: { title: "Closed trades", live: loadTrades },
  daily: { title: "Daily performance", live: loadDaily },
  mind: { title: "Psychology & discipline" },
  today: { title: "Today's stats" },
  backtest: { title: "Backtest" },
  wfo: { title: "Walk-forward optimize", live: loadWfoRuns },
  depth: { title: "Liquidity depth", live: loadDepth },
};

function showSection(sec) {
  document.querySelectorAll(".railbtn").forEach((b) => b.classList.toggle("active", b.dataset.sec === sec));
  document.querySelectorAll("#dockBody .panel").forEach((p) => p.classList.add("hidden"));
  const el = $("tab-" + sec);
  if (el) el.classList.remove("hidden");
  const meta = SECTIONS[sec] || {};
  if ($("dockTitle")) $("dockTitle").textContent = meta.title || sec;
  state._section = sec;
  if (!meta.live) { if ($("dockMeta")) $("dockMeta").textContent = ""; return; }
  try { meta.live(); } catch (e) { console.warn("section " + sec, e); }
}

function initRail() {
  document.querySelectorAll(".railbtn").forEach((b) => { b.onclick = () => showSection(b.dataset.sec); });
}

/* ---------------- layout: focus mode + resizable dock ---------------- */
function initLayout() {
  const app = document.querySelector(".app");
  const focusBtn = $("chartFocus");
  if (focusBtn && app) {
    focusBtn.onclick = () => {
      app.classList.toggle("focus");
      focusBtn.classList.toggle("active");
      focusBtn.textContent = app.classList.contains("focus") ? "⤡ exit" : "⤢ focus";
    };
  }
  const followBtn = $("chartFollow");
  if (followBtn) {
    followBtn.classList.toggle("active", state.follow);
    followBtn.onclick = () => {
      state.follow = !state.follow;
      followBtn.classList.toggle("active", state.follow);
    };
  }
  const grip = $("dockGrip");
  const min = $("dockMin");
  if (grip) {
    let dragging = false;
    grip.addEventListener("mousedown", (e) => {
      dragging = true; e.preventDefault();
      document.body.style.cursor = "ns-resize"; document.body.style.userSelect = "none";
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const h = Math.max(120, Math.min(window.innerHeight * 0.72, window.innerHeight - e.clientY - 8));
      document.documentElement.style.setProperty("--dockh", h + "px");
      if (min) { min.textContent = "▾"; }
      app && app.classList.remove("dockcollapsed");
    });
    window.addEventListener("mouseup", () => {
      if (dragging) { dragging = false; document.body.style.cursor = ""; document.body.style.userSelect = ""; }
    });
  }
  if (min && app) {
    min.onclick = () => {
      const collapsed = app.classList.toggle("dockcollapsed");
      if (collapsed) {
        document.documentElement.style.setProperty("--dockh", "40px");
        min.textContent = "▴";
      } else {
        document.documentElement.style.setProperty("--dockh", "300px");
        min.textContent = "▾";
      }
    };
  }
}

function loadSymbol(sym) {
  if (!sym) return;
  state.symbol = String(sym).toUpperCase();
  if ($("symbolInput")) $("symbolInput").value = state.symbol;
  loadChart();
}
function openResearch(sym) {
  state.researchSym = String(sym || state.symbol || "AAPL").toUpperCase();
  showSection("research");
}

/* ---------------- scanner ---------------- */
function loadScanner() {
  const bar = $("scannerBar");
  if (bar && !bar.dataset.init) {
    bar.innerHTML =
      `<form class="btform" onsubmit="return false">
        <input id="scQ" placeholder="symbol/name" style="width:130px">
        <select id="scSector"><option value="">all sectors</option></select>
        <select id="scSort">
          <option value="change_pct">% change</option>
          <option value="dollar_volume">dollar volume</option>
          <option value="volume">volume</option>
          <option value="rel_volume">rel volume</option>
          <option value="price">price</option>
        </select>
        <label class="fld"><input type="checkbox" id="scFull"> full universe</label>
        <label class="fld">min $<input id="scMinPrice" type="number" value="1" class="mini" style="width:52px"></label>
        <label class="fld">max $<input id="scMaxPrice" type="number" class="mini" style="width:52px"></label>
        <button id="scRun" class="btn primary">Scan</button>
        <span id="scStatus" class="muted small"></span>
      </form>`;
    bar.dataset.init = "1";
    $("scRun").onclick = () => loadScanner(true);
    $("scQ").onkeydown = (e) => { if (e.key === "Enter") loadScanner(true); };
    $("scSector").onchange = () => loadScanner(true);
    $("scSort").onchange = () => loadScanner(true);
  }
  const p = new URLSearchParams();
  const q = $("scQ").value.trim(); if (q) p.set("q", q);
  const sec = $("scSector").value; if (sec) p.set("sector", sec);
  p.set("sort", $("scSort").value);
  const minp = $("scMinPrice").value; if (minp) p.set("min_price", minp);
  const maxp = $("scMaxPrice").value; if (maxp) p.set("max_price", maxp);
  if ($("scFull").checked) p.set("full", "true");
  p.set("limit", "200");
  $("scStatus").textContent = "scanning…";
  fetch("/api/scanner?" + p).then((r) => r.json()).then((d) => {
    renderScanner(d);
    if ($("dockMeta")) $("dockMeta").textContent =
      `scanned ${d.scanned} · matched ${d.total_matched} · universe ${d.universe_size}`;
    $("scStatus").textContent = "";
    const sel = $("scSector");
    if (sel && (d.sectors || []).length && sel.options.length <= 1) {
      sel.innerHTML = '<option value="">all sectors</option>' +
        d.sectors.map((s) => `<option value="${esc(s.sector)}">${esc(s.sector)} (${s.count})</option>`).join("");
    }
  }).catch(() => { $("scStatus").textContent = "scan failed"; });
}

function moverChips(arr, k) {
  if (!arr || !arr.length) return '<span class="muted small">none</span>';
  return arr.slice(0, 10).map((m) =>
    `<span class="chip clickable" onclick="loadSymbol('${esc(m.symbol)}')">${esc(m.symbol)} ` +
    `<span class="${k}">${m.change_pct >= 0 ? "+" : ""}${Number(m.change_pct).toFixed(2)}%</span></span>`).join("");
}

function renderScanner(d) {
  let h = `<div class="cols">
    <div class="card"><h4>Top gainers</h4><div>${moverChips(d.gainers, "pos")}</div></div>
    <div class="card"><h4>Top losers</h4><div>${moverChips(d.losers, "neg")}</div></div>
  </div>`;
  h += `<div class="card" style="margin-top:12px"><h4>Most active</h4><div>${
    (d.most_active || []).slice(0, 14).map((m) =>
      `<span class="chip clickable" onclick="loadSymbol('${esc(m.symbol)}')">${esc(m.symbol)} ` +
      `<span class="muted">${fmtSize(m.volume)}</span></span>`).join("") || '<span class="muted">none</span>'}</div></div>`;
  h += `<h4 style="margin-top:16px">Scan results (${(d.rows || []).length})</h4>`;
  h += `<table><thead><tr><th>Symbol</th><th>Sector</th><th>Last</th><th>%Chg</th><th>RelVol</th>` +
       `<th>Vol</th><th>RSI</th><th>ATR%</th><th>Trend</th><th></th></tr></thead><tbody>`;
  for (const r of d.rows || []) {
    h += `<tr><td class="sym clickable" onclick="openResearch('${esc(r.symbol)}')">${esc(r.symbol)}</td>
      <td class="muted small">${esc(r.sector || "")}</td>
      <td>${money(r.price)}</td>
      <td class="${cls(r.change_pct)}">${r.change_pct == null ? "--" : (r.change_pct >= 0 ? "+" : "") + r.change_pct.toFixed(2) + "%"}</td>
      <td>${r.rel_volume == null ? "--" : r.rel_volume + "x"}</td>
      <td class="muted">${fmtSize(r.volume)}</td>
      <td>${r.rsi == null ? "--" : r.rsi}</td>
      <td>${r.atr_pct == null ? "--" : r.atr_pct + "%"}</td>
      <td class="${r.trend === "up" ? "pos" : r.trend === "down" ? "neg" : "muted"}">${esc(r.trend || "--")}</td>
      <td><button class="btn sm" onclick="loadSymbol('${esc(r.symbol)}')">chart</button></td></tr>`;
  }
  h += "</tbody></table>";
  $("scannerBody").innerHTML = h;
}

/* ---------------- research ---------------- */
function loadResearch(sym) {
  sym = String(sym || state.researchSym || state.symbol || "AAPL").toUpperCase();
  state.researchSym = sym;
  const bar = $("researchBar");
  if (bar && !bar.dataset.init) {
    bar.innerHTML =
      `<form class="btform" onsubmit="return false">
        <input id="rsSym" class="syminput" value="${esc(sym)}">
        <button id="rsRun" class="btn primary">Research</button>
        <span id="rsStatus" class="muted small"></span>
      </form>`;
    bar.dataset.init = "1";
    $("rsRun").onclick = () => loadResearch($("rsSym").value);
    $("rsSym").onkeydown = (e) => { if (e.key === "Enter") loadResearch($("rsSym").value); };
  }
  if ($("rsSym")) $("rsSym").value = sym;
  $("rsStatus").textContent = "analyzing…";
  $("researchBody").innerHTML = '<p class="muted">Building dossier…</p>';
  fetch("/api/research?symbol=" + encodeURIComponent(sym)).then((r) => r.json()).then((d) => {
    if (d.error) { $("rsStatus").textContent = d.error; $("researchBody").innerHTML = ""; return; }
    renderResearch(d);
    $("rsStatus").textContent = "";
  }).catch(() => { $("rsStatus").textContent = "research failed"; });
}

function subBar(v, label) {
  v = v == null ? 0 : v;
  const p = Math.round((v + 1) / 2 * 100);
  const c = v > 0.1 ? "pos" : v < -0.1 ? "neg" : "muted";
  const bg = v >= 0 ? "var(--green)" : "var(--red)";
  return `<div style="margin:5px 0"><div class="muted small">${label}` +
    `<span class="${c}" style="float:right">${v.toFixed(2)}</span></div>` +
    `<div class="bar"><span style="width:${p}%;background:${bg}"></span></div></div>`;
}

function renderResearch(d) {
  const s = d.stats || {}, sub = d.subscores || {}, lv = d.levels || {}, it = d.intraday || {};
  const isBuy = /Buy/.test(d.rating), isSell = /Sell/.test(d.rating);
  let h = `<div class="cols">
    <div class="card">
      <div style="display:flex;align-items:center;gap:12px">
        <div style="font-size:26px;font-weight:800">${esc(d.symbol)}</div>
        <div><span class="chip ${isBuy ? "buy" : isSell ? "sell" : "hold"}">${esc(d.rating)}</span>
          <span class="muted small">score ${d.score}/100</span></div>
        <span class="spacer"></span>
        <div style="text-align:right"><div class="mono" style="font-size:18px">${money(d.price)}</div></div>
      </div>
      <p class="muted small" style="margin-top:8px">${esc(d.summary || "")}</p>
      ${subBar(sub.trend, "Trend")}${subBar(sub.momentum, "Momentum")}
      ${subBar(sub.rel_strength, "Rel strength")}${subBar(sub.sentiment, "Sentiment")}
    </div>
    <div class="card">
      <h4>Key stats</h4>
      <div class="metric-grid">
        ${metric("52w high", money(s.high_52w))}
        ${metric("52w low", money(s.low_52w))}
        ${metric("% from high", `<span class="neg">${s.pct_from_high}%</span>`)}
        ${metric("RSI", s.rsi)}
        ${metric("ADX", s.adx)}
        ${metric("ATR%", s.atr_pct + "%")}
        ${metric("5d", `<span class="${cls(s.ret5)}">${s.ret5}%</span>`)}
        ${metric("20d", `<span class="${cls(s.ret20)}">${s.ret20}%</span>`)}
        ${metric("vs SPY 20d", s.rel_strength_spy == null ? "--" : `<span class="${cls(s.rel_strength_spy)}">${s.rel_strength_spy}%</span>`)}
        ${metric("SMA20", money(s.sma20))}
        ${metric("SMA50", money(s.sma50))}
        ${metric("SMA200", money(s.sma200))}
      </div>
    </div>
  </div>`;
  h += `<div class="cols" style="margin-top:12px">
    <div class="card"><h4>Levels</h4>
      <p class="small">Support ${(lv.support || []).map((x) => `<span class="chip">${x}</span>`).join("") || '<span class="muted">--</span>'}</p>
      <p class="small">Resistance ${(lv.resistance || []).map((x) => `<span class="chip">${x}</span>`).join("") || '<span class="muted">--</span>'}</p>
      <p class="small muted">POC ${lv.poc == null ? "--" : lv.poc} · Value area ${lv.value_low == null ? "--" : lv.value_low}–${lv.value_high == null ? "--" : lv.value_high}</p>
      ${it.vwap ? `<p class="small muted">Intraday VWAP ${money(it.vwap)} · H ${money(it.session_high)} · L ${money(it.session_low)} · RVOL ${it.rvol}</p>` : ""}
    </div>
    <div class="card"><h4>Thesis / Risks</h4>
      <ul class="tight">${(d.thesis || []).map((t) => `<li class="pos">${esc(t)}</li>`).join("") || '<li class="muted">none</li>'}</ul>
      <ul class="tight">${(d.risks || []).map((t) => `<li class="warn">${esc(t)}</li>`).join("")}</ul>
    </div>
  </div>`;
  h += `<div class="card" style="margin-top:12px"><h4>News</h4>${(d.news || []).length
    ? d.news.map((n) => {
        const sn = n.sentiment || 0;
        const c = sn > 0.1 ? "sent-pos" : sn < -0.1 ? "sent-neg" : "muted";
        return `<div class="news-item"><div class="hl">${esc(n.headline)}</div>` +
          `<div class="meta"><span class="${c}">${sn >= 0 ? "+" : ""}${sn.toFixed(2)}</span> · ${esc(n.source || "")} · ${tstr(n.ts)}</div></div>`;
      }).join("")
    : '<p class="muted small">No recent news.</p>'}</div>`;
  h += `<p class="muted small" style="margin-top:8px">${esc(d.fundamentals_note || "")}</p>`;
  $("researchBody").innerHTML = h;
}

/* ---------------- ideas ---------------- */
function loadIdeas() {
  $("ideasBody").innerHTML = '<p class="muted">Generating ideas across the market…</p>';
  fetch("/api/ideas").then((r) => r.json()).then(renderIdeas)
    .catch(() => { $("ideasBody").innerHTML = '<p class="muted">Ideas failed.</p>'; });
}

function renderIdeas(d) {
  const b = d.briefing || {}, c = b.counts || {};
  let h = `<div class="card"><h4>Daily briefing</h4><p>${esc(b.headline || "")}</p>
    <div class="metric-grid">
      ${metric("Mood", esc(b.mood || "--"))}
      ${metric("Long", c.BUY || 0)}
      ${metric("Short", c.SELL || 0)}
      ${metric("Sentiment", (b.sentiment_avg || 0).toFixed(2))}
      ${metric("Setups", d.total || 0)}
    </div></div>`;
  h += `<h4 style="margin-top:14px">Trade ideas (${(d.ideas || []).length})</h4>`;
  h += `<table><thead><tr><th>Symbol</th><th>Action</th><th>Conf</th><th>Entry</th><th>Stop</th>` +
       `<th>Target</th><th>RR</th><th>Regime</th><th>RSI</th><th>Signals</th><th></th></tr></thead><tbody>`;
  for (const i of d.ideas || []) {
    h += `<tr><td class="sym clickable" onclick="openResearch('${esc(i.symbol)}')">${esc(i.symbol)}</td>
      <td><span class="chip ${i.action === "BUY" ? "buy" : "sell"}">${i.action}</span></td>
      <td>${(i.confidence * 100).toFixed(0)}%</td><td>${money(i.entry)}</td><td class="neg">${money(i.stop)}</td>
      <td class="pos">${money(i.target)}</td><td>${i.rr == null ? "--" : i.rr}</td>
      <td><span class="chip regime">${esc(i.regime || "")}</span></td><td>${i.rsi == null ? "--" : i.rsi}</td>
      <td class="muted small">${(i.signals || []).join(", ")}</td>
      <td><button class="btn sm" onclick="loadSymbol('${esc(i.symbol)}')">chart</button></td></tr>`;
  }
  h += "</tbody></table>";
  h += `<div class="card" style="margin-top:14px"><h4>Discipline tips</h4><ul class="tight">${
    (d.tips || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>`;
  $("ideasBody").innerHTML = h;
}

/* ---------------- portfolio ---------------- */
function loadPortfolio() {
  $("portfolioBody").innerHTML = '<p class="muted">Computing analytics…</p>';
  fetch("/api/analytics").then((r) => r.json()).then(renderPortfolio)
    .catch(() => { $("portfolioBody").innerHTML = '<p class="muted">Analytics failed.</p>'; });
}

function renderPortfolio(d) {
  const t = d.trade_stats || {}, em = d.equity_metrics || {}, c = d.concentration || {};
  let h = `<div class="metric-grid">
    ${metric("Equity", money(d.equity))}
    ${metric("Cash", d.cash_pct + "%")}
    ${metric("Gross exp", d.gross_pct + "%")}
    ${metric("Net exp", d.net_pct + "%")}
    ${metric("Open pos", d.open_positions)}
    ${metric("HHI", c.hhi)}
    ${metric("Top weight", c.top_weight_pct + "%")}
    ${metric("Top-3", c.top3_pct + "%")}
    ${metric("Max DD", `<span class="neg">${em.max_drawdown_pct}%</span>`)}
    ${metric("Sharpe", em.sharpe_daily == null ? em.sharpe : em.sharpe_daily)}
  </div>`;
  h += `<div class="cols" style="margin-top:12px">
    <div class="card"><h4>Trade stats</h4><div class="metric-grid">
      ${metric("Trades", t.trades)}${metric("Win rate", pct(t.win_rate))}${metric("Profit factor", t.profit_factor)}
      ${metric("Expectancy", money(t.expectancy))}${metric("Avg win", money(t.avg_win))}${metric("Avg loss", money(t.avg_loss))}
    </div></div>
    <div class="card"><h4>Sector allocation</h4><table><tbody>${
      (d.sectors || []).map((s) =>
        `<tr><td>${esc(s.sector)}</td><td style="width:120px"><div class="bar"><span style="width:${s.pct}%"></span></div></td><td>${s.pct}%</td></tr>`).join("")
      || '<tr><td class="muted">no positions</td></tr>'}</tbody></table></div>
  </div>`;
  h += `<h4 style="margin-top:14px">Positions</h4><table><thead><tr><th>Symbol</th><th>Sector</th><th>Qty</th>` +
       `<th>Mkt val</th><th>Weight</th><th>P&L</th><th>%</th></tr></thead><tbody>`;
  for (const p of d.positions || []) {
    h += `<tr><td class="sym clickable" onclick="openResearch('${esc(p.symbol)}')">${esc(p.symbol)}</td>
      <td class="muted small">${esc(p.sector)}</td><td>${p.qty}</td><td>${money(p.market_value)}</td>
      <td>${p.weight}%</td><td class="${cls(p.unrealized_pl)}">${money(p.unrealized_pl)}</td>
      <td class="${cls(p.unrealized_pl)}">${p.unrealized_plpc}%</td></tr>`;
  }
  h += "</tbody></table>";
  if ((d.realized_top || []).length) {
    h += `<h4 style="margin-top:14px">Realized P&L (top)</h4><div>${
      d.realized_top.map((r) => `<span class="chip ${r.pnl >= 0 ? "buy" : "sell"} clickable" ` +
        `onclick="openResearch('${esc(r.symbol)}')">${esc(r.symbol)} ${money(r.pnl)}</span>`).join("")}</div>`;
  }
  const co = d.correlation || {};
  if ((co.labels || []).length >= 2) {
    h += `<h4 style="margin-top:14px">Correlation</h4><table><thead><tr><th></th>${
      co.labels.map((l) => `<th>${esc(l)}</th>`).join("")}</tr></thead><tbody>`;
    co.labels.forEach((l, i) => {
      h += `<tr><td class="sym">${esc(l)}</td>${co.matrix[i].map((v) => {
        const a = Math.abs(v);
        return `<td style="background:rgba(${v >= 0 ? "14,203,129" : "246,70,93"},${(a * 0.5).toFixed(2)})">${v.toFixed(2)}</td>`;
      }).join("")}</tr>`;
    });
    h += "</tbody></table>";
  }
  $("portfolioBody").innerHTML = h;
}

/* ---------------- journal ---------------- */
function numOrNull(v) { const n = parseFloat(v); return isNaN(n) ? null : n; }

function loadJournal() {
  const bar = $("journalBar");
  if (bar && !bar.dataset.init) {
    bar.innerHTML =
      `<form class="btform" onsubmit="return false">
        <input id="jSym" class="syminput" placeholder="SYM">
        <select id="jSide"><option value="">side</option><option>long</option><option>short</option></select>
        <input id="jEntry" class="mini" type="number" placeholder="entry">
        <input id="jExit" class="mini" type="number" placeholder="exit">
        <input id="jPnl" class="mini" type="number" placeholder="pnl">
        <input id="jRating" class="mini" type="number" min="1" max="5" placeholder="1-5">
        <input id="jTags" placeholder="tags,comma" style="width:130px">
        <input id="jNote" placeholder="note" style="width:220px">
        <button id="jAdd" class="btn primary">Add</button>
        <span id="jStatus" class="muted small"></span>
      </form>`;
    bar.dataset.init = "1";
    $("jAdd").onclick = addJournal;
  }
  fetch("/api/journal").then((r) => r.json()).then((d) => renderJournal(d.entries || [])).catch(() => {});
}

async function addJournal() {
  const tags = $("jTags").value.split(",").map((s) => s.trim()).filter(Boolean);
  const body = {
    symbol: ($("jSym").value || "").toUpperCase(), side: $("jSide").value || null,
    entry: numOrNull($("jEntry").value), exit: numOrNull($("jExit").value), pnl: numOrNull($("jPnl").value),
    rating: numOrNull($("jRating").value), tags, note: $("jNote").value || null,
  };
  if (!body.symbol) { $("jStatus").textContent = "symbol required"; return; }
  await fetch("/api/journal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  ["jSym", "jEntry", "jExit", "jPnl", "jRating", "jTags", "jNote"].forEach((id) => { const e = $(id); if (e) e.value = ""; });
  $("jStatus").textContent = "saved";
  loadJournal();
}

function renderJournal(es) {
  if (!es.length) { $("journalBody").innerHTML = '<p class="muted">No journal entries yet.</p>'; return; }
  let h = `<table><thead><tr><th>When</th><th>Sym</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&L</th>` +
          `<th>Rating</th><th>Tags</th><th>Note</th><th></th></tr></thead><tbody>`;
  for (const e of es) {
    let tags = e.tags; try { tags = JSON.parse(e.tags || "[]"); } catch (x) { tags = e.tags ? [e.tags] : []; }
    h += `<tr><td>${dstr(e.ts)}</td><td class="sym">${esc(e.symbol || "")}</td><td>${esc(e.side || "")}</td>
      <td>${e.entry == null ? "--" : money(e.entry)}</td><td>${e.exit == null ? "--" : money(e.exit)}</td>
      <td class="${cls(e.pnl)}">${e.pnl == null ? "--" : money(e.pnl)}</td>
      <td class="warn">${e.rating == null ? "" : "★".repeat(e.rating)}</td>
      <td class="muted small">${(tags || []).join(", ")}</td><td style="white-space:normal">${esc(e.note || "")}</td>
      <td><button class="btn sm" onclick="delJournal(${e.id})">✕</button></td></tr>`;
  }
  h += "</tbody></table>";
  $("journalBody").innerHTML = h;
}
async function delJournal(id) { await fetch("/api/journal/" + id, { method: "DELETE" }); loadJournal(); }

/* ---------------- alerts ---------------- */
function loadAlerts() {
  const bar = $("alertsBar");
  if (bar && !bar.dataset.init) {
    bar.innerHTML =
      `<form class="btform" onsubmit="return false">
        <input id="aSym" class="syminput" placeholder="SYM">
        <select id="aKind"><option value="price">price</option><option value="change_pct">change %</option><option value="volume">volume</option></select>
        <select id="aOp"><option>>=</option><option>></option><option><=</option><option><</option><option>==</option></select>
        <input id="aVal" class="mini" type="number" placeholder="value">
        <input id="aNote" placeholder="note" style="width:150px">
        <button id="aAdd" class="btn primary">Add</button>
        <button id="aEval" class="btn">Evaluate now</button>
        <span id="aStatus" class="muted small"></span>
      </form>`;
    bar.dataset.init = "1";
    $("aAdd").onclick = addAlert;
    $("aEval").onclick = evalAlerts;
  }
  fetch("/api/alerts").then((r) => r.json()).then((d) => {
    renderAlerts(d.alerts || []);
    renderFired(d.fired || []);
  }).catch(() => {});
}

async function addAlert() {
  const body = { symbol: ($("aSym").value || "").toUpperCase(), kind: $("aKind").value,
    op: $("aOp").value, value: parseFloat($("aVal").value), note: $("aNote").value || null };
  if (!body.symbol || isNaN(body.value)) { $("aStatus").textContent = "symbol + value required"; return; }
  await fetch("/api/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("aSym").value = ""; $("aVal").value = ""; $("aNote").value = ""; $("aStatus").textContent = "added";
  loadAlerts();
}
async function evalAlerts() {
  const d = await fetch("/api/alerts/evaluate", { method: "POST" }).then((r) => r.json());
  $("aStatus").textContent = (d.fired || []).length + " fired";
  loadAlerts();
}

function renderAlerts(as) {
  if (!as.length) { $("alertsBody").innerHTML = '<p class="muted">No alerts set.</p>'; return; }
  let h = `<table><thead><tr><th>Symbol</th><th>Kind</th><th>Condition</th><th>Last</th><th>Status</th><th></th></tr></thead><tbody>`;
  for (const a of as) {
    const st = a.triggered ? '<span class="chip sell">triggered</span>' : a.active ? '<span class="chip buy">active</span>' : '<span class="chip hold">paused</span>';
    h += `<tr><td class="sym">${esc(a.symbol)}</td><td>${esc(a.kind)}</td>
      <td class="mono">${esc(a.op)} ${a.kind === "volume" ? Number(a.value).toLocaleString() : a.value}${a.kind === "change_pct" ? "%" : ""}</td>
      <td>${a.last_price == null ? "--" : money(a.last_price)}</td><td>${st}</td>
      <td><button class="btn sm" onclick="toggleAlert(${a.id})">${a.triggered ? "reset" : a.active ? "pause" : "resume"}</button>
          <button class="btn sm" onclick="delAlert(${a.id})">✕</button></td></tr>`;
  }
  h += "</tbody></table>";
  $("alertsBody").innerHTML = h;
}
function renderFired(fs) {
  if (!fs.length) return;
  $("alertsBody").innerHTML += `<h4 style="margin-top:14px">Recently fired</h4>` +
    fs.map((f) => `<div class="logrow trade"><span class="t">${tstr(f.triggered_ts || f.ts)}</span>` +
      `${esc(f.symbol)} ${esc(f.kind)} ${esc(f.op)} ${f.value} — now ${money(f.last_price)}</div>`).join("");
}
async function toggleAlert(id) { await fetch("/api/alerts/" + id + "/toggle", { method: "POST" }); loadAlerts(); }
async function delAlert(id) { await fetch("/api/alerts/" + id, { method: "DELETE" }); loadAlerts(); }

/* ---------------- coach ---------------- */
function loadCoach() {
  $("coachBody").innerHTML = '<p class="muted">Reading the playbook for your situation…</p>';
  fetch("/api/coach").then((r) => r.json()).then(renderCoach)
    .catch(() => { $("coachBody").innerHTML = '<p class="muted">Coach unavailable.</p>'; });
  loadProfile();
}

function renderCoach(d) {
  let h = `<div class="card"><h4>Risk profile — capital preservation</h4>
    <select id="riskProfile" onchange="setProfile(this.value)"></select>
    <div id="profileInfo"></div></div>`;
  h += `<div class="card" style="margin-top:12px"><h4>Situation</h4><div class="metric-grid">${
    (d.situations || []).map((s) => metric(esc(s.tag), `<span class="small muted">${esc(s.note)}</span>`)).join("")}</div></div>`;
  const q = d.quote || {};
  h += `<div class="card" style="margin-top:12px;border-color:var(--accent-line)">
    <h4>Quote of the day</h4><p style="font-size:14px">“${esc(q.lesson || "")}”</p>
    <p class="muted small">— ${esc(q.author || "")}, <i>${esc(q.book || "")}</i></p></div>`;
  h += `<h4 style="margin-top:14px">What the books say about right now</h4>`;
  h += `<table><thead><tr><th>For</th><th>Principle</th><th>Source</th><th>Category</th></tr></thead><tbody>`;
  for (const p of d.principles || []) {
    h += `<tr><td><span class="chip regime">${esc(p.for || "")}</span></td>
      <td style="white-space:normal">${esc(p.lesson)}</td>
      <td class="muted small">${esc(p.book)} · ${esc(p.author)}</td>
      <td class="muted small">${esc(p.category)}</td></tr>`;
  }
  h += "</tbody></table>";
  h += `<div class="card" style="margin-top:14px"><h4>Capital-protection checklist</h4><ul class="tight">${
    (d.checklist || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
  $("coachBody").innerHTML = h;
}

/* ---------------- library ---------------- */
function loadLibrary() {
  const bar = $("libraryBar");
  if (bar && !bar.dataset.init) {
    bar.innerHTML =
      `<form class="btform" onsubmit="return false">
        <input id="kbQ" placeholder="search titles, authors, lessons" style="width:260px">
        <select id="kbCat"><option value="">all categories</option></select>
        <span id="kbStatus" class="muted small"></span>
      </form>`;
    bar.dataset.init = "1";
    $("kbQ").onkeydown = (e) => { if (e.key === "Enter") loadLibrary(true); };
    $("kbQ").oninput = () => loadLibrary(true);
    $("kbCat").onchange = () => loadLibrary(true);
  }
  const p = new URLSearchParams();
  const q = $("kbQ").value.trim(); if (q) p.set("q", q);
  const cat = $("kbCat").value; if (cat) p.set("category", cat);
  fetch("/api/knowledge?" + p).then((r) => r.json()).then((d) => {
    renderLibrary(d);
    $("kbStatus").textContent = `${d.total} books · ${d.stats.lessons} lessons`;
    const sel = $("kbCat");
    if (sel && sel.options.length <= 1) {
      (d.stats && d.stats.categories ? [] : []);
    }
  }).catch(() => {});
  // populate categories once
  if (!$("kbCat").dataset.filled) {
    fetch("/api/knowledge/categories").then((r) => r.json()).then((d) => {
      const sel = $("kbCat");
      if (sel) {
        sel.innerHTML = '<option value="">all categories</option>' +
          d.categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
      }
      $("kbCat").dataset.filled = "1";
    }).catch(() => {});
  }
}

function renderLibrary(d) {
  if (!d.rows || !d.rows.length) { $("libraryBody").innerHTML = '<p class="muted">No books match.</p>'; return; }
  let h = "";
  for (const b of d.rows) {
    h += `<div class="card" style="margin-bottom:10px">
      <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
        <b style="font-size:14px">${esc(b.title)}</b>
        <span class="muted small">${esc(b.author)} · ${b.year}</span>
        <span class="chip regime">${esc(b.category)}</span>
      </div>
      <ul class="tight" style="margin-top:6px">${b.lessons.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
    </div>`;
  }
  $("libraryBody").innerHTML = h;
}

/* ---------------- pulse ---------------- */
function loadPulse() {
  $("pulseBody").innerHTML = '<p class="muted">Gathering the live wire…</p>';
  fetch("/api/pulse").then((r) => r.json()).then(renderPulse)
    .catch(() => { $("pulseBody").innerHTML = '<p class="muted">Pulse unavailable.</p>'; });
}

function renderPulse(d) {
  const chip = (s, cls) => `<span class="chip ${cls || ""}">${esc(s)}</span>`;
  let h = `<div class="card" style="border-color:var(--accent-line)">
    <h4>Tip of the hour</h4><p style="font-size:14px">${esc(d.tip)}</p></div>`;

  h += '<div class="metric-grid" style="margin-top:12px">';
  h += metric("Ideas ready", d.ideas_count || 0);
  const b = d.breadth || {};
  h += metric("Breadth", esc(b.label || b.bias || "—"));
  h += metric("Wire items", (d.wire || []).length);
  h += metric("Talks shelved", (d.talks || []).length);
  h += "</div>";

  h += '<h4 style="margin-top:14px">Talk of the tape</h4>';
  h += '<div class="chips">';
  for (const g of d.gainers || []) h += chip(`${g.symbol} +${fmtPct(g.percent_change)}`, "up");
  for (const l of d.losers || []) h += chip(`${l.symbol} ${fmtPct(l.percent_change)}`, "down");
  h += "</div>";

  h += '<h4 style="margin-top:14px">Most active</h4>';
  h += '<div class="chips">' + (d.most_active || []).map((m) => chip(`${m.symbol} ${fmtVol(m.volume)}`)).join("") + "</div>";

  h += '<h4 style="margin-top:14px">Live wire</h4>';
  h += '<table><thead><tr><th>Symbol</th><th>Headline</th><th>Source</th><th>Time</th></tr></thead><tbody>';
  for (const n of d.wire || []) {
    h += `<tr><td>${n.symbol ? `<a href="#" onclick="openResearch('${esc(n.symbol)}');return false">${esc(n.symbol)}</a>` : ""}</td>
      <td style="white-space:normal">${esc(n.headline || "")}</td>
      <td class="muted small">${esc(n.source || "")}</td>
      <td class="muted small">${n.ts ? ago(n.ts) : ""}</td></tr>`;
  }
  h += "</tbody></table>";

  h += '<h4 style="margin-top:14px">Worth watching / listening</h4>';
  h += '<table><thead><tr><th>Talk</th><th>Speaker</th><th>Kind</th><th>Why</th></tr></thead><tbody>';
  for (const t of d.talks || []) {
    h += `<tr><td><a href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.title)}</a></td>
      <td>${esc(t.speaker)}</td><td class="muted small">${esc(t.kind)}</td>
      <td class="muted small" style="white-space:normal">${esc(t.why)}</td></tr>`;
  }
  h += "</tbody></table>";
  $("pulseBody").innerHTML = h;
}

/* ---------------- risk profile (in coach) ---------------- */
function loadProfile() {
  fetch("/api/profile").then((r) => r.json()).then((d) => {
    const sel = $("riskProfile");
    if (!sel) return;
    sel.innerHTML = (d.profiles || []).map((p) =>
      `<option value="${p.name}"${p.name === d.current ? " selected" : ""}>${esc(p.label)}</option>`).join("");
    renderLimits(d.limits, d.profiles.find((p) => p.name === d.current));
  }).catch(() => {});
}

function renderLimits(l, p) {
  const el = $("profileInfo");
  if (!el || !l) return;
  el.innerHTML = `<p class="muted small" style="margin:4px 0">${esc((p && p.desc) || "")}</p>
    <div class="metric-grid">
      ${metric("Risk / trade", fmtPct(l.risk_per_trade * 100))}
      ${metric("Max position", fmtPct(l.max_position_pct * 100))}
      ${metric("Max open", l.max_open_positions)}
      ${metric("Daily loss stop", fmtPct(l.daily_loss_limit_pct * 100))}
      ${metric("Max trades/day", l.max_trades_per_day)}
      ${metric("Min confidence", (l.min_confidence * 100).toFixed(0) + "%")}
      ${metric("Reward:Risk", "1:" + l.rr)}
      ${metric("Vol dampener", fmtPct(l.vol_dampen * 100))}
    </div>`;
}

async function setProfile(name) {
  const r = await fetch("/api/profile", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile: name }) });
  const d = await r.json();
  loadProfile();
  toast(`Risk profile → ${name}`);
  return d;
}

/* ----------------------------- wiring ----------------------------- */
function initTabs(group) {
  document.querySelectorAll(`.tabs[data-group="${group}"] .tab`).forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(`.tabs[data-group="${group}"] .tab`).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      const panels = group === "side"
        ? ["positions", "orders", "tape", "news", "log"]
        : ["reasoning", "mind", "today", "equity", "trades", "daily", "backtest", "depth", "wfo"];
      panels.forEach((p) => { const el = $("tab-" + p); if (el) el.classList.toggle("hidden", p !== tab); });
      if (tab === "equity") { loadEquity(); }
      if (tab === "depth") { loadDepth(); }
      if (tab === "wfo") { loadWfoRuns(); }
    };
  });
}

let _wsOk = false;
function initWS() {
  try {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { _wsOk = true; setConn("live"); };
    ws.onmessage = (ev) => {
      _wsOk = true;
      try {
        const m = JSON.parse(ev.data);
        if (m && m.type === "snapshot") renderSnapshot(m.data);
        else if (m && m.type === "tape") renderTape(m.data);
        else renderSnapshot(m);
      } catch (e) {}
    };
    ws.onclose = () => { _wsOk = false; setConn("down"); setTimeout(initWS, 3000); };
    ws.onerror = () => { _wsOk = false; setConn("down"); };
  } catch (e) { console.warn("ws", e); }
}

async function pollStatus() {
  try {
    const s = await fetch("/api/status").then((r) => r.json());
    if (s && !s.error) { renderSnapshot(s); if (!_wsOk) setConn("rest"); }
  } catch (e) { setConn("down"); }
}

function boot() {
  try { initChart(); } catch (e) { console.warn(e); }
  try { initEquityChart(); } catch (e) { console.warn(e); }
  try { initTabs("side"); } catch (e) { console.warn(e); }
  try { initRail(); } catch (e) { console.warn(e); }
  try { initLayout(); } catch (e) { console.warn(e); }
  try {
    applyTips();
    const mo = new MutationObserver(() => {
      if (mo._t) return;
      mo._t = setTimeout(() => { mo._t = null; try { applyTips(); } catch (e) {} }, 150);
    });
    mo.observe(document.body, { childList: true, subtree: true });
  } catch (e) { console.warn("tips", e); }
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("botToggle", botToggle);
  on("applyCfg", applyCfg);
  on("btRun", runBacktest);
  on("wfoRun", runWFO);
  on("chartResearch", () => openResearch(state.symbol));
  const ds = $("depthSymbol"); if (ds) ds.onchange = loadDepth;
  const si = $("symbolInput"); if (si) si.onchange = (e) => { state.symbol = e.target.value.toUpperCase(); loadChart(); };
  document.querySelectorAll(".tf").forEach((b) => {
    b.onclick = () => {
      document.querySelectorAll(".tf").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.tf = b.dataset.tf || "5Min";
      loadChart();
    };
  });
  try { loadChart(); } catch (e) {}
  try { loadDaily(); } catch (e) {}
  setInterval(() => { try { loadChart(); } catch (e) {} }, 20000);
  setInterval(() => { try { loadDaily(); } catch (e) {} }, 30000);
  setInterval(() => { const t = $("tab-equity"); if (t && !t.classList.contains("hidden")) loadEquity(); }, 30000);
  setInterval(() => { const t = $("tab-depth"); if (t && !t.classList.contains("hidden")) loadDepth(); }, 3000);
  setInterval(() => {
    const s = state._section;
    if (s === "alerts") { try { loadAlerts(); } catch (e) {} }
    else if (s === "ideas") { try { loadIdeas(); } catch (e) {} }
  }, 30000);
  // REST fallback: guarantee content even if the websocket is blocked.
  setInterval(() => { if (!_wsOk || !state.snap) pollStatus(); }, 4000);
  pollStatus();
  initWS();
}
window.useRun = useRun;
window.loadSymbol = loadSymbol;
window.openResearch = openResearch;
window.delJournal = delJournal;
window.toggleAlert = toggleAlert;
window.delAlert = delAlert;
window.setProfile = setProfile;

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
