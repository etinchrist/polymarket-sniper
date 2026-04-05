import requests
import time
from datetime import datetime, timezone

# ── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8747039226:AAEsiwvG8ltVTyIHxqTJcGmTCyEB23nnKAQ"
CHAT_ID   = "1083376877"

# ── FILTERS ─────────────────────────────────────────────────────────────────
MIN_LIQUIDITY   = 50_000   # $50,000 minimum
MIN_VOLUME_24H  =  5_000   # $5,000 minimum 24h volume
MIN_HOURS       =  2       # closes in at least 2 hours
MAX_HOURS       = 48       # closes in at most 48 hours (2 days)
MIN_YES_PRICE   =  0.20    # 20% — genuinely uncertain
MAX_YES_PRICE   =  0.80    # 80% — genuinely uncertain
TOP_N           =  5       # send only the best 5 signals
SCAN_INTERVAL   = 1800     # 30 minutes in seconds

POLYMARKET_API  = "https://clob.polymarket.com/markets"

# ── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Telegram error: {e}")

# ── FETCH MARKETS ─────────────────────────────────────────────────────────────
def fetch_markets():
    markets = []
    next_cursor = ""
    while True:
        try:
            params = {"limit": 100, "active": "true"}
            if next_cursor:
                params["next_cursor"] = next_cursor
            r = requests.get(POLYMARKET_API, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            markets.extend(data.get("data", []))
            next_cursor = data.get("next_cursor", "")
            if not next_cursor or next_cursor == "LTE=":
                break
        except Exception as e:
            print(f"Fetch error: {e}")
            break
    return markets

# ── SCORE A MARKET (higher = better) ─────────────────────────────────────────
def score_market(liquidity, volume_24h, yes_price):
    # Closer to 0.50 = more uncertain = more value
    uncertainty = 1 - abs(yes_price - 0.50) * 2   # 0→1, best at 0.50
    liq_score   = min(liquidity / 500_000, 1.0)    # normalise, cap at 1
    vol_score   = min(volume_24h / 50_000,  1.0)
    return (uncertainty * 0.5) + (liq_score * 0.3) + (vol_score * 0.2)

# ── FILTER & RANK ─────────────────────────────────────────────────────────────
def filter_and_rank(markets):
    now = datetime.now(timezone.utc)
    candidates = []

    for m in markets:
        try:
            # ── time filter ──
            end_str = m.get("end_date_iso") or m.get("end_date") or ""
            if not end_str:
                continue
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            hours_left = (end_dt - now).total_seconds() / 3600
            if not (MIN_HOURS <= hours_left <= MAX_HOURS):
                continue

            # ── price filter ──
            tokens = m.get("tokens", [])
            yes_price = None
            for t in tokens:
                if t.get("outcome", "").upper() == "YES":
                    yes_price = float(t.get("price", 0))
                    break
            if yes_price is None:
                continue
            if not (MIN_YES_PRICE <= yes_price <= MAX_YES_PRICE):
                continue

            no_price = round(1 - yes_price, 4)

            # ── liquidity filter ──
            liquidity = float(m.get("liquidity", 0) or 0)
            if liquidity < MIN_LIQUIDITY:
                continue

            # ── volume filter ──
            volume_24h = float(m.get("volume_24hr", 0) or 0)
            if volume_24h < MIN_VOLUME_24H:
                continue

            # ── profit potential ──
            yes_profit = round((1 / yes_price - 1) * 100, 1)
            no_profit  = round((1 / no_price  - 1) * 100, 1)

            candidates.append({
                "question":   m.get("question", "Unknown"),
                "yes_price":  yes_price,
                "no_price":   no_price,
                "yes_profit": yes_profit,
                "no_profit":  no_profit,
                "liquidity":  liquidity,
                "volume_24h": volume_24h,
                "hours_left": round(hours_left, 1),
                "url":        f"https://polymarket.com/event/{m.get('condition_id', '')}",
                "score":      score_market(liquidity, volume_24h, yes_price),
            })
        except Exception:
            continue

    # Sort best first
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:TOP_N]

# ── FORMAT ALERT ──────────────────────────────────────────────────────────────
def format_alert(rank: int, m: dict) -> str:
    medal = {1: "🏆 BEST BET", 2: "🥈 #2", 3: "🥉 #3", 4: "4️⃣ #4", 5: "5️⃣ #5"}
    label = medal.get(rank, f"#{rank}")

    return (
        f"{label}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>{m['question']}</b>\n\n"
        f"🟢 YES @ {m['yes_price']} → <b>+{m['yes_profit']}% profit</b>\n"
        f"🔴 NO  @ {m['no_price']} → <b>+{m['no_profit']}% profit</b>\n\n"
        f"💧 Liquidity: ${m['liquidity']:,.0f}\n"
        f"📊 24h Volume: ${m['volume_24h']:,.0f}\n"
        f"⏳ Closes in: {m['hours_left']}h\n"
        f"🔗 <a href='{m['url']}'>View on Polymarket</a>"
    )

# ── MAIN SCAN LOOP ────────────────────────────────────────────────────────────
def run():
    print("🚀 Polymarket Sniper Bot started")
    send_telegram("🚀 <b>Polymarket Sniper Bot is live!</b>\nScanning every 30 minutes for the TOP 5 trades.")

    while True:
        print(f"\n🔍 Scanning at {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        markets   = fetch_markets()
        top5      = filter_and_rank(markets)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if top5:
            # Header
            send_telegram(
                f"📡 <b>Polymarket Scan — {timestamp}</b>\n"
                f"Markets scanned: {len(markets)}\n"
                f"Qualifying signals: {len(top5)}\n\n"
                f"Here are your TOP 5 picks 👇"
            )
            time.sleep(1)
            for rank, market in enumerate(top5, start=1):
                send_telegram(format_alert(rank, market))
                time.sleep(1)
        else:
            send_telegram(
                f"📡 <b>Scan — {timestamp}</b>\n"
                f"No qualifying signals this round. Will check again in 30 mins."
            )

        print(f"✅ Scan done. Sleeping 30 minutes...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()
