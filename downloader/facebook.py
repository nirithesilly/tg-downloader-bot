import logging
import urllib.request
from pathlib import Path
from typing import Optional

import yt_dlp

from downloader.base import BaseDownloader, FileTooLargeError
from utils.download_manager import DownloadCancelled

log = logging.getLogger(__name__)

MAX_RETRIES = 3


class FacebookDownloader(BaseDownloader):
    def resolve_url(self, url: str) -> str:
        clean_url = url.replace("m.facebook.com", "www.facebook.com").replace("web.facebook.com", "www.facebook.com")
        try:
            req = urllib.request.Request(clean_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                resolved = resp.geturl()
                return resolved
        except Exception:
            return clean_url

    def get_info(self, url: str, **kwargs) -> dict:
        resolved = self.resolve_url(url)
        opts = self.default_opts.copy()
        opts.update(self.impersonate_opts())
        opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(resolved, download=False)
                    return {
                        'title': info.get('title') or 'facebook video',
                        'uploader': info.get('uploader') or 'unknown',
                        'duration': info.get('duration', 0),
                        'id': info.get('id', 'fb_video')
                    }
            except Exception as e:
                last_err = e
                log.warning("facebook get_info attempt %d failed: %s", attempt + 1, e)
        raise Exception(f"ошибка facebook: {str(last_err)}")

    def _video_format(self, quality: str) -> str:
        if quality == "720p":
            return ('bestvideo[height<=720]+bestaudio'
                    '/best[height<=720]/best')
        if quality == "480p":
            return ('bestvideo[height<=480]+bestaudio'
                    '/best[height<=480]/best')
        return 'bestvideo+bestaudio/best'

    def download_video(self, url: str, quality: str = "best", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        resolved = self.resolve_url(url)
        outtmpl, stamp = self.make_outtmpl()
        try:
            opts = self.default_opts.copy()
            opts['outtmpl'] = outtmpl
            opts.update(self.impersonate_opts())
            opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            opts['format'] = self._video_format(quality)
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]
            max_height = 720 if quality == "720p" else 480 if quality == "480p" else None

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved, download=False)
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                estimated = self._estimate_size(info, max_height)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, stamp)
        except (FileTooLargeError, DownloadCancelled):
            self.cleanup_stamp(stamp)
            raise
        except Exception:
            self.cleanup_stamp(stamp)
            raise

    def download_audio(self, url: str, format: str = "mp3", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        resolved = self.resolve_url(url)
        outtmpl, stamp = self.make_outtmpl()
        try:
            opts = self.default_opts.copy()
            opts['outtmpl'] = outtmpl
            opts.update(self.impersonate_opts())
            opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            }
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved, download=False)
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                estimated = self._estimate_size(info)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                base = Path(filename).stem
                candidate = str(Path(self.download_path) / f"{base}.{format}")
                return self.safe_find_file(candidate, stamp)
        except (FileTooLargeError, DownloadCancelled):
            self.cleanup_stamp(stamp)
            raise
        except Exception:
            self.cleanup_stamp(stamp)
            raise

