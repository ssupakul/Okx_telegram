import os
import requests
import pandas as pd
import pandas_ta as ta

# -------------------------------------------------------------------------
# SETUP & CONFIGURATION
# -------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WATCHLIST = [
    "BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", 
    "XRP-USDT", "EIGEN-USDT", "FLOKI-USDT", "NEAR-USDT", 
    "OP-USDT", "ADA-USDT", "SHIB-USDT", "DOGE-USDT"
]

# คอนฟิกค่าพารามิเตอร์ตามที่กำหนด
CONFIG = {
    "rsi_recovery_threshold": 45,    # ระดับ RSI ที่มองว่าฟื้นตัวจากเขตล่าง
    "rsi_pullback_threshold": 55,    # ระดับ RSI ที่มองว่าเริ่มย่อตัวจากเขตบน
    "rsi_recovery_lookback": 5,      # จำนวนแท่งย้อนหลังที่เช็กว่าเคย Oversold/Overbought
    "rsi_bull_div_max": 45,         # ค่า RSI ปัจจุบันสูงสุดที่ไม่เกินนี้ในการเกิด Bull Div
    "rsi_bear_div_min": 55,         # ค่า RSI ปัจจุบันต่ำสุดที่ต้องเกินนี้ในการเกิด Bear Div
    "lookback_bars": 15,            # ระยะเวลาหาจุดกลับตัวในอดีต
    "lookback_skip_bars": 3          # จำนวนแท่งล่าสุดที่จะข้าม (ไม่นับรวมในกล่องอดีต)
}

def get_coin_tier_config(symbol):
    """ 
    แยก Tier ของเหรียญเพื่อกำหนดเปอร์เซ็นต์ Take Profit 2 ระยะ
    ส่งกลับค่าเป็น: (Tier, TP1_percent, TP2_percent)
    """
    tier_mapping = {
        # Tier 1: TP1 +8%, TP2 +12%
        "BTC-USDT": (1, 0.08, 0.12), "ETH-USDT": (1, 0.08, 0.12),  
        # Tier 2: TP1 +15%, TP2 +20%
        "BNB-USDT": (2, 0.15, 0.20), "SOL-USDT": (2, 0.15, 0.20), "XRP-USDT": (2, 0.15, 0.20),
        "NEAR-USDT": (2, 0.15, 0.20), "OP-USDT": (2, 0.15, 0.20), "ADA-USDT": (2, 0.15, 0.20),
        "EIGEN-USDT": (2, 0.15, 0.20),  
        # Tier 3: TP1 +20%, TP2 +30%
        "FLOKI-USDT": (3, 0.20, 0.30), "SHIB-USDT": (3, 0.20, 0.30), "DOGE-USDT": (3, 0.20, 0.30)  
    }
    return tier_mapping.get(symbol, (2, 0.15, 0.20)) # Default เป็น Tier 2

def send_telegram_message(text_msg):
    """ ฟังก์ชันส่งข้อความไปยัง Telegram """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Failed to send Telegram message: {response.status_code}")
    except Exception as e:
        print(f"Exception while sending Telegram message: {e}")

