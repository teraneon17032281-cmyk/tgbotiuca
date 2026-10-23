from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import os
import runpy


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

    os.chdir(bot_dir)
    port = int(os.environ.get("PORT", os.environ.get("WEBSITES_PORT", "8000")))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    Thread(target=server.serve_forever, daemon=True).start()

    print(f"Starting Telegram bot from {bot_file}...", flush=True)
    runpy.run_path(str(bot_file), run_name="__main__")
