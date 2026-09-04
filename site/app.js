/* QuantDesk site. Vanilla JS, zero external scripts.
 * Loads ./data/{build,board,backtest,null}.json, all produced by
 * scripts/build_site.py from SYNTHETIC fixtures, and renders five hash-routed
 * sections. Every renderer tolerates {ok:false, error} payloads and nulls. */
"use strict";

/* ---------- i18n: the zh dictionary is the only place non-English text lives ---------- */
const I18N = {
  en: {
    tagline: "agentic factor mining and strategy research, with honesty gates",
    nav_home: "Home", nav_explorer: "Explorer", nav_backtest: "Backtest", nav_honesty: "Honesty", nav_method: "Method",
    badge_synthetic: "synthetic data", loading: "Loading", unavailable: "Unavailable:",
    hero_title: "Agents propose. Gates decide.",
    hero_lede: "QuantDesk is an agentic factor-mining and quant-strategy research stack. This page runs its deterministic half: a stdlib-only Python library that evaluates 19 adapted Alpha101 expressions and a vol-scaled time-series momentum stack, refuses to print a Rank-IC or a correlation its sample cannot support, and explains every simulated backtest trade tick by tick with no model in the loop. The LLM alpha-search loop is the sibling repository and is being merged in. Everything here is computed at build time on synthetic geometric-Brownian-motion data: the pipeline is real, the numbers are deliberately meaningless.",
    cta_explore: "Open the factor explorer", home_board_title: "Factor board", home_build_title: "Build stamp",
    explorer_title: "Alpha explorer", explorer_table_title: "19 adapted alphas + 11 library rows", explorer_corr_title: "Correlation heatmap",
    bt_title: "Target-weight backtest", bt_chart_title: "Equity vs buy-and-hold", bt_cost_title: "Cost grid", bt_tickets_title: "Tickets",
    bt_tickets_tag: "every trade explained tick by tick, no language model",
    hon_null_title: "Empirical null", hon_gates_title: "Gates that refuse to print", hon_not_title: "What this is not",
    method_title: "Verdict matrix", method_tag: "15 candidate inputs, one standalone survivor",
    method_note: "Verdicts assume a retail venue with roughly 190 bps round-trip cost measured in 2026-08. At that fee level the only input that survives as a standalone position rule is vol-scaled time-series momentum; everything else is feature-only (a regime feature, a risk layer, a gate) or execution-layer, the vocabulary of docs/FACTOR_VERDICTS.md.",
    foot_docs: "Docs", foot_note: "Synthetic data only. No venue data is stored, displayed, or redistributed.",
    col_factor: "Factor", col_style: "Style / TF", col_value: "Value", col_n: "n", col_ic1: "IC h1", col_ic2: "IC h2", col_decay: "Decay", col_turn: "Turnover", col_spark: "Last 24",
    warming: "warming up:", need: "need", have: "have", bars: "bars", low_sample: "low sample", refused: "refused", ok: "ok",
    blend: "TSMOM blend S = 0.5 s22 + 0.5 s261", deadzone: "dead zone", inside_band: "inside dead zone", sigma: "sigma annualized (t-2)", fast: "fast", slow: "slow",
    vol_ratio: "fast / slow vol ratio", overheat: "overheat", overheat_line: "overheat line 1.25", daily_bars: "daily bars", ic_1d: "IC 1d", alphas_1h: "19 adapted alphas, 1h bars",
    insufficient: "insufficient daily history", generated: "generated", package: "package", python: "python", fixture: "fixture", seed: "seed", symbols: "symbols",
    gates: "gates", costs: "default costs", corr_basis: "basis", no_corr: "No correlation matrix.", micro_na: "microstructure: not available (no lake on this build)",
    signal: "signal", band: "no-trade band", trials: "trials", trials_note: "configurations tried before publishing this chart",
    m_sharpe: "Sharpe", m_sortino: "Sortino", m_calmar: "Calmar", m_mdd: "Max drawdown", m_ret: "Total return", m_trades: "Trades", m_fees: "Fees paid",
    cost_bps: "cost bps", total_return: "total return", sharpe: "Sharpe", equity: "strategy", buy_hold: "buy and hold",
    tk_id: "ticket", tk_side: "side", tk_open: "open", tk_close: "close", tk_px: "entry / exit", tk_size: "size", tk_peak: "peak wt", tk_fills: "fills", tk_pnl: "pnl", tk_fees: "fees", tk_n: "decisions", tk_thesis: "thesis",
    tk_px_note: "entry / exit are the first and last simulated fill prices of a position that is rebalanced at every decision (see fills and peak weight); pnl is the realized cash flow of all its fills net of fees, so exit above entry with negative pnl is possible and not a bug.",
    simulated: "simulated fill",
    no_tickets: "No tickets: the strategy never left cash on this fixture.", why_open: "Why opened", why_close: "Why closed", still_open: "still open at the end of the sample",
    tick: "tick", conf: "conf", target: "target", position: "position", fill: "fill", fee: "fee", weight_after: "weight after", no_fill: "no fill",
    null_meta: "reseeds", pooled: "pooled", register: "institutional register 0.02-0.05", null_axis: "|Rank-IC| under the null (random walks)",
    null_legend: "bar = p95 of |IC| per alpha across reseeds; dark tick = median; light tick = max; dashed = pooled p50 / p95 / p99",
    reg_trend_up: "trend up", reg_trend_down: "trend down", reg_range_bound: "range bound", reg_hve: "high volatility event", reg_uncertain: "uncertain",
    act_tw100: "target 100%", act_tw60: "target 60%", act_tw30: "target 30%", act_tw20: "target 20%", act_halve: "halve position", act_flat: "flat", act_maintain: "maintain",
    v_standalone: "standalone-viable", v_feature: "feature-only", v_regime: "feature-only (regime)", v_risk: "feature-only (risk layer)", v_exec: "execution-layer",
    col_id: "id", col_name: "input", col_verdict: "verdict", col_why: "why",
    long: "long", flat: "flat",
    gate_items: [
    "<b>Closed bars only.</b> The still-forming bar is dropped before any factor sees it (<code>_closed_bars</code>); a partial bar is intra-bar lookahead.",
    "<b>Rank-IC refused below {pairs} pairs.</b> n is always reported; the number is not.",
    "<b>Overlapping horizons carry n_eff = n // h.</b> Below {eff} effective samples the IC is nulled.",
    "<b>Correlation cells refused below {pairs} overlapping observations;</b> daily and hourly series are never paired by index.",
    "<b>Time-series IC per symbol only.</b> A cross-sectional rank over a handful of symbols is degenerate and is deliberately not computed.",
    "<b>TSMOM needs 263 closed daily bars</b> (261-day lookback plus a two-day lag); short histories return <code>ok: false</code>, not a number.",
    "<b>Backtest timeline: decide on close(t), execute at open(t+1).</b> Per-fill fees and slippage, long/flat spot, cash can never go negative.",
    "<b>No-trade band</b> on target weights: a rebalance inside the band is skipped, so turnover is a first-class cost control.",
    "<b>Trial count reported, not counted.</b> <code>trial_count</code> is printed beside every backtest; the demo carries 1 (one parameter set, no sweep). A trial ledger that counts attempts is roadmap, not built.",
    "<b>Every ticket carries its reasoning</b> as a deterministic sentence generated from the numbers and the policy table; there is no language model anywhere in this library.",
    ],
    not_items: [
    "<b>Not a trading signal.</b> Rank-IC 0.02-0.05 is the institutional register; on this page every IC is computed on random walks and means nothing.",
    "<b>Not a venue client.</b> No exchange adapter, no order path, no credentials. Bring your own bars.",
    "<b>Not a data redistribution.</b> No venue data is stored, displayed, or redistributed; the build fixture is synthetic geometric Brownian motion.",
    "<b>Not an alpha claim.</b> The published verdict is that formulaic micro-alphas do not qualify standalone at roughly 190 bps round trip; the fee saved is the only edge that is certain.",
    "<b>Not financial advice.</b> Research tooling under the MIT license, provided as is.",
    ],
  },
  zh: {
    tagline: "带诚实闸门的 agentic 因子挖掘与策略研究", nav_home: "首页", nav_explorer: "浏览器", nav_backtest: "回测", nav_honesty: "诚实", nav_method: "方法",
    badge_synthetic: "合成数据", loading: "加载中", unavailable: "不可用:",
    hero_title: "Agent 负责提出,闸门负责裁决。",
    hero_lede: "QuantDesk 是一个 agentic 因子挖掘与量化策略研究栈。本页运行的是它的确定性一半:一个仅依赖标准库的 Python 因子库,评估 19 个时序化 Alpha101 表达式和波动率缩放的时序动量栈,拒绝打印样本不足以支撑的 Rank-IC 或相关性,并对每一笔模拟回测交易逐 tick 给出解释,过程中没有模型参与。LLM alpha 搜索循环在姊妹仓库中,正在并入。本页所有数字都是构建时在合成几何布朗运动数据上算出的:流水线是真的,数字刻意无意义。",
    cta_explore: "打开因子浏览器", home_board_title: "因子板", home_build_title: "构建戳",
    explorer_title: "Alpha 浏览器", explorer_table_title: "19 个适配 alpha + 11 个库因子行", explorer_corr_title: "相关性热图",
    bt_title: "目标权重回测", bt_chart_title: "策略 vs 买入持有", bt_cost_title: "成本网格", bt_tickets_title: "交易单",
    bt_tickets_tag: "每笔交易逐 tick 解释,无语言模型",
    hon_null_title: "经验零假设", hon_gates_title: "拒绝打印的闸门", hon_not_title: "这不是什么",
    method_title: "裁决矩阵", method_tag: "15 项候选输入,仅 1 项 standalone 幸存",
    method_note: "裁决基于 2026-08 实测约 190 bps 往返成本的零售场所。在该费率下唯一以 standalone 仓位规则幸存的输入是波动率缩放时序动量;其余是仅作特征(regime 特征、风险层、闸门)或执行层,即 docs/FACTOR_VERDICTS.md 的裁决词汇。",
    foot_docs: "文档", foot_note: "仅合成数据。不存储、展示或再分发任何场所数据。",
    col_factor: "因子", col_style: "风格 / 周期", col_value: "值", col_n: "n", col_ic1: "IC h1", col_ic2: "IC h2", col_decay: "衰减", col_turn: "换手代理", col_spark: "近 24 值",
    warming: "预热中:", need: "需", have: "现", bars: "根", low_sample: "低样本", refused: "拒绝", ok: "通过",
    blend: "TSMOM 混合分 S = 0.5 s22 + 0.5 s261", deadzone: "死区", inside_band: "死区内", sigma: "年化波动 (t-2)", fast: "快", slow: "慢",
    vol_ratio: "快慢波动比", overheat: "过热", overheat_line: "过热阈 1.25", daily_bars: "日线根数", ic_1d: "IC 1d", alphas_1h: "19 个适配 alpha,1h K 线",
    insufficient: "日线历史不足", generated: "生成时间", package: "包版本", python: "Python", fixture: "夹具", seed: "种子", symbols: "标的",
    gates: "闸门", costs: "默认成本", corr_basis: "口径", no_corr: "无相关性矩阵。", micro_na: "微结构:不可用(本次构建无数据湖)",
    signal: "信号", band: "不交易带", trials: "试验次数", trials_note: "发布此图前尝试过的配置数",
    m_sharpe: "夏普", m_sortino: "索提诺", m_calmar: "卡玛", m_mdd: "最大回撤", m_ret: "总收益", m_trades: "交易数", m_fees: "已付费用",
    cost_bps: "成本 bps", total_return: "总收益", sharpe: "夏普", equity: "策略", buy_hold: "买入持有",
    tk_id: "单号", tk_side: "方向", tk_open: "开仓", tk_close: "平仓", tk_px: "入场 / 出场", tk_size: "仓位", tk_peak: "峰值权重", tk_fills: "成交数", tk_pnl: "盈亏", tk_fees: "费用", tk_n: "决策数", tk_thesis: "论点",
    tk_px_note: "入场 / 出场是每次决策都再平衡的仓位的首笔与末笔模拟成交价(见成交数与峰值权重);盈亏是其全部成交扣费后的已实现现金流,因此出场高于入场而盈亏为负是可能的,并非错误。",
    simulated: "模拟成交",
    no_tickets: "无交易单:策略在此夹具上从未离开现金。", why_open: "开仓原因", why_close: "平仓原因", still_open: "样本结束时仍持有",
    tick: "tick", conf: "置信", target: "目标", position: "持仓", fill: "成交", fee: "费用", weight_after: "之后权重", no_fill: "未成交",
    null_meta: "重采样次数", pooled: "汇总", register: "机构级区间 0.02-0.05", null_axis: "零假设下的 |Rank-IC|(随机游走)",
    null_legend: "柱 = 各 alpha 跨重采样的 |IC| p95;深色刻度 = 中位数;浅色刻度 = 最大值;虚线 = 汇总 p50 / p95 / p99",
    reg_trend_up: "上升趋势", reg_trend_down: "下降趋势", reg_range_bound: "区间震荡", reg_hve: "高波动事件", reg_uncertain: "不确定",
    act_tw100: "目标 100%", act_tw60: "目标 60%", act_tw30: "目标 30%", act_tw20: "目标 20%", act_halve: "减半", act_flat: "清仓", act_maintain: "维持",
    v_standalone: "standalone-viable", v_feature: "仅作特征", v_regime: "仅作特征(regime)", v_risk: "仅作特征(风险层)", v_exec: "执行层",
    col_id: "编号", col_name: "输入", col_verdict: "裁决", col_why: "原因",
    long: "多头", flat: "空仓",
    gate_items: [
    "<b>只用已收盘 K 线。</b> 尚未收盘的 bar 在任何因子看到之前被丢弃(<code>_closed_bars</code>);部分 bar 是 bar 内前视。",
    "<b>Rank-IC 在 {pairs} 对以下拒绝打印。</b> n 总是报告,数值不报告。",
    "<b>重叠 horizon 携带 n_eff = n // h。</b> 有效样本低于 {eff} 时 IC 置空。",
    "<b>相关性格子在 {pairs} 个重叠观测以下拒绝;</b> 日线和小时线序列绝不按索引配对。",
    "<b>仅逐标的时序 IC。</b> 少数几个标的上的横截面排名是退化的,刻意不计算。",
    "<b>TSMOM 需要 263 根已收盘日线</b>(261 日回看加两日滞后);历史不足返回 <code>ok: false</code>,不返回数字。",
    "<b>回测时间线:在 close(t) 决策,在 open(t+1) 执行。</b> 逐笔费用与滑点,多头/空仓现货,现金永不为负。",
    "<b>目标权重的不交易带</b>:带内的再平衡被跳过,换手率因此是一等成本控制。",
    "<b>试验次数只报告、不计数。</b> 每个回测旁打印 <code>trial_count</code>;本演示为 1(单一参数集,无扫描)。会计数尝试次数的试验台账是路线图项目,尚未构建。",
    "<b>每张交易单携带其推理</b>:由数字和策略表生成的确定性句子;本库任何地方都没有语言模型。",
    ],
    not_items: [
    "<b>不是交易信号。</b> Rank-IC 0.02-0.05 是机构级区间;本页每个 IC 都在随机游走上计算,没有任何意义。",
    "<b>不是场所客户端。</b> 无交易所适配器、无下单路径、无凭证。请自带 K 线。",
    "<b>不是数据再分发。</b> 不存储、展示或再分发任何场所数据;构建夹具是合成几何布朗运动。",
    "<b>不是 alpha 声明。</b> 已发布的裁决是:在约 190 bps 往返成本下公式化微 alpha 不具备 standalone 资格;省下的费用才是唯一确定的优势。",
    "<b>不是投资建议。</b> MIT 许可下的研究工具,按原样提供。",
    ],
  },
};
let LANG = "en";
const t = k => { const d = I18N[LANG] || I18N.en; return d[k] != null ? d[k] : (I18N.en[k] != null ? I18N.en[k] : k); };

