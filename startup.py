from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import os
import subprocess
import sys


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    bot_dir = Path(__file__).resolve().parent / "iuca_schedule_bot-2"
    bot_file = bot_dir / "bot.py"
    if not bot_file.is_file():
        raise FileNotFoundError(f"Bot file not found: {bot_file}")

    port = int(os.environ.get("PORT", os.environ.get("WEBSITES_PORT", "8000")))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()

    print("Starting Telegram bot...", flush=True)
    bot = subprocess.Popen([sys.executable, str(bot_file)], cwd=str(bot_dir))
    try:
        exit_code = bot.wait()
    finally:
        server.shutdown()
        server.server_close()
    raise SystemExit(exit_code)
