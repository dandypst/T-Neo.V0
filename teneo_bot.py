#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         TENEO AGENT BOT  - CLI Runner        ║
║   Auto-run Agent requests for Quest Points   ║
╚══════════════════════════════════════════════╝

Setup:
  pip install websockets aiohttp colorama python-dotenv

Usage:
  python teneo_bot.py                  # run with .env config
  python teneo_bot.py --requests 100   # override target requests
  python teneo_bot.py --delay 3        # set delay between requests (seconds)
  python teneo_bot.py --agent crypto-tracker-ai-v2
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
from datetime import datetime

try:
    import websockets
    import aiohttp
    from colorama import Fore, Style, init as colorama_init
    from dotenv import load_dotenv
except ImportError:
    print("\n[ERROR] Missing dependencies. Run:\n")
    print("  pip install websockets aiohttp colorama python-dotenv\n")
    sys.exit(1)

colorama_init(autoreset=True)
load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────

WS_URL   = "wss://backend.developer.chatroom.teneo-protocol.ai/ws"
API_BASE = "https://backend.developer.chatroom.teneo-protocol.ai"

DEFAULT_CONFIG = {
    "SESSION_KEY":      os.getenv("TENEO_SESSION_KEY", ""),
    "WALLET_ADDRESS":   os.getenv("TENEO_WALLET_ADDRESS", ""),
    "TARGET_REQUESTS":  int(os.getenv("TENEO_TARGET_REQUESTS", "50")),
    "DELAY_SECONDS":    float(os.getenv("TENEO_DELAY_SECONDS", "3")),
    "AGENT_ID":         os.getenv("TENEO_AGENT_ID", ""),
}

# Agent IDs yang tersedia
KNOWN_AGENTS = [
    "crypto-tracker-ai-v2",    # Crypto Tracker — murah, recommended
    "trading-knowledge-agent",  # Trading Agent
    "gas-sniper-agent",         # Gas War Sniper
    "amazon",                   # Amazon
    "x-agent-enterprise-v2",   # X Platform Agent (lebih mahal)
]

# Commands per agent — pilih yang paling murah
AGENT_COMMANDS = {
    "crypto-tracker-ai-v2": [
        "price BTC",
        "price ETH",
        "price PEAQ",
        "price SOL",
        "price BNB",
        "price AVAX",
        "price MATIC",
        "price ARB",
        "price OP",
        "price LINK",
    ],
    "trading-knowledge-agent": [
        "What is DCA strategy?",
        "Explain support and resistance.",
        "What is RSI indicator?",
        "What is MACD?",
        "Explain bollinger bands.",
        "What is a stop loss?",
        "Explain market cap.",
        "What is liquidity?",
        "Explain order book.",
        "What is slippage?",
    ],
    "x-agent-enterprise-v2": [
        "user elonmusk",
        "user VitalikButerin",
        "user cz_binance",
        "user naval",
        "user balajis",
    ],
    "default": [
        "price BTC",
        "price ETH",
        "price SOL",
        "price BNB",
        "price AVAX",
    ],
}

# ─── HELPERS ────────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg, color=Fore.WHITE, prefix="•"):
    print(f"{Fore.CYAN}{ts()}{Style.RESET_ALL}  {color}{prefix} {msg}{Style.RESET_ALL}")

def log_ok(msg):    log(msg, Fore.GREEN,   "✓")
def log_info(msg):  log(msg, Fore.CYAN,    "ℹ")
def log_warn(msg):  log(msg, Fore.YELLOW,  "⚠")
def log_err(msg):   log(msg, Fore.RED,     "✗")
def log_req(msg):   log(msg, Fore.MAGENTA, "→")
def log_res(msg):   log(msg, Fore.WHITE,   "←")

def gen_msg_id():
    """Generate WebSocket message ID: ws-XXXXXXXXXXXXXXXXXXXX"""
    chars = string.ascii_letters + string.digits
    return "ws-" + "".join(random.choices(chars, k=20))

def progress_bar(current, total, width=28):
    filled = int(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / max(total, 1))
    return f"{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{pct}%{Style.RESET_ALL} ({current}/{total})"

def print_banner():
    print(f"""
{Fore.GREEN}╔══════════════════════════════════════════════════╗
║{Fore.YELLOW}        TENEO AGENT BOT  ·  Quest Automation       {Fore.GREEN}║
║{Fore.WHITE}    WebSocket · agent-console.ai · Real Requests  {Fore.GREEN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}""")