/* ---------- vocabulary: 5 market states x 7 target-weight actions ---------- */
const REGIME = {
  trend_up: { c: "--r-up", k: "reg_trend_up" }, trend_down: { c: "--r-down", k: "reg_trend_down" },
  range_bound: { c: "--r-range", k: "reg_range_bound" }, high_volatility_event: { c: "--r-vol", k: "reg_hve" },
  uncertain: { c: "--r-unc", k: "reg_uncertain" },
};
const ACTION = {
  target_weight_100: "act_tw100", target_weight_60: "act_tw60", target_weight_30: "act_tw30", target_weight_20: "act_tw20",
  halve_position: "act_halve", flat_position: "act_flat", maintain: "act_maintain",
};
const regimeLabel = r => REGIME[r] ? t(REGIME[r].k) : String(r || "-");
const regimeDot = r => `<span class="rdot" style="background:var(${(REGIME[r] || REGIME.uncertain).c})"></span>`;
const actionLabel = a => ACTION[a] ? t(ACTION[a]) : String(a || "-");

/* ---------- helpers ---------- */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = v => typeof v === "number" && isFinite(v);
const DASH = "—";
const nf = (v, d = 2) => isNum(v) ? v.toFixed(d) : DASH;
const sf = (v, d = 2) => isNum(v) ? (v > 0 ? "+" : "") + v.toFixed(d) : DASH;
const pct = (v, d = 2) => isNum(v) ? (v >= 0 ? "+" : "") + (v * 100).toFixed(d) + "%" : DASH;
const px = v => isNum(v) ? v.toFixed(v < 10 ? 4 : 2) : DASH;
function fmtTs(ts) {
  if (ts == null) return DASH;
  const d = typeof ts === "number" ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
  return isNaN(d.getTime()) ? esc(String(ts)) : d.toISOString().slice(0, 16).replace("T", " ");
}
const failBox = (d, what) => `<div class="empty">${esc(t("unavailable"))} ${esc(what)}<div class="err">${esc((d && d.error) || "no payload")}</div></div>`;
const GATES = { min_ic_pairs: 30, min_ic_eff: 8 };
const DATA = { build: null, board: null, backtest: null, null: null };
const EX = { sym: null, sortKey: "order", dir: 1 };
const BT = { sym: null };

