import json
import uuid
import urllib.request
import urllib.parse
from pathlib import Path

import yt_dlp

from downloader.base import BaseDownloader, FileTooLargeError
from utils.download_manager import DownloadCancelled


class TikTokDownloader(BaseDownloader):
    def _fetch_tikwm_info(self, url: str) -> dict:
        resolved_url = self.resolve_url(url)
        api_url = "https://www.tikwm.com/api/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }
        data = urllib.parse.urlencode({'url': resolved_url, 'hd': 1}).encode('utf-8')
        req = urllib.request.Request(api_url, data=data, headers=headers)

        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            if res_data.get('code') == 0:
                return res_data['data']
        raise Exception(f"tikwm api ответ: {res_data.get('msg', 'ошибка')}")

    def _download_file(self, file_url: str, output_path: Path, max_size_mb: int = None,
                       cancel_check=None) -> str:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            req = urllib.request.Request(file_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp, open(output_path, 'wb') as out_file:
                if max_size_mb:
                    length = resp.headers.get('Content-Length')
                    if length and int(length) > max_size_mb * 1024 * 1024:
                        raise FileTooLargeError(
                            f"файл слишком большой: ~{int(length) / 1048576:.1f} мб > лимита {max_size_mb} мб"
                        )
                while True:
                    if cancel_check and cancel_check():
                        raise DownloadCancelled()
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    out_file.write(chunk)
            return str(output_path)
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    def get_info(self, url: str) -> dict:
        resolved_url = self.resolve_url(url)
        try:
            tikwm_data = self._fetch_tikwm_info(resolved_url)
            author = tikwm_data.get('author', {})
            return {
                'title': tikwm_data.get('title') or 'tiktok video',
                'uploader': author.get('nickname') or author.get('unique_id') or 'unknown',
                'duration': tikwm_data.get('duration', 0),
                'description': (tikwm_data.get('title') or '')[:200],
                'video_url': tikwm_data.get('hdplay') or tikwm_data.get('play'),
                'audio_url': tikwm_data.get('music'),
                'id': tikwm_data.get('id', 'tiktok_video')
            }
        except Exception:
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    info = ydl.extract_info(resolved_url, download=False)
                    return {
                        'title': info.get('title', 'tiktok video'),
                        'uploader': info.get('uploader', 'unknown'),
                        'duration': info.get('duration', 0),
                        'description': info.get('description', '')[:200],
                        'id': info.get('id', 'tiktok_video')
                    }
            except Exception as ydl_err:
                raise Exception(f"ошибка получения видео tiktok: {ydl_err}")

    def download_video(self, url: str, max_size_mb: int = None, progress_hook=None,
                       cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        try:
            info = self.get_info(url)
            video_direct_url = info.get('video_url')
            video_id = info.get('id', 'video')

            if video_direct_url:
                file_path = Path(self.download_path) / f"tiktok_{video_id}_{uuid.uuid4().hex[:8]}.mp4"
                return self._download_file(video_direct_url, file_path, max_size_mb, cancel_check)

            resolved_url = self.resolve_url(url)
            opts = self.default_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'best'
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved_url, download=False)
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                estimated = self._estimate_size(info)
                if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                    raise FileTooLargeError(
                        f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                    )
                ydl.process_ie_result(info, download=True)
                filename = ydl.prepare_filename(info)
                return self.safe_find_file(filename, Path(filename).stem)
        except (FileTooLargeError, DownloadCancelled):
            raise
        except Exception:
            self.cleanup_partial()
            raise

    def download_audio(self, url: str, format: str = "mp3", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        try:
            info = self.get_info(url)
            audio_direct_url = info.get('audio_url')
            video_id = info.get('id', 'audio')

            if audio_direct_url:
                file_path = Path(self.download_path) / f"tiktok_{video_id}_{uuid.uuid4().hex[:8]}.{format}"
                return self._download_file(audio_direct_url, file_path, max_size_mb, cancel_check)

            resolved_url = self.resolve_url(url)
            opts = self.default_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved_url, download=False)
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
                return str(Path(self.download_path) / f"{base}.{format}")
        except (FileTooLargeError, DownloadCancelled):
            raise
        except Exception:
            self.cleanup_partial()
            raise
