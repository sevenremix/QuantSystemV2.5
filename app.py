import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import pandas_datareader.data as web
from datetime import datetime, timedelta

# 配置 Streamlit 页面
st.set_page_config(page_title="QuantSystem L2.5", layout="wide")

# --- 0. 核心样式美化 (CSS Injection) ---
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    div[data-testid="stMetricValue"] {
        font-size: 32px;
        color: #00d4ff;
    }
    .stTable {
        border-radius: 10px;
        overflow: hidden;
        border: 1px solid #30363d;
    }
    h1, h2, h3 {
        color: #ffffff;
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .stInfo {
        background-color: rgba(23, 31, 45, 0.8);
        border: 1px solid #1f6feb;
        border-radius: 8px;
    }
    div[data-testid="stMetric"] {
        text-align: right;
    }
    div[data-testid="stMetric"] > div {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 1. 配置控制矩阵 (TICKER_CONFIG) ---
GLOBAL_DEFAULT_CONFIG = {
    "tp_z": 1.5, "sl_z_min": -2.5, "R_base": 0.33
}

TICKER_CONFIG = {
    "NVDA": {
        "pe_threshold": 60, "buy_z": -1.5, "g_expected": 0.80, 
        "sl_pe_max": 70, "sl_z_min": -3.0, "R_base": 0.3
    },
    "TSM": {
        "pe_threshold": 20, "buy_z": -1.5, "g_expected": 0.20, 
        "tp_z": 1.5, "sl_pe_max": 25, "R_base": 0.5
    },
    "MSFT": {
        "pe_threshold": 32, "buy_z": -1.8, "g_expected": 0.15,
        "sl_pe_max": 38
    },
    "MU": {
        "pe_threshold": "N/A", "pb_threshold": 1.5, "buy_z": -1.5, 
        "g_expected": "N/A", "sl_pb_max": 2.5, "is_cyclical": True
    },
    "AVGO": {
        "pe_threshold": 28, "buy_z": -1.5, "g_expected": 0.25,
        "sl_pe_max": 35
    }
}

INDEX_CONFIG = ["QQQ", "VOO"]
PORTFOLIO = list(TICKER_CONFIG.keys()) + INDEX_CONFIG + ["IAU"]

# --- 2. 数据获取模块 ---
@st.cache_data(ttl=3600)
def get_macro_data():
    """从 FRED 获取 10年期实际利率 (DFII10) 并执行 EMA3 平滑处理"""
    try:
        start = datetime.now() - timedelta(days=60)
        df_fred = web.DataReader("DFII10", "fred", start, datetime.now())
        recent_peak = float(df_fred['DFII10'].tail(20).max())
        df_fred['EMA3'] = df_fred['DFII10'].ewm(span=3, adjust=False).mean()
        current_ema = float(df_fred['EMA3'].iloc[-1])
        ma20 = float(df_fred['DFII10'].rolling(window=20).mean().iloc[-1])
        return current_ema, recent_peak, ma20
    except Exception as e:
        return None, None, None

def get_fundamental_data(ticker_symbol):
    """同时获取 P/E 与 P/B (市净率，为了周期股审查)"""
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        return {
            "forwardPE": info.get('forwardPE', None),
            "priceToBook": info.get('priceToBook', None)
        }
    except:
        return {"forwardPE": None, "priceToBook": None}

def get_zscore_data(ticker_symbol, period="100d", window=20):
    try:
        df = yf.download(ticker_symbol, period=period, interval="1d", progress=False)
        if df.empty: return None, None
        close = df['Close']
        ma = close.rolling(window=window).mean()
        std = close.rolling(window=window).std()
        z_score = (close - ma) / std
        # 兼容 yfinance v0.2+ 的 MultiIndex 输出，确保返回标量
        z_val = z_score.iloc[-1]
        price_val = close.iloc[-1]
        if hasattr(z_val, 'values'): z_val = z_val.values.flatten()[0]
        if hasattr(price_val, 'values'): price_val = price_val.values.flatten()[0]
        
        return float(z_val), float(price_val)
    except Exception as e:
        return None, None

# --- 3. 逻辑引擎 v2.5 (三门共振与解耦执行) ---
def get_trading_signal(symbol, z_score, fundamentals, macro_status, bench_z, gold_z):
    try:
        z = float(z_score) if z_score is not None else None
        bz = float(bench_z) if bench_z is not None else None
        gz = float(gold_z) if gold_z is not None else None
    except:
        return "Exception", "🚫 数据歧义", "N/A"

    if z is None or bz is None:
        return "Exception", "🚫 核心数据缺失", "N/A"

    curr_val = macro_status['val']
    peak_val = macro_status['peak']
    v_drop = peak_val - curr_val

    # 1. 权重调节与 C_action 基础推演
    if v_drop >= 0.17: w_macro = 0.5
    elif 0 < v_drop < 0.17: w_macro = 1.0
    else: w_macro = 1.5

    if bz > 0: w_market = 0.8
    elif -0.5 <= bz <= 0: w_market = 1.0
    else: w_market = 1.5

    macro_bullish = bool(v_drop > 0.1)
    market_confirmed = bool(bz >= -0.5)

    if symbol == "IAU":
        if macro_bullish and (gz is not None and gz < -1.5): return "Strong Buy", "🔥 黄金避险", "安全"
        elif gz is not None and gz > 1.5: return "Sell", "超卖", "清仓"
        return "Neutral", "", "维持"

    if symbol in INDEX_CONFIG:
        if z < -1.5 and market_confirmed: return "💎 Index Buy", "情绪恐慌", "买入"
        elif z > 1.5: return "🟡 Index Sell", "动能耗尽", "减持"
        return "Neutral", "", "维持"

    if symbol not in TICKER_CONFIG:
        return "Neutral", "未配置此标的", "N/A"

    cfg = TICKER_CONFIG[symbol]
    
    # 无缝调用缺省架构，避免死机
    r_base = cfg.get("R_base", GLOBAL_DEFAULT_CONFIG["R_base"])
    tp_z = cfg.get("tp_z", GLOBAL_DEFAULT_CONFIG["tp_z"])
    buy_z = cfg.get("buy_z", -1.5)
    
    # 动态公式：C_action
    c_action = min(1.0, r_base * w_macro * w_market)
    c_act_str = f"减仓 {c_action * 100:.1f}%"

    is_cyclical = cfg.get("is_cyclical", False)
    fwd_pe = fundamentals.get("forwardPE")
    pb = fundamentals.get("priceToBook")

    # 2. 优先级极高：逻辑止损 (PE/PB 崩坏直接清仓)
    if is_cyclical:
        sl_pb_max = cfg.get("sl_pb_max", float('inf'))
        curr_pb = float(pb) if pb is not None else float('inf')
        if curr_pb > sl_pb_max:
            return "🔴 逻辑止损", "PB 崩坏", "100% 强制全清"
    else:
        sl_pe_max = cfg.get("sl_pe_max", float('inf'))
        curr_pe = float(fwd_pe) if fwd_pe is not None else float('inf')
        if curr_pe > sl_pe_max:
            return "🔴 逻辑止损", "PE 崩坏", "100% 强制全清"

    # 3. 优先级中：技术止盈止损与共振准入
    stock_cheap = False
    peg_str = ""
    
    if is_cyclical:
        pb_threshold = cfg.get("pb_threshold", 0)
        curr_pb = float(pb) if pb is not None else float('inf')
        if (curr_pb < pb_threshold) and (z <= buy_z): stock_cheap = True
    else:
        curr_pe = float(fwd_pe) if fwd_pe is not None else float('inf')
        g_exp = cfg.get("g_expected", None)
        pe_threshold = cfg.get("pe_threshold", 0)
        
        peg = curr_pe / (g_exp * 100) if (g_exp and g_exp != "N/A" and curr_pe != float('inf')) else float('inf')
        peg_str = f"(PEG={peg:.2f})" if peg != float('inf') else ""
        
        if (curr_pe < pe_threshold) and (z <= buy_z) and (peg <= 1.0):
            stock_cheap = True

    if stock_cheap and macro_bullish and market_confirmed:
        return "💎 逻辑确认", f"三门共振开启 {peg_str}", "安全建立底仓"
        
    # 其余走廊波动管理
    if z >= tp_z:
        return "🟡 部分止盈", f"抵达走廊上轨", c_act_str
    elif z <= buy_z and not (macro_bullish and market_confirmed):
        return "🟠 防御降仓", "技术超卖+环境压制", c_act_str

    distance = round(tp_z - z, 2)
    return "🟢 安全持有", f"Z-距止盈: {distance}", "维持"

# --- 4. UI 展示层 ---
curr_ema, peak_val, ma20 = get_macro_data()
if curr_ema is not None:
    vel = peak_val - curr_ema
    macro_status = {'val': curr_ema, 'peak': peak_val}
else:
    st.sidebar.error("FRED 数据读取失败")
    macro_status = {'val': 0, 'peak': 0}
    vel = 0

# 5. 顶层标题与宏观看板整合 (Header Row)
title_col, metric_col = st.columns([3, 1])
with title_col:
    st.title("QuantSystem L2.5: 监控矩阵")
with metric_col:
    if curr_ema:
        st.metric("10Y Real Rate (EMA3)", f"{curr_ema:.2f}%", delta=f"-{vel:.2f}% (平滑势能)")

bench_z, _ = get_zscore_data("QQQ")
gold_z, _ = get_zscore_data("IAU")

results = []
for ticker in PORTFOLIO:
    z, price = get_zscore_data(ticker)
    fundamentals = get_fundamental_data(ticker)
    sig, warn, action = get_trading_signal(ticker, z, fundamentals, macro_status, bench_z, gold_z)
    
    if ticker in TICKER_CONFIG:
        cfg = TICKER_CONFIG[ticker]
        curr_z = round(float(z), 2) if z is not None else "待测算"
        is_cyclical = cfg.get("is_cyclical", False)
        tp_z = cfg.get("tp_z", GLOBAL_DEFAULT_CONFIG["tp_z"])
        if is_cyclical:
            sl_str = f"P/B > {cfg.get('sl_pb_max', 'N/A')} (周期见顶)"
        else:
            sl_pe_max = cfg.get("sl_pe_max", float('inf'))
            sl_z_min = cfg.get("sl_z_min", GLOBAL_DEFAULT_CONFIG["sl_z_min"])
            if sl_pe_max != float('inf'):
                sl_str = f"PE > {sl_pe_max} (逻辑死) | Z < {sl_z_min}"
            else:
                sl_str = f"Z < {sl_z_min} (技术死)"
        tp_str = f"Z > {tp_z} (过热)"
    else:
        sl_str = ""
        curr_z = round(float(z), 2) if z is not None else "N/A"
        tp_str = ""
    
    results.append({
        "Symbol": ticker,
        "Price": f"${price:.2f}" if price else "N/A",
        "Fwd PE": round(float(fundamentals.get("forwardPE") or 0), 1) if fundamentals.get("forwardPE") else "N/A",
        "P/B": round(float(fundamentals.get("priceToBook") or 0), 2) if fundamentals.get("priceToBook") else "N/A",
        "走廊地板 (SL)": sl_str,
        "当前位置 (Z-Score)": curr_z,
        "走廊天花板 (TP)": tp_str,
        "Signal": sig,
        "Logic/Alert": warn,
        "Action Plan": action
    })

# 布局展示
st.subheader("三阶判定矩阵")
df_display = pd.DataFrame(results)
st.dataframe(
    df_display, 
    use_container_width=True, 
    hide_index=True
)

st.info(f"""
**审计状态灯 (Signal Mapping)**
- **🟢 安全持有**: Z 值处于中轨，逻辑锚点稳固。
- **🟡 部分止盈 (Partial TP)**: 触碰走廊天花板，建议减仓 $C_{{action}}$ 比例。
- **🟠 部分止损 (Partial SL)**: 触碰技术超卖，建议防御性减仓 $C_{{action}}$。
- **💎 逻辑确认**: 三门共振，触发最终买入指令。
- **🔴 逻辑止损**: 长期估值与财务数据崩坏，建议立刻 100% 全清。

---
**L2.5 数据门控与执行引擎控制台**:
- **[Macro Gate] 宏观平滑势能**: $V_{{drop}} = {vel:.4f}$% ({'✅ 锁定开启' if vel > 0.1 else '🚫 暂无燃料'})
- **[Market Gate] 情绪容错水位**: $QQQ\_Z = {bench_z if bench_z else 0:.2f}$ ({'✅ 允许买入' if (bench_z and bench_z >= -0.5) else '🚨 强制防御'})
- **[System Core] 策略引擎架构**: L2.5 数据解耦范式运行中。自动计算动态动作调节系数 (C)。
""")
