"""
Generate final report and Skill from one XHS video details JSON.

Outputs:
  output/{name}_视频蒸馏报告.html
  output/{name}_视频创作指南.skill/SKILL.md
  output/_过程文件/原始素材/{name}_视频AI蒸馏任务.md
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyze import extract_tags
from utils.common import parse_count, safe_filename


def _first_detail(details: list[dict]) -> dict:
    for item in details:
        if "_error" not in item:
            return item
    raise ValueError("details JSON 中没有有效视频数据")


def _note_obj(entry: dict) -> dict:
    return entry.get("note") or entry.get("data", {}).get("note") or entry


def _interact(note: dict) -> dict:
    return note.get("interactInfo") or note.get("interact_info") or {}


def _count(interact: dict, *keys: str) -> int:
    for key in keys:
        if key in interact:
            return parse_count(interact.get(key))
    return 0


def _pick(note: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = note.get(key)
        if value not in (None, "", []):
            return str(value)
    return default


def _comments(entry: dict, limit: int = 10) -> list[dict]:
    comments_obj = entry.get("comments") or {}
    raw = comments_obj.get("list", []) if isinstance(comments_obj, dict) else []
    out = []
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "speaker": c.get("speaker") or c.get("userInfo", {}).get("nickname") or "读者",
                "content": c.get("content", ""),
                "likes": c.get("likeCount") or c.get("like_count") or c.get("liked_count") or 0,
            }
        )
    return out


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*|[\n\r]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 4]


def top_keywords(text: str, tags: list[str], limit: int = 12) -> list[str]:
    words: dict[str, int] = {}
    stop = set("的了是在我你他她它们这那有也都就和与或但而被把让给对从到为以及一个一些这个那个可以就是没有我们你们他们")
    clean = re.sub(r"#[^#\s]+?(?:\[.*?\])?#?", "", text or "")
    for token in re.split(r"[\s，。！？、；：,.!?【】《》（）()\-—/|]+", clean):
        token = token.strip()
        if 2 <= len(token) <= 8 and token not in stop and re.match(r"^[\u4e00-\u9fffA-Za-z0-9]+$", token):
            words[token] = words.get(token, 0) + 1
    for tag in tags:
        words[tag] = words.get(tag, 0) + 3
    return [w for w, _ in sorted(words.items(), key=lambda kv: kv[1], reverse=True)[:limit]]


def title_patterns(title: str) -> list[str]:
    patterns = []
    checks = [
        ("数字承诺", r"\d+|min|分钟|天|步"),
        ("教程型", r"教程|手把手|工作流|攻略|方法|搭建|复盘"),
        ("结果型", r"爆款|效率|变现|涨粉|提升|搞定|搭"),
        ("情绪放大型", r"🔥|🙌|！|绝了|太|狠狠"),
        ("工具组合型", r"\+|➕|×|x|和|与"),
    ]
    for name, regex in checks:
        if re.search(regex, title, re.IGNORECASE):
            patterns.append(name)
    return patterns or ["直给主题型"]


def script_arc(transcript: str, desc: str) -> list[tuple[str, str]]:
    source = transcript or desc
    if not source:
        return [("信息缺口", "未拿到正文或口播，当前只能依据标题、互动和评论做保守拆解。")]
    sentences = split_sentences(source)
    if not sentences:
        return [("核心文本", source[:180])]
    n = len(sentences)
    chunks = [
        ("开头钩子", sentences[: max(1, n // 4)]),
        ("问题铺垫", sentences[max(1, n // 4) : max(2, n // 2)]),
        ("方法展开", sentences[max(2, n // 2) : max(3, n * 3 // 4)]),
        ("收束转化", sentences[max(3, n * 3 // 4) :]),
    ]
    return [(label, " ".join(part)[:260]) for label, part in chunks if part]


def build_analysis(details_path: Path, explicit_name: str | None = None) -> dict:
    details = json.loads(details_path.read_text(encoding="utf-8"))
    entry = _first_detail(details)
    note = _note_obj(entry)
    interact = _interact(note)

    title = _pick(note, "title", "displayTitle", "display_title", default=details_path.stem)
    desc = _pick(note, "desc", default="")
    transcript = (entry.get("transcript") or {}).get("text", "")
    tags = extract_tags(desc)
    comments = _comments(entry)

    likes = _count(interact, "likedCount", "liked_count", "likes")
    collects = _count(interact, "collectedCount", "collected_count", "collects")
    comments_count = _count(interact, "commentCount", "comment_count", "comments")
    shares = _count(interact, "shareCount", "sharedCount", "shared_count", "shares")
    save_ratio = round(collects / likes * 100, 1) if likes else 0
    text_all = "\n".join([title, desc, transcript])
    keywords = top_keywords(text_all, tags)
    patterns = title_patterns(title)
    arc = script_arc(transcript, desc)

    hook = "标题同时给出工具组合、时间成本和结果承诺" if "教程型" in patterns else "标题先抛出明确问题或结果"
    if transcript:
        content_base = "标题 + 正文 + 口播逐字稿 + 评论"
    else:
        content_base = "标题 + 正文 + 评论（未取得口播逐字稿）"

    name = explicit_name or title
    safe_name = safe_filename(name)
    return {
        "name": name,
        "safe_name": safe_name,
        "title": title,
        "desc": desc,
        "transcript": transcript,
        "tags": tags,
        "comments": comments,
        "likes": likes,
        "collects": collects,
        "comments_count": comments_count,
        "shares": shares,
        "save_ratio": save_ratio,
        "keywords": keywords,
        "patterns": patterns,
        "arc": arc,
        "hook": hook,
        "content_base": content_base,
        "note_id": entry.get("_feed_id") or _pick(note, "noteId", "id"),
        "source_url": entry.get("_meta", {}).get("resolved_url") or entry.get("_meta", {}).get("original_url") or "",
        "transcript_words": len(transcript),
        "details_path": str(details_path),
    }


def generate_task(data: dict, output_dir: Path) -> Path:
    process_dir = output_dir / "_过程文件" / "原始素材"
    process_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# 视频 AI 蒸馏任务 — {data['name']}",
        "",
        f"> 本文件由 generate_video_final.py 自动生成 | {today}",
        "> 场景：单条小红书视频深度拆解",
        "> 说明：样本只有 1 条，不输出账号级发布频率、爆款率和长期定位结论。",
        "",
        "## 基础信息",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 视频标题 | {data['title']} |",
        f"| Note ID | {data['note_id']} |",
        f"| 原始链接 | {data['source_url']} |",
        f"| 赞 | {data['likes']:,} |",
        f"| 收藏 | {data['collects']:,} |",
        f"| 评论 | {data['comments_count']:,} |",
        f"| 分享 | {data['shares']:,} |",
        f"| 藏赞比 | {data['save_ratio']}% |",
        f"| 口播字数 | {data['transcript_words']} |",
        f"| 数据依据 | {data['content_base']} |",
        "",
        "## 标题与封面承诺",
        "",
        f"- 标题模式：{' / '.join(data['patterns'])}",
        f"- 核心钩子：{data['hook']}",
        f"- 关键词：{' / '.join(data['keywords'])}",
        "",
        "## 正文",
        "",
        data["desc"] or "（未取得正文）",
        "",
        "## 口播结构",
        "",
    ]
    for label, body in data["arc"]:
        lines.append(f"### {label}")
        lines.append(body or "（该段无文本）")
        lines.append("")

    if data["transcript"]:
        lines += [
            "## 口播逐字稿",
            "",
            data["transcript"],
            "",
        ]

    lines += ["## 热评样本", ""]
    if data["comments"]:
        for c in data["comments"][:10]:
            lines.append(f"- {c['speaker']}（{c['likes']}赞）：{c['content']}")
    else:
        lines.append("（未取得评论）")

    lines += [
        "",
        "## 生成要求",
        "",
        f"- 生成 HTML：`{data['safe_name']}_视频蒸馏报告.html`",
        f"- 生成 Skill：`{data['safe_name']}_视频创作指南.skill/SKILL.md`",
        "- 只能基于本文件内的数据推断。",
        "- 必须明确这是单视频分析，不能扩展成博主账号长期结论。",
    ]

    task_path = process_dir / f"{data['safe_name']}_视频AI蒸馏任务.md"
    task_path.write_text("\n".join(lines), encoding="utf-8")
    return task_path


def generate_html(data: dict, output_dir: Path) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    arc_html = "".join(
        f"<div class='rule'><div class='k'>{html.escape(label)}</div><p>{html.escape(body)}</p></div>"
        for label, body in data["arc"]
    )
    comments_html = "".join(
        f"<li><span>{html.escape(str(c['speaker']))}</span>{html.escape(str(c['content']))}</li>"
        for c in data["comments"][:8]
    ) or "<li><span>系统</span>未取得评论样本</li>"
    tags = " ".join(f"#{t}" for t in data["tags"]) or "无标签"
    transcript_note = (
        f"已提取 {data['transcript_words']} 字口播，可分析真实表达节奏。"
        if data["transcript"]
        else "未取得口播，以下表达拆解主要来自标题、正文和评论。"
    )
    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(data['name'])}｜视频蒸馏报告</title>
<style>
:root{{--bg:#d8d3c8;--ink:#181412;--muted:#6f6258;--accent:#9a3f2b;--cream:#fbf6ee;--line:#8a7b6f;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;--serif:Georgia,"Noto Serif SC",serif}}
*{{box-sizing:border-box;border-radius:0;box-shadow:none}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--serif);line-height:1.65}}.bar{{position:sticky;top:0;background:#090706;color:var(--cream);font:13px var(--mono);letter-spacing:.04em;padding:10px 18px;z-index:5;overflow:auto;white-space:nowrap}}main{{max-width:1040px;margin:auto;padding:0 30px}}section{{display:grid;grid-template-columns:92px 1fr;gap:42px;padding:56px 0;border-bottom:1px solid var(--ink)}}.inv{{background:var(--accent);color:var(--cream);margin:0 -30px;padding:56px 30px;border:0}}.num{{font:700 78px/1 var(--mono);color:rgba(24,20,18,.1)}}.inv .num{{color:rgba(251,246,238,.18)}}.eyebrow,.k{{font:12px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}.inv .eyebrow,.inv .k{{color:rgba(251,246,238,.75)}}h1{{font-size:34px;line-height:1.2;margin:0 0 14px}}h2{{font-size:23px;margin:0 0 14px}}h3{{font-size:17px;margin:20px 0 8px}}p{{margin:0 0 12px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);border-left:1px solid currentColor;border-top:1px solid currentColor;margin:20px 0}}.cell{{padding:14px;border-right:1px solid currentColor;border-bottom:1px solid currentColor}}.label{{font:11px var(--mono);color:var(--muted)}}.inv .label{{color:rgba(251,246,238,.75)}}.val{{font-weight:700}}.quote{{border-left:4px solid var(--accent);padding-left:14px;font-weight:700}}.inv .quote{{border-color:var(--cream)}}.rule{{border-top:1px solid var(--line);padding:14px 0}}ul{{padding-left:18px}}li{{margin:8px 0}}li span{{font-family:var(--mono);font-size:12px;margin-right:8px;color:var(--accent)}}.inv li span{{color:var(--cream)}}code{{font-family:var(--mono)}}@media(max-width:760px){{main{{padding:0 18px}}section{{grid-template-columns:1fr;gap:10px;padding:40px 0}}.inv{{margin:0 -18px;padding:40px 18px}}.num{{font-size:54px}}.grid{{grid-template-columns:1fr}}h1{{font-size:28px}}}}
</style></head><body><div class="bar">VIDEO_DISTILLATION | NOTE_ID: {html.escape(data['note_id'])} | GENERATED: {today} | STATUS: READY</div><main>
<section class="inv"><div class="num">01</div><div><div class="eyebrow">Snapshot</div><h1>{html.escape(data['title'])}</h1><p class="quote">这条视频的核心价值是：用低时间成本承诺把一个工作流讲清楚，让观众相信“我也可以照着搭”。</p><div class="grid"><div class="cell"><div class="label">赞</div><div class="val">{data['likes']:,}</div></div><div class="cell"><div class="label">收藏</div><div class="val">{data['collects']:,}</div></div><div class="cell"><div class="label">评论</div><div class="val">{data['comments_count']:,}</div></div><div class="cell"><div class="label">藏赞比</div><div class="val">{data['save_ratio']}%</div></div></div><p>{html.escape(transcript_note)}</p></div></section>
<section><div class="num">02</div><div><div class="eyebrow">Hook</div><h2>标题钩子</h2><p><strong>模式：</strong>{html.escape(" / ".join(data['patterns']))}</p><p><strong>标签：</strong>{html.escape(tags)}</p><p><strong>关键词：</strong>{html.escape(" / ".join(data['keywords']))}</p><p class="quote">标题要同时回答三件事：用什么工具、花多少成本、得到什么结果。</p></div></section>
<section><div class="num">03</div><div><div class="eyebrow">Script</div><h2>口播/正文结构</h2>{arc_html}</div></section>
<section><div class="num">04</div><div><div class="eyebrow">Engagement</div><h2>评论区反馈</h2><ul>{comments_html}</ul><p>评论区可用来判断观众最需要的补充内容：安装步骤、模板文件、排错说明、案例复刻。</p></div></section>
<section><div class="num">05</div><div><div class="eyebrow">Formula</div><h2>可复刻内容公式</h2><div class="rule"><div class="k">Title</div><p>工具组合 + 时间成本 + 明确结果 + 情绪符号。</p></div><div class="rule"><div class="k">Body</div><p>先展示最终效果，再拆步骤，再补关键设置，最后给适用场景和下一步。</p></div><div class="rule"><div class="k">CTA</div><p>引导收藏、评论关键词、领取模板或询问下一期，而不是泛泛求赞。</p></div></div></section>
<section class="inv"><div class="num">06</div><div><div class="eyebrow">Conclusion</div><h2>创作建议</h2><ol><li>复刻时不要只讲工具名，必须让观众看到可落地的工作流结果。</li><li>把“10min”这类成本承诺拆成真实步骤，降低观众行动门槛。</li><li>下一条可延展为排错、模板、进阶玩法、真实案例四个方向。</li></ol></div></section>
</main></body></html>"""
    path = output_dir / f"{data['safe_name']}_视频蒸馏报告.html"
    path.write_text(html_doc, encoding="utf-8")
    return path


