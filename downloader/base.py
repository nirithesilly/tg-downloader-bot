import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

from config import COOKIES_FILE, DOWNLOAD_PATH, HTTP_PROXY
from utils.download_manager import DownloadCancelled

try:
    import curl_cffi  # noqa: F401
    import yt_dlp.networking._curlcffi  # noqa: F401
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False


class FileTooLargeError(Exception):
    pass


class BaseDownloader:
    def __init__(self):
        self.download_path = DOWNLOAD_PATH
        os.makedirs(self.download_path, exist_ok=True)
        self._info_cache: dict[str, tuple[float, dict]] = {}
        self.default_opts: dict = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
        }
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            self.default_opts['cookiefile'] = COOKIES_FILE
        if HTTP_PROXY:
            self.default_opts['proxy'] = HTTP_PROXY

    def make_outtmpl(self, stamp: Optional[str] = None) -> tuple[str, str]:
        actual_stamp = stamp or uuid.uuid4().hex[:8]
        outtmpl = f'{self.download_path}/%(title).50s_%(id)s_{actual_stamp}.%(ext)s'
        return outtmpl, actual_stamp

    def cleanup_stamp(self, stamp: Optional[str]) -> None:
        if not stamp:
            return
        try:
            for f in Path(self.download_path).glob(f"*{stamp}*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def cleanup_partial(self, stamp: Optional[str] = None) -> None:
        actual_stamp = stamp or getattr(self, '_stamp', None)
        if actual_stamp:
            self.cleanup_stamp(actual_stamp)

    def _make_progress_hook(self, progress_hook: Optional[callable] = None,
                            cancel_check: Optional[callable] = None) -> callable:
        def hook(d: dict) -> None:
            if cancel_check and cancel_check():
                raise DownloadCancelled()
            if progress_hook:
                progress_hook(d)
        return hook

    def impersonate_opts(self) -> dict:
        if CURL_CFFI_AVAILABLE:
            from yt_dlp.networking.impersonate import ImpersonateTarget
            return {'impersonate': ImpersonateTarget.from_str('chrome')}
        return {}

    def _estimate_size(self, info: dict, max_height: Optional[int] = None) -> Optional[int]:
        formats = info.get('formats') or []
        if not formats:
            return info.get('filesize') or info.get('filesize_approx') or None

        def size(f: dict) -> int:
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
                return resolved
        except Exception:
            return url

    def safe_find_file(self, filename: str, stem: str) -> str:
        if Path(filename).exists():
            return filename
        if stem:
            for f in Path(self.download_path).glob(f"*{stem}*"):
                if f.is_file():
                    return str(f)
        return filename


    def get_info_cached(self, url: str, max_age: int = 300, **kwargs) -> dict:
        now = time.time()
        cached = self._info_cache.get(url)
        if cached and now - cached[0] < max_age:
            return cached[1]
        info = self.get_info(url, **kwargs)
        self._info_cache[url] = (now, info)
        expired = [k for k, (ts, _) in self._info_cache.items() if now - ts > max_age]
        for k in expired:
            self._info_cache.pop(k, None)
        return info

    def get_info(self, url: str, **kwargs) -> dict:
        raise NotImplementedError
