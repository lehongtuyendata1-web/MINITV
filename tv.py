import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime

st.set_page_config(page_title="Bộ Lọc Thép - Auto Radar 3 Phút", layout="wide")

# ================= CẤU HÌNH NTFY CỦA TƯ LỆNH =================
NTFY_TOPIC = "SIG_SAR"  # Topic nhận tin nhắn trên điện thoại của anh

def send_ntfy_startup():
    """Hàm gửi tin nhắn chào mừng khi bot vừa khởi động để test thông tuyến NTFY"""
    try:
        startup_msg = (
            f"🛡️ HỆ THỐNG BỘ LỌC THÉP ĐÃ KHỞI ĐỘNG!\n"
            f"• Thời gian bật: {datetime.now().strftime('%H:%M:%S - %d/%m/%Y')}\n"
            f"• Trạng thái: NTFY đã thông suốt (Topic: {NTFY_TOPIC}).\n"
            f"• Sẵn sàng quét radar 3 phút/lần!"
        )
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=startup_msg.encode('utf-8'),
            headers={
                "Title": "BOT RADAR DAI SAN SANG",
                "Priority": "high",
                "Tags": "white_check_mark,robot"
            },
            timeout=5
        )
        print("✅ Đã gửi tin nhắn chào mừng qua NTFY thành công!")
    except Exception as e:
        print(f"Lỗi gửi tin nhắn chào mừng NTFY: {e}")

def send_ntfy_alert(symbol, price, change, vol, tf_label):
    """Hàm bắn tin nhắn thông báo chi tiết mã coin phát hiện về điện thoại"""
    try:
        message = (
            f"🎯 PHÁT HIỆN TÍN HIỆU {tf_label}!\n"
            f"• Cặp coin: {symbol}\n"
            f"• Giá hiện tại: {price}\n"
            f"• Thay đổi 24h: {change:+.2f}%\n"
            f"• Volume 24h: ${vol:,.0f}\n"
            f"• Trạng thái: SAR Vừa Cắt Xuống (Chân sóng)"
        )
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode('utf-8'),
            headers={
                "Title": f"KEO MOI: {symbol} ({tf_label})",
                "Priority": "high",
                "Tags": "rocket,moneybag"
            },
            timeout=5
        )
    except Exception as e:
        print(f"Lỗi gửi NTFY: {e}")

if 'alerted_history' not in st.session_state:
    st.session_state.alerted_history = set()

if 'startup_sent' not in st.session_state:
    send_ntfy_startup()
    st.session_state.startup_sent = True

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