def generate_skill(data: dict, output_dir: Path) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    skill_dir = output_dir / f"{data['safe_name']}_视频创作指南.skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill = f"""---
name: {data['safe_name']}-视频创作指南
description: >
  基于单条小红书视频《{data['title']}》蒸馏出的创作指南。
  适用于复刻同类教程、工具工作流、效率方法类视频笔记。
---

# {data['name']} 视频创作指南

> 基于 1 条小红书视频蒸馏 | 生成时间：{today}

## 使用规则

- 当用户要写同类视频脚本时，先确定“工具组合 + 时间成本 + 明确结果”。
- 当用户要优化标题时，检查是否同时包含工具、收益、门槛和情绪钩子。
- 当用户要做系列选题时，从评论区需求、排错、模板、案例复刻四个方向延展。
- 这是单视频 Skill，不能把本条视频推断成博主长期账号策略。

## 核心公式

```text
最终效果展示
↓
为什么这个工作流值得学
↓
步骤 1/2/3 拆解
↓
关键设置或避坑
↓
适用场景
↓
收藏/评论/领取模板 CTA
```

## 标题模板

1. `{data['keywords'][0] if data['keywords'] else '工具'} + {data['keywords'][1] if len(data['keywords']) > 1 else '工作流'}，10min 搭出一个可直接用的 XXX`
2. `我用 XXX + YYY，把 ZZZ 流程压缩到 10 分钟`
3. `不是教程太难，是你缺一个能照抄的 XXX 工作流`