def print_config(cfg, agent_id, room_id):
    wallet = cfg["WALLET_ADDRESS"]
    key    = cfg["SESSION_KEY"]
    w_disp = f"{wallet[:10]}...{wallet[-6:]}" if len(wallet) > 16 else wallet
    k_disp = f"{key[:10]}...{key[-6:]}"       if len(key) > 16    else key
    print(f"  {Fore.CYAN}Wallet         {Fore.WHITE}{w_disp}")
    print(f"  {Fore.CYAN}Session Key    {Fore.WHITE}{k_disp}")
    print(f"  {Fore.CYAN}Agent          {Fore.YELLOW}{agent_id}")
    print(f"  {Fore.CYAN}Room           {Fore.WHITE}{room_id or 'none'}")
    print(f"  {Fore.CYAN}Target         {Fore.YELLOW}{cfg['TARGET_REQUESTS']} requests")
    print(f"  {Fore.CYAN}Delay          {Fore.WHITE}{cfg['DELAY_SECONDS']}s + jitter")
    print()

# ─── CORE BOT ───────────────────────────────────────────────────────────────────

class TeneoBot:
    def __init__(self, config):
        self.cfg         = config
        self.session_key = config["SESSION_KEY"]
        self.wallet      = config["WALLET_ADDRESS"]
        self.target      = config["TARGET_REQUESTS"]
        self.delay       = config["DELAY_SECONDS"]
        self.agent_id    = config["AGENT_ID"] or ""

        self.count      = 0
        self.errors     = 0
        self.running    = False
        self.start_time = None
        self.ws         = None
        self.room_id    = None

    # ── WS: Connect ───────────────────────────────────────────────────────────
    async def connect(self):
        log_info("Connecting to WebSocket...")
        self.ws = await websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=15,
            open_timeout=15,
        )
        log_ok("WebSocket connected")

        # Tunggu welcome message (server kirim list agents)
        try:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(raw)
            if data.get("type") == "agents":
                agents = data.get("data", [])
                log_ok(f"Server: {len(agents)} agent(s) available")

                # Auto-pilih agent kalau belum diset
                if not self.agent_id:
                    self.agent_id = self._pick_agent(agents)

                # Ambil room_id untuk agent yang dipilih
                for a in agents:
                    if a.get("id") == self.agent_id:
                        rooms = a.get("rooms", [])
                        if rooms:
                            self.room_id = rooms[0]
                        break

        except asyncio.TimeoutError:
            log_warn("No welcome message, continuing anyway...")

        log_info(f"Agent  : {Fore.YELLOW}{self.agent_id}")
        log_info(f"Room   : {self.room_id or 'none'}")

    def _pick_agent(self, agents):
        """Pilih agent online termurah."""
        online_ids = {a.get("id") for a in agents if a.get("status") == "online"}
        for preferred in KNOWN_AGENTS:
            if preferred in online_ids:
                return preferred
        # Fallback: agent pertama yang online
        for a in agents:
            if a.get("status") == "online":
                return a.get("id", "crypto-tracker-ai-v2")
        return "crypto-tracker-ai-v2"

    # ── WS: Kirim 1 request ───────────────────────────────────────────────────
    async def send_request(self, command):
        msg_id = gen_msg_id()

        payload = {
            "type":       "task",
            "id":         msg_id,
            "from":       self.wallet,
            "to":         self.agent_id,
            "roomId":     self.room_id,
            "sessionKey": self.session_key,
            "data": {
                "command": command,
            },
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        }

        await self.ws.send(json.dumps(payload))

        # Tunggu response
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
                data = json.loads(raw)
                t = data.get("type", "")

                # Response untuk request kita
                if data.get("id") == msg_id:
                    if t in ("task_result", "result", "response", "task_complete"):
                        result = data.get("data", {})
                        return True, str(result)[:100]
                    if t == "error":
                        err = data.get("data", {})
                        return False, str(err.get("message", err))[:100]

                # Pesan lain — skip
            except asyncio.TimeoutError:
                break

        return False, "Timeout"

    # ── Reconnect ─────────────────────────────────────────────────────────────
    async def ensure_connected(self):
        if self.ws is None or self.ws.closed:
            log_warn("Disconnected, reconnecting...")
            await asyncio.sleep(2)
            await self.connect()

    # ── Main loop ─────────────────────────────────────────────────────────────
    async def run(self):
        self.running    = True
        self.start_time = time.time()

        print_banner()

        if not self.session_key:
            log_err("TENEO_SESSION_KEY belum diset!")
            log_warn("Edit .env → isi TENEO_SESSION_KEY=...")
            log_warn("Dapatkan dari: https://agent-console.ai")
            sys.exit(1)

        if not self.wallet:
            log_warn("TENEO_WALLET_ADDRESS tidak diset")
            log_warn("Tambahkan TENEO_WALLET_ADDRESS=0x... di .env")
            sys.exit(1)

        log_info("Starting Teneo Agent Bot...")

        try:
            await self.connect()
        except Exception as e:
            log_err(f"Gagal connect: {e}")
            sys.exit(1)

        print_config(self.cfg, self.agent_id, self.room_id)
        log_info("Tekan Ctrl+C untuk berhenti.\n")

        commands = AGENT_COMMANDS.get(self.agent_id, AGENT_COMMANDS["default"])
        cmd_cycle          = 0
        consecutive_errors = 0

        while self.count < self.target and self.running:
            command = commands[cmd_cycle % len(commands)]
            cmd_cycle += 1
            req_num = self.count + 1

            log_req(f"[{req_num:>3}/{self.target}] \"{command}\"")

            try:
                await self.ensure_connected()
                success, reply = await self.send_request(command)

                if success:
                    self.count        += 1
                    consecutive_errors = 0
                    elapsed = time.time() - self.start_time
                    rate    = self.count / elapsed * 60 if elapsed > 0 else 0
                    log_ok(f"{progress_bar(self.count, self.target)}  {rate:.1f} req/min")
                    if reply and reply not in ("{}", ""):
                        log_res(reply[:80])
                else:
                    consecutive_errors += 1
                    self.errors        += 1
                    log_err(f"Failed: {reply}")
                    if consecutive_errors >= 5:
                        log_err("5 error berturut-turut. Cek session key / saldo USDC.")
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
                consecutive_errors += 1
                self.errors        += 1
                log_err(f"Error: {e}")
                await asyncio.sleep(2)
                continue

            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(self.delay * jitter)

        if self.ws and not self.ws.closed:
            await self.ws.close()

        self.print_summary()

    def print_summary(self):
        elapsed = time.time() - (self.start_time or time.time())
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        rate = self.count / elapsed * 60 if elapsed > 0 else 0

        print(f"\n{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}  SESSION COMPLETE{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}Requests sent   {Fore.WHITE}{self.count} / {self.target}")
        print(f"  {Fore.CYAN}Errors          {Fore.RED if self.errors else Fore.GREEN}{self.errors}")
        print(f"  {Fore.CYAN}Duration        {Fore.WHITE}{mins}m {secs}s")
        print(f"  {Fore.CYAN}Avg rate        {Fore.WHITE}{rate:.1f} req/min")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}\n")

        if self.count >= self.target:
            print(f"  {Fore.GREEN}✓ Target tercapai! Cek Dashboard untuk points.{Style.RESET_ALL}")
            print(f"    {Fore.CYAN}https://go.teneo-protocol.ai/4d2Xipw{Style.RESET_ALL}\n")
        else:
            print(f"  {Fore.YELLOW}⚠  Berhenti di {self.count}/{self.target} requests{Style.RESET_ALL}\n")

    def stop(self):
        log_warn("Stopping...")
        self.running = False