async function loadJson(name) {
  try {
    const r = await fetch(`./data/${name}.json`, { cache: "no-cache" });
    if (!r.ok) return { ok: false, error: `HTTP ${r.status} for data/${name}.json` };
    return await r.json();
  } catch (e) { return { ok: false, error: `fetch failed for data/${name}.json: ${(e && e.message) || e}` }; }
}
const boardOk = b => b && b.ok !== false && Array.isArray(b.symbols);
const symbolRow = sym => boardOk(DATA.board) ? (DATA.board.symbols.find(s => s.symbol === sym) || null) : null;

function buildSeg(host, names, cur, onPick) {
  host.innerHTML = "";
  names.forEach(n => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = n; b.className = n === cur ? "active" : "";
    b.addEventListener("click", () => onPick(n)); host.appendChild(b);
  });
}

/* ---------- small SVG renderers ---------- */
function miniSpark(vals) {
  if (!Array.isArray(vals)) return DASH;
  const nums = vals.filter(isNum);
  if (nums.length < 2) return DASH;
  const w = 72, h = 20, mn = Math.min(...nums), mx = Math.max(...nums), rng = (mx - mn) || 1;
  const segs = []; let cur = [];
  vals.forEach((v, i) => {
    if (!isNum(v)) { if (cur.length > 1) segs.push(cur); cur = []; return; }
    cur.push(`${(i / Math.max(vals.length - 1, 1) * w).toFixed(1)},${(h - 2 - ((v - mn) / rng) * (h - 4)).toFixed(1)}`);
  });
  if (cur.length > 1) segs.push(cur);
  if (!segs.length) return DASH;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${segs.map(s => `<polyline points="${s.join(" ")}" fill="none" style="stroke:var(--accent)" stroke-width="1.2" stroke-linejoin="round"/>`).join("")}</svg>`;
}
function decayChart(d) {
  if (!d || !Array.isArray(d.lags) || !Array.isArray(d.ic)) return `<span class="faint">${DASH}</span>`;
  const k = d.lags.length, w = 72, h = 20, bw = Math.max(2, Math.floor(w / k) - 2);
  const scale = Math.max(0.05, ...d.ic.filter(isNum).map(Math.abs));
  const title = d.lags.map((l, i) => `h=${l}: ${isNum(d.ic[i]) ? sf(d.ic[i], 3) : "refused"} (n ${d.n && d.n[i] != null ? d.n[i] : "?"})`).join("\n");
  const bars = d.lags.map((l, i) => {
    const x = i * (w / k), v = d.ic[i];
    if (!isNum(v)) return `<rect x="${x.toFixed(1)}" y="${h / 2 - 0.5}" width="${bw}" height="1" style="fill:var(--faint)"/>`;
    const bh = Math.max(1, Math.abs(v) / scale * (h / 2 - 1));
    const y = v >= 0 ? h / 2 - bh : h / 2;
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw}" height="${bh.toFixed(1)}" style="fill:var(${v >= 0 ? "--gain" : "--loss"})"/>`;
  }).join("");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><title>${esc(title)}</title><line x1="0" x2="${w}" y1="${h / 2}" y2="${h / 2}" style="stroke:var(--border-strong)" stroke-width="0.6"/>${bars}</svg>`;
}
function dbarHtml(v, marks) {
  const X = x => ((Math.max(-1, Math.min(1, x)) + 1) / 2 * 100);
  let fill = "";
  if (isNum(v)) { const a = X(v), c = 50, l = Math.min(a, c), w = Math.max(Math.abs(a - c), 0.8); fill = `<i class="fill" style="left:${l}%;width:${w}%;background:var(${v >= 0 ? "--gain" : "--loss"})"></i>`; }
  return `<div class="dbar">${fill}<i class="zero" style="left:50%"></i>${(marks || []).map(m => `<i class="tick" style="left:${X(m)}%"></i>`).join("")}</div>`;
}
function ratioBarHtml(v, thresh, max) {
  const X = x => Math.max(0, Math.min(100, x / max * 100));
  const fill = isNum(v) ? `<i class="fill" style="left:0;width:${X(v)}%;background:var(${v > thresh ? "--loss" : "--gain"})"></i>` : "";
  return `<div class="dbar">${fill}<i class="tick" style="left:${X(thresh)}%"></i></div>`;
}

/* ---------- IC cell with gate badges ---------- */
function icCell(e) {
  if (!e) return `<span class="faint">${DASH}</span>`;
  const meta = `<small>n ${e.n == null ? DASH : e.n}${e.n_eff != null ? ` · n_eff ${e.n_eff}` : ""}</small>`;
  if (!isNum(e.ic)) {
    const why = (e.n != null && e.n < GATES.min_ic_pairs) ? `n<${GATES.min_ic_pairs}`
      : (e.overlap && e.n_eff != null && e.n_eff < GATES.min_ic_eff) ? `n_eff<${GATES.min_ic_eff}` : "degenerate";
    return `<span class="badge refused">${esc(t("refused"))}: ${why}</span> ${meta}`;
  }
  return `<span class="${e.ic > 0 ? "pos" : e.ic < 0 ? "neg" : ""}">${sf(e.ic, 3)}</span> <span class="badge ok">${esc(t("ok"))}</span> ${meta}`;
}

/* ---------- HOME ---------- */
function tsmomCard(sy, bars1d) {
  const card = document.createElement("div"); card.className = "scard";
  const rows = sy.existing || [];
  const row = rows.find(r => r.id === "tsmom_score") || {};
  const d = row.diag || {};
  const s = row.value, need = row.need || 263;
  card.style.setProperty("--regc", isNum(s) ? `var(${s >= 0 ? "--gain" : "--loss"})` : "var(--border)");
  const head = `<div class="sc-top"><span class="sc-tk">${esc(sy.symbol)}</span><span class="sc-px"><div class="p">${sf(s, 3)}</div><div class="c">${esc(t("blend"))}</div></span></div>`;
  if (row.ok === false || !isNum(s)) {
    card.innerHTML = head + `<div class="empty">${esc(t("insufficient"))}: ${bars1d == null ? "?" : bars1d} / ${need} ${esc(t("bars"))}</div>`;
    return card;
  }
  const sig = k => isNum(d[k]) ? (d[k] * 100).toFixed(1) + "%" : DASH;
  card.innerHTML = head + `<div class="fgrid">
    <div class="fcell wide"><div class="fl"><span>S</span><span>${esc(t("deadzone"))} ±0.15</span></div>
      <div class="fv">${sf(s, 3)}${Math.abs(s) < 0.15 ? `<small>${esc(t("inside_band"))}</small>` : ""}</div>${dbarHtml(s, [-0.15, 0.15])}</div>
    <div class="fcell"><div class="fl"><span>s22</span></div><div class="fv">${sf(d.s22, 3)}</div>${dbarHtml(d.s22)}</div>
    <div class="fcell"><div class="fl"><span>s261</span></div><div class="fv">${sf(d.s261, 3)}</div>${dbarHtml(d.s261)}</div>
    <div class="fcell"><div class="fl"><span>s65</span></div><div class="fv">${sf(d.s65, 3)}</div>${dbarHtml(d.s65)}</div>
    <div class="fcell"><div class="fl"><span>${esc(t("sigma"))}</span></div><div class="fv">${sig("sigma_ann")}<small>${esc(t("fast"))} ${sig("sigma_fast")} / ${esc(t("slow"))} ${sig("sigma_slow")}</small></div></div>
    <div class="fcell"><div class="fl"><span>${esc(t("vol_ratio"))}</span><span>${esc(t("overheat_line"))}</span></div>
      <div class="fv">${nf(d.vol_ratio, 3)}${isNum(d.vol_ratio) && d.vol_ratio > 1.25 ? `<span class="tag2 t-hot">${esc(t("overheat"))}</span>` : ""}</div>${ratioBarHtml(d.vol_ratio, 1.25, 2.5)}</div>
    <div class="fcell"><div class="fl"><span>${esc(t("daily_bars"))}</span><span>${bars1d == null ? DASH : bars1d} / ${need}</span></div>
      <div class="fv">${bars1d == null ? DASH : Math.min(100, Math.round(bars1d / need * 100)) + "%"}</div>
      <div class="track"><i style="width:${bars1d == null ? 0 : Math.min(100, bars1d / need * 100)}%;background:var(--accent)"></i></div></div>
    <div class="fcell wide"><div class="fl"><span>${esc(t("ic_1d"))}</span><span>${esc(t("col_turn"))} ${sf(row.turnover_proxy, 2)}</span></div><div class="fv">${icCell((row.ic || [])[0])}</div></div>
  </div>`;
  return card;
}
function alphaSummaryCard(sy) {
  const card = document.createElement("div"); card.className = "scard";
  const rows = sy.alpha101 || [];
  const body = rows.map(r => `<tr><td><b title="${esc(r.formula || "")}">${esc(r.id)}</b> <small>#${esc(r.num)}</small></td><td>${r.ok === false ? `<small>${esc(t("warming"))} ${r.need}</small>` : sf(r.value, 4)}</td><td>${icCell((r.ic || [])[0])}</td><td>${icCell((r.ic || [])[1])}</td><td>${miniSpark(r.spark)}</td></tr>`).join("");
  card.innerHTML = `<div class="sc-top"><span class="sc-tk">${esc(t("alphas_1h"))}</span><span class="sc-px"><div class="c">n_obs ≤ ${esc(DATA.board.bars_1h)}</div></span></div>
    <div class="tbl-scroll"><table class="pt"><thead><tr><th>${esc(t("col_factor"))}</th><th>${esc(t("col_value"))}</th><th>IC 1h</th><th>IC 24h</th><th>${esc(t("col_spark"))}</th></tr></thead><tbody>${body || `<tr><td colspan="5" class="empty">${DASH}</td></tr>`}</tbody></table></div>`;
  return card;
}
function renderHome() {
  const host = $("homeBoard"), b = DATA.board;
  if (!boardOk(b)) { host.innerHTML = failBox(b, "board.json"); }
  else {
    const sy = b.symbols.find(s => s.symbol === "SYN-1") || b.symbols[0];
    $("homeBoardSym").textContent = sy ? sy.symbol : DASH;
    host.innerHTML = "";
    if (!sy) host.innerHTML = `<div class="empty">${DASH}</div>`;
    else if (sy.ok === false) host.innerHTML = failBox(sy, sy.symbol);
    else { host.appendChild(tsmomCard(sy, b.bars_1d)); host.appendChild(alphaSummaryCard(sy)); }
  }
  const s = $("buildStamp"), d = DATA.build;
  if (!d || d.ok === false) { s.innerHTML = failBox(d, "build.json"); return; }
  const fx = d.fixture || {}, g = d.gates || {}, c = d.cost_bps_default || {};
  const cell = (k, v) => `<div><div class="fl">${esc(k)}</div><div class="fv">${v}</div></div>`;
  s.innerHTML = `<div class="stamp">
    ${cell(t("generated"), esc(d.generated_at || DASH))}${cell(t("package"), esc(d.package_version || DASH))}${cell(t("python"), esc(d.python_version || DASH))}
    ${cell(t("fixture"), `<span class="badge amber">${esc(fx.kind || "synthetic")}</span> ${esc(t("seed"))} ${esc(fx.seed ?? DASH)}`)}
    ${cell(t("symbols"), esc((fx.symbols || []).join(", ") || DASH) + ` · ${esc(fx.bars_1h ?? DASH)} x 1h · ${esc(fx.bars_1d ?? DASH)} x 1d`)}
    ${cell(t("gates"), `min_ic_pairs ${esc(g.min_ic_pairs ?? DASH)} · min_ic_eff ${esc(g.min_ic_eff ?? DASH)}`)}
    ${cell(t("costs"), `trading ${esc(c.trading ?? DASH)} bps · slippage ${esc(c.slippage ?? DASH)} bps`)}
    <div class="note">${esc(d.note || "")}</div></div>`;
}

