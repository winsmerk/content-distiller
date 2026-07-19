"""Generate a YouTube distillation report, script, storyboard, and Skill."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawl_youtube_video import format_time
from utils.common import safe_filename
from utils.openai_vision import DEFAULT_MODEL, analyze_shots


def load_details(path: Path, explicit_name: str | None = None) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("source") != "youtube":
        raise ValueError("输入文件不是 crawl_youtube_video.py 生成的 YouTube 数据。")
    if explicit_name:
        data["name"] = explicit_name
        data["safe_name"] = safe_filename(explicit_name)
    data["details_path"] = str(path)
    return data


def _phase(index: int, total: int) -> str:
    ratio = index / max(1, total)
    if index == 1:
        return "开场钩子"
    if ratio <= 0.25:
        return "背景/问题铺垫"
    if ratio <= 0.7:
        return "核心内容展开"
    if ratio <= 0.9:
        return "证明/总结"
    return "结尾行动引导"


def build_script_blocks(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for segment in segments:
        current.append(segment)
        text = " ".join(str(item.get("text") or "").strip() for item in current).strip()
        duration = float(current[-1].get("end") or 0) - float(current[0].get("start") or 0)
        sentence_end = bool(re.search(r"[。！？!?]$", text))
        if len(text) >= 150 or duration >= 22 or (len(text) >= 70 and sentence_end):
            blocks.append(
                {
                    "start": float(current[0].get("start") or 0),
                    "end": float(current[-1].get("end") or 0),
                    "text": re.sub(r"\s+", " ", text),
                }
            )
            current = []
    if current:
        blocks.append(
            {
                "start": float(current[0].get("start") or 0),
                "end": float(current[-1].get("end") or 0),
                "text": re.sub(r"\s+", " ", " ".join(str(item.get("text") or "") for item in current)).strip(),
            }
        )
    for index, block in enumerate(blocks, 1):
        block["index"] = index
        block["timecode"] = f"{format_time(block['start'])} - {format_time(block['end'])}"
        block["function"] = _phase(index, len(blocks))
    return blocks


def copy_frames(data: dict[str, Any], output_dir: Path) -> Path:
    target = output_dir / f"{data['safe_name']}_YouTube分镜素材" / "frames"
    if target.parent.exists():
        shutil.rmtree(target.parent)
    target.mkdir(parents=True, exist_ok=True)
    for shot in data.get("shots", []):
        source = Path(shot["frame_path"])
        destination = target / source.name
        shutil.copy2(source, destination)
        shot["report_frame"] = f"{target.parent.name}/frames/{destination.name}"
    return target.parent


def _shot_pattern(data: dict[str, Any]) -> dict[str, Any]:
    shots = data.get("shots", [])
    durations = [float(item.get("duration") or 0) for item in shots if float(item.get("duration") or 0) > 0]
    shot_sizes = Counter(
        str(item.get("visual", {}).get("shot_size") or "未识别") for item in shots
    )
    return {
        "count": len(shots),
        "average_duration": round(sum(durations) / len(durations), 1) if durations else 0,
        "fast_count": sum(1 for value in durations if value <= 3),
        "long_count": sum(1 for value in durations if value >= 10),
        "top_shot_sizes": shot_sizes.most_common(4),
    }


def generate_script_markdown(data: dict[str, Any], blocks: list[dict[str, Any]], output_dir: Path) -> Path:
    transcript = data.get("transcript") or {}
    lines = [
        f"# {data['title']} - YouTube 详细文字版剧本",
        "",
        f"> 来源：{data.get('webpage_url') or ''}",
        f"> 频道：{data.get('channel') or '未知'}",
        f"> 时长：{format_time(float(data.get('duration') or 0))}",
        f"> 文本来源：{transcript.get('source') or 'none'} / {transcript.get('language') or 'unknown'}",
        "",
        "## 分段剧本",
        "",
    ]
    if blocks:
        for block in blocks:
            lines.extend(
                [
                    f"### {block['index']:02d}. {block['function']}｜{block['timecode']}",
                    "",
                    block["text"],
                    "",
                ]
            )
    else:
        lines.extend(["本次未取得可用字幕或口播。", ""])
    lines.extend(["## 连续逐字稿", "", transcript.get("text") or "本次未取得可用逐字稿。", ""])
    path = output_dir / f"{data['safe_name']}_YouTube文字剧本.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate_storyboard_csv(data: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / f"{data['safe_name']}_YouTube分镜表.csv"
    fields = [
        "镜号",
        "时间码",
        "时长秒",
        "关键帧",
        "画面描述",
        "主体",
        "场景",
        "景别",
        "机位与运动",
        "构图",
        "屏幕文字",
        "动作",
        "转场",
        "同期口播",
        "叙事作用",
        "置信度",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for shot in data.get("shots", []):
            visual = shot.get("visual") or {}
            writer.writerow(
                {
                    "镜号": shot["index"],
                    "时间码": shot["timecode"],
                    "时长秒": shot["duration"],
                    "关键帧": shot.get("report_frame") or shot.get("frame_path") or "",
                    "画面描述": visual.get("summary") or "",
                    "主体": visual.get("subjects") or "",
                    "场景": visual.get("scene") or "",
                    "景别": visual.get("shot_size") or "",
                    "机位与运动": visual.get("camera") or "",
                    "构图": visual.get("composition") or "",
                    "屏幕文字": visual.get("on_screen_text") or "",
                    "动作": visual.get("action") or "",
                    "转场": visual.get("transition") or "",
                    "同期口播": shot.get("transcript") or "",
                    "叙事作用": visual.get("purpose") or "",
                    "置信度": visual.get("confidence") or "",
                }
            )
    return path


def generate_task(data: dict[str, Any], blocks: list[dict[str, Any]], output_dir: Path) -> Path:
    process_dir = output_dir / "_过程文件" / "原始素材"
    process_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# YouTube 视频 AI 蒸馏任务 - {data['name']}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d')}",
        f"> 视频：{data.get('webpage_url') or ''}",
        f"> 频道：{data.get('channel') or '未知'}",
        f"> 时长：{format_time(float(data.get('duration') or 0))}",
        "",
        "## 文字剧本",
        "",
    ]
    for block in blocks:
        lines.append(f"- [{block['timecode']}] {block['function']}：{block['text']}")
    lines.extend(["", "## 分镜摘要", ""])
    for shot in data.get("shots", []):
        visual = shot.get("visual") or {}
        lines.extend(
            [
                f"### 镜头 {shot['index']:02d}｜{shot['timecode']}",
                f"- 画面：{visual.get('summary') or ''}",
                f"- 景别/机位：{visual.get('shot_size') or ''} / {visual.get('camera') or ''}",
                f"- 屏幕文字：{visual.get('on_screen_text') or ''}",
                f"- 同期口播：{shot.get('transcript') or '无'}",
                f"- 叙事作用：{visual.get('purpose') or ''}",
                "",
            ]
        )
    path = process_dir / f"{data['safe_name']}_YouTube视频AI蒸馏任务.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _e(value: Any) -> str:
    return html.escape(str(value or ""))


def generate_html(
    data: dict[str, Any],
    blocks: list[dict[str, Any]],
    pattern: dict[str, Any],
    output_dir: Path,
) -> Path:
    transcript = data.get("transcript") or {}
    script_html = "".join(
        f"<article class='script-row'><div class='time'>{_e(block['timecode'])}</div>"
        f"<div><b>{_e(block['function'])}</b><p>{_e(block['text'])}</p></div></article>"
        for block in blocks
    ) or "<p>本次未取得可用字幕或口播。</p>"
    shots_html = "".join(
        (
            f"<article class='shot'><div class='frame'><img src='{_e(shot.get('report_frame'))}' "
            f"alt='镜头 {shot['index']}' loading='lazy'><span>{_e(shot['timecode'])}</span></div>"
            f"<div class='shot-copy'><div class='shot-head'><b>镜头 {shot['index']:02d}</b>"
            f"<span>{_e(shot.get('visual', {}).get('shot_size'))}</span></div>"
            f"<p class='summary'>{_e(shot.get('visual', {}).get('summary'))}</p>"
            f"<dl><dt>场景与主体</dt><dd>{_e(shot.get('visual', {}).get('scene'))}；{_e(shot.get('visual', {}).get('subjects'))}</dd>"
            f"<dt>机位与构图</dt><dd>{_e(shot.get('visual', {}).get('camera'))}；{_e(shot.get('visual', {}).get('composition'))}</dd>"
            f"<dt>屏幕文字</dt><dd>{_e(shot.get('visual', {}).get('on_screen_text'))}</dd>"
            f"<dt>动作与转场</dt><dd>{_e(shot.get('visual', {}).get('action'))}；{_e(shot.get('visual', {}).get('transition'))}</dd>"
            f"<dt>同期口播</dt><dd>{_e(shot.get('transcript') or '无')}</dd>"
            f"<dt>叙事作用</dt><dd>{_e(shot.get('visual', {}).get('purpose'))}</dd></dl></div></article>"
        )
        for shot in data.get("shots", [])
    )
    source_url = _e(data.get("webpage_url"))
    vision = data.get("vision_analysis") or {}
    vision_note = (
        f"视觉模型：{vision.get('model')}（{vision.get('status')}）"
        if vision.get("enabled")
        else "未配置视觉模型：关键帧已保留，语义描述为基础版"
    )
    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(data['title'])}｜YouTube 视频蒸馏报告</title>
<style>
:root{{--paper:#f5f4ef;--ink:#171918;--muted:#65706b;--line:#c9ceca;--red:#b33a2b;--teal:#176c69;--dark:#1f2927;--white:#fff;--sans:Inter,"PingFang SC","Microsoft YaHei",sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.65}}a{{color:inherit}}header{{background:var(--dark);color:var(--white);padding:52px max(24px,calc((100vw - 1180px)/2)) 44px;border-bottom:8px solid var(--red)}}header .kicker,.eyebrow{{font:12px var(--mono);letter-spacing:0;color:#9fc5bd;text-transform:uppercase}}h1{{max-width:920px;font-size:58px;line-height:1.08;margin:12px 0 18px;letter-spacing:0}}header p{{max-width:850px;color:#d3ded9}}nav{{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);display:flex;gap:22px;overflow:auto;padding:10px max(20px,calc((100vw - 1180px)/2));white-space:nowrap}}nav a{{font-size:13px;text-decoration:none}}main{{max-width:1180px;margin:auto;padding:0 24px 80px}}section{{padding:58px 0;border-bottom:1px solid var(--line)}}h2{{font-size:29px;line-height:1.2;margin:8px 0 24px;letter-spacing:0}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--ink);border-left:1px solid var(--ink)}}.metric{{padding:18px;border-right:1px solid var(--ink);border-bottom:1px solid var(--ink)}}.metric small{{display:block;color:var(--muted)}}.metric strong{{font:700 23px var(--mono)}}.notice{{margin-top:22px;padding:14px 0;border-top:3px solid var(--teal);color:var(--muted)}}.script-row{{display:grid;grid-template-columns:150px 1fr;gap:26px;padding:18px 0;border-top:1px solid var(--line)}}.time{{font:13px var(--mono);color:var(--teal)}}.script-row p{{margin:5px 0}}.shot{{display:grid;grid-template-columns:minmax(280px,42%) 1fr;gap:30px;padding:30px 0;border-top:1px solid var(--ink)}}.frame{{position:relative;background:#111;aspect-ratio:16/9;overflow:hidden}}.frame img{{width:100%;height:100%;object-fit:contain;display:block}}.frame span{{position:absolute;left:0;bottom:0;background:#111;color:#fff;padding:5px 9px;font:12px var(--mono)}}.shot-head{{display:flex;justify-content:space-between;gap:16px;border-bottom:3px solid var(--red);padding-bottom:8px}}.shot-head span{{color:var(--muted)}}.summary{{font-size:17px;font-weight:650}}dl{{display:grid;grid-template-columns:100px 1fr;margin:0}}dt,dd{{padding:7px 0;border-top:1px solid var(--line);margin:0}}dt{{font-size:12px;color:var(--muted)}}.transcript{{white-space:pre-wrap;background:#fff;padding:24px;border-left:5px solid var(--teal);max-height:520px;overflow:auto}}.formula{{background:var(--red);color:#fff;padding:34px;margin:0 -24px}}.formula ol{{columns:2;column-gap:50px}}footer{{max-width:1180px;margin:auto;padding:28px 24px 50px;color:var(--muted);font-size:13px}}@media(max-width:760px){{.metrics{{grid-template-columns:1fr 1fr}}.script-row,.shot{{grid-template-columns:1fr;gap:10px}}.formula ol{{columns:1}}h1{{font-size:34px}}}}
</style></head><body>
<header><div class="kicker">YouTube Video Distillation</div><h1>{_e(data['title'])}</h1><p>把在线视频拆成可检索的逐字稿、叙事段落和逐镜头画面表，保留时间码与关键帧，便于复盘、改编和二次创作。</p><p><a href="{source_url}">查看原视频</a> · {_e(data.get('channel') or '未知频道')} · {format_time(float(data.get('duration') or 0))}</p></header>
<nav><a href="#overview">总览</a><a href="#script">文字剧本</a><a href="#storyboard">分镜表</a><a href="#transcript">连续逐字稿</a><a href="#formula">复刻指南</a></nav><main>
<section id="overview"><div class="eyebrow">01 / Overview</div><h2>视频结构总览</h2><div class="metrics">
<div class="metric"><small>播放</small><strong>{int(data.get('view_count') or 0):,}</strong></div><div class="metric"><small>点赞</small><strong>{int(data.get('like_count') or 0):,}</strong></div><div class="metric"><small>镜头节点</small><strong>{pattern['count']}</strong></div><div class="metric"><small>平均镜长</small><strong>{pattern['average_duration']}s</strong></div><div class="metric"><small>逐字稿</small><strong>{int(transcript.get('word_count') or 0):,}字</strong></div></div>
<p class="notice">文本来源：{_e(transcript.get('source'))} / {_e(transcript.get('language'))}。{_e(vision_note)}。关键帧由镜头变化检测与定时采样共同选取，时间段代表分析节点而非严格影视剪辑点。</p></section>
<section id="script"><div class="eyebrow">02 / Script</div><h2>详细文字版剧本</h2>{script_html}</section>
<section id="storyboard"><div class="eyebrow">03 / Storyboard</div><h2>逐镜头分镜表</h2>{shots_html}</section>
<section id="transcript"><div class="eyebrow">04 / Transcript</div><h2>连续逐字稿</h2><div class="transcript">{_e(transcript.get('text') or '本次未取得可用逐字稿。')}</div></section>
<section id="formula" class="formula"><div class="eyebrow">05 / Creation Guide</div><h2>下一条视频的复刻顺序</h2><ol><li>先用一句结果承诺或冲突问题建立开场。</li><li>在 15 秒内交代观众、问题和观看收益。</li><li>每个观点都配一个画面证据、操作演示或案例。</li><li>口播进入新信息块时同步换景、推近或切屏。</li><li>屏幕字幕只保留当前句的关键词和数字。</li><li>结尾收束成一条可执行动作，再给明确 CTA。</li></ol></section>
</main><footer>生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据只用于内容研究与获得授权的创作分析 · <a href="{source_url}">原视频来源</a></footer></body></html>"""
    path = output_dir / f"{data['safe_name']}_YouTube视频蒸馏报告.html"
    path.write_text(html_doc, encoding="utf-8")
    return path