# ================= 1. HÀM TẢI DỮ LIỆU TỪ LÕI BINANCE =================
def fetch_real_binance_data():
    try: res = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10).json()
    except: return pd.DataFrame()
    valid = [{'symbol': i['symbol'], 'price': float(i['lastPrice']), 'change': float(i['priceChangePercent']), 'vol': float(i['quoteVolume'])} 
             for i in res if i['symbol'].endswith('USDT') and float(i['lastPrice'])<=100 and i['symbol'] not in ['USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'BUSDUSDT', 'USDPUSDT'] and 'UPUSDT' not in i['symbol'] and 'DOWNUSDT' not in i['symbol']]
    valid = sorted(valid, key=lambda x: x['vol'], reverse=True)[:150]
    data_list = []
    my_bar = st.progress(0, text="Đang đồng bộ dữ liệu từ Binance...")
    total = len(valid)
    
    for i, coin in enumerate(valid):
        sym = coin['symbol']
        row = {'Cặp giao dịch': sym, 'Giá hiện tại': coin['price'], 'Thay đổi 24h (%)': coin['change'], 'Volume 24h ($)': f"{coin['vol']:,.0f}"}
        for tf in ['1h', '4h']:
            try:
                kline = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={tf}&limit=1000", timeout=5).json()
                df = pd.DataFrame(kline, columns=['t','o','high','low','close','v','ct','qav','n','tbv','tqv','i']).astype({'high':float, 'low':float, 'close':float})
                df['E20'], df['S100'] = calculate_ema(df['close'], 20), calculate_sma(df['close'], 100)
                df['K'], df['D'] = calculate_stoch_rsi(df['close'])
                _, df['P_DIR'] = calculate_psar(df['high'], df['low'], df['close'])
                lst, prv = df.iloc[-1], df.iloc[-2]
                
                ma_status = "Giá > EMA20 > SMA100" if lst['close']>lst['E20']>lst['S100'] else "Giá < EMA20 < SMA100" if lst['close']<lst['E20']<lst['S100'] else "Đi ngang / Lộn xộn"
                
                sar_status = "Bình thường"
                if lst['P_DIR']==1 and prv['P_DIR']==-1:
                    sar_status = "SAR Vừa Cắt Xuống (Chân Sóng)"
                    if tf == '4h' and lst['close'] > lst['E20'] > lst['S100']:
                        alert_key = f"{sym}_4H_{lst['t']}"
                        if alert_key not in st.session_state.alerted_history:
                            st.session_state.alerted_history.add(alert_key)
                            send_ntfy_alert(sym, coin['price'], coin['change'], coin['vol'], "Khung 4H")
                            
                elif lst['P_DIR']==-1 and prv['P_DIR']==1:
                    sar_status = "SAR Vừa Cắt Lên (Đỉnh Sóng)"
                elif lst['P_DIR']==1:
                    sar_status = "SAR Nằm Dưới (Tăng)"
                else:
                    sar_status = "SAR Nằm Trên (Giảm)"
                
                row[f'[{tf.upper()}] Trạng thái MA'] = ma_status
                row[f'[{tf.upper()}] Trạng thái SAR'] = sar_status
                row[f'[{tf.upper()}] StochRSI'] = "K > D" if lst['K']>lst['D'] else "K < D"
            except: pass
        data_list.append(row)
        my_bar.progress(int((i+1)/total*100), text=f"Đang đồng bộ... {int((i+1)/total*100)}%")
    my_bar.empty()
    return pd.DataFrame(data_list)

# ================= 2. QUẢN LÝ TRẠNG THÁI & GIAO DIỆN =================
st.title("🛡️ BỘ LỌC THÉP - AUTO RADAR 3 PHÚT (NTFY: SIG_SAR)")

if 'last_update' not in st.session_state: st.session_state.last_update = time.time()
if 'df_cache' not in st.session_state: st.session_state.df_cache = pd.DataFrame()

col1, col2 = st.columns([1, 5])
with col1:
    if st.button("🔄 Quét Ngay"): st.session_state.last_update = 0 
with col2:
    st.caption(f"Lần cập nhật cuối: {time.strftime('%H:%M:%S', time.localtime(st.session_state.last_update))} | Tự động quét ngầm mỗi 3 phút và đẩy tin về topic **SIG_SAR**.")

current_time = time.time()
if current_time - st.session_state.last_update > 180 or st.session_state.df_cache.empty:
    with st.spinner("Hệ thống đang quét thị trường (Sẽ mất khoảng 1 phút)..."):
        st.session_state.df_cache = fetch_real_binance_data()
        st.session_state.last_update = time.time()

df = st.session_state.df_cache.copy()

# ================= SIDEBAR MENU (ĐÃ THÊM KEY ĐỂ GHI NHỚ LỰA CHỌN) =================
st.sidebar.header("🛠️ KẸP CHÉO ĐIỀU KIỆN")

st.sidebar.markdown("### ⏱️ KHUNG 4H")
ma_4h = st.sidebar.selectbox("MA (4H):", ['Bỏ qua', 'Giá > EMA20 > SMA100', 'Giá < EMA20 < SMA100', 'Đi ngang / Lộn xộn'], key='sel_ma_4h')
sar_4h = st.sidebar.selectbox("SAR (4H):", ['Bỏ qua', 'SAR Nằm Dưới (Tăng)', 'SAR Vừa Cắt Xuống (Chân Sóng)', 'SAR Nằm Trên (Giảm)', 'SAR Vừa Cắt Lên (Đỉnh Sóng)'], key='sel_sar_4h')
stoch_4h = st.sidebar.selectbox("Stoch (4H):", ['Bỏ qua', 'K > D', 'K < D'], key='sel_stoch_4h')

st.sidebar.markdown("---")

st.sidebar.markdown("### ⏱️ KHUNG 1H")
ma_1h = st.sidebar.selectbox("MA (1H):", ['Bỏ qua', 'Giá > EMA20 > SMA100', 'Giá < EMA20 < SMA100', 'Đi ngang / Lộn xộn'], key='sel_ma_1h')
sar_1h = st.sidebar.selectbox("SAR (1H):", ['Bỏ qua', 'SAR Nằm Dưới (Tăng)', 'SAR Vừa Cắt Xuống (Chân Sóng)', 'SAR Nằm Trên (Giảm)', 'SAR Vừa Cắt Lên (Đỉnh Sóng)'], key='sel_sar_1h')
stoch_1h = st.sidebar.selectbox("Stoch (1H):", ['Bỏ qua', 'K > D', 'K < D'], key='sel_stoch_1h')

# ================= XỬ LÝ LỌC =================
filtered = df.copy()

if ma_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] Trạng thái MA'] == ma_4h]
if sar_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] Trạng thái SAR'] == sar_4h]
if stoch_4h != 'Bỏ qua': filtered = filtered[filtered['[4H] StochRSI'] == stoch_4h]

if ma_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] Trạng thái MA'] == ma_1h]
if sar_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] Trạng thái SAR'] == sar_1h]
if stoch_1h != 'Bỏ qua': filtered = filtered[filtered['[1H] StochRSI'] == stoch_1h]

st.success(f"🎯 Lưới quét thu được {len(filtered)} mã.")
st.dataframe(filtered.style.map(lambda x: 'color: #00ff00' if isinstance(x, (int, float)) and x>0 else ('color: #ff0000' if isinstance(x, (int, float)) and x<0 else ''), subset=['Thay đổi 24h (%)']), use_container_width=True, height=650)

time.sleep(180)
st.rerun()