/* ---------- EXPLORER ---------- */
const EX_COLS = [["order", "col_factor"], ["style", "col_style"], ["value", "col_value"], ["n_obs", "col_n"], ["ic1", "col_ic1"], ["ic2", "col_ic2"], ["decay", "col_decay"], ["turnover", "col_turn"], ["spark", "col_spark"]];
const sortVal = (r, k) => {
  const ics = Array.isArray(r.ic) ? r.ic : [];
  switch (k) {
    case "order": return r._order; case "style": return (r.style || "") + (r.timeframe || ""); case "value": return r.value;
    case "n_obs": return r.n_obs; case "ic1": return ics[0] ? ics[0].ic : null; case "ic2": return ics[1] ? ics[1].ic : null;
    case "turnover": return r.turnover_proxy; default: return null;
  }
};
function factorRowHtml(r) {
  const tip = [r.formula ? `formula: ${r.formula}` : "", r.adaptation ? `adaptation: ${r.adaptation}` : "", r.paper_ref ? `ref: ${r.paper_ref}` : "", r.source ? `source: ${r.source}` : ""].filter(Boolean).join("\n");
  const diag = r.diag ? `<span class="sub mono">s22 ${sf(r.diag.s22, 2)} · s65 ${sf(r.diag.s65, 2)} · s261 ${sf(r.diag.s261, 2)} · vr ${nf(r.diag.vol_ratio, 2)} · sigma ${isNum(r.diag.sigma_ann) ? (r.diag.sigma_ann * 100).toFixed(0) + "%" : DASH}</span>` : "";
  const idCell = `<td style="white-space:normal"><b title="${esc(tip)}">${esc(r.id)}</b>${r.num != null ? ` <small>#${esc(r.num)}</small>` : ""}${r.paper_ref ? `<span class="sub">${esc(r.paper_ref)}</span>` : ""}${diag}${r.note ? `<span class="sub" style="color:var(--amber)">${esc(r.note)}</span>` : ""}</td>`;
  const styleCell = `<td class="muted" style="font-family:var(--sans)">${esc(r.style || "")}${r.style && r.timeframe ? " · " : ""}${esc(r.timeframe || "")}</td>`;
  if (r.ok === false) return `<tr>${idCell}${styleCell}<td colspan="7" class="muted" style="text-align:left;font-family:var(--sans)">${esc(t("warming"))} ${esc(t("need"))} ${r.need == null ? "?" : r.need} ${esc(t("bars"))}, ${esc(t("have"))} ${r.n_obs == null ? "?" : r.n_obs}</td></tr>`;
  const ics = Array.isArray(r.ic) ? r.ic : [], warn = isNum(r.n_obs) && r.n_obs < 100;
  return `<tr class="${warn ? "warnrow" : ""}">${idCell}${styleCell}<td>${sf(r.value, 4)}${warn ? ` <span class="tag2 t-warm">${esc(t("low_sample"))}</span>` : ""}</td><td class="muted">${r.n_obs == null ? DASH : r.n_obs}</td>
    <td>${icCell(ics[0])}</td><td>${icCell(ics[1])}</td><td>${decayChart(r.decay)}</td><td>${sf(r.turnover_proxy, 2)}</td><td>${miniSpark(r.spark)}</td></tr>`;
}
function renderExplorer() {
  const b = DATA.board, disc = $("exDisc"), tbl = $("exTable"), corr = $("exCorr");
  if (!boardOk(b)) { disc.innerHTML = failBox(b, "board.json"); tbl.tHead.innerHTML = ""; tbl.tBodies[0].innerHTML = ""; corr.innerHTML = ""; $("exCount").textContent = ""; return; }
  const names = b.symbols.map(s => s.symbol);
  if (!names.includes(EX.sym)) EX.sym = names[0];
  buildSeg($("exSymSeg"), names, EX.sym, n => { EX.sym = n; renderExplorer(); });
  const sy = symbolRow(EX.sym);
  const dsc = b.disclaimer || {}, micro = (sy && sy.microstructure) || {};
  disc.innerHTML = `<section class="panel disc"><p>${esc(dsc.en || "")} <span class="mono" style="font-size:11px">${esc(dsc.ref || "")}</span></p>
    <p class="mono" style="font-size:11px">${esc(b.ic_convention || "")}</p>
    <p class="mono" style="font-size:11px">granularity ${esc(b.granularity || "1h")} · 1h bars ${esc(b.bars_1h ?? DASH)} · 1d bars ${esc(b.bars_1d ?? DASH)} · ${micro.available ? "microstructure: available" : esc(t("micro_na"))}</p></section>`;
  if (!sy || sy.ok === false) { tbl.tHead.innerHTML = ""; tbl.tBodies[0].innerHTML = `<tr><td colspan="9">${failBox(sy, EX.sym)}</td></tr>`; corr.innerHTML = ""; return; }
  const rows = [];
  (sy.alpha101 || []).forEach((r, i) => rows.push(Object.assign({ _order: i }, r)));
  (sy.existing || []).forEach((r, i) => rows.push(Object.assign({ _order: 100 + i }, r)));
  rows.sort((a, c) => {
    const x = sortVal(a, EX.sortKey), y = sortVal(c, EX.sortKey);
    if (x == null && y == null) return a._order - c._order; if (x == null) return 1; if (y == null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * EX.dir || a._order - c._order;
  });
  tbl.tHead.innerHTML = `<tr>${EX_COLS.map(([k, lab]) => { const s = !["decay", "spark"].includes(k); return `<th class="${s ? "sortable" : ""} ${EX.sortKey === k ? "sorted" : ""}" data-k="${k}">${esc(t(lab))}${EX.sortKey === k ? (EX.dir > 0 ? " ▴" : " ▾") : ""}</th>`; }).join("")}</tr>`;
  tbl.tBodies[0].innerHTML = rows.map(factorRowHtml).join("");
  $("exCount").textContent = `${(sy.alpha101 || []).length} alphas · ${(sy.existing || []).length} library rows`;
  const c = sy.correlation || {}, ids = c.ids || [], M = c.matrix || [];
  if (!ids.length || !M.length) { corr.innerHTML = `<div class="empty">${esc(t("no_corr"))}</div>`; return; }
  const cellHtml = (v, i, j) => {
    if (!isNum(v)) return `<td class="faint" data-i="${i}" data-j="${j}">${DASH}</td>`;
    const a = Math.round(8 + 60 * Math.min(1, Math.abs(v)));
    return `<td class="mono" data-i="${i}" data-j="${j}" style="background:color-mix(in srgb,var(${v >= 0 ? "--gain" : "--loss"}) ${a}%,transparent)">${v.toFixed(2)}</td>`;
  };
  corr.innerHTML = `<div style="padding:8px 16px 0;font-size:11px;color:var(--faint)">${esc(t("corr_basis"))}: ${esc(c.basis || "")}</div>
    <div class="tbl-scroll" style="padding:6px 10px 12px"><table class="pt corr" id="corrTable"><thead><tr><th></th>${ids.map(i => `<th>${esc(i)}</th>`).join("")}</tr></thead><tbody>${M.map((row, i) => `<tr><td class="rowlab mono">${esc(ids[i] || "")}</td>${row.map((v, j) => cellHtml(v, i, j)).join("")}</tr>`).join("")}</tbody></table></div>`;
  $("corrTable").addEventListener("mouseover", ev => {
    const td = ev.target.closest("td[data-i]"); if (!td) return;
    const i = +td.dataset.i, j = +td.dataset.j, v = (M[i] || [])[j];
    $("corrHover").textContent = `${ids[i]} × ${ids[j]} = ${isNum(v) ? sf(v, 3) : `${t("refused")}: n<${GATES.min_ic_pairs}`}`;
  });
}

/* ---------- BACKTEST ---------- */
function eqChart(eq, bh) {
  const pts = (arr) => (Array.isArray(arr) ? arr : []).filter(p => p && isNum(p.equity)).map(p => ({ ts: p.ts, v: p.equity }));
  const A = pts(eq), B = pts(bh);
  if (A.length < 2) return `<div class="empty">${DASH}</div>`;
  const a0 = A[0].v || 1, b0 = (B[0] && B[0].v) || 1;
  const na = A.map(p => p.v / a0), nb = B.map(p => p.v / b0);
  const all = na.concat(nb), mn = Math.min(...all), mx = Math.max(...all), rng = (mx - mn) || 1;
  const W = 640, H = 240, L = 46, R = 10, T = 12, Bm = 26, iw = W - L - R, ih = H - T - Bm;
  const path = (arr) => arr.map((v, i) => `${(L + i / Math.max(arr.length - 1, 1) * iw).toFixed(1)},${(T + ih - (v - mn) / rng * ih).toFixed(1)}`).join(" ");
  const yt = [mn, mn + rng / 2, mx].map(v => `<text class="axis" x="${L - 6}" y="${(T + ih - (v - mn) / rng * ih + 3).toFixed(1)}" text-anchor="end">${v.toFixed(2)}</text>`).join("");
  const grid = [0, 0.5, 1].map(f => `<line x1="${L}" x2="${W - R}" y1="${(T + ih * f).toFixed(1)}" y2="${(T + ih * f).toFixed(1)}" style="stroke:var(--border)" stroke-width="0.7"/>`).join("");
  const xt = [[0, "start"], [0.5, "middle"], [1, "end"]].map(([f, an]) => `<text class="axis" x="${(L + iw * f).toFixed(1)}" y="${H - 8}" text-anchor="${an}">${fmtTs(A[Math.round(f * (A.length - 1))].ts).slice(0, 10)}</text>`).join("");
  const one = `<line x1="${L}" x2="${W - R}" y1="${(T + ih - (1 - mn) / rng * ih).toFixed(1)}" y2="${(T + ih - (1 - mn) / rng * ih).toFixed(1)}" style="stroke:var(--faint)" stroke-dasharray="3 3" stroke-width="0.7"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="equity chart">${grid}${one}${yt}${xt}
    ${nb.length > 1 ? `<polyline points="${path(nb)}" fill="none" style="stroke:var(--muted)" stroke-width="1.3"/>` : ""}
    <polyline points="${path(na)}" fill="none" style="stroke:var(--accent)" stroke-width="1.8" stroke-linejoin="round"/></svg>
    <div class="legend"><span><i style="background:var(--accent)"></i>${esc(t("equity"))} ${pct(na[na.length - 1] - 1)}</span><span><i style="background:var(--muted)"></i>${esc(t("buy_hold"))} ${nb.length ? pct(nb[nb.length - 1] - 1) : DASH}</span></div>`;
}
function ticketRow(tk) {
  const pnlCls = isNum(tk.pnl) ? (tk.pnl >= 0 ? "pos" : "neg") : "";
  const nFills = (Array.isArray(tk.decisions) ? tk.decisions : []).filter(d => d && d.outcome && d.outcome.fill_px != null).length;
  return `<tr class="clickable" data-tk="${esc(tk.ticket_id)}"><td><b>${esc(tk.ticket_id)}</b></td><td><span class="tag2 ${tk.side === "long" ? "t-up" : "t-neu"}">${esc(tk.side === "long" ? t("long") : tk.side === "flat" ? t("flat") : tk.side)}</span></td>
    <td>${fmtTs(tk.open_ts)}</td><td>${tk.close_ts == null ? `<small>${esc(t("still_open"))}</small>` : fmtTs(tk.close_ts)}</td><td>${px(tk.entry)} / ${px(tk.exit)}</td><td>${nf(tk.size, 2)}</td><td>${tk.side === "long" ? nf(tk.peak_weight, 2) : DASH}</td><td>${nFills}</td>
    <td class="${pnlCls}">${isNum(tk.pnl) ? sf(tk.pnl, 2) : DASH}</td><td>${nf(tk.fees, 2)}</td><td>${tk.n_decisions ?? DASH}</td><td class="sub" style="text-align:left">${esc(tk.thesis || "")}</td></tr>`;
}
function renderBacktest() {
  const d = DATA.backtest, note = $("btNote");
  const hosts = ["btChart", "btMetrics", "btCost", "btTickets"];
  if (!d || d.ok === false || !d.symbols || typeof d.symbols !== "object") { note.innerHTML = failBox(d, "backtest.json"); hosts.forEach(h => { $(h).innerHTML = ""; }); $("btSymSeg").innerHTML = ""; return; }
  const names = Object.keys(d.symbols);
  if (!names.includes(BT.sym)) BT.sym = names.includes("SYN-1") ? "SYN-1" : names[0];
  buildSeg($("btSymSeg"), names, BT.sym, n => { BT.sym = n; renderBacktest(); });
  note.innerHTML = `<section class="panel disc"><p><b>${esc(t("signal"))}</b> ${esc(d.signal || DASH)} · <b>${esc(t("band"))}</b> ${isNum(d.band) ? d.band.toFixed(2) : esc(d.band ?? DASH)}</p><p>${esc(d.note || "")}</p></section>`;
  const s = d.symbols[BT.sym];
  if (!s || s.ok === false) { hosts.forEach(h => { $(h).innerHTML = failBox(s, BT.sym); }); return; }
  $("btChart").innerHTML = eqChart(s.equity, s.buy_hold);
  $("btChartMeta").textContent = `${(s.equity || []).length} bars`;
  const m = s.metrics || {};
  const tile = (lab, val, sub) => `<div class="kpi"><div class="klab">${esc(lab)}</div><div class="kval">${val}</div>${sub ? `<div class="ksub">${esc(sub)}</div>` : ""}</div>`;
  $("btMetrics").innerHTML = tile(t("m_ret"), `<span class="${isNum(m.total_return) ? (m.total_return >= 0 ? "pos" : "neg") : ""}">${pct(m.total_return)}</span>`) + tile(t("m_sharpe"), nf(m.sharpe, 2)) + tile(t("m_sortino"), nf(m.sortino, 2))
    + tile(t("m_calmar"), nf(m.calmar, 2)) + tile(t("m_mdd"), `<span class="neg">${pct(m.max_drawdown)}</span>`) + tile(t("m_trades"), isNum(m.n_trades) ? String(Math.round(m.n_trades)) : DASH) + tile(t("m_fees"), nf(m.fees_paid_bps, 1), "bps of initial equity");
  const grid = Array.isArray(s.cost_grid) ? s.cost_grid : [];
  let be = false;
  $("btCost").innerHTML = grid.length ? `<table class="pt"><thead><tr><th>${esc(t("cost_bps"))}</th><th>${esc(t("total_return"))}</th><th>${esc(t("sharpe"))}</th></tr></thead><tbody>${grid.map(g => { const neg = isNum(g.total_return) && g.total_return < 0, cls = neg && !be ? "breakeven" : ""; if (neg) be = true; return `<tr class="${cls}"><td>${esc(g.cost_bps)}</td><td class="${neg ? "neg" : "pos"}">${pct(g.total_return)}</td><td>${nf(g.sharpe, 2)}</td></tr>`; }).join("")}</tbody></table>` : `<div class="empty">${DASH}</div>`;
  $("btTrials").textContent = `${t("trials")}: ${s.trial_count ?? DASH} — ${t("trials_note")}`;
  const tks = Array.isArray(s.tickets) ? s.tickets : [];
  $("btTickets").innerHTML = tks.length ? `<div class="tbl-scroll"><table class="pt"><thead><tr><th>${esc(t("tk_id"))}</th><th>${esc(t("tk_side"))}</th><th>${esc(t("tk_open"))}</th><th>${esc(t("tk_close"))}</th><th>${esc(t("tk_px"))}</th><th>${esc(t("tk_size"))}</th><th>${esc(t("tk_peak"))}</th><th>${esc(t("tk_fills"))}</th><th>${esc(t("tk_pnl"))}</th><th>${esc(t("tk_fees"))}</th><th>${esc(t("tk_n"))}</th><th style="text-align:left">${esc(t("tk_thesis"))}</th></tr></thead><tbody>${tks.map(ticketRow).join("")}</tbody></table></div><p class="why muted" style="padding:6px 16px 10px;font-size:12px">${esc(t("tk_px_note"))}</p>` : `<div class="empty">${esc(t("no_tickets"))}</div>`;
  $("btTickets").querySelectorAll("tr[data-tk]").forEach(tr => tr.addEventListener("click", () => { const tk = tks.find(x => String(x.ticket_id) === tr.dataset.tk); if (tk) openDrawer(tk); }));
}
function decisionHtml(dc) {
  const o = dc.observation || {}, out = dc.outcome || {};
  const tw = o.target_weight, pw = o.position_weight;
  const cls = isNum(tw) && isNum(pw) ? (tw > pw + 1e-9 ? "buy" : tw < pw - 1e-9 ? "sell" : "") : "";
  const ob = (k, v) => `<span>${esc(k)} <b>${v}</b></span>`;
  return `<div class="tick"><div class="th"><b>#${esc(dc.tick_no)}</b><span>${fmtTs(dc.ts)}</span>${regimeDot(dc.regime)}<span>${esc(regimeLabel(dc.regime))}</span><span>${esc(t("conf"))} ${nf(dc.confidence, 2)}</span><span class="act ${cls}">${esc(actionLabel(dc.action))}</span></div>
    <div class="obs">${ob("close", px(o.close))}${ob("tsmom", sf(o.tsmom_score, 3))}${ob("sigma", isNum(o.sigma_ann) ? (o.sigma_ann * 100).toFixed(1) + "%" : DASH)}${ob("vr", nf(o.vol_ratio, 2))}${ob(t("target"), nf(tw, 2))}${ob(t("position"), nf(pw, 2))}</div>
    <div class="reason">${esc(dc.reasoning || "")}</div>
    <div class="out">${out.fill_px == null ? esc(t("no_fill")) : `${esc(t("fill"))} ${px(out.fill_px)} (${esc(t("simulated"))}) · ${esc(t("fee"))} ${nf(out.fee, 2)}`} · ${esc(t("weight_after"))} ${nf(out.weight_after, 2)}</div></div>`;
}
function openDrawer(tk) {
  $("drawerTitle").textContent = `${tk.ticket_id} · ${tk.symbol || ""} · ${tk.side === "long" ? t("long") : tk.side === "flat" ? t("flat") : tk.side || ""}`;
  const decs = Array.isArray(tk.decisions) ? tk.decisions : [];
  $("drawerBody").innerHTML = `<p class="why"><b>${esc(t("why_open"))}:</b> ${esc(tk.why_open || DASH)}</p><p class="why"><b>${esc(t("why_close"))}:</b> ${esc(tk.why_close || t("still_open"))}</p>
    <p class="why mono" style="font-size:12px">${esc(t("tk_px"))} ${px(tk.entry)} / ${px(tk.exit)} · ${esc(t("tk_size"))} ${nf(tk.size, 2)} · ${esc(t("tk_pnl"))} ${isNum(tk.pnl) ? sf(tk.pnl, 2) : DASH} · ${esc(t("tk_fees"))} ${nf(tk.fees, 2)} · ${decs.length} ${esc(t("tk_n"))}</p>${decs.map(decisionHtml).join("")}`;
  $("drawer").hidden = false; $("drawerMask").hidden = false;
}
function closeDrawer() { $("drawer").hidden = true; $("drawerMask").hidden = true; }

/* ---------- HONESTY ---------- */
function renderNull() {
  const d = DATA.null, host = $("nullChart");
  if (!d || d.ok === false || !Array.isArray(d.alphas)) { host.innerHTML = failBox(d, "null.json"); $("nullMeta").textContent = ""; return; }
  const P = d.pooled || {};
  $("nullMeta").textContent = `${t("null_meta")} ${d.n_reseeds ?? DASH} · ${t("bars")} ${d.bars ?? DASH} · ${t("pooled")} p50 ${nf(P.p50, 3)} p95 ${nf(P.p95, 3)} p99 ${nf(P.p99, 3)} (n ${P.n ?? DASH})`;
  const rows = d.alphas.slice().sort((a, b) => (b.abs_ic_p95 || 0) - (a.abs_ic_p95 || 0));
  const xmax = Math.max(0.1, ...rows.map(r => r.abs_ic_max || 0), P.p99 || 0) * 1.08;
  const W = 640, L = 52, R = 14, T = 22, rh = 15, H = T + rows.length * rh + 30, iw = W - L - R;
  const X = v => L + Math.max(0, Math.min(1, v / xmax)) * iw;
  const band = `<rect x="${X(0.02).toFixed(1)}" y="${T - 6}" width="${(X(0.05) - X(0.02)).toFixed(1)}" height="${rows.length * rh + 8}" style="fill:var(--amber-soft)"/><text class="axis" x="${X(0.035).toFixed(1)}" y="${T - 9}" text-anchor="middle" style="fill:var(--amber)">${esc(t("register"))}</text>`;
  const bars = rows.map((r, i) => {
    const y = T + i * rh;
    return `<text class="axis" x="${L - 6}" y="${y + 10}" text-anchor="end">${esc(r.id)}</text>
      <rect x="${L}" y="${y + 2}" width="${(X(r.abs_ic_p95 || 0) - L).toFixed(1)}" height="${rh - 5}" style="fill:var(--accent-soft)"/>
      ${isNum(r.abs_ic_p50) ? `<rect x="${(X(r.abs_ic_p50) - 1).toFixed(1)}" y="${y + 1}" width="2" height="${rh - 3}" style="fill:var(--accent)"/>` : ""}
      ${isNum(r.abs_ic_max) ? `<rect x="${(X(r.abs_ic_max) - 0.7).toFixed(1)}" y="${y + 3}" width="1.4" height="${rh - 7}" style="fill:var(--faint)"/>` : ""}
      <title>${esc(r.id)}: p50 ${nf(r.abs_ic_p50, 3)} p95 ${nf(r.abs_ic_p95, 3)} max ${nf(r.abs_ic_max, 3)}</title>`;
  }).join("");
  const pooled = [["p50", P.p50], ["p95", P.p95], ["p99", P.p99]].filter(([, v]) => isNum(v)).map(([k, v]) => `<line x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${T - 4}" y2="${T + rows.length * rh}" style="stroke:var(--loss)" stroke-dasharray="3 3" stroke-width="0.9"/><text class="axis" x="${X(v).toFixed(1)}" y="${T + rows.length * rh + 11}" text-anchor="middle" style="fill:var(--loss)">${k}</text>`).join("");
  const ticks = [0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4].filter(v => v <= xmax).map(v => `<line x1="${X(v).toFixed(1)}" x2="${X(v).toFixed(1)}" y1="${T - 4}" y2="${T + rows.length * rh}" style="stroke:var(--border)" stroke-width="0.6"/><text class="axis" x="${X(v).toFixed(1)}" y="${H - 4}" text-anchor="middle">${v.toFixed(2)}</text>`).join("");
  host.innerHTML = `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("null_axis"))}">${ticks}${band}${bars}${pooled}</svg><div class="legend"><span>${esc(t("null_axis"))}</span><span>${esc(t("null_legend"))}</span></div><p class="why muted" style="padding:0 4px 8px;font-size:12.5px">${esc(d.note || "")}</p></div>`;
}
function renderHonesty() {
  renderNull();
  const g = (DATA.build && DATA.build.gates) || GATES;
  const fill = s => s.replace(/\{pairs\}/g, g.min_ic_pairs).replace(/\{eff\}/g, g.min_ic_eff);
  $("gatesList").innerHTML = t("gate_items").map(s => `<li>${fill(s)}</li>`).join("");
  $("notList").innerHTML = t("not_items").map(s => `<li>${s}</li>`).join("");
  const b = DATA.build || {};
  $("termsNote").innerHTML = `<p>${esc(b.note || t("foot_note"))}</p><p class="mono" style="font-size:11px">${esc(b.generated_at ? `build ${b.generated_at} · quantdesk ${b.package_version || ""} · python ${b.python_version || ""}` : "")}</p>`;
}

/* ---------- METHOD ---------- */
const METHOD = [
  ["F1", "Time-series momentum (vol-scaled)", "v_standalone", "The only standalone position rule: vol targeting holds a fraction of notional, so the fee load shrinks with the exposure."],
  ["F2", "Gaussian-mixture regime classifier", "v_regime", "Benchmark for any regime read, never a trade signal."],
  ["F3", "Cross-sectional momentum (market-residualized)", "v_feature", "Carries information but cannot pay for its own trades: published premia are cost-free, long-short and small-cap; large caps flattened after 2021. Roadmap."],
  ["F4", "Market beta and residual decomposition", "v_risk", "Prerequisite for every cross-sectional factor; not alpha by itself."],
  ["F5", "Funding-rate carry", "v_feature", "A conditioning input on spot, zero marginal cost as a gate; 8h settlement cannot clear the round trip standalone and the series is not aligned to 1h bars. z-score built, no feed."],
  ["F6", "Volatility and dispersion regime", "v_regime", "Hosts the overheat gate: fast / slow vol ratio above 1.25 marks a high-volatility event, which the policy table answers with halve_position."],
  ["F7", "Inventory-skewed maker quoting", "v_exec", "The fee lever itself: taker to maker saves roughly 60 bps per side, more than any micro-alpha predicts."],
  ["F8", "Cross-venue lead-lag fair value", "v_exec", "Fair-value anchor for quoting; needs a multi-venue feed."],
  ["F9", "Cross-sectional low volatility", "v_feature", "Survives only at monthly-or-slower rebalance with a band; IC test pending, not shipped. Roadmap."],
  ["F10", "Order-flow imbalance and multi-level book pressure", "v_exec", "Observable only, no IC evaluation yet; execution-layer use class."],
  ["F11", "Markout flow toxicity", "v_exec", "A quote-pulling input, not a direction."],
  ["F12", "Stale-quote pickoff surface", "v_exec", "Mispricing versus latency curve."],
  ["F13", "Cross-venue dispersion and oracle confidence", "v_feature", "Modulates sizing or the band, produces no trades; deferred until it beats free proxies (realized vol, range, spread). Roadmap."],
  ["F14", "Stablecoin depeg stress", "v_regime", "Low-cost observable; regime feature only."],
  ["F15", "Lasso combination layer", "v_exec", "Execution layer for the portfolio: decides weights among validated factors. Built last, only after five or more factors pass IC validation; today zero qualify. Roadmap."],
];
function renderMethod() {
  $("methodTable").innerHTML = `<table class="pt"><thead><tr><th>${esc(t("col_id"))}</th><th style="text-align:left">${esc(t("col_name"))}</th><th style="text-align:left">${esc(t("col_verdict"))}</th><th style="text-align:left">${esc(t("col_why"))}</th></tr></thead><tbody>${METHOD.map(([id, name, v, why]) => `<tr><td><b>${id}</b></td><td style="text-align:left;font-family:var(--sans)">${esc(name)}</td><td style="text-align:left"><span class="badge ${v === "v_standalone" ? "ok" : ""}">${esc(t(v))}</span></td><td class="sub" style="text-align:left;max-width:520px">${esc(why)}</td></tr>`).join("")}</tbody></table>`;
}

/* ---------- router, i18n, theme, boot ---------- */
const VIEWS = ["home", "explorer", "backtest", "honesty", "method"];
function applyHash() {
  let h = (location.hash || "#home").slice(1);
  if (!VIEWS.includes(h)) h = "home";
  VIEWS.forEach(v => $("view-" + v).classList.toggle("active", v === h));
  document.querySelectorAll(".tab").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "#" + h));
  closeDrawer();
}
function applyI18n() {
  document.documentElement.lang = LANG === "zh" ? "zh" : "en";
  document.querySelectorAll("[data-i18n]").forEach(e => { e.textContent = t(e.dataset.i18n); });
  $("langBtn").textContent = LANG === "en" ? "ZH" : "EN";
}
function renderAll() { applyI18n(); renderHome(); renderExplorer(); renderBacktest(); renderHonesty(); renderMethod(); }
const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
$("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next); store.set("qd-theme", next);
});
$("langBtn").addEventListener("click", () => { LANG = LANG === "en" ? "zh" : "en"; store.set("qd-lang", LANG); renderAll(); });
$("exTable").tHead.addEventListener("click", ev => {
  const th = ev.target.closest("th.sortable"); if (!th) return;
  const k = th.dataset.k;
  if (EX.sortKey === k) EX.dir = -EX.dir; else { EX.sortKey = k; EX.dir = k === "order" || k === "style" ? 1 : -1; }
  renderExplorer();
});
$("drawerClose").addEventListener("click", closeDrawer);
$("drawerMask").addEventListener("click", closeDrawer);
document.addEventListener("keydown", ev => { if (ev.key === "Escape") closeDrawer(); });
window.addEventListener("hashchange", applyHash);
(function boot() {
  const th = store.get("qd-theme"); if (th === "dark" || th === "light") document.documentElement.setAttribute("data-theme", th);
  const lg = store.get("qd-lang"); if (lg === "zh" || lg === "en") LANG = lg;
  applyI18n(); applyHash();
  Promise.all(["build", "board", "backtest", "null"].map(loadJson)).then(([build, board, backtest, nul]) => {
    DATA.build = build; DATA.board = board; DATA.backtest = backtest; DATA.null = nul;
    if (build && build.gates) { GATES.min_ic_pairs = build.gates.min_ic_pairs ?? GATES.min_ic_pairs; GATES.min_ic_eff = build.gates.min_ic_eff ?? GATES.min_ic_eff; }
    renderAll();
  });
})();