## 内容拆解

| 模块 | 写法 | 目的 |
|------|------|------|
| 开头 | 直接展示最终效果或痛点 | 让观众知道看完能得到什么 |
| 中段 | 按步骤拆工具连接关系 | 降低理解成本 |
| 转折 | 补充关键设置、坑点或替代方案 | 增强收藏价值 |
| 结尾 | 给模板、清单或下一期方向 | 承接评论和关注 |

## 本条视频指纹

- 标题模式：{' / '.join(data['patterns'])}
- 关键词：{' / '.join(data['keywords'])}
- 藏赞比：{data['save_ratio']}%
- 口播字数：{data['transcript_words']}

## 创作禁区

- 不要只罗列工具名，必须展示工作流结果。
- 不要承诺“10min”但步骤过粗。
- 不要把教程写成概念科普。
- 不要缺少模板、清单、排错这类收藏理由。

## 自检清单

| 检查项 | 通过标准 |
|--------|----------|
| 标题 | 有工具、有结果、有低门槛 |
| 开头 | 5 秒内说清收益 |
| 步骤 | 能让新手照着做 |
| 证据 | 有画面、口播或案例支撑 |
| CTA | 引导收藏或评论具体关键词 |
"""
    path = skill_dir / "SKILL.md"
    path.write_text(skill, encoding="utf-8")
    return path


def generate(details_path: Path, output_dir: Path, name: str | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = build_analysis(details_path, explicit_name=name)
    task_path = generate_task(data, output_dir)
    html_path = generate_html(data, output_dir)
    skill_path = generate_skill(data, output_dir)
    print(f"  📋 视频AI蒸馏任务: {task_path}")
    print(f"  🌐 视频蒸馏报告: {html_path}")
    print(f"  🧠 视频创作指南 Skill: {skill_path}")
    return {"task_path": task_path, "html_path": html_path, "skill_path": skill_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="从单条小红书视频详情生成 HTML 报告和 Skill")
    parser.add_argument("details_path", help="crawl_xhs_video.py 生成的 *_video_details.json")
    parser.add_argument("-o", "--output-dir", default="./output", help="输出目录")
    parser.add_argument("--name", help="自定义产物名称")
    args = parser.parse_args()
    generate(Path(args.details_path), Path(args.output_dir), name=args.name)


if __name__ == "__main__":
    main()
