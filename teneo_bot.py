#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         TENEO AGENT BOT  - CLI Runner        ║
║   Auto-run Agent requests for Quest Points   ║
╚══════════════════════════════════════════════╝

Setup:
  pip install websockets aiohttp colorama python-dotenv

Usage:
  python teneo_bot.py                        # run dengan .env config
  python teneo_bot.py --requests 100         # target 100 requests
  python teneo_bot.py --agent crypto-tracker-ai-v2 --requests 100
"""

import asyncio
import json
import os
import sys
import time
import random
import string
import argparse
import signal
from datetime import datetime, timezone

try:
    import websockets
    from colorama import Fore, Style, init as colorama_init
    from dotenv import load_dotenv
except ImportError:
    print("\n[ERROR] Missing dependencies. Run:\n")
    print("  pip install websockets colorama python-dotenv\n")
    sys.exit(1)

colorama_init(autoreset=True)
load_dotenv()

# ─── ENDPOINTS ─────────────────────────────────────────────────────────────────

WS_URL = "wss://backend.developer.chatroom.teneo-protocol.ai/ws"

# ─── CONFIG ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "SESSION_KEY":     os.getenv("TENEO_SESSION_KEY", ""),
    "WALLET_ADDRESS":  os.getenv("TENEO_WALLET_ADDRESS", ""),
    "TARGET_REQUESTS": int(os.getenv("TENEO_TARGET_REQUESTS", "50")),
    "DELAY_SECONDS":   float(os.getenv("TENEO_DELAY_SECONDS", "3")),
    "AGENT_ID":        os.getenv("TENEO_AGENT_ID", ""),
}

KNOWN_AGENTS = [
    "crypto-tracker-ai-v2",
    "trading-knowledge-agent",
    "gas-sniper-agent",
    "amazon",
    "x-agent-enterprise-v2",
]

AGENT_COMMANDS = {
    "crypto-tracker-ai-v2": [
        "price BTC", "price ETH", "price PEAQ", "price SOL", "price BNB",
        "price AVAX", "price MATIC", "price ARB", "price OP", "price LINK",
    ],
    "trading-knowledge-agent": [
        "What is DCA strategy?", "Explain support and resistance.",
        "What is RSI indicator?", "What is MACD?", "Explain bollinger bands.",
        "What is a stop loss?", "Explain market cap.",
        "What is liquidity?", "Explain order book.", "What is slippage?",
    ],
    "x-agent-enterprise-v2": [
        "user elonmusk", "user VitalikButerin", "user cz_binance",
        "user naval", "user balajis",
    ],
    "default": [
        "price BTC", "price ETH", "price SOL", "price BNB", "price AVAX",
    ],
}

# ─── HELPERS ────────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg, color=Fore.WHITE, prefix="•"):
    print(f"{Fore.CYAN}{ts()}{Style.RESET_ALL}  {color}{prefix} {msg}{Style.RESET_ALL}")

def log_ok(msg):   log(msg, Fore.GREEN,   "✓")
def log_info(msg): log(msg, Fore.CYAN,    "ℹ")
def log_warn(msg): log(msg, Fore.YELLOW,  "⚠")
def log_err(msg):  log(msg, Fore.RED,     "✗")
def log_req(msg):  log(msg, Fore.MAGENTA, "→")
def log_res(msg):  log(msg, Fore.WHITE,   "←")

def gen_msg_id():
    return "ws-" + "".join(random.choices(string.ascii_letters + string.digits, k=20))

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

def progress_bar(current, total, width=28):
    filled = int(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / max(total, 1))
    return f"{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{pct}%{Style.RESET_ALL} ({current}/{total})"

def ws_is_open(ws):
    """Cek koneksi WebSocket masih open — kompatibel semua versi websockets."""
    if ws is None:
        return False
    # websockets >= 13 (ClientConnection) — pakai .state
    try:
        import websockets.connection as _wsc
        return ws.state is _wsc.State.OPEN
    except Exception:
        pass
    # websockets 10-12 — pakai .open
    try:
        return bool(ws.open)
    except AttributeError:
        pass
    # Fallback — asumsikan open
    return True

def print_banner():
    print(f"""
{Fore.GREEN}╔══════════════════════════════════════════════════╗
║{Fore.YELLOW}        TENEO AGENT BOT  ·  Quest Automation       {Fore.GREEN}║
║{Fore.WHITE}    WebSocket · agent-console.ai · Real Requests  {Fore.GREEN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}""")

# ─── BOT ────────────────────────────────────────────────────────────────────────

class TeneoBot:
    def __init__(self, config):
        self.cfg         = config
        self.session_key = config["SESSION_KEY"]
        self.wallet      = config["WALLET_ADDRESS"]
        self.target      = config["TARGET_REQUESTS"]
        self.delay       = config["DELAY_SECONDS"]
        self.agent_id    = config["AGENT_ID"] or ""
        self.count       = 0
        self.errors      = 0
        self.running     = False
        self.start_time  = None
        self.ws          = None
        self.room_id     = None

    async def connect(self):
        log_info("Connecting WebSocket...")
        self.ws = await websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=15,
            open_timeout=15,
        )
        log_ok("Connected!")

        # Tunggu welcome message dari server
        try:
            raw  = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(raw)
            if data.get("type") == "agents":
                agents = data.get("data", [])
                log_ok(f"Server: {len(agents)} agent(s) online")

                if not self.agent_id:
                    self.agent_id = self._pick_agent(agents)

                for a in agents:
                    if a.get("id") == self.agent_id:
                        rooms = a.get("rooms", [])
                        if rooms:
                            self.room_id = rooms[0]
                        break

                log_info(f"Agent  : {Fore.YELLOW}{self.agent_id}")
                log_info(f"Room   : {self.room_id or 'none'}")
        except asyncio.TimeoutError:
            log_warn("No welcome message received, continuing...")

    def _pick_agent(self, agents):
        online = {a.get("id") for a in agents if a.get("status") == "online"}
        for a in KNOWN_AGENTS:
            if a in online:
                return a
        for a in agents:
            if a.get("status") == "online":
                return a.get("id", "crypto-tracker-ai-v2")
        return "crypto-tracker-ai-v2"

    async def send_request(self, command):
        msg_id  = gen_msg_id()
        payload = {
            "type":       "task",
            "id":         msg_id,
            "from":       self.wallet,
            "to":         self.agent_id,
            "roomId":     self.room_id,
            "sessionKey": self.session_key,
            "data":       {"command": command},
            "timestamp":  now_iso(),
        }

        await self.ws.send(json.dumps(payload))
        log_res(f"Sent [{msg_id[:14]}] — waiting response...")

        # Terima response apapun yang relevan (bukan pesan sistem)
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                raw  = await asyncio.wait_for(self.ws.recv(), timeout=15)
                data = json.loads(raw)
                t    = data.get("type", "")

                log_res(f"[IN] type={t!r}  keys={list(data.keys())}")

                # Skip pesan sistem
                if t in ("agents", "ping", "pong", "heartbeat", "connected"):
                    continue

                # Response sukses
                if t in ("task_result", "result", "response", "task_complete",
                         "task_response", "message", "output"):
                    val = data.get("data") or data.get("result") or data.get("message") or "ok"
                    return True, str(val)[:100]

                # Error
                if t == "error":
                    val = data.get("data") or data.get("message") or "error"
                    return False, str(val)[:100]

                # ID match
                if data.get("id") == msg_id:
                    return True, str(data.get("data", "ok"))[:100]

                log_warn(f"Unknown type={t!r}, skip")

            except asyncio.TimeoutError:
                log_warn("15s no response, still waiting...")
                continue
            except json.JSONDecodeError:
                continue

        return False, "Timeout (45s)"

    async def ensure_connected(self):
        if not ws_is_open(self.ws):
            log_warn("WebSocket not open, reconnecting...")
            await asyncio.sleep(2)
            await self.connect()

    async def run(self):
        self.running    = True
        self.start_time = time.time()

        print_banner()

        if not self.session_key:
            log_err("TENEO_SESSION_KEY belum diset di .env!")
            sys.exit(1)
        if not self.wallet:
            log_err("TENEO_WALLET_ADDRESS belum diset di .env!")
            sys.exit(1)

        log_info("Starting...")
        print(f"  {Fore.CYAN}Wallet    {Fore.WHITE}{self.wallet[:10]}...{self.wallet[-6:]}")
        print(f"  {Fore.CYAN}Target    {Fore.YELLOW}{self.target} requests")
        print(f"  {Fore.CYAN}Delay     {Fore.WHITE}{self.delay}s + jitter\n")

        try:
            await self.connect()
        except Exception as e:
            log_err(f"Gagal connect: {e}")
            sys.exit(1)

        log_info("Tekan Ctrl+C untuk berhenti.\n")

        commands  = AGENT_COMMANDS.get(self.agent_id, AGENT_COMMANDS["default"])
        cmd_cycle = 0
        consec_err = 0

        while self.count < self.target and self.running:
            command = commands[cmd_cycle % len(commands)]
            cmd_cycle += 1

            log_req(f"[{self.count+1:>3}/{self.target}] \"{command}\"")

            try:
                await self.ensure_connected()
                success, reply = await self.send_request(command)

                if success:
                    self.count += 1
                    consec_err  = 0
                    elapsed = time.time() - self.start_time
                    rate    = self.count / elapsed * 60 if elapsed > 0 else 0
                    log_ok(f"{progress_bar(self.count, self.target)}  {rate:.1f} req/min")
                    if reply and reply not in ("{}", "ok", ""):
                        log_res(reply[:80])
                else:
                    consec_err  += 1
                    self.errors += 1
                    log_err(f"Failed: {reply}")
                    if consec_err >= 5:
                        log_err("5 error berturut. Cek session key / saldo USDC.")
                        break
                    await asyncio.sleep(3)
                    continue

            except websockets.exceptions.ConnectionClosed:
                log_warn("Connection closed, reconnecting...")
                await asyncio.sleep(3)
                try:
                    await self.connect()
                except Exception as e:
                    log_err(f"Reconnect gagal: {e}")
                    break
                continue

            except Exception as e:
                consec_err  += 1
                self.errors += 1
                log_err(f"Error: {e}")
                await asyncio.sleep(2)
                continue

            await asyncio.sleep(self.delay * random.uniform(0.8, 1.4))

        # Tutup koneksi
        try:
            if ws_is_open(self.ws):
                await self.ws.close()
        except Exception:
            pass

        self.print_summary()

    def print_summary(self):
        elapsed = time.time() - (self.start_time or time.time())
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        rate = self.count / elapsed * 60 if elapsed > 0 else 0

        print(f"\n{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}  SESSION COMPLETE{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}Requests   {Fore.WHITE}{self.count} / {self.target}")
        print(f"  {Fore.CYAN}Errors     {Fore.RED if self.errors else Fore.GREEN}{self.errors}")
        print(f"  {Fore.CYAN}Duration   {Fore.WHITE}{mins}m {secs}s")
        print(f"  {Fore.CYAN}Rate       {Fore.WHITE}{rate:.1f} req/min")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}\n")

        if self.count >= self.target:
            print(f"  {Fore.GREEN}✓ Target tercapai! Cek Dashboard untuk points.{Style.RESET_ALL}")
            print(f"    {Fore.CYAN}https://go.teneo-protocol.ai/4d2Xipw{Style.RESET_ALL}\n")
        else:
            print(f"  {Fore.YELLOW}⚠  Berhenti di {self.count}/{self.target}{Style.RESET_ALL}\n")

    def stop(self):
        log_warn("Stopping...")
        self.running = False

# ─── MAIN ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Teneo Agent Bot — WebSocket CLI")
    p.add_argument("--requests", type=int,   help="Jumlah requests (default: 50)")
    p.add_argument("--delay",    type=float, help="Delay antar request detik (default: 3)")
    p.add_argument("--agent",    type=str,   help="Agent ID")
    return p.parse_args()

async def main():
    args   = parse_args()
    config = DEFAULT_CONFIG.copy()
    if args.requests: config["TARGET_REQUESTS"] = args.requests
    if args.delay:    config["DELAY_SECONDS"]   = args.delay
    if args.agent:    config["AGENT_ID"]        = args.agent

    bot  = TeneoBot(config)
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop)
        except Exception:
            pass

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.stop()
        bot.print_summary()

if __name__ == "__main__":
    asyncio.run(main())
