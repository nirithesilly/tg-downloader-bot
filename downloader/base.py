import os
import uuid
import urllib.request
import urllib.parse
from pathlib import Path
import yt_dlp
from config import DOWNLOAD_PATH


class FileTooLargeError(Exception):
    pass


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
        }

    def make_outtmpl(self) -> str:
        return f'{self.download_path}/%(title).50s_%(id)s_{uuid.uuid4().hex[:8]}.%(ext)s'

    def _estimate_size(self, info: dict, max_height: int = None):
        formats = info.get('formats') or []
        if not formats:
            return info.get('filesize') or info.get('filesize_approx') or None

        def size(f):
            return f.get('filesize') or f.get('filesize_approx') or 0

        candidates = formats
        videos = [f for f in formats if (f.get('vcodec') or 'none') != 'none']
        audios = [f for f in formats if (f.get('vcodec') in (None, 'none')) and (f.get('acodec') or 'none') != 'none']

        if max_height:
            videos = [f for f in videos if (f.get('height') or 0) <= max_height]

        total = 0
        if videos:
            total += size(max(videos, key=lambda f: ((f.get('height') or 0), size(f))))
        if audios:
            total += size(max(audios, key=lambda f: ((f.get('abr') or 0), size(f))))
        if total:
            return total

        for f in candidates:
            if size(f):
                return size(f)
        return None

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
