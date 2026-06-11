"""
telegram_bot.py
───────────────
Sends trade alerts and status updates to Telegram.
"""

import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SYMBOL, USE_TESTNET

logger = logging.getLogger(__name__)

MODE_TAG = "🧪 TESTNET" if USE_TESTNET else "🔴 LIVE"


def send_message(text: str):
    """Send a plain text message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set — skipping notification")
        return
    try:
        url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }
        resp = requests.post(url, json=payload, timeout=5)
        if not resp.ok:
            logger.error(f"Telegram error: {resp.text}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


# ─────────────────────────────────────────────
#  NOTIFICATION TEMPLATES
# ─────────────────────────────────────────────

def notify_bot_started():
    send_message(
        f"🤖 <b>HFT Bot Started</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"Pair: <b>{SYMBOL}</b>\n"
        f"Status: Scanning for signals..."
    )


def notify_entry(direction: str, entry_price: float, qty: float,
                 tp_price: float, sl_price: float, signals: dict):
    arrow   = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    sig_str = " | ".join([f"{k}: {v}" for k, v in signals.items()])
    send_message(
        f"📈 <b>ENTRY — {arrow}</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"Pair:  <b>{SYMBOL}</b>\n"
        f"Price: <code>{entry_price:.4f}</code>\n"
        f"Qty:   <code>{qty}</code>\n"
        f"TP:    <code>{tp_price:.4f}</code>\n"
        f"SL:    <code>{sl_price:.4f}</code>\n"
        f"Signals: {sig_str}"
    )


def notify_entry_timeout(direction: str, order_id: int):
    send_message(
        f"⏱️ <b>Entry Timeout</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"Direction: {direction}\n"
        f"Order #{order_id} cancelled — not filled in time"
    )


def notify_take_profit(direction: str, entry_price: float,
                        tp_price: float, pnl: float):
    send_message(
        f"✅ <b>TAKE PROFIT HIT</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"Pair:   <b>{SYMBOL}</b>\n"
        f"Entry:  <code>{entry_price:.4f}</code>\n"
        f"Exit:   <code>{tp_price:.4f}</code>\n"
        f"PnL:    <code>+{pnl:.4f} USDT</code>"
    )


def notify_stop_loss(direction: str, entry_price: float,
                      sl_price: float, pnl: float):
    send_message(
        f"🛑 <b>STOP LOSS HIT</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"Pair:   <b>{SYMBOL}</b>\n"
        f"Entry:  <code>{entry_price:.4f}</code>\n"
        f"Exit:   <code>{sl_price:.4f}</code>\n"
        f"PnL:    <code>{pnl:.4f} USDT</code>"
    )


def notify_error(error_msg: str):
    send_message(
        f"⚠️ <b>Bot Error</b>\n"
        f"Mode: {MODE_TAG}\n"
        f"<code>{error_msg}</code>"
    )


def notify_bot_stopped():
    send_message(
        f"🔴 <b>HFT Bot Stopped</b>\n"
        f"Mode: {MODE_TAG}"
    )
