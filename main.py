import requests
import time
from datetime import datetime, timezone

# ── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN = "8747039226:AAEsiwvG8ltVTyIHxqTJcGmTCyEB23nnKAQ"
CHAT_ID   = "1083376877"

# ── FILTERS ─────────────────────────────────────────────────────────────────
MIN_LIQUIDITY  = 50_000
MIN_VOLUME_24H =  5_000
MIN_HOURS      =  2
MAX_HOURS      = 48
MIN_YES_PRICE  =  0.20
MAX_YES_PRICE  =  0.80
TOP_N          =  5
SCAN_INTERVAL  = 1800  # 30 minutes

POLYMARKET_API = "https://clob.polymarket.com/markets"

# ── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

# ── FETCH LIMITED MARKETS ────────────────────────────────────────────────────
def fetch_markets():
    """Fetch only 100 markets to stay within memory limits."""
    try:
        r = requests.get(POLYMARKET_API, params={
            "limit": 100,
            "active": "true"
        }, timeout=15)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"Fetch error: {e}")
        return []

# ── SCORE ────────────────────────────────────────────────────────────────────
def score(liquidity, volume_24h, yes_price):
    uncertainty = 1 - abs(yes_price - 0.50) * 2
    liq_score   = min(liquidity / 500_000, 1.0)
    vol_score   = min(volume_24h / 50_000,  1.0)
    return (uncertainty * 0.5) + (liq_score * 0.3) + (vol_score * 0.2)

# ── FILTER & RANK ─────────────────────────────────────────────────────────────
def filter_and_rank(markets):
    now = datetime.now(timezone.utc)
    candidates = []

    for m in markets:
        try:
            end_str = m.get("end_date_iso") or m.get("end_date") or ""
            if not end_str:
                continue
            end_dt     = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            hours_left = (end_dt - now).total_seconds() / 3600
            if not (MIN_HOURS <= hours_left <= MAX_HOURS):
                continue

            yes_price = None
            for t in m.get("tokens", []):
                if t.get("outcome", "").upper() == "YES":
                    yes_price = float(t.get("price", 0))
                    break
            if yes_price is None or not (MIN_YES_PRICE <= yes_price <= MAX_YES_PRICE):
                continue

            liquidity  = float(m.get("liquidity",   0) or 0)
            volume_24h = float(m.get("volume_24hr", 0) or 0)
            if liquidity < MIN_LIQUIDITY or volume_24h < MIN_VOLUME_24H:
                continue

            no_price   = round(1 - yes_price, 4)
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
                "url":        f"https://polymarket.com/event/{m.get('condition_id','')}",
                "score":      score(liquidity, volume_24h, yes_price),
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:TOP_N]

# ── FORMAT ───────────────────────────────────────────────────────────────────
def format_alert(rank, m):
    labels = {1: "🏆 BEST BET", 2: "🥈 #2", 3: "🥉 #3", 4: "4️⃣ #4", 5: "5️⃣ #5"}
    label  = labels.get(rank, f"#{rank}")
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

# ── MAIN ─────────────────────────────────────────────────────────────────────
def run():
    print("🚀 Polymarket Sniper Bot started")
    send_telegram("🚀 <b>Polymarket Sniper Bot is live!</b>\nScanning every 30 mins for TOP 5 trades.")

    while True:
        print(f"🔍 Scanning at {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
        markets = fetch_markets()
        top5    = filter_and_rank(markets)
        ts      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if top5:
            send_telegram(
                f"📡 <b>Scan — {ts}</b>\n"
                f"Scanned: {len(markets)} markets\n"
                f"Qualified: {len(top5)}\n\n"
                f"Your TOP 5 picks 👇"
            )
            time.sleep(1)
            for rank, m in enumerate(top5, 1):
                send_telegram(format_alert(rank, m))
                time.sleep(1)
        else:
            send_telegram(f"📡 <b>Scan — {ts}</b>\nNo qualifying signals. Checking again in 30 mins.")

        print("✅ Done. Sleeping 30 mins...")
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    run()

