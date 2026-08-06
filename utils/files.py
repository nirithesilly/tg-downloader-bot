import os
import shutil
from pathlib import Path

from config import DOWNLOAD_PATH

def get_temp_path(filename: str) -> str:
    return os.path.join(DOWNLOAD_PATH, filename)

def cleanup_temp_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
    except Exception as e:
        print(f"Failed to delete {filepath}: {e}")
    return False

def cleanup_temp_folder():
    try:
        if os.path.exists(DOWNLOAD_PATH):
            shutil.rmtree(DOWNLOAD_PATH)
            os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    except Exception as e:
        print(f"Failed to clean downloads folder: {e}")

def get_file_size_mb(filepath: str) -> float:
    if os.path.exists(filepath):
        return os.path.getsize(filepath) / (1024 * 1024)
    return 0.0

