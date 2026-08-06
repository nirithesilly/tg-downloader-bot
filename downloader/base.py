import os
import urllib.request
import urllib.parse
from pathlib import Path
import yt_dlp
from config import DOWNLOAD_PATH

class BaseDownloader:
    def __init__(self):
        self.download_path = DOWNLOAD_PATH
        os.makedirs(self.download_path, exist_ok=True)
        self.default_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'outtmpl': f'{self.download_path}/%(title).50s_%(id)s.%(ext)s',
        }

    def resolve_url(self, url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                resolved = resp.geturl()
                return resolved.split('?')[0] if '?' in resolved else resolved
        except Exception:
            return url

    def safe_find_file(self, filename: str, stem: str) -> str:
        if Path(filename).exists():
            return filename
        for f in Path(self.download_path).glob(f"*{stem}*"):
            return str(f)
        return filename
