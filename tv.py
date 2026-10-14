import streamlit as st
import pandas as pd
import numpy as np
import requests
import time

st.set_page_config(page_title="Bộ Lọc Thép - Auto Radar 3 Phút", layout="wide")

# ================= 0. TOÁN HỌC CHUẨN XÁC =================
def calculate_sma(series, length): return series.rolling(window=length).mean()
def calculate_ema(series, length): return series.ewm(span=length, adjust=False).mean()
def calculate_stoch_rsi(close, length=14, rsi_length=14, k=3, d=3):
    delta = close.diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=rsi_length - 1, adjust=False).mean() / down.ewm(com=rsi_length - 1, adjust=False).mean()
    rsi = 100 - (100 / (1 + rs))
    rsi_min, rsi_max = rsi.rolling(length).min(), rsi.rolling(length).max()
    stochrsi = (rsi - rsi_min) / (rsi_max - rsi_min) * 100
    stochrsi_k = calculate_sma(stochrsi, k)
    return stochrsi_k, calculate_sma(stochrsi_k, d)
def calculate_psar(high, low, close, step=0.02, max_step=0.2):
    length = len(close)
    psar, psar_dir, ep, af = np.zeros(length), np.zeros(length), np.zeros(length), np.zeros(length)
    if length < 2: return pd.Series(psar), pd.Series(psar_dir)
    if close.iloc[1] > close.iloc[0]:
        psar_dir[1], psar[1], ep[1] = 1, low.iloc[0], high.iloc[1]
    else:
        psar_dir[1], psar[1], ep[1] = -1, high.iloc[0], low.iloc[1]
    af[1] = step
    for i in range(2, length):
        psar[i] = psar[i-1] + af[i-1] * (ep[i-1] - psar[i-1])
        psar_dir[i], ep[i], af[i] = psar_dir[i-1], ep[i-1], af[i-1]
        if psar_dir[i] == 1:
            if low.iloc[i] < psar[i]:
                psar_dir[i], psar[i], ep[i], af[i] = -1, max(ep[i-1], high.iloc[i]), low.iloc[i], step
            else:
                if high.iloc[i] > ep[i]: ep[i], af[i] = high.iloc[i], min(af[i] + step, max_step)
                if psar[i] > low.iloc[i-1]: psar[i] = low.iloc[i-1]
                if psar[i] > low.iloc[i-2]: psar[i] = low.iloc[i-2]
        else:
            if high.iloc[i] > psar[i]:
                psar_dir[i], psar[i], ep[i], af[i] = 1, min(ep[i-1], low.iloc[i]), high.iloc[i], step
            else:
                if low.iloc[i] < ep[i]: ep[i], af[i] = low.iloc[i], min(af[i] + step, max_step)
                if psar[i] < high.iloc[i-1]: psar[i] = high.iloc[i-1]
                if psar[i] < high.iloc[i-2]: psar[i] = high.iloc[i-2]
    return pd.Series(psar, index=close.index), pd.Series(psar_dir, index=close.index)

# ================= 1. HÀM TẢI DỮ LIỆU TỪ LÕI BINANCE (TỐI ƯU TỐC ĐỘ & AN TOÀN) =================
def fetch_real_binance_data():
    try:
        response = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10)
        if response.status_code != 200:
            return pd.DataFrame()
        res = response.json()
    except Exception:
        return pd.DataFrame()
        
    if not isinstance(res, list):
        return pd.DataFrame()
        
    valid = []
    for i in res:
        try:
            if i['symbol'].endswith('USDT') and float(i['lastPrice']) <= 100 and i['symbol'] not in ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'BUSDUSDT', 'USDPUSDT'] and 'UPUSDT' not in i['symbol'] and 'DOWNUSDT' not in i['symbol']:
                valid.append({'symbol': i['symbol'], 'price': float(i['lastPrice']), 'change': float(i['priceChangePercent']), 'vol': float(i['quoteVolume'])})
        except:
            continue
            
    # Lấy top 50 mã có volume cao nhất để bot quét cực nhanh trên Cloud không bị nghẽn
    valid = sorted(valid, key=lambda x: x['vol'], reverse=True)[:50]
    data_list = []
    
    if not valid:
        return pd.DataFrame()
        
    my_bar = st.progress(0, text="Đang đồng bộ dữ liệu từ Binance...")
    total = len(valid)
    for i, coin in enumerate(valid):
        sym = coin['symbol']
        row = {'Cặp giao dịch': sym, 'Giá hiện tại': coin['price'], 'Thay đổi 24h (%)': coin['change'], 'Volume 24h ($)': f"{coin['vol']:,.0f}"}
        for tf in ['1h', '4h']:
            try:
                kline = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={tf}&limit=500", timeout=5).json()
                df = pd.DataFrame(kline, columns=['t','o','high','low','close','v','ct','qav','n','tbv','tqv','i']).astype({'high':float, 'low':float, 'close':float})
                df['E20'], df['S100'] = calculate_ema(df['close'], 20), calculate_sma(df['close'], 100)
                df['K'], df['D'] = calculate_stoch_rsi(df['close'])
                _, df['P_DIR'] = calculate_psar(df['high'], df['low'], df['close'])
                lst, prv = df.iloc[-1], df.iloc[-2]
                
                row[f'[{tf.upper()}] Trạng thái MA'] = "Giá > EMA20 > SMA100" if lst['close']>