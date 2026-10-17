# AutoFlow Studio — Desktop, Browser, Gmail OTP & Smart Vision Bot

Modern macOS-styled full-screen automation, signup testing, Gmail OAuth OTP fetching, and Smart Visual/OCR target bot for Windows & Cloud VMs (Azure / AWS EC2).

## Quick Start (On Another Machine / VM)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/hussain301/autoflow-testing-bot.git
   cd autoflow-testing-bot
   ```
2. **Copy your `credentials.json` (and `token.json` if already authorized)** into this folder.
3. **Run the bot:**
   Double-click **`run_bot.bat`** (it automatically installs `requirements.txt` on first run) or run:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```

## Hotkeys
- **`F2`** — Type random `@nariwal.shop` email & start Auto-OTP watcher
- **`F3`** — Smart Target Click (OCR / Visual Reference lock)
- **`F4`** — Type secondary forwarded email (`mobile.j3pro@gmail.com`)
- **`F6`** — Pause / Resume Recording
- **`F7`** — Fetch & Type Fresh Gmail OTP
- **`F8`** — Start / Stop Recording
- **`F9`** — Play / Loop Macro
- **`F10`** — Emergency Stop
