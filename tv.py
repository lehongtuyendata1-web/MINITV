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

# ================= 1. HÀM TẢI DỮ LIỆU AN TOÀN TUYỆT ĐỐI =================
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
            if isinstance(i, dict) and 'symbol' in i and 'lastPrice' in i:
                sym = i['symbol']
                if sym.endswith('USDT') and float(i['lastPrice']) <= 100 and sym not in ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'BUSDUSDT', 'USDPUSDT'] and 'UPUSDT' not in sym and 'DOWNUSDT' not in sym:
                    valid.append({'symbol': sym, 'price': float(i['lastPrice']), 'change': float(i['priceChangePercent']), 'vol': float(i['quoteVolume'])})
        except:
            continue
            
    # Lấy top 50 mã volume cao nhất để quét siêu tốc
    valid = sorted(valid, key=lambda x: x['vol'], reverse=True)[:50]
    data_list = []
    
    if not valid:
        return pd.DataFrame()
        
    my_bar = st.progress(0, text="Đang đồng bộ dữ liệu từ Binance...")
    total = len(valid)
    for idx, coin in enumerate(valid):
        sym = coin['symbol']
        row = {'Cặp giao dịch': sym, 'Giá hiện tại': coin['price'], 'Thay đổi 24h (%)': coin['change'], 'Volume 24h ($)': f"{coin['vol']:,.0f}"}
        for tf in ['1h', '4h']:
            try:
                kline_res = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={tf}&limit=500", timeout=5)
                if kline_res.status_code != 200: continue
                kline = kline_res.json()
                if not isinstance(kline, list): continue
                
                df = pd.DataFrame(kline, columns=['t','o','high','low','close','v','ct','qav','n','tbv','tqv','i']).astype({'high':float, 'low':float, 'close':float})
                df['E20'] = calculate_ema(df['close'], 20)
                df['S100'] = calculate_sma(df['close'], 100)
                df['K'], df['D'] = calculate_stoch_rsi(df['close'])
                _, df['P_DIR'] = calculate_psar(df['high'], df['low'], df['close'])
                lst, prv = df.iloc[-1], df.iloc[-2]
                
                # Trạng thái MA
                if lst['close'] > lst['E20'] > lst['S100']:
                    ma_status = "Giá > EMA20 > SMA100"
                elif lst['close'] < lst['E20'] < lst['S100']:
                    ma_status = "Giá < EMA20 < SMA100"
                else:
                    ma_status = "Đi ngang / Lộn xộn"
                row[f'[{tf.upper()}] Trạng thái MA'] = ma_status

                # Trạng thái SAR
                if lst['P_DIR'] == 1 and prv['P_DIR'] == -1:
                    sar_status = "SAR Vừa Cắt Xuống (Chân Sóng)"
                elif lst['P_DIR'] == -1 and prv['P_DIR'] == 1:
                    sar_status = "SAR Vừa Cắt Lên (Đỉnh Sóng)"
                elif lst['P_DIR'] == 1:
                    sar_status = "SAR Nằm Dưới (Tăng)"
                else:
                    sar_status = "SAR Nằm Trên (Giảm)"
                row[f'[{tf.upper()}] Trạng thái SAR'] = sar_status

                # Trạng thái StochRSI
                row[f'[{tf.upper()}] StochRSI'] = "K > D" if lst['K'] > lst['D'] else "K < D"
            except: 
                pass
        data_list.append(row)
        my_bar.progress(int((idx + 1) / total * 100), text=f"Đang đồng bộ... {int((idx + 1) / total * 100)}%")
    my_bar.empty()
    return pd.DataFrame(data_list)

# ================= 2. QUẢN LÝ TRẠNG THÁI & GIAO DIỆN =================
st.title("🛡️ BỘ LỌC THÉP - AUTO RADAR 3 PHÚT")

if 'last_update' not in st.session_state: st.session_state.last_update = time.time()
if 'df_cache' not in st.session_state: st.session_state.df_cache = pd.DataFrame()

col1, col2 = st.columns([1, 5])
with col1:
    if st.button("🔄 Quét Ngay"): st.session_state.last_update = 0
with col2:
    st.caption(f"Lần cập nhật cuối: {time.strftime('%H:%M:%S', time.localtime(st.session_state.last_update))} | Hệ thống sẽ tự động quét lại ngầm sau mỗi 3 phút.")

current_time = time.time()
if current_time - st.session_state.last_update > 180 or st.session_state.df_cache.empty:
    with st.spinner("Hệ thống đang quét thị trường..."):
        st.session_state.df_cache = fetch_real_binance_data()
        st.session_state.last_update = time.time()

df = st.session_state.df_cache.copy()

# ================= SIDEBAR MENU =================
st.sidebar.header("🛠️ KẸP CHÉO ĐIỀU KIỆN")

st.sidebar.markdown("### ⏱️ KHUNG 4H")
ma_4h = st.sidebar.selectbox("MA (4H):", ['Bỏ qua', 'Giá > EMA20 > SMA100', 'Giá < EMA20 < SMA100', 'Đi ngang / Lộn xộn'])
sar_4h = st.sidebar.selectbox("SAR (4H):", ['Bỏ qua', 'SAR Nằm Dưới (Tăng)', 'SAR Vừa Cắt Xuống (Chân Sóng)', 'SAR Nằm Trên (Giảm)', 'SAR Vừa Cắt Lên (Đỉnh Sóng)'])
stoch_4h = st.sidebar.selectbox("Stoch (4H):", ['Bỏ qua', 'K > D', 'K < D'])

st.sidebar.markdown("---")

st.sidebar.markdown("### ⏱️ KHUNG 1H")
ma_1h = st.sidebar.selectbox("MA (1H):", ['Bỏ qua', 'Giá > EMA20 > SMA100', 'Giá < EMA20 < SMA100', 'Đi ngang / Lộn xộn'])
sar_1h = st.sidebar.selectbox("SAR (1H):", ['Bỏ qua', 'SAR Nằm Dưới (Tăng)', 'SAR Vừa Cắt Xuống (Chân Sóng)', 'SAR Nằm Trên (Giảm)', 'SAR Vừa Cắt Lên (Đỉnh Sóng)'])
stoch_1h = st.sidebar.selectbox("Stoch (1H):", ['Bỏ qua', 'K > D', 'K < D'])

# ================= XỬ LÝ LỌC TRỰC TIẾP TỪ BIẾN =================
filtered = df.copy()

if not filtered.empty:
    if ma_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] Trạng thái MA'] == ma_4h]
    if sar_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] Trạng thái SAR'] == sar_4h]
    if stoch_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] StochRSI'] == stoch_4h]

    if ma_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] Trạng thái MA'] == ma_1h]
    if sar_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] Trạng thái SAR'] == sar_1h]
    if stoch_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] StochRSI'] == stoch_1h]

st.success(f"🎯 Lưới quét thu được {len(filtered)} mã.")
if not filtered.empty:
    st.dataframe(filtered.style.map(lambda x: 'color: #00ff00' if isinstance(x, (int, float)) and x>0 else ('color: #ff0000' if isinstance(x, (int, float)) and x<0 else ''), subset=['Thay đổi 24h (%)']), use_container_width=True, height=650)
else:
    st.info("Đang chờ dữ liệu hoặc không có mã thỏa mãn điều kiện lọc.")

# ================= VÒNG LẶP AUTO REFRESH NGẦM =================
time.sleep(180)
st.rerun()