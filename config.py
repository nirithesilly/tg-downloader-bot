import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN or not BOT_TOKEN.strip():
    print("error: BOT_TOKEN not set. create .env file or export BOT_TOKEN.", file=sys.stderr)
    sys.exit(1)

MAX_FILE_SIZE_MB = 50
PART_SIZE_MB = 45
MAX_DOWNLOAD_SIZE_MB = 1000
DOWNLOAD_PATH = str(BASE_DIR / "downloads")
LOG_DIR = str(BASE_DIR / "logs")

os.makedirs(DOWNLOAD_PATH, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
