import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import pandas_datareader.data as web
from datetime import datetime, timedelta

# 配置 Streamlit 页面
st.set_page_config(page_title="QuantSystem L2.4: Logic Confirmation", layout="wide")

# --- 1. 数据获取模块 ---

@st.cache_data(ttl=3600)
def get_macro_data():
    """从 FRED 获取 10年期实际利率 (DFII10) 及其峰值"""
    start = datetime.now() - timedelta(days=60)
    df_fred = web.DataReader("DFII10", "fred", start, datetime.now())
    
    # 获取当前值
    current_val = df_fred['DFII10'].iloc[-1]
    # 获取过去20天的峰值，用于计算下坠动能 (v2.3/v2.4 核心)
    recent_peak = df_fred['DFII10'].tail(20).max()
    # 计算 MA20 趋势
    ma20 = df_fred['DFII10'].rolling(window=20).mean().iloc[-1]
    
    return current_val, recent_peak, ma20

def get_fundamental_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        return ticker.info.get('forwardPE', None)
    except:
        return None

def get_zscore_data(ticker_symbol, period="100d", window=20):
    df = yf.download(ticker_symbol, period=period, interval="1d", progress=False)
    if df.empty: return None, None
    close = df['Close']
    ma = close.rolling(window=window).mean()
    std = close.rolling(window=window).std()
    z_score = (close - ma) / std
    return float(z_score.iloc[-1]), float(close.iloc[-1])

# --- 2. 逻辑引擎 v2.4 ---

def get_trading_signal(symbol, z_score, fwd_pe, macro_status, bench_z):
    """
    S_v2.4: 逻辑确认模型 (Macro -> Market -> Stock)
    """
    # 安全标量化：防止 pandas Series 导致布尔歧义
    try:
        z_score = float(z_score) if z_score is not None else None
    except (TypeError, ValueError):
        z_score = None
    try:
        bench_z = float(bench_z) if bench_z is not None else None
    except (TypeError, ValueError):
        bench_z = None

    # 若关键数据缺失，直接返回 Exception
    if z_score is None or bench_z is None:
        return "Exception", "🚫 核心数据抓取失败"

    current_dfii = macro_status['val']
    prev_peak = macro_status['peak']
    drop_velocity = float(prev_peak) - float(current_dfii)  # 下坠动能

    # 宏观开关状态
    macro_bullish = bool(drop_velocity > 0.1)
    # 市场确认状态 (QQQ 已经走出坑)
    market_confirmed = bool(bench_z > -0.5)

    signal = "Neutral"
    warning = ""
    
    # 1. 黄金宏观逻辑
    if symbol == "IAU":
        if macro_bullish:
            warning = "🔥 燃料注入 (利率加速下行)"
            logic_veto = False
        elif current_dfii > 1.8:
            warning = "⚠️ 警惕：实际利率过高"
            logic_veto = True
        else:
            logic_veto = False
            
        if z_score < -1.5 and not logic_veto: signal = "Strong Buy"
        elif z_score > 1.5: signal = "Sell"
        return signal, warning

    # 2. 个股逻辑 (MSFT, MU, TSM, NVDA)
    # v2.4 核心：逻辑确认 (Macro Bullish + Market Confirmed + Stock Cheap)
    pe_thresholds = {"TSM": 20, "NVDA": 45, "MSFT": 32, "MU": 15}
    
    if symbol in pe_thresholds:
        valid_pe = fwd_pe if fwd_pe is not None else float('inf')
        stock_cheap = (z_score < -1.5) and (valid_pe < pe_thresholds[symbol])
        
        if macro_bullish and market_confirmed and stock_cheap:
            signal = "💎 逻辑确认"
        else:
            if symbol == "TSM":
                if z_score > 1.5: signal = "Sell"
            elif symbol == "NVDA":
                if z_score > 2.0 and valid_pe > 55: signal = "🔥 估值泡沫"
            elif symbol == "MSFT":
                if z_score < -1.8: signal = "Technical Oversold"
            elif symbol == "MU":
                if z_score < -1.5: signal = "Buy"

    # 3. 指数逻辑
    elif symbol in ["QQQ", "VOO"]:
        if z_score < -1.5: signal = "Index Buy"
        elif z_score > 1.5: signal = "Index Sell"

    return signal, warning

# --- 3. UI 展示层 ---

st.title("QuantSystem L2.4: 宏观·基本面·市场确认系统")

# 侧边栏宏观监控
st.sidebar.header("📊 宏观指标 (FRED)")
try:
    curr_dfii, peak_dfii, ma20_dfii = get_macro_data()
    vel = peak_dfii - curr_dfii
    st.sidebar.metric("10Y Real Rate (DFII10)", f"{curr_dfii:.2f}%", delta=f"-{vel:.2f}% (下行势能)")
    macro_status = {'val': curr_dfii, 'peak': peak_dfii, 'trend': "DOWN" if curr_dfii < ma20_dfii else "UP"}
except:
    st.sidebar.error("FRED 数据读取失败")
    macro_status = {'val': 0, 'peak': 0, 'trend': "N/A"}

# 获取基准 QQQ 的 Z-Score，用于 v2.4 市场确认逻辑
bench_z, _ = get_zscore_data("QQQ")

portfolio = ["TSM", "NVDA", "MSFT", "MU", "QQQ", "VOO", "IAU"]
results = []

for ticker in portfolio:
    z, price = get_zscore_data(ticker)
    pe = get_fundamental_data(ticker)
    sig, warn = get_trading_signal(ticker, z, pe, macro_status, bench_z)
    
    results.append({
        "Symbol": ticker,
        "Price": f"${price:.2f}" if price else "N/A",
        "Z-Score": round(z, 2) if z else "N/A",
        "Fwd PE": pe if pe else "N/A",
        "Signal": sig,
        "Logic/Alert": warn
    })

df_display = pd.DataFrame(results)
st.table(df_display)

st.info(f"""
**v2.4 运行诊断**:
- **宏观驱动**: DFII10 下行势能为 {vel:.2f}%。({'🔥 强劲' if vel > 0.1 else '❄️ 平淡'})
- **市场确认**: QQQ Z-Score 为 {bench_z:.2f}。({'✅ 已确认反弹' if bench_z > -0.5 else '⏳ 市场尚未反应'})
- **操作指南**: 只有当宏观驱动与市场确认同时亮绿灯时，个股才会触发 **"💎 逻辑确认"** 信号。
""")