def generate_skill(data: dict[str, Any], pattern: dict[str, Any], output_dir: Path) -> Path:
    skill_dir = output_dir / f"{data['safe_name']}_YouTube创作指南.skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    video_id = re.sub(r"[^a-z0-9-]+", "-", str(data.get("video_id") or "video").lower()).strip("-") or "video"
    top_sizes = " / ".join(f"{name}×{count}" for name, count in pattern["top_shot_sizes"])
    skill = f"""---
name: youtube-video-creation-guide-{video_id}
description: >
  基于 YouTube 视频《{data['title']}》的逐字稿和关键帧分镜蒸馏出的创作指南。
  当用户要复刻同类视频、写口播脚本、设计分镜、规划 B-roll、优化开场或剪辑节奏时使用。
---

# {data['name']} YouTube 创作指南

## 使用边界

- 这是单条视频样本，只复用结构、表达方法和镜头组织，不推断频道长期策略。
- 不照搬原文、独特案例、人物身份或受版权保护的具体表达。
- 输出新内容时保留方法，替换主题、论据、案例、措辞和视觉素材。

## 原片节奏指纹

- 时长：{format_time(float(data.get('duration') or 0))}
- 分镜节点：{pattern['count']} 个
- 平均镜长：{pattern['average_duration']} 秒
- 3 秒内快镜头：{pattern['fast_count']} 个
- 10 秒以上长镜头：{pattern['long_count']} 个
- 常见景别：{top_sizes or '视觉模型未识别'}

## 生成工作流

1. 先询问主题、目标观众、视频时长、发布平台和期望行动。
2. 给出一句核心承诺，确保观众能判断“看完得到什么”。
3. 把脚本拆成：开场钩子、问题铺垫、核心展开、证明总结、行动引导。
4. 为每个脚本段落配置画面主体、场景、景别、机位、屏幕文字、动作、转场和 B-roll。
5. 输出逐字口播稿，再输出带时间码的分镜表。
6. 最后检查版权替换、信息真实性、镜头可拍性和节奏密度。

## 标准输出

### A. 文字剧本

按时间码输出，每段包含“叙事功能 + 完整口播 + 预计时长”。开头 5-10 秒必须出现问题、冲突或结果承诺。

### B. 分镜表

| 镜号 | 时间码 | 画面主体 | 景别/机位 | 动作 | 屏幕文字 | 同期口播 | 转场 | 叙事作用 |
|------|--------|----------|-----------|------|----------|----------|------|----------|

### C. 剪辑说明

- 观点首次出现时，优先让画面直接证明观点。
- 连续口播超过 8-12 秒时，用 B-roll、切屏、推近或关键词字幕制造视觉变化。
- 屏幕文字不重复整段口播，只保留关键词、步骤、数字和结论。
- 转场由语义变化驱动，不为炫技增加无意义效果。

## 自检清单

- 标题、开场和结尾是否围绕同一个承诺。
- 每个关键观点是否有对应画面，而不是全程单人口播。
- 分镜是否能由现有场地、人物和素材真正拍出来。
- 时间码相加是否接近目标总时长。
- 是否替换了原视频的独特措辞、案例和视觉资产。
- CTA 是否具体到评论关键词、下载清单、订阅系列或执行一步。
"""
    path = skill_dir / "SKILL.md"
    path.write_text(skill, encoding="utf-8")
    return path


