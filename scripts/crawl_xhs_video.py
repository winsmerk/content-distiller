"""
Phase 1-XHS-Video: fetch one Xiaohongshu note/video by share link.

This module turns a public XHS share URL into the same internal
`notes_details.json` shape used by blogger crawling, so downstream analyzers can
reuse comments, transcript, and privacy handling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_xhs import _extract_supplement_entry, fetch_comments_batch
from utils.common import safe_filename
from utils.privacy import PRIVACY_VERSION, anonymize_note_comments_inplace
from utils.tikhub_client import BROWSER_UA, TikHubClient, TikHubError


def extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s)\]）】>]+", text or "")
    return match.group(0).strip() if match else text.strip()


def resolve_share_url(url_or_text: str, timeout: int = 20) -> tuple[str, str]:
    """Return (original_url, resolved_url). Non-URL text is returned as-is."""
    original = extract_first_url(url_or_text)
    if not original.startswith("http"):
        return original, original

    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        req = urllib.request.Request(original, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return original, resp.geturl() or original
    except Exception as exc:
        print(f"  ⚠️ 短链解析失败，尝试直接解析原始链接: {exc}")
        return original, original


def parse_note_id_and_xsec(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)

    note_id = ""
    for key in ("note_id", "noteId", "item_id", "id"):
        if query.get(key):
            note_id = query[key][0]
            break

    if not note_id:
        patterns = [
            r"/explore/([A-Za-z0-9]+)",
            r"/discovery/item/([A-Za-z0-9]+)",
            r"/items/([A-Za-z0-9]+)",
            r"/note/([A-Za-z0-9]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, parsed.path)
            if match:
                note_id = match.group(1)
                break

    xsec_token = ""
    for key in ("xsec_token", "xsecToken"):
        if query.get(key):
            xsec_token = query[key][0]
            break

    return note_id, xsec_token


def _pick_video_url(note_obj: dict) -> str:
    video_url = note_obj.get("videoUrl") or note_obj.get("video_url") or ""
    if video_url:
        return video_url

    video = note_obj.get("video", {}) or {}
    media = video.get("media", {}) or {}
    stream = media.get("stream", {}) or video.get("stream", {}) or {}
    for codec in ("h264", "h265", "av1"):
        items = stream.get(codec) or []
        if isinstance(items, list) and items:
            backups = items[0].get("backupUrls") or items[0].get("backup_urls") or []
            backup_url = backups[0] if isinstance(backups, list) and backups else ""
            url = items[0].get("masterUrl") or items[0].get("master_url") or backup_url
            if url:
                return url
    return ""


def transcribe_entry(entry: dict, max_duration: int = 600) -> bool:
    from utils.transcript import _get_video_duration, get_whisper_model, transcribe_from_url

    note_obj = entry.get("note", {})
    video_url = _pick_video_url(note_obj)
    if not video_url:
        entry["_transcript_error"] = "video_url_missing"
        print("  ⚠️ 未拿到视频 URL，跳过口播转写")
        return False

    model = get_whisper_model()
    if model is None:
        entry["_transcript_error"] = "whisper_unavailable"
        print("  ⚠️ Whisper 模型不可用，跳过口播转写")
        return False

    duration = _get_video_duration(video_url)
    if duration is not None and duration > max_duration:
        entry["_transcript_error"] = "duration_exceeded"
        print(f"  ⏭ 视频时长约 {int(duration // 60)} 分钟，超过 {max_duration // 60} 分钟上限")
        return False

    print("  🎙 正在提取视频口播...", end="", flush=True)
    t0 = time.time()
    result = transcribe_from_url(video_url, model=model)
    if not result:
        entry["_transcript_error"] = "transcribe_failed"
        print(" ⚠️ 失败")
        return False
    entry["transcript"] = result
    print(f" ✅ ({round(time.time() - t0, 1)}s, {result['word_count']}字)")
    return True


def note_title(note_obj: dict, fallback: str = "小红书视频") -> str:
    return (
        note_obj.get("title")
        or note_obj.get("displayTitle")
        or note_obj.get("display_title")
        or fallback
    ).strip()


def crawl_xhs_video(
    url_or_text: str,
    output_dir: str = "./data",
    token: str | None = None,
    name: str | None = None,
    transcript: bool = True,
    max_comments: int = 30,
    note_id: str | None = None,
    xsec_token: str | None = None,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    print("\n🔗 解析小红书视频链接")
    original_url, resolved_url = resolve_share_url(url_or_text)
    parsed_note_id, parsed_xsec = parse_note_id_and_xsec(resolved_url)
    note_id = note_id or parsed_note_id
    xsec_token = xsec_token or parsed_xsec

    if not note_id:
        raise TikHubError(
            "无法从链接中解析 note_id。请传入原始小红书笔记链接，或使用 --note-id 手动指定。"
        )

    print(f"  原始链接: {original_url}")
    if resolved_url != original_url:
        print(f"  跳转后: {resolved_url}")
    print(f"  Note ID: {note_id}")

    client = TikHubClient(token=token, platform="xhs")

    print("\n📖 获取单条视频详情...")
    raw = client.fetch_note_detail(
        note_id,
        xsec_token=xsec_token or "",
        share_text=resolved_url if resolved_url.startswith("http") else original_url,
        note_type="video",
    )
    entry = _extract_supplement_entry(raw, note_id)
    if not entry:
        raise TikHubError("详情端点未返回可解析的笔记内容")

    note_obj = entry.get("note", {})
    title = note_title(note_obj, fallback=note_id)
    safe_name = safe_filename(name or title or note_id)
    entry["_meta"] = {
        **entry.get("_meta", {}),
        "source": "single_xhs_video",
        "original_url": original_url,
        "resolved_url": resolved_url,
        "note_type": note_obj.get("type") or "video",
        "source_endpoint": raw.get("_endpoint_used", ""),
        "source_group": raw.get("_endpoint_group", ""),
        "xsec_token": xsec_token or "",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    entry["_feed_id"] = note_id

    interact = note_obj.get("interactInfo") or note_obj.get("interact_info") or {}
    print(
        "  ✅ 标题: "
        f"{title[:60]} | 赞 {interact.get('likedCount') or interact.get('liked_count') or 0} "
        f"藏 {interact.get('collectedCount') or interact.get('collected_count') or 0} "
        f"评 {interact.get('commentCount') or interact.get('comment_count') or 0}"
    )

    details = [entry]
    details, comments_fetched = fetch_comments_batch(
        details,
        client,
        max_comments_per_note=max_comments,
        top_n_notes=1,
    )

    transcript_ok = False
    if transcript:
        transcript_ok = transcribe_entry(details[0])
    else:
        print("  ⏭ 已按参数跳过口播转写")

    anonymize_note_comments_inplace(details[0])
    details[0].setdefault("_meta", {})["privacy_version"] = PRIVACY_VERSION

    details_path = os.path.join(output_dir, f"{safe_name}_video_details.json")
    with open(details_path, "w", encoding="utf-8") as f:
        json.dump(details, f, ensure_ascii=False, indent=2)

    meta_path = os.path.join(output_dir, f"{safe_name}_video_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "name": name or title,
                "title": title,
                "note_id": note_id,
                "original_url": original_url,
                "resolved_url": resolved_url,
                "comments_fetched": comments_fetched,
                "transcript_ok": transcript_ok,
                "details_path": details_path,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\n💾 视频详情: {details_path}")
    return {
        "name": name or title,
        "title": title,
        "note_id": note_id,
        "details_path": details_path,
        "meta_path": meta_path,
        "transcript_ok": transcript_ok,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书单条视频链接采集")
    parser.add_argument("link", nargs="+", help="小红书视频分享链接或整段分享文案")
    parser.add_argument("-o", "--output-dir", default="./data", help="数据输出目录")
    parser.add_argument("--token", help="TikHub API Token")
    parser.add_argument("--name", help="输出文件名使用的自定义名称")
    parser.add_argument("--note-id", help="无法解析短链时手动指定 note_id")
    parser.add_argument("--xsec-token", help="手动指定 xsec_token")
    parser.add_argument("--max-comments", type=int, default=30, help="最多采集评论数")
    parser.add_argument("--no-transcript", action="store_true", help="跳过视频口播转写")
    args = parser.parse_args()

    crawl_xhs_video(
        " ".join(args.link),
        output_dir=args.output_dir,
        token=args.token,
        name=args.name,
        transcript=not args.no_transcript,
        max_comments=args.max_comments,
        note_id=args.note_id,
        xsec_token=args.xsec_token,
    )


if __name__ == "__main__":
    main()
