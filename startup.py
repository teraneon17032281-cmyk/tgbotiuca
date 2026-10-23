from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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

    print("Starting Telegram bot...", flush=True)
    bot = subprocess.Popen([sys.executable, str(bot_file)], cwd=str(bot_dir))

    port = int(os.environ.get("PORT", os.environ.get("WEBSITES_PORT", "8000")))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    try:
        while bot.poll() is None:
            server.handle_request()
    finally:
        server.server_close()
