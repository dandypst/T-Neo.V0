#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         TENEO AGENT BOT  - CLI Runner        ║
║   Auto-run Agent requests for Quest Points   ║
╚══════════════════════════════════════════════╝

Setup:
  pip install websockets colorama python-dotenv eth-account

Usage:
  python teneo_bot.py
  python teneo_bot.py --requests 100
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
import base64
from datetime import datetime, timezone

try:
    import websockets
    from colorama import Fore, Style, init as colorama_init
    from dotenv import load_dotenv
except ImportError:
    print("\n[ERROR] Missing dependencies. Run:\n")
    print("  pip install websockets colorama python-dotenv eth-account\n")
    sys.exit(1)

try:
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    HAS_ETH = True
except ImportError:
    HAS_ETH = False

colorama_init(autoreset=True)
load_dotenv()

# ─── ENDPOINTS ─────────────────────────────────────────────────────────────────

WS_URL = "wss://backend.developer.chatroom.teneo-protocol.ai/ws"

# ─── CONFIG ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "SESSION_KEY":     os.getenv("TENEO_SESSION_KEY", ""),
    "SESSION_TOKEN":   os.getenv("TENEO_SESSION_TOKEN", ""),   # dari browser
    "WALLET_ADDRESS":  os.getenv("TENEO_WALLET_ADDRESS", ""),
    "TARGET_REQUESTS": int(os.getenv("TENEO_TARGET_REQUESTS", "50")),
    "DELAY_SECONDS":   float(os.getenv("TENEO_DELAY_SECONDS", "3")),
    "AGENT_ID":        os.getenv("TENEO_AGENT_ID", "crypto-tracker-ai-v2"),
    "NETWORK":         os.getenv("TENEO_NETWORK", "eip155:3338"),
}

KNOWN_AGENTS = [
    "crypto-tracker-ai-v2",
    "trading-knowledge-agent",
    "gas-sniper-agent",
    "amazon",
    "x-agent-enterprise-v2",
]