# ─── ENTRYPOINT ─────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Teneo Agent Bot — WebSocket CLI runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Agents tersedia:
  crypto-tracker-ai-v2     Crypto price (termurah, recommended)
  trading-knowledge-agent  Trading knowledge
  gas-sniper-agent         Gas war sniper
  x-agent-enterprise-v2   X/Twitter (lebih mahal)

Contoh:
  python teneo_bot.py
  python teneo_bot.py --requests 100
  python teneo_bot.py --agent crypto-tracker-ai-v2 --requests 100
  python teneo_bot.py --requests 25 --delay 5
        """,
    )
    p.add_argument("--requests", type=int,   help="Jumlah requests (default: 50)")
    p.add_argument("--delay",    type=float, help="Delay antar request (detik, default: 3)")
    p.add_argument("--agent",    type=str,   help="Agent ID")
    return p.parse_args()


async def main():
    args = parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.requests: config["TARGET_REQUESTS"] = args.requests
    if args.delay:    config["DELAY_SECONDS"]   = args.delay
    if args.agent:    config["AGENT_ID"]        = args.agent

    bot = TeneoBot(config)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop)
        except (NotImplementedError, ValueError):
            pass

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.stop()
        bot.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║         TENEO AGENT BOT  - CLI Runner        ║
║   Auto-run Agent requests for Quest Points   ║
╚══════════════════════════════════════════════╝

Setup:
  pip install websockets aiohttp colorama python-dotenv

Usage:
  python teneo_bot.py                  # run with .env config
  python teneo_bot.py --requests 100   # override target requests
  python teneo_bot.py --delay 3        # set delay between requests (seconds)
  python teneo_bot.py --agent crypto-tracker-ai-v2
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
from datetime import datetime

try:
    import websockets
    import aiohttp
    from colorama import Fore, Style, init as colorama_init
    from dotenv import load_dotenv
except ImportError:
    print("\n[ERROR] Missing dependencies. Run:\n")
    print("  pip install websockets aiohttp colorama python-dotenv\n")
    sys.exit(1)

colorama_init(autoreset=True)
load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────

WS_URL   = "wss://backend.developer.chatroom.teneo-protocol.ai/ws"
API_BASE = "https://backend.developer.chatroom.teneo-protocol.ai"

DEFAULT_CONFIG = {
    "SESSION_KEY":      os.getenv("TENEO_SESSION_KEY", ""),
    "WALLET_ADDRESS":   os.getenv("TENEO_WALLET_ADDRESS", ""),
    "TARGET_REQUESTS":  int(os.getenv("TENEO_TARGET_REQUESTS", "50")),
    "DELAY_SECONDS":    float(os.getenv("TENEO_DELAY_SECONDS", "3")),
    "AGENT_ID":         os.getenv("TENEO_AGENT_ID", ""),
}

# Agent IDs yang tersedia
KNOWN_AGENTS = [
    "crypto-tracker-ai-v2",    # Crypto Tracker — murah, recommended
    "trading-knowledge-agent",  # Trading Agent
    "gas-sniper-agent",         # Gas War Sniper
    "amazon",                   # Amazon
    "x-agent-enterprise-v2",   # X Platform Agent (lebih mahal)
]

# Commands per agent — pilih yang paling murah
AGENT_COMMANDS = {
    "crypto-tracker-ai-v2": [
        "price BTC",
        "price ETH",
        "price PEAQ",
        "price SOL",
        "price BNB",
        "price AVAX",
        "price MATIC",
        "price ARB",
        "price OP",
        "price LINK",
    ],
    "trading-knowledge-agent": [
        "What is DCA strategy?",
        "Explain support and resistance.",
        "What is RSI indicator?",
        "What is MACD?",
        "Explain bollinger bands.",
        "What is a stop loss?",
        "Explain market cap.",
        "What is liquidity?",
        "Explain order book.",
        "What is slippage?",
    ],
    "x-agent-enterprise-v2": [
        "user elonmusk",
        "user VitalikButerin",
        "user cz_binance",
        "user naval",
        "user balajis",
    ],
    "default": [
        "price BTC",
        "price ETH",
        "price SOL",
        "price BNB",
        "price AVAX",
    ],
}

# ─── HELPERS ────────────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg, color=Fore.WHITE, prefix="•"):
    print(f"{Fore.CYAN}{ts()}{Style.RESET_ALL}  {color}{prefix} {msg}{Style.RESET_ALL}")

def log_ok(msg):    log(msg, Fore.GREEN,   "✓")
def log_info(msg):  log(msg, Fore.CYAN,    "ℹ")
def log_warn(msg):  log(msg, Fore.YELLOW,  "⚠")
def log_err(msg):   log(msg, Fore.RED,     "✗")
def log_req(msg):   log(msg, Fore.MAGENTA, "→")
def log_res(msg):   log(msg, Fore.WHITE,   "←")

def gen_msg_id():
    """Generate WebSocket message ID: ws-XXXXXXXXXXXXXXXXXXXX"""
    chars = string.ascii_letters + string.digits
    return "ws-" + "".join(random.choices(chars, k=20))

def progress_bar(current, total, width=28):
    filled = int(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / max(total, 1))
    return f"{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{pct}%{Style.RESET_ALL} ({current}/{total})"

def print_banner():
    print(f"""
{Fore.GREEN}╔══════════════════════════════════════════════════╗
║{Fore.YELLOW}        TENEO AGENT BOT  ·  Quest Automation       {Fore.GREEN}║
║{Fore.WHITE}    WebSocket · agent-console.ai · Real Requests  {Fore.GREEN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}""")

def print_config(cfg, agent_id, room_id):
    wallet = cfg["WALLET_ADDRESS"]
    key    = cfg["SESSION_KEY"]
    w_disp = f"{wallet[:10]}...{wallet[-6:]}" if len(wallet) > 16 else wallet
    k_disp = f"{key[:10]}...{key[-6:]}"       if len(key) > 16    else key
    print(f"  {Fore.CYAN}Wallet         {Fore.WHITE}{w_disp}")
    print(f"  {Fore.CYAN}Session Key    {Fore.WHITE}{k_disp}")
    print(f"  {Fore.CYAN}Agent          {Fore.YELLOW}{agent_id}")
    print(f"  {Fore.CYAN}Room           {Fore.WHITE}{room_id or 'none'}")
    print(f"  {Fore.CYAN}Target         {Fore.YELLOW}{cfg['TARGET_REQUESTS']} requests")
    print(f"  {Fore.CYAN}Delay          {Fore.WHITE}{cfg['DELAY_SECONDS']}s + jitter")
    print()

# ─── CORE BOT ───────────────────────────────────────────────────────────────────

class TeneoBot:
    def __init__(self, config):
        self.cfg         = config
        self.session_key = config["SESSION_KEY"]
        self.wallet      = config["WALLET_ADDRESS"]
        self.target      = config["TARGET_REQUESTS"]
        self.delay       = config["DELAY_SECONDS"]
        self.agent_id    = config["AGENT_ID"] or ""

        self.count      = 0
        self.errors     = 0
        self.running    = False
        self.start_time = None
        self.ws         = None
        self.room_id    = None

    # ── WS: Connect ───────────────────────────────────────────────────────────
    async def connect(self):
        log_info("Connecting to WebSocket...")
        self.ws = await websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=15,
            open_timeout=15,
        )
        log_ok("WebSocket connected")

        # Tunggu welcome message (server kirim list agents)
        try:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(raw)
            if data.get("type") == "agents":
                agents = data.get("data", [])
                log_ok(f"Server: {len(agents)} agent(s) available")

                # Auto-pilih agent kalau belum diset
                if not self.agent_id:
                    self.agent_id = self._pick_agent(agents)

                # Ambil room_id untuk agent yang dipilih
                for a in agents:
                    if a.get("id") == self.agent_id:
                        rooms = a.get("rooms", [])
                        if rooms:
                            self.room_id = rooms[0]
                        break

        except asyncio.TimeoutError:
            log_warn("No welcome message, continuing anyway...")

        log_info(f"Agent  : {Fore.YELLOW}{self.agent_id}")
        log_info(f"Room   : {self.room_id or 'none'}")

    def _pick_agent(self, agents):
        """Pilih agent online termurah."""
        online_ids = {a.get("id") for a in agents if a.get("status") == "online"}
        for preferred in KNOWN_AGENTS:
            if preferred in online_ids:
                return preferred
        # Fallback: agent pertama yang online
        for a in agents:
            if a.get("status") == "online":
                return a.get("id", "crypto-tracker-ai-v2")
        return "crypto-tracker-ai-v2"

    # ── WS: Kirim 1 request ───────────────────────────────────────────────────
    async def send_request(self, command):
        msg_id = gen_msg_id()

        payload = {
            "type":       "task",
            "id":         msg_id,
            "from":       self.wallet,
            "to":         self.agent_id,
            "roomId":     self.room_id,
            "sessionKey": self.session_key,
            "data": {
                "command": command,
            },
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        }

        await self.ws.send(json.dumps(payload))

        # Tunggu response
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
                data = json.loads(raw)
                t = data.get("type", "")

                # Response untuk request kita
                if data.get("id") == msg_id:
                    if t in ("task_result", "result", "response", "task_complete"):
                        result = data.get("data", {})
                        return True, str(result)[:100]
                    if t == "error":
                        err = data.get("data", {})
                        return False, str(err.get("message", err))[:100]

                # Pesan lain — skip
            except asyncio.TimeoutError:
                break

        return False, "Timeout"

    # ── Reconnect ─────────────────────────────────────────────────────────────
    async def ensure_connected(self):
        if self.ws is None or self.ws.closed:
            log_warn("Disconnected, reconnecting...")
            await asyncio.sleep(2)
            await self.connect()

    # ── Main loop ─────────────────────────────────────────────────────────────
    async def run(self):
        self.running    = True
        self.start_time = time.time()

        print_banner()

        if not self.session_key:
            log_err("TENEO_SESSION_KEY belum diset!")
            log_warn("Edit .env → isi TENEO_SESSION_KEY=...")
            log_warn("Dapatkan dari: https://agent-console.ai")
            sys.exit(1)

        if not self.wallet:
            log_warn("TENEO_WALLET_ADDRESS tidak diset")
            log_warn("Tambahkan TENEO_WALLET_ADDRESS=0x... di .env")
            sys.exit(1)

        log_info("Starting Teneo Agent Bot...")

        try:
            await self.connect()
        except Exception as e:
            log_err(f"Gagal connect: {e}")
            sys.exit(1)

        print_config(self.cfg, self.agent_id, self.room_id)
        log_info("Tekan Ctrl+C untuk berhenti.\n")

        commands = AGENT_COMMANDS.get(self.agent_id, AGENT_COMMANDS["default"])
        cmd_cycle          = 0
        consecutive_errors = 0

        while self.count < self.target and self.running:
            command = commands[cmd_cycle % len(commands)]
            cmd_cycle += 1
            req_num = self.count + 1

            log_req(f"[{req_num:>3}/{self.target}] \"{command}\"")

            try:
                await self.ensure_connected()
                success, reply = await self.send_request(command)

                if success:
                    self.count        += 1
                    consecutive_errors = 0
                    elapsed = time.time() - self.start_time
                    rate    = self.count / elapsed * 60 if elapsed > 0 else 0
                    log_ok(f"{progress_bar(self.count, self.target)}  {rate:.1f} req/min")
                    if reply and reply not in ("{}", ""):
                        log_res(reply[:80])
                else:
                    consecutive_errors += 1
                    self.errors        += 1
                    log_err(f"Failed: {reply}")
                    if consecutive_errors >= 5:
                        log_err("5 error berturut-turut. Cek session key / saldo USDC.")
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
                consecutive_errors += 1
                self.errors        += 1
                log_err(f"Error: {e}")
                await asyncio.sleep(2)
                continue

            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep(self.delay * jitter)

        if self.ws and not self.ws.closed:
            await self.ws.close()

        self.print_summary()

    def print_summary(self):
        elapsed = time.time() - (self.start_time or time.time())
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        rate = self.count / elapsed * 60 if elapsed > 0 else 0

        print(f"\n{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}  SESSION COMPLETE{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}Requests sent   {Fore.WHITE}{self.count} / {self.target}")
        print(f"  {Fore.CYAN}Errors          {Fore.RED if self.errors else Fore.GREEN}{self.errors}")
        print(f"  {Fore.CYAN}Duration        {Fore.WHITE}{mins}m {secs}s")
        print(f"  {Fore.CYAN}Avg rate        {Fore.WHITE}{rate:.1f} req/min")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}\n")

        if self.count >= self.target:
            print(f"  {Fore.GREEN}✓ Target tercapai! Cek Dashboard untuk points.{Style.RESET_ALL}")
            print(f"    {Fore.CYAN}https://go.teneo-protocol.ai/4d2Xipw{Style.RESET_ALL}\n")
        else:
            print(f"  {Fore.YELLOW}⚠  Berhenti di {self.count}/{self.target} requests{Style.RESET_ALL}\n")

    def stop(self):
        log_warn("Stopping...")
        self.running = False


# ─── ENTRYPOINT ─────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Teneo Agent Bot — WebSocket CLI runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Agents tersedia:
  crypto-tracker-ai-v2     Crypto price (termurah, recommended)
  trading-knowledge-agent  Trading knowledge
  gas-sniper-agent         Gas war sniper
  x-agent-enterprise-v2   X/Twitter (lebih mahal)

Contoh:
  python teneo_bot.py
  python teneo_bot.py --requests 100
  python teneo_bot.py --agent crypto-tracker-ai-v2 --requests 100
  python teneo_bot.py --requests 25 --delay 5
        """,
    )
    p.add_argument("--requests", type=int,   help="Jumlah requests (default: 50)")
    p.add_argument("--delay",    type=float, help="Delay antar request (detik, default: 3)")
    p.add_argument("--agent",    type=str,   help="Agent ID")
    return p.parse_args()


async def main():
    args = parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.requests: config["TARGET_REQUESTS"] = args.requests
    if args.delay:    config["DELAY_SECONDS"]   = args.delay
    if args.agent:    config["AGENT_ID"]        = args.agent

    bot = TeneoBot(config)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop)
        except (NotImplementedError, ValueError):
            pass

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.stop()
        bot.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