def generate(
    details_path: Path,
    output_dir: Path,
    name: str | None = None,
    openai_key: str | None = None,
    vision_model: str = DEFAULT_MODEL,
    vision: bool = True,
    vision_batch_size: int = 6,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = load_details(details_path, explicit_name=name)
    copy_frames(data, output_dir)
    if vision:
        shots, vision_meta = analyze_shots(
            data.get("shots", []),
            api_key=openai_key,
            model=vision_model,
            batch_size=vision_batch_size,
        )
    else:
        shots, vision_meta = analyze_shots(data.get("shots", []), disabled=True)
    data["shots"] = shots
    data["vision_analysis"] = vision_meta

    blocks = build_script_blocks((data.get("transcript") or {}).get("segments") or [])
    pattern = _shot_pattern(data)
    script_path = generate_script_markdown(data, blocks, output_dir)
    csv_path = generate_storyboard_csv(data, output_dir)
    task_path = generate_task(data, blocks, output_dir)
    html_path = generate_html(data, blocks, pattern, output_dir)
    skill_path = generate_skill(data, pattern, output_dir)
    analysis_path = output_dir / f"{data['safe_name']}_YouTube分析数据.json"
    analysis_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "html_path": str(html_path),
        "script_path": str(script_path),
        "storyboard_path": str(csv_path),
        "skill_path": str(skill_path),
        "task_path": str(task_path),
        "analysis_path": str(analysis_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 YouTube 数据生成蒸馏报告、文字剧本、分镜表和 Skill")
    parser.add_argument("details_path", help="*_youtube_details.json")
    parser.add_argument("-o", "--output-dir", default="./output", help="产物目录")
    parser.add_argument("--name", help="自定义产物名称")
    parser.add_argument("--openai-key", help="OpenAI API Key，也可使用 OPENAI_API_KEY")
    parser.add_argument("--vision-model", default=DEFAULT_MODEL, help="关键帧视觉分析模型")
    parser.add_argument("--no-vision", action="store_true", help="不调用视觉模型")
    parser.add_argument("--vision-batch-size", type=int, default=6, help="每次视觉分析的关键帧数")
    args = parser.parse_args()
    results = generate(
        Path(args.details_path),
        Path(args.output_dir),
        name=args.name,
        openai_key=args.openai_key,
        vision_model=args.vision_model,
        vision=not args.no_vision,
        vision_batch_size=args.vision_batch_size,
    )
    for label, path in results.items():
        print(f"  {label}: {path}")


if __name__ == "__main__":
    main()
