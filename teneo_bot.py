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
"""

import asyncio
import json
import os
import sys
import time
import random
import argparse
import signal
from datetime import datetime
from pathlib import Path

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

DEFAULT_CONFIG = {
    "SESSION_KEY":    os.getenv("TENEO_SESSION_KEY", ""),
    "TARGET_REQUESTS": int(os.getenv("TENEO_TARGET_REQUESTS", "50")),
    "DELAY_SECONDS":   float(os.getenv("TENEO_DELAY_SECONDS", "2")),
    "AGENT_ID":        os.getenv("TENEO_AGENT_ID", ""),          # optional: target a specific agent
    "WS_URL":          os.getenv("TENEO_WS_URL", "wss://api.teneo-protocol.ai/ws"),
    "API_BASE":        os.getenv("TENEO_API_BASE", "https://api.teneo-protocol.ai"),
}

# Prompts to cycle through when sending requests
SAMPLE_PROMPTS = [
    "What can you help me with?",
    "Give me a brief summary of your capabilities.",
    "What tasks are you best suited for?",
    "Tell me something interesting.",
    "What's the latest update on Teneo Protocol?",
    "How does the x402 payment protocol work?",
    "Explain agent monetization in one sentence.",
    "What blockchain networks does Teneo support?",
    "How do session keys improve user experience?",
    "What is the Teneo Agent Console?",
]

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

def print_banner():
    banner = f"""
{Fore.GREEN}╔══════════════════════════════════════════════════╗
║{Fore.YELLOW}        TENEO AGENT BOT  ·  Quest Automation       {Fore.GREEN}║
║{Fore.WHITE}    Auto-runs Agent requests to earn points        {Fore.GREEN}║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}
"""
    print(banner)

def print_config(cfg):
    has_key = bool(cfg["SESSION_KEY"])
    key_display = cfg["SESSION_KEY"][:8] + "..." if has_key else f"{Fore.RED}NOT SET"
    print(f"  {Fore.CYAN}Session Key    {Fore.WHITE}{key_display}")
    print(f"  {Fore.CYAN}Target Reqs    {Fore.YELLOW}{cfg['TARGET_REQUESTS']}")
    print(f"  {Fore.CYAN}Delay          {Fore.WHITE}{cfg['DELAY_SECONDS']}s between requests")
    print(f"  {Fore.CYAN}Agent ID       {Fore.WHITE}{cfg['AGENT_ID'] or 'auto-discover'}")
    print()

def progress_bar(current, total, width=30):
    filled = int(width * current / max(total, 1))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / max(total, 1))
    return f"{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{pct}%{Style.RESET_ALL} ({current}/{total})"

# ─── CORE BOT ───────────────────────────────────────────────────────────────────

class TeneoBot:
    def __init__(self, config):
        self.cfg = config
        self.session_key = config["SESSION_KEY"]
        self.target = config["TARGET_REQUESTS"]
        self.delay = config["DELAY_SECONDS"]
        self.agent_id = config["AGENT_ID"]
        self.ws_url = config["WS_URL"]
        self.api_base = config["API_BASE"]

        self.count = 0
        self.points = 0
        self.errors = 0
        self.running = False
        self.start_time = None
        self.ws = None

    async def discover_agent(self, session):
        """Fetch first available public agent from Agent Console."""
        try:
            url = f"{self.api_base}/v1/agents?limit=5&status=public"
            headers = {"Authorization": f"Bearer {self.session_key}"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    agents = data.get("agents") or data.get("data") or []
                    if agents:
                        aid = agents[0].get("id") or agents[0].get("agentId")
                        log_ok(f"Discovered agent: {aid}")
                        return aid
        except Exception as e:
            log_warn(f"Agent discovery failed: {e}")
        return None

    async def send_request_http(self, session, prompt):
        """Send a single agent request via HTTP API."""
        url = f"{self.api_base}/v1/agents/{self.agent_id}/chat"
        headers = {
            "Authorization": f"Bearer {self.session_key}",
            "Content-Type":  "application/json",
            "User-Agent":    "TeneoBot/1.0",
        }
        payload = {
            "message": prompt,
            "sessionKey": self.session_key,
        }
        async with session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as r:
            body = await r.json()
            if r.status in (200, 201):
                pts = body.get("pointsEarned") or body.get("points") or 0
                return True, pts, body.get("response", "")[:80]
            else:
                return False, 0, body.get("error", f"HTTP {r.status}")

    async def send_request_ws(self, prompt):
        """Send a single agent request via WebSocket."""
        if not self.ws or self.ws.closed:
            raise ConnectionError("WebSocket not connected")
        msg = json.dumps({
            "type":      "task",
            "agentId":   self.agent_id,
            "message":   prompt,
            "sessionKey": self.session_key,
        })
        await self.ws.send(msg)
        # wait for response with timeout
        raw = await asyncio.wait_for(self.ws.recv(), timeout=20)
        data = json.loads(raw)
        if data.get("type") == "task_result":
            pts = data.get("pointsEarned") or 0
            return True, pts, str(data.get("result", ""))[:80]
        return False, 0, str(data)

    async def connect_ws(self):
        """Establish WebSocket connection with auth."""
        headers = {"Authorization": f"Bearer {self.session_key}"}
        url = f"{self.ws_url}?sessionKey={self.session_key}"
        log_info("Connecting via WebSocket...")
        self.ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        )
        log_ok("WebSocket connected")

    async def run(self):
        self.running = True
        self.start_time = time.time()

        print_banner()

        # Validate session key
        if not self.session_key:
            log_err("SESSION_KEY is not set!")
            log_warn("Create a .env file with TENEO_SESSION_KEY=your_key")
            log_warn("Get your Session Key from: https://agent-console.ai")
            sys.exit(1)

        log_info("Starting Teneo Agent Bot...")
        print_config(self.cfg)

        async with aiohttp.ClientSession() as http_session:
            # Discover agent if not set
            if not self.agent_id:
                self.agent_id = await self.discover_agent(http_session)
                if not self.agent_id:
                    log_warn("Could not auto-discover agent. Set TENEO_AGENT_ID in .env")
                    log_warn("Using fallback generic endpoint...")
                    self.agent_id = "default"

            log_info(f"Target: {self.target} requests  |  Agent: {self.agent_id}")
            log_info("Press Ctrl+C to stop at any time.\n")

            prompt_cycle = 0

            while self.count < self.target and self.running:
                prompt = SAMPLE_PROMPTS[prompt_cycle % len(SAMPLE_PROMPTS)]
                prompt_cycle += 1

                req_num = self.count + 1
                log_req(f"[{req_num:>3}/{self.target}] Sending: \"{prompt}\"")

                try:
                    success, pts, reply = await self.send_request_http(http_session, prompt)

                    if success:
                        self.count += 1
                        self.points += pts
                        elapsed = time.time() - self.start_time
                        rate = self.count / elapsed * 60 if elapsed > 0 else 0
                        pts_str = f"+{pts} pts" if pts else "✓"
                        log_ok(f"Done  {pts_str}  |  {progress_bar(self.count, self.target)}  |  {rate:.1f} req/min")
                        if reply:
                            log_res(f"Response: {reply}...")
                    else:
                        self.errors += 1
                        log_err(f"Request failed: {reply}")
                        if self.errors >= 5:
                            log_err("Too many consecutive errors. Check your session key.")
                            break

                except aiohttp.ClientConnectionError as e:
                    self.errors += 1
                    log_err(f"Connection error: {e}")
                    log_warn("Retrying in 5s...")
                    await asyncio.sleep(5)
                    continue

                except asyncio.TimeoutError:
                    self.errors += 1
                    log_warn("Request timed out. Retrying...")
                    await asyncio.sleep(3)
                    continue

                except Exception as e:
                    self.errors += 1
                    log_err(f"Unexpected error: {e}")
                    await asyncio.sleep(2)
                    continue

                # Jitter delay to avoid rate limits
                jitter = random.uniform(0.5, 1.5)
                await asyncio.sleep(self.delay * jitter)

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
        print(f"  {Fore.CYAN}Points earned   {Fore.YELLOW}{self.points:,}")
        print(f"  {Fore.CYAN}Errors          {Fore.RED if self.errors else Fore.GREEN}{self.errors}")
        print(f"  {Fore.CYAN}Duration        {Fore.WHITE}{mins}m {secs}s")
        print(f"  {Fore.CYAN}Avg rate        {Fore.WHITE}{rate:.1f} req/min")
        print(f"{Fore.GREEN}{'═'*52}{Style.RESET_ALL}\n")

        if self.count >= self.target:
            print(f"  {Fore.GREEN}✓ Quest target reached! Check Dashboard for points.{Style.RESET_ALL}")
            print(f"    Dashboard → {Fore.CYAN}https://go.teneo-protocol.ai/4d2Xipw{Style.RESET_ALL}\n")
        else:
            print(f"  {Fore.YELLOW}⚠  Stopped early ({self.count}/{self.target} requests){Style.RESET_ALL}\n")

    def stop(self):
        log_warn("Stopping bot...")
        self.running = False


# ─── ENTRYPOINT ─────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Teneo Agent Bot — Auto-run agent requests for quest points",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python teneo_bot.py
  python teneo_bot.py --requests 100
  python teneo_bot.py --requests 25 --delay 3
  TENEO_SESSION_KEY=abc123 python teneo_bot.py
        """,
    )
    p.add_argument("--requests", type=int,   help="Number of requests to send (default: 50)")
    p.add_argument("--delay",    type=float, help="Seconds between requests (default: 2)")
    p.add_argument("--agent",    type=str,   help="Agent ID to target")
    return p.parse_args()


async def main():
    args = parse_args()

    config = DEFAULT_CONFIG.copy()
    if args.requests: config["TARGET_REQUESTS"] = args.requests
    if args.delay:    config["DELAY_SECONDS"]   = args.delay
    if args.agent:    config["AGENT_ID"]        = args.agent

    bot = TeneoBot(config)

    # Graceful shutdown on Ctrl+C
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, bot.stop)
        except (NotImplementedError, ValueError):
            pass  # Windows fallback

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.stop()
        bot.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