def get_historical_data_okx(symbol, interval="1h"):
    try:
        bar_mapping = {"1h": "1H", "4h": "4H", "1d": "1D"}
        okx_interval = bar_mapping.get(interval, "1H")
        all_candles = []
        after_ts = ""
        
        for _ in range(3):
            url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar={okx_interval}&limit=100"
            if after_ts:
                url += f"&after={after_ts}"
            response = requests.get(url, timeout=10)
            data = response.json()
            if data.get("code") != "0" or not data.get("data"):
                break
            candles = data["data"]
            all_candles.extend(candles)
            if len(candles) < 100:
                break
            after_ts = candles[-1][0]
            
        if not all_candles:
            return None
            
        df = pd.DataFrame(all_candles, columns=["ts", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
            
        # กลับลำดับข้อมูล (เก่า -> ใหม่) เพื่อใช้คำนวณเทคนิคอลอินดิเคเตอร์
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception as e:
        print(f"Exception fetching {symbol}: {e}")
        return None

def check_bullish_divergence(df):
    """ ตรวจสอบสัญญาณ Bullish Divergence ตามพารามิเตอร์ที่ปรับปรุงใหม่ """
    if len(df) < CONFIG["lookback_bars"]: return False
    
    current_close = df["close"].iloc[-1]
    current_rsi = df["RSI"].iloc[-1]
    
    # ดึงกล่องข้อมูลในอดีตตามค่าที่ตั้งไว้ (ข้าม 3 แท่งล่าสุด ย้อนหลังไป 15 แท่ง)
    start_idx = -CONFIG["lookback_bars"]
    end_idx = -CONFIG["lookback_skip_bars"]
    lookback_df = df.iloc[start_idx:end_idx]
    
    lowest_price_idx = lookback_df["close"].idxmin()
    older_close = df["close"].loc[lowest_price_idx]
    older_rsi = df["RSI"].loc[lowest_price_idx]
    
    # เงื่อนไข: ราคาทำจุดต่ำสุดใหม่ แต่ RSI ยกตัวสูงขึ้น และ RSI ปัจจุบันต้องไม่เกินขอบบนที่ตั้งไว้
    if current_close < older_close and current_rsi > older_rsi and current_rsi <= CONFIG["rsi_bull_div_max"]:
        return True
    return False

def check_bearish_divergence(df):
    """ ตรวจสอบสัญญาณ Bearish Divergence ตามพารามิเตอร์ที่ปรับปรุงใหม่ """
    if len(df) < CONFIG["lookback_bars"]: return False
    
    current_close = df["close"].iloc[-1]
    current_rsi = df["RSI"].iloc[-1]
    
    start_idx = -CONFIG["lookback_bars"]
    end_idx = -CONFIG["lookback_skip_bars"]
    lookback_df = df.iloc[start_idx:end_idx]
    
    highest_price_idx = lookback_df["close"].idxmax()
    older_close = df["close"].loc[highest_price_idx]
    older_rsi = df["RSI"].loc[highest_price_idx]
    
    # เงื่อนไข: ราคาทำจุดสูงสุดใหม่ แต่ RSI ลดต่ำลง และ RSI ปัจจุบันต้องมากกว่าขอบล่างที่ตั้งไว้
    if current_close > older_close and current_rsi < older_rsi and current_rsi >= CONFIG["rsi_bear_div_min"]:
        return True
    return False

def screen_crypto():
    print("🚀 Starting Crypto Screener [Advanced Strategy Mode]...")
    
    signal_sent_count = 0
    coin_summaries = []
    bullish_count = 0
    total_coins = 0
    
    for symbol in WATCHLIST:
        display_name = symbol.replace("-", "_")
        df = get_historical_data_okx(symbol, interval="1h")
        if df is None or df.empty:
            continue
            
        # คำนวณอินดิเคเตอร์
        df["EMA_50"] = ta.ema(df["close"], length=50)
        df["EMA_200"] = ta.ema(df["close"], length=200)
        df["RSI"] = ta.rsi(df["close"], length=14)
        
        if len(df) < 20 or "RSI" not in df.columns:
            continue
            
        last_row = df.iloc[-1]
        last_close_usd = last_row["close"]
        last_rsi = last_row["RSI"]
        last_ema50_usd = last_row["EMA_50"]
        last_ema200_usd = last_row["EMA_200"]
        
        if pd.isna(last_rsi):
            continue

        total_coins += 1
        tier_num, tp1_pct, tp2_pct = get_coin_tier_config(symbol)
        
        # จัดรูปแบบทศนิยมให้เหมาะสมกับราคา
        fmt = ".6f" if last_close_usd < 0.001 else (".4f" if last_close_usd < 1 else ".2f")
        price_format = f"${last_close_usd:,.6f}" if last_close_usd < 0.001 else (f"${last_close_usd:,.4f}" if last_close_usd < 1 else f"${last_close_usd:,.2f}")

        # -------------------------------------------------------------------------
        # เช็กโครงสร้างแนวโน้มแบบต่อเนื่อง (Trend Continuity)
        # -------------------------------------------------------------------------
        if pd.isna(last_ema200_usd) or pd.isna(last_ema50_usd):
            coin_trend = "⚪ ข้อมูลไม่พอ"
            trend_status = "ข้อมูลไม่เพียงพอกำหนดเทรนด์"
        elif last_close_usd > last_ema50_usd and last_ema50_usd > last_ema200_usd:
            coin_trend = "🟢 ขาขึ้นต่อเนื่องแข็งแกร่ง"
            trend_status = "🟢 ขาขึ้นต่อเนื่องแข็งแกร่ง (Price > EMA50 > EMA200) 🔥"
            bullish_count += 1
        elif last_close_usd > last_ema200_usd:
            coin_trend = "📈 โซนขาขึ้น"
            trend_status = "📈 โซนขาขึ้น (เหนือเส้น EMA200)"
            bullish_count += 1
        elif last_close_usd < last_ema50_usd and last_ema50_usd < last_ema200_usd:
            coin_trend = "🔴 ขาลงต่อเนื่องรุนแรง"
            trend_status = "🔴 ขาลงต่อเนื่องรุนแรง (Price < EMA50 < EMA200) ⚠️"
        else:
            coin_trend = "📉 โซนขาลง"
            trend_status = "📉 โซนขาลง (ใต้เส้น EMA200)"

        rsi_str = f"{last_rsi:.1f}"
        coin_summaries.append(f"• <b>{display_name}</b> (Tier {tier_num}): {price_format}\n  └ เทรนด์: {coin_trend} | RSI: {rsi_str}")

        # ดึงชุดข้อมูลย้อนหลังสั้นๆ เพื่อตรวจสอบการฟื้นตัวของ RSI
        recent_rsi_df = df["RSI"].iloc[-CONFIG["rsi_recovery_lookback"]:]
        
        # สรุปตัวแปรสถานะ RSI ก่อนเข้าเงื่อนไขตรวจสอบสัญญาณ เพื่อความชัดเจน
        is_rsi_recovering = (last_rsi >= CONFIG["rsi_recovery_threshold"]) and (recent_rsi_df.min() <= 32)
        is_rsi_pulling_back = (last_rsi <= CONFIG["rsi_pullback_threshold"]) and (recent_rsi_df.max() >= 70)

        # -------------------------------------------------------------------------
        # ตรวจสอบสัญญาณซื้อขาย (SIGNAL CHECK)
        # -------------------------------------------------------------------------
        if is_rsi_recovering:
            is_bull_div = check_bullish_divergence(df)
            
            buy_zone = f"{format(last_close_usd, fmt)} - {format(last_close_usd * 0.98, fmt)}"
            tp1_price = f"{format(last_close_usd * (1 + tp1_pct), fmt)} (+{int(tp1_pct*100)}%)"
            tp2_price = f"{format(last_close_usd * (1 + tp2_pct), fmt)} (+{int(tp2_pct*100)}%)"
            stop_loss = f"{format(last_close_usd * 0.95, fmt)} (-5%)"
            
            safety_rating = "⭐ ดีที่สุดและปลอดภัยสูง (ซื้อในเทรนด์ขาขึ้น)" if "🟢" in coin_trend or "📈" in coin_trend else "⚠️ ความเสี่ยงสูง (ซื้อสวนเทรนด์ขาลงต่อเนื่อง)"

            msg = (
                f"🟢 <b>[SIGNAL BUY] {display_name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>กลุ่มเหรียญ:</b> Tier {tier_num}\n"
                f"💰 <b>ราคาปัจจุบัน:</b> {price_format} USD\n"
                f"📊 <b>ค่า RSI (1h):</b> {last_rsi:.2f} (ฟื้นตัวจากเขตล่างสำเร็จ 📈)\n"
                f"📈 <b>โครงสร้างเทรนด์:</b> {trend_status}\n"
                f"🎯 <b>ระดับความปลอดภัย:</b> {safety_rating}\n"
                f"⚡ <b>Divergence:</b> {'พบบูลลิชไดเวอร์เจนท์! 🚀' if is_bull_div else 'ไม่พบสัญญาณซ้อน'}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>แผนการเทรดแบบแบ่งเป้า (Tier {tier_num}):</b>\n"
                f"📍 โซนเข้าซื้อ: {buy_zone} USD\n"
                f"💰 เป้าทำกำไรระยะสั้น (TP1): {tp1_price} USD\n"
                f"🚀 เป้าทำกำไรลากเทรนด์ (TP2): {tp2_price} USD\n"
                f"❌ จุดตัดขาดทุน (SL): {stop_loss} USD"
            )
            send_telegram_message(msg)
            signal_sent_count += 1

        elif is_rsi_pulling_back:
            is_bear_div = check_bearish_divergence(df)
            
            sell_zone = f"{format(last_close_usd * 1.02, fmt)} - {format(last_close_usd, fmt)}"
            ema50_str = format(last_ema50_usd, fmt) if not pd.isna(last_ema50_usd) else "N/A"
            re_entry_zone = f"{format(last_close_usd * 0.95, fmt)} (หรือแนวรับ EMA50: {ema50_str})"
            trailing_stop = f"{format(last_close_usd * 0.97, fmt)}"
            
            msg = (
                f"🔴 <b>[SIGNAL SELL] {display_name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>กลุ่มเหรียญ:</b> Tier {tier_num}\n"
                f"💰 <b>ราคาปัจจุบัน:</b> {price_format} USD\n"
                f"📊 <b>ค่า RSI (1h):</b> {last_rsi:.2f} (เริ่มย่อตัวจากเขตบน 📉)\n"
                f"📈 <b>โครงสร้างเทรนด์:</b> {trend_status}\n"
                f"⚡ <b>Divergence:</b> {'พบแบร์ริชไดเวอร์เจนท์! 🚨' if is_bear_div else 'ไม่พบสัญญาณซ้อน'}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 <b>แผนการเก็บกำไร/บริหารความเสี่ยง:</b>\n"
                f"📍 โซนทยอยขายล็อกกำไร: {sell_zone} USD\n"
                f"🎯 รอรับกลับเมื่อราคาย่อตัว: {re_entry_zone} USD\n"
                f"❌ จุดล็อกกำไร/หนี (Trailing Stop): {trailing_stop} USD"
            )
            send_telegram_message(msg)
            signal_sent_count += 1

    # -------------------------------------------------------------------------
    # กรณีไม่มีสัญญาณเร่งด่วนในรอบชั่วโมงนี้ -> ส่งสรุปภาพรวมตลาด
    # -------------------------------------------------------------------------
    if signal_sent_count == 0 and total_coins > 0:
        bullish_ratio = bullish_count / total_coins
        if bullish_ratio >= 0.6:
            market_overview = "📈 ขาขึ้นแข็งแกร่ง (Bullish Market)"
        elif bullish_ratio <= 0.4:
            market_overview = "📉 ขาลงชัดเจน (Bearish Market)"
        else:
            market_overview = "↔️ ไซด์เวย์พักตัวเลือกทาง (Sideways Market)"
            
        no_signal_msg = (
            f"📊 <b>[Crypto Overview Report] ไม่พบสัญญาณเร่งด่วน</b>\n"
            f"ℹ️ <i>ในชั่วโมงนี้ไม่มีเหรียญใดเข้าเงื่อนไขสัญญานซื้อ/ขายที่สมบูรณ์</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔮 <b>ภาพรวมตลาดปัจจุบัน:</b> {market_overview}\n"
            f"📊 สัดส่วนเหรียญแนวโน้มขาขึ้น: {bullish_count} จากทั้งหมด {total_coins} ตัว\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧐 <b>สถานะ Trend & RSI รายเหรียญ:</b>\n" + 
            "\n".join(coin_summaries)
        )
        send_telegram_message(no_signal_msg)
        print("No urgent signal found. Market report sent successfully.")
    else:
        print(f"Process complete. Sent {signal_sent_count} signals.")

if __name__ == "__main__":
    screen_crypto()
