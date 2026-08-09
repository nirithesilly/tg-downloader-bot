import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

MAX_FILE_SIZE_MB = 50
DOWNLOAD_PATH = str(BASE_DIR / "downloads")

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
