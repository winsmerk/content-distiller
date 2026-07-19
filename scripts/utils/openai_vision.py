"""Optional OpenAI vision analysis for extracted video keyframes."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4-nano"


SHOT_SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "summary": {"type": "string"},
                    "subjects": {"type": "string"},
                    "scene": {"type": "string"},
                    "shot_size": {"type": "string"},
                    "camera": {"type": "string"},
                    "composition": {"type": "string"},
                    "on_screen_text": {"type": "string"},
                    "action": {"type": "string"},
                    "transition": {"type": "string"},
                    "purpose": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "index",
                    "summary",
                    "subjects",
                    "scene",
                    "shot_size",
                    "camera",
                    "composition",
                    "on_screen_text",
                    "action",
                    "transition",
                    "purpose",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["shots"],
    "additionalProperties": False,
}


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return str(content.get("text") or "")
    return ""


def _fallback_visual(shot: dict[str, Any], reason: str = "") -> dict[str, str]:
    position = int(shot.get("index") or 1)
    purpose = "建立主题与观看预期" if position == 1 else "承接口播信息并维持画面节奏"
    return {
        "summary": "该关键帧记录了此时间点的实际画面，需结合图片和同期口播复核具体主体。",
        "subjects": "未启用视觉语义分析",
        "scene": "见关键帧",
        "shot_size": "待人工确认",
        "camera": "待人工确认",
        "composition": "待人工确认",
        "on_screen_text": "未自动识别",
        "action": "见关键帧",
        "transition": "由相邻关键帧时间差推断剪辑节奏",
        "purpose": purpose,
        "confidence": "low",
        "analysis_note": reason or "未提供 OPENAI_API_KEY",
    }


def _request_batch(
    shots: list[dict[str, Any]],
    api_key: str,
    model: str,
    timeout: int,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "你是视频导演和剪辑分析师。请逐张分析下面按时间顺序排列的关键帧。"
                "每张图只描述肉眼可见事实；不要根据外貌猜测人物身份。"
                "summary 要具体写清人物/物体、环境、动作与画面信息；"
                "shot_size 写景别，camera 写机位/运动迹象，composition 写构图，"
                "on_screen_text 抄录清晰可见的屏幕文字，transition 推断与上一镜头的衔接，"
                "purpose 说明该镜头在脚本中的叙事作用。"
            ),
        }
    ]
    for shot in shots:
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"镜头 index={shot['index']}，时间码={shot['timecode']}，"
                    f"同期口播={shot.get('transcript') or '无'}"
                ),
            }
        )
        content.append({"type": "input_image", "image_url": _data_url(Path(shot["frame_path"])), "detail": "high"})

    body = {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "video_shot_analysis",
                "strict": True,
                "schema": SHOT_SCHEMA,
            }
        },
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    text = _output_text(payload)
    if not text:
        raise RuntimeError("OpenAI API 未返回可解析的 output_text")
    result = json.loads(text)
    return list(result.get("shots") or [])


def analyze_shots(
    shots: list[dict[str, Any]],
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    batch_size: int = 6,
    timeout: int = 120,
    disabled: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if disabled:
        enriched = [{**shot, "visual": _fallback_visual(shot, "视觉分析已关闭")} for shot in shots]
        return enriched, {"enabled": False, "model": "", "status": "disabled"}
    key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        enriched = [{**shot, "visual": _fallback_visual(shot)} for shot in shots]
        return enriched, {"enabled": False, "model": "", "status": "key_missing"}

    enriched: list[dict[str, Any]] = []
    errors: list[str] = []
    size = max(1, min(10, batch_size))
    for offset in range(0, len(shots), size):
        batch = shots[offset : offset + size]
        print(f"  视觉分析 {offset + 1}-{offset + len(batch)}/{len(shots)}...")
        try:
            results = _request_batch(batch, key, model, timeout)
            by_index = {int(item.get("index") or 0): item for item in results}
            for shot in batch:
                visual = by_index.get(int(shot["index"])) or _fallback_visual(shot, "模型未返回该镜头")
                enriched.append({**shot, "visual": visual})
        except Exception as exc:
            message = str(exc)
            errors.append(message)
            for shot in batch:
                enriched.append({**shot, "visual": _fallback_visual(shot, message)})

    status = "ok" if not errors else ("partial" if len(errors) * size < len(shots) else "failed")
    return enriched, {"enabled": True, "model": model, "status": status, "errors": errors}
