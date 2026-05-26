import os
import requests
import pandas as pd
import pandas_ta as ta

# -------------------------------------------------------------------------
# SETUP & CONFIGURATION
# -------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ปรับสัญลักษณ์ให้ตรงกับรูปแบบคู่เทรด Spot ของ OKX (เปลี่ยนจาก -USD เป็น -USDT)
WATCHLIST = ["BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT", "EIGEN-USDT", "FLOKI-USDT", "NEAR-USDT", "OP-USDT", "ADA-USDT", "SHIB-USDT", "DOGE-USDT"]

def send_telegram_message(text_msg):
    """ ฟังก์ชันส่งข้อความไปยัง Telegram ด้วยรูปแบบ HTML """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True # ปิดพรีวิวลิงก์เผื่อมีสัญลักษณ์แปลกๆ
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Successfully sent message via Telegram Bot.")
        else:
            print(f"Failed to send Telegram message: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Exception while sending Telegram message: {e}")

def get_historical_data_okx(symbol, interval="1H"):
    """ ดึงข้อมูลแท่งเทียนย้อนหลังโดยตรงจาก OKX API (Public) """
    try:
        # ปรับค่าแกนเวลาให้เข้ากับ API ของ OKX (เช่น 1h ของเดิม ใน OKX จะใช้ 1H ตัวใหญ่)
        bar_mapping = {"1h": "1H", "4h": "4H", "1d": "1D"}
        okx_interval = bar_mapping.get(interval, "1H")
        
        # OKX REST API v5 สำหรับดึงข้อมูล Candlesticks (จำกัดสูงสุด 100 แท่งต่อครั้ง เพียงพอสำหรับคำนวณ EMA200 / RSI)
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={okx_interval}&limit=100"
        
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get("code") != "0" or not data.get("data"):
            print(f"Error fetching data from OKX for {symbol}: {data.get('msg')}")
            return None
            
        # ข้อมูลจาก OKX เรียงจาก "ใหม่ไปเก่า" [0] คือแท่งปัจจุบัน
        # โครงสร้าง: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        raw_candles = data["data"]
        
        df = pd.DataFrame(raw_candles, columns=["ts", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"])
        
        # แปลงชนิดข้อมูลให้เป็นตัวเลข (Float)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
            
        # กลับด้าน DataFrame ให้ "เก่าไปใหม่" เพื่อใช้คำนวณ Indicator ได้ถูกต้อง
        df = df.iloc[::-1].reset_index(drop=True)
        return df
        
    except Exception as e:
        print(f"Exception fetching {symbol} from OKX: {e}")
        return None

def check_bullish_divergence(df):
    if len(df) < 20:
        return False
    current_close = df["close"].iloc[-1]
    current_rsi = df["RSI"].iloc[-1]
    lookback_df = df.iloc[-15:-3]
    lowest_price_idx = lookback_df["close"].idxmin()
    older_close = df["close"].loc[lowest_price_idx]
    older_rsi = df["RSI"].loc[lowest_price_idx]
    
    if current_close < older_close and current_rsi > older_rsi and current_rsi < 45:
        return True
    return False

def check_bearish_divergence(df):
    if len(df) < 20:
        return False
    current_close = df["close"].iloc[-1]
    current_rsi = df["RSI"].iloc[-1]
    lookback_df = df.iloc[-15:-3]
    highest_price_idx = lookback_df["close"].idxmax()
    older_close = df["close"].loc[highest_price_idx]
    older_rsi = df["RSI"].loc[highest_price_idx]
    
    if current_close > older_close and current_rsi < older_rsi and current_rsi > 55:
        return True
    return False

def screen_crypto():
    print("🚀 Starting Crypto Screener [Engine: OKX Spot API]...")
    
    signals = []
    coin_summaries = []
    bullish_count = 0
    total_coins = 0
    
    for symbol in WATCHLIST:
        display_name = symbol.replace("-", "_")
        print(f"Scanning {display_name}...")
        
        # เรียกใช้งานฟังก์ชันที่เปลี่ยนเป็น OKX
        df = get_historical_data_okx(symbol, interval="1h")
        if df is None or df.empty:
            continue
            
        df["EMA_50"] = ta.ema(df["close"], length=50)
        df["EMA_200"] = ta.ema(df["close"], length=200)
        df["RSI"] = ta.rsi(df["close"], length=14)
        
        if len(df) < 2:
            continue
            
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        last_close_usd = last_row["close"]
        last_rsi = last_row["RSI"]
        prev_rsi = prev_row["RSI"]
        last_ema50_usd = last_row["EMA_50"]
        last_ema200_usd = last_row["EMA_200"]
        
        total_coins += 1
        
        # -------------------------------------------------------------------------
        # 1. เช็กแนวโน้มรายเหรียญ (ตามเกณฑ์เหนือ/ใต้เส้น EMA200)
        # -------------------------------------------------------------------------
        # ใส่เงื่อนไขดักกรณีที่แท่งเทียนมีไม่ถึง 200 วัน ทำให้ไม่มีค่า EMA_200 ป้องกันโค้ดพัง
        if pd.isna(last_ema200_usd):
            coin_trend = "⚪ ข้อมูลไม่พอคำนวณเทรนด์"
        elif last_close_usd > last_ema200_usd:
            coin_trend = "🟢 ขาขึ้น"
            bullish_count += 1
        else:
            coin_trend = "🔴 ขาลง"
            
        # ปรับแก้การจัดรูปแบบทศนิยมให้ยืดหยุ่น (รองรับเหรียญมีมราคาต่ำๆ เช่น FLOKI, SHIB)
        if last_close_usd < 0.01:
            price_format = f"${last_close_usd:,.6f}"
        else:
            price_format = f"${last_close_usd:,.4f}"
            
        # ตรวจสอบค่า RSI เผื่อกรณีค่าเป็น NaN
        rsi_str = f"{last_rsi:.1f}" if not pd.isna(last_rsi) else "N/A"
            
        coin_summaries.append(f"• <b>{display_name}</b>: {price_format} ({coin_trend} | RSI: {rsi_str})")
        
        # หากคำนวณข้อมูลชี้วัดไม่สมบูรณ์ ข้ามกระบวนการส่งสัญญาณไปก่อน
        if pd.isna(last_rsi) or pd.isna(prev_rsi):
            continue

        # -------------------------------------------------------------------------
        # 2. คัดกรองสัญญาณเทรด (RSI Signals)
        # -------------------------------------------------------------------------
        # 🟢 เงื่อนไขเข้าซื้อ
        if last_rsi <= 35 and prev_rsi > 35:
            is_bull_div = check_bullish_divergence(df)
            buy_zone = f"{last_close_usd:,.4f} - {(last_close_usd * 0.98):,.4f}" if last_close_usd >= 0.01 else f"{last_close_usd:,.6f}"
            take_profit = f"{(last_close_usd * 1.05):,.4f}" if last_close_usd >= 0.01 else f"{(last_close_usd * 1.05):,.6f}"
            stop_loss = f"{(last_close_usd * 0.95):,.4f}" if last_close_usd >= 0.01 else f"{(last_close_usd * 0.95):,.6f}"
            
            status_context = "📉 RSI Oversold"
            if not pd.isna(last_ema200_usd):
                if last_close_usd > last_ema200_usd:
                    status_context += "\n+ ยืนเหนือเส้น EMA200 (ภาพใหญ่ยังเป็นแนวโน้มขาขึ้น)"
                else:
                    status_context += "\n- อยู่ใต้เส้น EMA200 (ภาพใหญ่ขาลง ระวังเน้นเล่นรอบสั้น)"
                
            if is_bull_div:
                status_context += "\n🔥 พบบูลลิชไดเวอร์เจนท์ (Bullish Divergence) มีโอกาสกลับตัวสูง!"
                
            msg = (
                f"\n🟢 <b>[SIGNAL BUY] {display_name}</b>\n"
                f"ราคาปัจจุบัน: {price_format} USD ({coin_trend})\n"
                f"RSI (1h): {last_rsi:.2f}\n"
                f"สถานะกราฟ: {status_context}\n"
                f"📍 ช่วงราคาเข้าซื้อ: {buy_zone} USD\n"
                f"🎯 เป้าขายทำกำไร: {take_profit} USD\n"
                f"❌ จุดตัดขาดทุน: {stop_loss} USD\n"
                f"--------------------------------"
            )
            signals.append(msg)
            
        # 🔴 เงื่อนไขเตือนขาย
        elif last_rsi >= 65 and prev_rsi < 65:
            is_bear_div = check_bearish_divergence(df)
            sell_zone = f"{last_close_usd:,.4f} - {(last_close_usd * 1.02):,.4f}" if last_close_usd >= 0.01 else f"{last_close_usd:,.6f}"
            re_entry_zone = f"{(last_close_usd * 0.95):,.4f}" if last_close_usd >= 0.01 else f"{(last_close_usd * 0.95):,.6f}"
            trailing_stop = f"{(last_close_usd * 0.97):,.4f}" if last_close_usd >= 0.01 else f"{(last_close_usd * 0.97):,.6f}"
            
            status_context = "⚠️ RSI Overbought (ซื้อมากเกินไป)"
            if not pd.isna(last_ema200_usd):
                if last_close_usd > last_ema200_usd:
                    status_context += "\n+ ยืนเหนือเส้น EMA200 (โครงสร้างแข็งแกร่ง แต่อาจย่อตัวระยะสั้น)"
                else:
                    status_context += "\n- อยู่ใต้เส้น EMA200 (เด้งเพื่อลงต่อในภาพใหญ่ ระวังแรงเทขาย)"
                
            if is_bear_div:
                status_context += "\n🚨 พบแบร์ริชไดเวอร์เจนท์ (Bearish Divergence) สัญญาณกลับตัวลงรุนแรง!"
                
            msg = (
                f"\n🔴 <b>[SIGNAL SELL] {display_name}</b>\n"
                f"ราคาปัจจุบัน: {price_format} USD ({coin_trend})\n"
                f"RSI (1h): {last_rsi:.2f}\n"
                f"สถานะกราฟ: {status_context}\n"
                f"📍 โซนแบ่งขายทำกำไร: {sell_zone} USD\n"
                f"🎯 รอรับกลับเมื่อย่อตัว: {re_entry_zone} USD\n"
                f"❌ หลุดจุดนี้ควรหนี (Trailing Stop): {trailing_stop} USD\n"
                f"--------------------------------"
            )
            signals.append(msg)

    # -------------------------------------------------------------------------
    # 3. จัดการแสดงผลข้อความใน Header และภาพรวมตลาด
    # -------------------------------------------------------------------------
    if total_coins > 0:
        bullish_ratio = bullish_count / total_coins
        if bullish_ratio >= 0.6:
            market_overview = "📈 ขาขึ้นชัดเจน (Bullish)"
        elif bullish_ratio <= 0.4:
            market_overview = "📉 ขาลงรุนแรง (Bearish)"
        else:
            market_overview = "↔️ ไซด์เวย์เลือกทาง (Sideways)"
            
        report_msg = f"📊 <b>[Crypto Screener Report] ภาพรวมตลาด: {market_overview}</b>\n"
        report_msg += f"สัดส่วนเหรียญทรงขาขึ้น: {bullish_count} จากทั้งหมด {total_coins} ตัว\n"
        report_msg += "=================================\n\n"
        
        report_msg += "<b>🧐 สรุปรายเหรียญล่าสุด:</b>\n"
        report_msg += "\n".join(coin_summaries) + "\n\n"
        report_msg += "=================================\n"
        
        if signals:
            report_msg += "⚡ <b>สัญญาณเทรดเร่งด่วนในชั่วโมงนี้:</b>\n"
            report_msg += "".join(signals)
        else:
            report_msg += "\nℹ️ <i>ในชั่วโมงนี้ไม่มีเหรียญใดเข้าเงื่อนไขสัญญาณซื้อ/ขาย</i>"
            
        send_telegram_message(report_msg)
        print("Process complete: Updated layout report sent to Telegram.")
    else:
        print("Process complete: No data found to analyze.")

if __name__ == "__main__":
    screen_crypto()
