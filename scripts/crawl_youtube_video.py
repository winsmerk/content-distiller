"""Download and preprocess one YouTube video for content distillation."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.common import safe_filename
from utils.transcript import get_whisper_model


YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt"}
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4a"}


class YouTubeDistillError(RuntimeError):
    """A user-facing YouTube preprocessing error."""


def ensure_youtube_url(url: str) -> str:
    from urllib.parse import urlparse

    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in YOUTUBE_HOSTS:
        raise YouTubeDistillError("请输入单条 YouTube 视频链接（youtube.com 或 youtu.be）。")
    return value


def require_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:
        raise YouTubeDistillError(
            f"当前 Python 环境缺少 yt-dlp。请运行：{sys.executable} -m pip install -U yt-dlp"
        ) from exc
    return yt_dlp


def require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise YouTubeDistillError("YouTube 画面分析需要 ffmpeg 和 ffprobe，请先安装 ffmpeg。")
    return ffmpeg, ffprobe


def format_time(seconds: float) -> str:
    value = max(0, int(round(seconds or 0)))
    hours, rem = divmod(value, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _pick_subtitle(info: dict[str, Any], preferred: list[str]) -> tuple[str, str]:
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    for lang in preferred:
        for source_name, source in (("manual", manual), ("automatic", automatic)):
            if lang in source:
                return source_name, lang
    for source_name, source in (("manual", manual), ("automatic", automatic)):
        for lang in source:
            if lang != "live_chat":
                return source_name, lang
    return "", ""


def _find_downloaded_file(directory: Path, extensions: set[str]) -> Path | None:
    matches = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in extensions]
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def download_youtube(
    url: str,
    assets_dir: Path,
    preferred_languages: list[str],
    cookies_from_browser: str | None = None,
    max_duration: int = 3600,
    download_subtitles: bool = True,
) -> tuple[dict[str, Any], Path, Path | None, str, str]:
    yt_dlp = require_yt_dlp()
    assets_dir.mkdir(parents=True, exist_ok=True)

    base_opts: dict[str, Any] = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_from_browser:
        base_opts["cookiesfrombrowser"] = (cookies_from_browser,)

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeDistillError(
            "YouTube 无法读取该视频。请确认链接公开可用；如视频需要登录，可增加 "
            "--cookies-from-browser chrome。"
        ) from exc

    if info.get("_type") in {"playlist", "multi_video"}:
        raise YouTubeDistillError("当前只支持单条 YouTube 视频，不支持播放列表。")
    duration = int(float(info.get("duration") or 0))
    if duration and duration > max_duration:
        raise YouTubeDistillError(
            f"视频时长 {format_time(duration)}，超过当前 {format_time(max_duration)} 的分析上限。"
        )

    subtitle_source, subtitle_language = _pick_subtitle(info, preferred_languages) if download_subtitles else ("", "")
    outtmpl = str(assets_dir / "source.%(ext)s")
    opts: dict[str, Any] = {
        **base_opts,
        "quiet": False,
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "overwrites": True,
    }
    if subtitle_language:
        opts.update(
            {
                "writesubtitles": subtitle_source == "manual",
                "writeautomaticsub": subtitle_source == "automatic",
                "subtitleslangs": [subtitle_language],
                "subtitlesformat": "vtt/best",
            }
        )

    print("  下载视频与元数据...")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            downloaded = ydl.extract_info(url, download=True)
            downloaded = ydl.sanitize_info(downloaded)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeDistillError(
            "YouTube 视频下载失败。可更新 yt-dlp，或对需要登录的视频增加 "
            "--cookies-from-browser chrome。"
        ) from exc

    video_path = _find_downloaded_file(assets_dir, MEDIA_EXTENSIONS)
    if not video_path:
        raise YouTubeDistillError("yt-dlp 已运行，但没有找到下载后的视频文件。")
    subtitle_path = _find_downloaded_file(assets_dir, SUBTITLE_EXTENSIONS)
    return downloaded, video_path, subtitle_path, subtitle_source, subtitle_language


def _timestamp_seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return int(parts[0]) * 60 + float(parts[1])
    except (ValueError, IndexError):
        return 0.0


def _clean_caption(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_subtitle(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    lines = raw.splitlines()
    timing_re = re.compile(
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s+-->\s+"
        r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})"
    )
    segments: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        match = timing_re.search(lines[i])
        if not match:
            i += 1
            continue
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip():
            body.append(lines[i])
            i += 1
        text = _clean_caption(" ".join(body))
        if text:
            item = {
                "start": round(_timestamp_seconds(match.group("start")), 3),
                "end": round(_timestamp_seconds(match.group("end")), 3),
                "text": text,
            }
            if segments and segments[-1]["text"] == text:
                segments[-1]["end"] = item["end"]
            else:
                segments.append(item)
        i += 1
    return segments


def transcript_text(segments: list[dict[str, Any]]) -> str:
    pieces: list[str] = []
    previous = ""
    for segment in segments:
        current = str(segment.get("text") or "").strip()
        if not current:
            continue
        if current == previous:
            continue
        if previous and current.startswith(previous):
            suffix = current[len(previous) :].strip()
            if suffix:
                pieces.append(suffix)
        elif previous and previous.endswith(current):
            pass
        else:
            pieces.append(current)
        previous = current
    return re.sub(r"\s+", " ", " ".join(pieces)).strip()


def whisper_transcribe(video_path: Path, model_name: str | None = None) -> dict[str, Any] | None:
    model = get_whisper_model(model_name)
    if model is None:
        print("  警告：视频没有可用字幕，且当前环境无法加载 Whisper，文字剧本将为空。")
        return None
    try:
        import whisper

        print("  YouTube 无可用字幕，正在使用 Whisper 转写...")
        audio = whisper.load_audio(str(video_path))
        result = model.transcribe(audio, task="transcribe", condition_on_previous_text=False)
        segments = [
            {
                "start": round(float(item.get("start") or 0), 3),
                "end": round(float(item.get("end") or 0), 3),
                "text": str(item.get("text") or "").strip(),
            }
            for item in result.get("segments", [])
            if str(item.get("text") or "").strip()
        ]
        text = str(result.get("text") or transcript_text(segments)).strip()
        return {
            "source": "whisper",
            "language": result.get("language") or "unknown",
            "text": text,
            "word_count": len(text),
            "segments": segments,
        }
    except Exception as exc:
        print(f"  警告：Whisper 转写失败：{exc}")
        return None


def detect_scene_times(video_path: Path, ffmpeg: str, threshold: float) -> list[float]:
    vf = f"select=gt(scene\\,{threshold}),showinfo"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(video_path), "-vf", vf, "-an", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    values = [float(v) for v in re.findall(r"pts_time:([0-9.]+)", result.stderr)]
    return sorted(set(round(value, 3) for value in values))


def choose_frame_times(duration: float, scene_times: list[float], max_shots: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    interval = max(8.0, duration / max(1, max_shots - 1))
    regular = [i * interval for i in range(int(duration // interval) + 1)]
    candidates = sorted({0.0, *scene_times, *regular, max(0.0, duration - 0.1)})

    filtered: list[float] = []
    for value in candidates:
        if not filtered or value - filtered[-1] >= 1.25:
            filtered.append(value)
    if len(filtered) <= max_shots:
        return filtered
    indexes = {round(i * (len(filtered) - 1) / (max_shots - 1)) for i in range(max_shots)}
    return [filtered[i] for i in sorted(indexes)]


def extract_frames(
    video_path: Path,
    frames_dir: Path,
    ffmpeg: str,
    times: list[float],
) -> list[dict[str, Any]]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, timestamp in enumerate(times, 1):
        filename = f"frame_{index:04d}.jpg"
        path = frames_dir / filename
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(960,iw)':-2",
                "-q:v",
                "3",
                "-y",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and path.exists():
            frames.append({"index": len(frames) + 1, "time": round(timestamp, 3), "path": str(path)})
    return frames


def align_shots(
    frames: list[dict[str, Any]],
    duration: float,
    transcript_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for i, frame in enumerate(frames):
        start = float(frame["time"])
        end = float(frames[i + 1]["time"]) if i + 1 < len(frames) else float(duration)
        overlapping = [
            seg for seg in transcript_segments
            if float(seg.get("end") or 0) > start and float(seg.get("start") or 0) < end
        ]
        speech = transcript_text(overlapping)
        shots.append(
            {
                "index": i + 1,
                "start": round(start, 3),
                "end": round(max(start, end), 3),
                "duration": round(max(0.0, end - start), 3),
                "timecode": f"{format_time(start)} - {format_time(end)}",
                "frame_path": frame["path"],
                "transcript": speech,
            }
        )
    return shots


def crawl_youtube_video(
    url: str,
    output_dir: str = "./data",
    name: str | None = None,
    preferred_languages: list[str] | None = None,
    max_duration: int = 3600,
    max_shots: int = 48,
    scene_threshold: float = 0.32,
    transcript: bool = True,
    whisper_model: str | None = None,
    cookies_from_browser: str | None = None,
    keep_video: bool = False,
) -> dict[str, Any]:
    url = ensure_youtube_url(url)
    ffmpeg, _ = require_ffmpeg()
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    preferred = preferred_languages or ["zh-Hans", "zh-CN", "zh", "zh-Hant", "en", "en-US"]

    print("\nYouTube 视频采集", flush=True)
    print(f"  链接: {url}")
    staging_dir = root / "_youtube_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    info, video_path, subtitle_path, subtitle_source, subtitle_language = download_youtube(
        url,
        staging_dir,
        preferred,
        cookies_from_browser=cookies_from_browser,
        max_duration=max_duration,
        download_subtitles=transcript,
    )

    title = str(info.get("title") or info.get("id") or "YouTube视频")
    safe_name = safe_filename(name or title)
    assets_dir = root / f"{safe_name}_youtube_assets"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    staging_dir.replace(assets_dir)
    video_path = assets_dir / video_path.name
    subtitle_path = assets_dir / subtitle_path.name if subtitle_path else None

    duration = float(info.get("duration") or 0)
    transcript_data: dict[str, Any] | None = None
    if transcript and subtitle_path:
        segments = parse_subtitle(subtitle_path)
        text = transcript_text(segments)
        transcript_data = {
            "source": f"youtube_{subtitle_source}_subtitle",
            "language": subtitle_language or "unknown",
            "text": text,
            "word_count": len(text),
            "segments": segments,
        }
        print(f"  字幕: {subtitle_source}/{subtitle_language}，{len(text)} 字")
    elif transcript:
        transcript_data = whisper_transcribe(video_path, whisper_model)
    if transcript_data is None:
        transcript_data = {"source": "none", "language": "unknown", "text": "", "word_count": 0, "segments": []}

    print("  检测镜头变化并提取关键帧...")
    scene_times = detect_scene_times(video_path, ffmpeg, scene_threshold)
    frame_times = choose_frame_times(duration, scene_times, max_shots)
    frames = extract_frames(video_path, assets_dir / "frames", ffmpeg, frame_times)
    shots = align_shots(frames, duration, transcript_data["segments"])
    print(f"  镜头变化点 {len(scene_times)} 个，保留关键帧 {len(frames)} 张")

    details = {
        "source": "youtube",
        "name": name or title,
        "safe_name": safe_name,
        "video_id": info.get("id") or "",
        "title": title,
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "description": info.get("description") or "",
        "webpage_url": info.get("webpage_url") or url,
        "upload_date": info.get("upload_date") or "",
        "duration": duration,
        "view_count": int(info.get("view_count") or 0),
        "like_count": int(info.get("like_count") or 0),
        "comment_count": int(info.get("comment_count") or 0),
        "thumbnail": info.get("thumbnail") or "",
        "transcript": transcript_data,
        "shots": shots,
        "scene_threshold": scene_threshold,
        "assets_dir": str(assets_dir),
        "video_path": str(video_path) if keep_video else "",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    details_path = root / f"{safe_name}_youtube_details.json"
    details_path.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    if not keep_video:
        try:
            video_path.unlink()
        except OSError:
            pass
    print(f"  数据详情: {details_path}")
    return {"details_path": str(details_path), "safe_name": safe_name, "title": title}


def main() -> None:
    parser = argparse.ArgumentParser(description="采集并预处理单条 YouTube 视频")
    parser.add_argument("url", help="YouTube 视频链接")
    parser.add_argument("-o", "--output-dir", default="./data", help="数据目录")
    parser.add_argument("--name", help="自定义产物名称")
    parser.add_argument("--languages", default="zh-Hans,zh-CN,zh,zh-Hant,en,en-US", help="字幕语言优先级")
    parser.add_argument("--max-duration", type=int, default=3600, help="最大视频时长（秒）")
    parser.add_argument("--max-shots", type=int, default=48, help="最多保留关键帧数")
    parser.add_argument("--scene-threshold", type=float, default=0.32, help="镜头变化阈值，0-1")
    parser.add_argument("--no-transcript", action="store_true", help="不提取字幕或口播")
    parser.add_argument("--whisper-model", help="Whisper 模型名")
    parser.add_argument("--cookies-from-browser", help="受限视频使用的浏览器，如 chrome/safari/firefox")
    parser.add_argument("--keep-video", action="store_true", help="分析后保留原视频")
    args = parser.parse_args()
    crawl_youtube_video(
        args.url,
        output_dir=args.output_dir,
        name=args.name,
        preferred_languages=[item.strip() for item in args.languages.split(",") if item.strip()],
        max_duration=args.max_duration,
        max_shots=max(2, args.max_shots),
        scene_threshold=min(1.0, max(0.01, args.scene_threshold)),
        transcript=not args.no_transcript,
        whisper_model=args.whisper_model,
        cookies_from_browser=args.cookies_from_browser,
        keep_video=args.keep_video,
    )


if __name__ == "__main__":
    try:
        main()
    except YouTubeDistillError as exc:
        print(f"\n错误: {exc}")
        sys.exit(1)
