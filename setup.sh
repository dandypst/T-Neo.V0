#!/data/data/com.termux/files/usr/bin/bash
# ╔══════════════════════════════════════════╗
# ║     TENEO BOT — Termux Setup Script     ║
# ╚══════════════════════════════════════════╝

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}║     TENEO BOT — Termux Setup Script     ║${RESET}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ─── 1. Update & install Python ───────────────────────────────
echo -e "${CYAN}[1/4] Update packages & install Python...${RESET}"
pkg update -y -q && pkg upgrade -y -q
pkg install -y python > /dev/null 2>&1
echo -e "${GREEN}✓ Python ready${RESET}"

# ─── 2. Install pip dependencies ──────────────────────────────
echo -e "${CYAN}[2/4] Install Python dependencies...${RESET}"
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${RESET}"

# ─── 3. Setup .env ────────────────────────────────────────────
echo -e "${CYAN}[3/4] Setup config...${RESET}"

if [ -f ".env" ]; then
  echo -e "${YELLOW}⚠  .env sudah ada, skip.${RESET}"
else
  cp .env.example .env
  echo -e "${GREEN}✓ File .env dibuat dari .env.example${RESET}"
  echo ""
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${YELLOW}  PENTING: Isi SESSION KEY kamu di .env !${RESET}"
  echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""
  echo -e "  Buka file .env:"
  echo -e "  ${CYAN}nano .env${RESET}"
  echo ""
  echo -e "  Ganti baris ini:"
  echo -e "  ${RED}TENEO_SESSION_KEY=paste_session_key_kamu_disini${RESET}"
  echo ""
  echo -e "  Dapatkan Session Key di:"
  echo -e "  ${CYAN}https://agent-console.ai → Create Session Key${RESET}"
  echo ""
fi

# ─── 4. Done ──────────────────────────────────────────────────
echo -e "${CYAN}[4/4] Setup selesai!${RESET}"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}  Cara jalankan bot:${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo -e "  ${CYAN}python teneo_bot.py${RESET}                    # 50 requests"
echo -e "  ${CYAN}python teneo_bot.py --requests 100${RESET}     # 100 requests"
echo -e "  ${CYAN}python teneo_bot.py --requests 25${RESET}      # 25 requests"
echo ""
echo -e "  Ctrl+C untuk berhenti kapan saja."
echo ""
