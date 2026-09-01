import json
import logging
import re
import subprocess
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yt_dlp

from downloader.base import BaseDownloader, FileTooLargeError
from utils.download_manager import DownloadCancelled

log = logging.getLogger(__name__)

MAX_RETRIES = 3
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


class SpotifyDownloader(BaseDownloader):
    def _fetch_embed(self, track_id: str) -> dict:
        embed_url = f"https://open.spotify.com/embed/track/{track_id}"
        req = urllib.request.Request(embed_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html, re.DOTALL
        )
        if not match:
            raise Exception("метаданные трека не найдены")
        payload = json.loads(match.group(1))
        return payload['props']['pageProps']['state']['data']

    def _info_from_embed(self, track_id: str) -> dict:
        data = self._fetch_embed(track_id)
        entity = data.get('entity') or {}
        artists = entity.get('artists') or []
        artist = ', '.join(
            a.get('name') for a in artists if a.get('name')
        ) or 'unknown artist'
        title = entity.get('title') or entity.get('name') or 'spotify track'

        thumbnail = None
        images = (entity.get('visualIdentity') or {}).get('image') or []
        for img in sorted(images, key=lambda i: i.get('maxWidth') or 0, reverse=True):
            if img.get('url'):
                thumbnail = img['url']
                break

        duration_ms = entity.get('duration') or 0
        return {
            'title': title,
            'uploader': artist,
            'artist': artist,
            'track_id': track_id,
            'thumbnail': thumbnail,
            'duration': round(duration_ms / 1000) if duration_ms else 0,
            'is_explicit': bool(entity.get('isExplicit')),
        }

    def _info_from_oembed(self, url: str, track_id: str) -> dict:
        oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(oembed_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        title = data.get('title') or 'spotify track'
        artist = 'unknown artist'
        if ' - ' in title:
            artist, title = [part.strip() for part in title.split(' - ', 1)]

        return {
            'title': title,
            'uploader': artist,
            'artist': artist,
            'track_id': track_id,
            'thumbnail': data.get('thumbnail_url'),
            'duration': 0,
            'is_explicit': False,
        }

    def get_info(self, url: str, **kwargs) -> dict:
        match = re.search(r'open\.spotify\.com/track/([A-Za-z0-9]+)', url)
        if not match:
            raise Exception("поддерживаются только ссылки на треки spotify (open.spotify.com/track/...)")
        track_id = match.group(1)
        last_err: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                return self._info_from_embed(track_id)
            except Exception as e:
                last_err = e
                log.warning("spotify embed attempt %d failed: %s", attempt + 1, e)
                try:
                    return self._info_from_oembed(url, track_id)
                except Exception:
                    continue
        raise Exception(f"ошибка получения информации spotify: {last_err}")

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower()
        text = re.sub(r'\(.*?\)|\[.*?\]', ' ', text)
        text = re.sub(r'[^a-z0-9а-яё]+', ' ', text)
        return ' '.join(text.split())

    @classmethod
    def _match_score(cls, entry: dict, artist: str, title: str) -> float:
        result_title = cls._normalize(entry.get('title') or '')
        channel = cls._normalize(entry.get('channel') or entry.get('uploader') or '')
        artist_n = cls._normalize(artist)
        title_n = cls._normalize(title)

        score = 0.0
        if artist_n and artist_n in result_title:
            score += 35
        if title_n and title_n in result_title:
            score += 35
        if artist_n and artist_n in channel:
            score += 20
        score += SequenceMatcher(None, result_title, f"{artist_n} {title_n}").ratio() * 30
        for bad in ('cover', 'karaoke', 'reaction', 'live', 'remix', 'rework'):
            if bad in result_title:
                score -= 15
        return score

    def _search_track(self, info: dict, cancel_check=None) -> dict:
        artist, title = info['artist'], info['title']
        queries = [
            f"{artist} - {title}",
            f"{artist} {title}",
            f"{artist} {title} audio",
            f"{artist} {title} lyrics",
            f"{title} {artist}",
        ]
        best_entry = None
        best_score = 0.0

        with yt_dlp.YoutubeDL({
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls', 'dash'],
                }
            }
        }) as ydl:
            for query in queries:
                if cancel_check and cancel_check():
                    raise DownloadCancelled()
                try:
                    results = ydl.extract_info(f"ytsearch5:{query}", download=False)
                except Exception:
                    continue
                for entry in results.get('entries') or []:
                    if cancel_check and cancel_check():
                        raise DownloadCancelled()
                    score = self._match_score(entry, artist, title)
                    if score > best_score:
                        best_score, best_entry = score, entry
                if best_score >= 75:
                    break

        if not best_entry:
            raise Exception("не удалось найти трек на youtube")
        return best_entry

    def _download_cover(self, url: str, filename: str) -> Path:
        path = Path(self.download_path) / filename
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp, open(path, 'wb') as out:
            out.write(resp.read())
        return path

    def _apply_metadata_and_cover(self, audio_path: Path, info: dict) -> str:
        cover_path = None
        if info.get('thumbnail'):
            try:
                cover_path = self._download_cover(
                    info['thumbnail'], f"spotify_cover_{info['track_id']}.jpg"
                )
            except Exception:
                cover_path = None

        tmp_out = audio_path.with_name(f"{audio_path.stem}_meta{audio_path.suffix}")
        cmd = ['ffmpeg', '-y', '-i', str(audio_path)]
        if cover_path:
            cmd += ['-i', str(cover_path)]
        cmd += ['-map', '0:a']
        if cover_path:
            cmd += ['-map', '1:v']
        cmd += ['-c', 'copy', '-id3v2_version', '3', '-map_metadata', '-1']
        cmd += ['-metadata', f"title={info['title']}"]
        cmd += ['-metadata', f"artist={info['artist']}"]
        cmd += ['-metadata', f"album={info['artist']}"]
        if cover_path:
            cmd += ['-disposition:v', 'attached_pic']
            cmd += ['-metadata:s:v', 'title=Album cover']
            cmd += ['-metadata:s:v', 'comment=Cover (front)']
        cmd += [str(tmp_out)]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logging.warning("ffmpeg metadata failed: %s", result.stderr[:200])
            if result.returncode == 0 and tmp_out.exists():
                audio_path.unlink(missing_ok=True)
                audio_path = tmp_out
        except subprocess.TimeoutExpired:
            logging.warning("ffmpeg metadata timed out")
        except Exception:
            pass

        if cover_path and cover_path.exists():
            cover_path.unlink(missing_ok=True)
        return str(audio_path)

    def download_audio(self, url: str, format: str = "mp3", max_size_mb: int = None,
                       progress_hook=None, cancel_check=None) -> str:
        if cancel_check and cancel_check():
            raise DownloadCancelled()
        try:
            info = self.get_info(url)
            entry = self._search_track(info, cancel_check)

            opts = self.default_opts.copy()
            opts['outtmpl'] = self.make_outtmpl()
            opts['format'] = 'bestaudio/best'
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'skip': ['hls', 'dash'],
                }
            }
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }]
            if progress_hook or cancel_check:
                opts['progress_hooks'] = [self._make_progress_hook(progress_hook, cancel_check)]

            estimated = self._estimate_size(entry)
            if max_size_mb and estimated and estimated > max_size_mb * 1024 * 1024:
                raise FileTooLargeError(
                    f"файл слишком большой: ~{estimated / 1048576:.1f} мб > лимита {max_size_mb} мб"
                )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.process_ie_result(entry, download=True)
                filename = ydl.prepare_filename(entry)
                audio_path = Path(self.download_path) / f"{Path(filename).stem}.{format}"

            if cancel_check and cancel_check():
                raise DownloadCancelled()
            return self._apply_metadata_and_cover(audio_path, info)
        except FileTooLargeError:
            raise
        except DownloadCancelled:
            raise
        except Exception:
            self.cleanup_partial()
            raise
