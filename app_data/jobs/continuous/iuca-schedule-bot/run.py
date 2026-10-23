from pathlib import Path
import runpy
import os


app_root = Path(__file__).resolve().parents[4]
bot_dir = app_root / "iuca_schedule_bot-2"
os.chdir(bot_dir)
runpy.run_path(str(bot_dir / "bot.py"), run_name="__main__")