# Command murah per agent
AGENT_COMMANDS = {
    "crypto-tracker-ai-v2": [
        "price BTC", "price ETH", "price PEAQ", "price SOL", "price BNB",
        "price AVAX", "price MATIC", "price ARB", "price OP", "price LINK",
        "analyze BTC", "analyze ETH", "analyze SOL", "analyze BNB", "analyze AVAX",
    ],
    "trading-knowledge-agent": [
        "What is DCA?", "Explain RSI.", "What is MACD?",
        "Explain bollinger bands.", "What is a stop loss?",
        "What is liquidity?", "What is slippage?",
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

def gen_req_id():
    ts_ms = int(time.time() * 1000)
    rand  = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
    return f"req-{ts_ms}-{rand}"

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def progress_bar(current, total, width=28):
    filled = int(width * current / max(total, 1))
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(100 * current / max(total, 1))
    return f"{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{pct}%{Style.RESET_ALL} ({current}/{total})"

def ws_is_open(ws):
    if ws is None:
        return False
    try:
        import websockets.connection as _wsc
        return ws.state is _wsc.State.OPEN
    except Exception:
        pass
    try:
        return bool(ws.open)
    except AttributeError:
        pass
    return True

def sign_payment(payment_token: str, private_key: str) -> str:
    """
    Sign x402 payment token menggunakan Session Key (private key).
    Payment token adalah JWT/base64 — dikembalikan as-is jika tidak bisa sign.
    Server kemungkinan sudah pre-signed via Session Key saat connect.
    """
    if not HAS_ETH or not private_key:
        return payment_token

    try:
        # Decode payment token untuk cek isi
        # Token ini sudah berisi signature dari Session Key
        # Kita kembalikan as-is karena sudah signed oleh smart account
        return payment_token
    except Exception:
        return payment_token

def generate_payment_token(quote_data: dict, wallet_address: str, session_key: str) -> str:
    """
    Generate x402 payment token dari task_quote data.
    Sign EIP-3009 transferWithAuthorization menggunakan Session Key.
    """
    import time, os, json, base64

    amount          = str(int(float(quote_data.get("pricing", {}).get("price_per_unit", 0.01)) * 1_000_000))  # USDC 6 decimals
    facilitator_fee = quote_data.get("facilitator_fee", "1000")
    total_amount    = str(int(amount) + int(facilitator_fee))
    salt            = quote_data.get("salt", "0x" + os.urandom(32).hex())
    settlement_router = quote_data.get("settlement_router", "0xCD57f4596f70b18a0fd0c42daa4F3066d3adc8d4")
    agent_wallet    = quote_data.get("agent_wallet", "0xcca7acda8c0e0a057c89600e7f438ff5d9afadb4")
    hook            = quote_data.get("hook", "0xf45FA7713a58eBd0C353186F9e49A7C39a0eD34E")
    hook_data       = quote_data.get("hook_data", "0x")
    usdc_contract   = "0xbbA60da06c2c5424f03f7434542280FCAd453d10"
    network         = quote_data.get("network", "eip155:3338")
    chain_id        = int(network.split(":")[-1])

    now         = int(time.time())
    valid_after = now - 10
    valid_before = now + 3600
    nonce       = "0x" + os.urandom(32).hex()

    authorization = {
        "from":        wallet_address,
        "to":          settlement_router,
        "value":       total_amount,
        "validAfter":  str(valid_after),
        "validBefore": str(valid_before),
        "nonce":       nonce,
    }

    signature = "0x" + "00" * 65  # placeholder if no eth_account

    if HAS_ETH and session_key and session_key.startswith("0x") and len(session_key) == 66:
        try:
            domain = {
                "name":              "USD Coin",
                "version":           "2",
                "chainId":           chain_id,
                "verifyingContract": usdc_contract,
            }
            types = {
                "TransferWithAuthorization": [
                    {"name": "from",        "type": "address"},
                    {"name": "to",          "type": "address"},
                    {"name": "value",       "type": "uint256"},
                    {"name": "validAfter",  "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce",       "type": "bytes32"},
                ]
            }
            message = {
                "from":        wallet_address,
                "to":          settlement_router,
                "value":       int(total_amount),
                "validAfter":  valid_after,
                "validBefore": valid_before,
                "nonce":       bytes.fromhex(nonce[2:]),
            }
            structured = {"domain": domain, "types": types, "primaryType": "TransferWithAuthorization", "message": message}
            signed     = Account.sign_typed_data(session_key, full_message=structured)
            signature  = signed.signature.hex()
            if not signature.startswith("0x"):
                signature = "0x" + signature
        except Exception as e:
            log_warn(f"EIP-712 sign failed: {e} — using placeholder signature")

    token_data = {
        "x402Version": 2,
        "resource": {
            "url":         "https://backend.developer.chatroom.teneo-protocol.ai/x402",
            "description": "WebSocket AI interaction on Peaq",
            "mimeType":    "application/json",
        },
        "accepted": {
            "scheme":            "exact",
            "network":           network,
            "amount":            amount,
            "asset":             usdc_contract,
            "payTo":             agent_wallet,
            "maxTimeoutSeconds": 60,
            "extra": {
                "name":             "USDC",
                "version":          "2",
                "settlementRouter": settlement_router,
                "salt":             salt,
                "payTo":            agent_wallet,
                "facilitatorFee":   hex(int(facilitator_fee)),
                "hook":             hook,
                "hookData":         hook_data,
            },
        },
        "payload": {
            "authorization": authorization,
            "signature":     signature,
        },
        "extensions": {
            "x402x-router-settlement": {
                "info": {
                    "settlementRouter": settlement_router,
                    "salt":             salt,
                    "finalPayTo":       agent_wallet,
                    "facilitatorFee":   hex(int(facilitator_fee)),
                    "hook":             hook,
                    "hookData":         hook_data,
                }
            }
        },
    }

    return base64.b64encode(json.dumps(token_data, separators=(",", ":")).encode()).decode()


def print_banner():
    print(f"""
{Fore.GREEN}╔══════════════════════════════════════════════════╗
║{Fore.YELLOW}        TENEO AGENT BOT  ·  Quest Automation       {Fore.GREEN}║
║{Fore.WHITE}  request_task → confirm_task → x402 payment flow {Fore.GREEN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}""")

# ─── BOT ────────────────────────────────────────────────────────────────────────

class TeneoBot:
    def __init__(self, config):
        self.cfg         = config
        self.session_key   = config["SESSION_KEY"]
        self.session_token = config["SESSION_TOKEN"]
        self.wallet        = config["WALLET_ADDRESS"]
        self.target      = config["TARGET_REQUESTS"]
        self.delay       = config["DELAY_SECONDS"]
        self.agent_id    = config["AGENT_ID"] or "crypto-tracker-ai-v2"
        self.network     = config["NETWORK"]
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

        # Handle auth + welcome message loop
        authed   = False
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                raw  = await asyncio.wait_for(self.ws.recv(), timeout=10)
                data = json.loads(raw)
                t    = data.get("type", "")
                log_info(f"[CONNECT] type={t!r}")

                # Step 1: Server minta auth
                if t == "auth_required":
                    log_info(f"Auth required — session_token={'SET' if self.session_token else 'EMPTY'}")
                    auth_msg = {
                        "type": "check_cached_auth",
                        "data": {
                            "address":        self.wallet,
                            "platform":       "community",
                            "request_source": "console",
                            "session_token":  self.session_token,
                        },
                    }
                    log_info(f"Sending check_cached_auth: wallet={self.wallet[:10]}... token={self.session_token[:10] if self.session_token else 'NONE'}...")
                    await self.ws.send(json.dumps(auth_msg))
                    continue

                # Step 2: Auth berhasil
                if t == "auth":
                    content_msg = data.get("content", "")
                    log_ok(f"Auth OK: {content_msg[:80]}")
                    authed    = True
                    auth_data = data.get("data", {})
                    private_rooms = auth_data.get("private_rooms", [])
                    if private_rooms and not self.room_id:
                        self.room_id = private_rooms[0].get("id")
                        log_ok(f"Room set from auth: {self.room_id}")
                    continue

                # Auth gagal
                if t == "error":
                    log_err(f"Auth error: {data.get('data') or data.get('content')}")
                    break

                # Step 3: Server kirim list agents (setelah auth)
                if t == "agents":
                    agents = data.get("data", [])
                    log_ok(f"Server: {len(agents)} agent(s) available")
                    if not self.agent_id:
                        self.agent_id = self._pick_agent(agents)
                    for a in agents:
                        if a.get("id") == self.agent_id:
                            rooms = a.get("rooms", [])
                            if rooms and not self.room_id:
                                self.room_id = rooms[0]
                            break
                    if authed:
                        break  # selesai setup
                    continue

            except asyncio.TimeoutError:
                log_warn("[CONNECT] timeout waiting for message")
                break

        if not authed:
            log_err("AUTH GAGAL — pastikan TENEO_SESSION_TOKEN benar di .env")
            log_warn("Cara ambil: buka agent-console.ai → F12 → WS Messages → cari check_cached_auth → copy session_token")

        log_info(f"Agent  : {Fore.YELLOW}{self.agent_id}")
        log_info(f"Room   : {self.room_id or 'none'}")

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
        """
        Flow:
          1. Kirim request_task dengan content="@agent-id command"
          2. Tunggu confirm_task dari server (berisi payment token)
          3. Kirim balik confirm_task dengan payment token
          4. Tunggu result/response
        """
        req_id        = gen_req_id()
        content       = f"@{self.agent_id} {command}"
        task_id       = None
        payment_token = None
        server_req_id = None

        # ── Step 1: Kirim request_task ─────────────────────────────────────
        request_msg = {
            "type":      "request_task",
            "content":   content,
            "from":      self.wallet,
            "room":      self.room_id,
            "data":      {"network": self.network},
            "timestamp": now_iso(),
        }

        await self.ws.send(json.dumps(request_msg))
        log_res(f"[1/3] request_task sent: {content}")

        # ── Step 2: Tunggu confirm_task dari server ────────────────────────
        payment_token = None
        task_id       = None
        server_req_id = None
        deadline      = time.time() + 30

        while time.time() < deadline:
            try:
                raw  = await asyncio.wait_for(self.ws.recv(), timeout=10)
                data = json.loads(raw)
                t    = data.get("type", "")

                log_res(f"[IN] type={t!r}")

                if t in ("ping", "pong", "heartbeat", "agents"):
                    continue

                if t == "task_quote":
                    qdata         = data.get("data", {})
                    task_id       = qdata.get("task_id")
                    server_req_id = data.get("request_id")
                    log_ok(f"[2/3] Got task_quote — task_id={task_id}, generating payment...")

                    payment_token = generate_payment_token(qdata, self.wallet, self.session_key)
                    log_res(f"[2/3] Payment token generated ({len(payment_token)} chars)")

                    confirm_msg = {
                        "type":       "confirm_task",
                        "room":       self.room_id,
                        "data":       {"task_id": task_id},
                        "payment":    payment_token,
                        "request_id": server_req_id,
                        "timestamp":  now_iso(),
                    }
                    await self.ws.send(json.dumps(confirm_msg))
                    log_res(f"[3/3] confirm_task sent — waiting result...")
                    # Lanjut tunggu result di loop
                    continue

                if t == "confirm_task":
                    payment_token = data.get("payment")
                    task_id       = (data.get("data") or {}).get("task_id") or data.get("task_id")
                    server_req_id = data.get("request_id")
                    log_ok(f"[2/3] Got confirm_task — task_id={task_id}")
                    break

                if t == "error":
                    err = data.get("data") or data.get("content") or "error"
                    return False, str(err)[:100]

            except asyncio.TimeoutError:
                continue

        if not payment_token:
            return False, "No confirm_task received (timeout)"

        # confirm_task sudah dikirim di dalam loop task_quote di atas
        if not task_id:
            return False, "No task_quote received"

        # ── Step 4: Tunggu hasil ───────────────────────────────────────────
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                raw  = await asyncio.wait_for(self.ws.recv(), timeout=15)
                data = json.loads(raw)
                t    = data.get("type", "")

                log_res(f"[IN] type={t!r}  keys={list(data.keys())}")

                if t in ("ping", "pong", "heartbeat", "agents"):
                    continue

                # Hasil sukses
                if t in ("task_result", "result", "response", "output",
                         "task_complete", "task_response", "reply"):
                    val = (data.get("content") or data.get("data")
                           or data.get("result") or "ok")
                    return True, str(val)[:120]

                # Message dari agent = hasil
                if t == "message" and data.get("from") == self.agent_id:
                    val = data.get("content") or data.get("data") or "ok"
                    return True, str(val)[:120]

                if t == "error":
                    val = data.get("data") or data.get("content") or "error"
                    return False, str(val)[:100]

                log_warn(f"Unhandled type={t!r}, waiting...")

            except asyncio.TimeoutError:
                log_warn("15s no result, still waiting...")
                continue

        return False, "Timeout waiting for result"

    async def ensure_connected(self):
        if not ws_is_open(self.ws):
            log_warn("Reconnecting...")
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
        if not self.room_id and not self.wallet:
            log_err("TENEO_WALLET_ADDRESS diperlukan untuk room_id")
            sys.exit(1)

        log_info("Starting Teneo Agent Bot...")
        print(f"  {Fore.CYAN}Wallet    {Fore.WHITE}{self.wallet[:10]}...{self.wallet[-6:]}")
        print(f"  {Fore.CYAN}Agent     {Fore.YELLOW}{self.agent_id}")
        print(f"  {Fore.CYAN}Target    {Fore.YELLOW}{self.target} requests")
        print(f"  {Fore.CYAN}Network   {Fore.WHITE}{self.network}\n")

        try:
            await self.connect()
        except Exception as e:
            log_err(f"Gagal connect: {e}")
            sys.exit(1)

        log_info("Tekan Ctrl+C untuk berhenti.\n")

        commands   = AGENT_COMMANDS.get(self.agent_id, AGENT_COMMANDS["default"])
        cmd_cycle  = 0
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
                        log_res(str(reply)[:80])
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

        try:
            if ws_is_open(self.ws):
                await self.ws.close()
        except Exception:
            pass

        self.print_summary()

    def print_summary(self):
        elapsed = time.time() - (self.start_time or time.time())
        mins    = int(elapsed // 60)
        secs    = int(elapsed % 60)
        rate    = self.count / elapsed * 60 if elapsed > 0 else 0

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
    p = argparse.ArgumentParser(
        description="Teneo Agent Bot — WebSocket CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Agents:
  crypto-tracker-ai-v2     Crypto price (termurah, default)
  trading-knowledge-agent  Trading knowledge
  gas-sniper-agent         Gas war sniper
  x-agent-enterprise-v2   X/Twitter

Contoh:
  python teneo_bot.py
  python teneo_bot.py --requests 100
  python teneo_bot.py --agent crypto-tracker-ai-v2 --requests 100
        """,
    )
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
