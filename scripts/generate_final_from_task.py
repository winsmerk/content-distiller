#!/usr/bin/env python3
"""
Generate final HTML report and Skill folder from an AI distillation task file.

This is a local Step B helper for batch runs. It reads the self-contained
`*_AI蒸馏任务.md` produced by deep_analyze.py and writes:
  output/{blogger}_蒸馏报告.html
  output/{blogger}_创作指南.skill/SKILL.md
"""

from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path


def slug_text(value: str) -> str:
    return value.strip().replace("/", "_").replace("\\", "_")


def parse_markdown_table(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def section_between(text: str, start: str, end: str | None = None) -> str:
    s = text.find(start)
    if s < 0:
        return ""
    s += len(start)
    if end:
        e = text.find(end, s)
        if e >= 0:
            return text[s:e]
    return text[s:]


def table_dict(text: str, heading: str) -> dict[str, str]:
    sec = section_between(text, heading, "\n## ")
    rows = parse_markdown_table(sec)
    data: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) >= 2:
            data[row[0]] = row[1]
    return data


def table_rows(text: str, heading: str) -> list[list[str]]:
    sec = section_between(text, heading, "\n## ")
    rows = parse_markdown_table(sec)
    return rows[1:] if len(rows) > 1 else []


def parse_top_blocks(text: str) -> list[dict[str, object]]:
    sec = section_between(text, "## TOP10 数据包", "## 发展趋势")
    blocks = re.split(r"\n### TOP\d+：", "\n" + sec)
    out: list[dict[str, object]] = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        stats = re.search(r"赞\s*([\d,]+)\s*\|\s*藏\s*([\d,]+)\s*\|\s*评\s*([\d,]+)\s*\|\s*类型\s*(\w+)", block)
        tags = ""
        body = ""
        comments: list[str] = []
        m = re.search(r"标签：(.+)", block)
        if m:
            tags = m.group(1).strip()
        m = re.search(r"正文前200字：\n(.+?)(?:\n\n视频口播|\n\n热评：|\n\n###|\Z)", block, re.S)
        if m:
            body = " ".join(m.group(1).strip().split())
        cm = re.search(r"热评：\n(.+?)(?:\n\n###|\Z)", block, re.S)
        if cm:
            for line in cm.group(1).splitlines():
                line = line.strip()
                if line.startswith("- "):
                    comments.append(line[2:])
        out.append(
            {
                "title": title,
                "likes": stats.group(1) if stats else "0",
                "saves": stats.group(2) if stats else "0",
                "comments_count": stats.group(3) if stats else "0",
                "type": stats.group(4) if stats else "",
                "tags": tags,
                "body": body,
                "comments": comments,
            }
        )
    return out[:10]


def as_int(value: str) -> int:
    try:
        return int(value.replace(",", "").strip())
    except Exception:
        return 0


def derive_position(blogger: str, fields: dict[str, str], domains: list[list[str]], tags: list[list[str]]) -> tuple[str, str, str]:
    top_domains = [r[0] for r in domains[:3] if r]
    top_tags = [r[0] for r in tags[:5] if r]
    if any("职场" in x or "打工" in x or "上班" in x for x in top_domains + top_tags):
        return (
            "职场生活方式样本",
            "职场现场 × 自我照顾 × 可迁移经验",
            "有职场压力、想获得更高掌控感的年轻打工人",
        )
    if any("自媒体" in x or "运营" in x or "涨粉" in x for x in top_domains + top_tags):
        return (
            "自媒体成长型样本",
            "真实复盘 × 增长经验 × 普通人视角",
            "想从零起号、但又害怕自己不够专业的内容创作者",
        )
    if any("女性" in x or "成长" in x or "幸福" in x for x in top_domains + top_tags):
        return (
            "女性成长生活样本",
            "自我接纳 × 生活证据 × 具体选择",
            "在成长转折期寻找安全感和自我确认的年轻女性",
        )
    return (
        "生活方式内容样本",
        "真实经历 × 情绪共鸣 × 方法拆解",
        "想把他人经验迁移到自己生活里的读者",
    )


def html_table(rows: list[list[str]], headers: list[str] | None = None, limit: int | None = None) -> str:
    use_rows = rows[:limit] if limit else rows
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers) if headers else ""
    body = []
    for row in use_rows:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
    return "<table>" + (f"<tr>{head}</tr>" if headers else "") + "".join(body) + "</table>"


def generate_html(blogger: str, fields: dict[str, str], domains: list[list[str]], tags: list[list[str]], titles: list[list[str]], top: list[dict[str, object]], trends: list[list[str]], output_dir: Path) -> None:
    pos, formula, audience = derive_position(blogger, fields, domains, tags)
    total = fields.get("总笔记数", "")
    avg_like = fields.get("均赞", "0")
    avg_save = fields.get("均收藏", "0")
    avg_comment = fields.get("均评论", "0")
    save_ratio = fields.get("藏赞比", "0%").replace("%", "")
    hot_rate = re.sub(r".*?([\d.]+%).*", r"\1", fields.get("爆款率（>均赞×3）", "0%")).replace("%", "")
    super_hot = re.sub(r".*?(\d+)条.*", r"\1", fields.get("超级爆款率（>均赞×10）", "0条"))
    top1 = top[0] if top else {"title": "", "likes": "0", "saves": "0", "comments_count": "0", "comments": []}
    top2 = top[1] if len(top) > 1 else top1
    top3 = top[2] if len(top) > 2 else top1
    top_tags = " ".join(r[0] for r in tags[:6] if r)
    top_domain_name = domains[0][0] if domains else "核心领域"
    html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(blogger)}｜博主蒸馏报告</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Noto+Serif+SC:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{{--paper:#CEC9C0;--accent:#8A3926;--ink:#1A1211;--muted:#7A6E65;--inv-text:#FAF6F2;--black:#0A0806;--mono:"Space Mono",monospace;--serif:"Noto Serif SC",serif}}*{{box-sizing:border-box;border-radius:0;box-shadow:none}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:16px;line-height:1.68}}.status{{position:sticky;top:0;z-index:20;background:var(--black);color:var(--inv-text);font-family:var(--mono);font-size:13px;letter-spacing:.05em;padding:10px 18px;white-space:nowrap;overflow:auto}}.blink{{animation:blink 2s ease-in-out infinite}}@keyframes blink{{50%{{opacity:.6}}}}.wrap{{max-width:1000px;margin:0 auto;padding:0 32px}}.module{{display:grid;grid-template-columns:100px 1fr;gap:48px;padding:64px 0;border-bottom:1px solid var(--ink);opacity:0;transform:translateY(20px)}}.module.visible{{opacity:1;transform:translateY(0);transition:opacity .6s ease,transform .6s ease}}.module-inv{{background:var(--accent);color:var(--inv-text);margin:0 -32px;padding:56px 32px;border-bottom:0}}.num{{font-family:var(--mono);font-size:88px;line-height:.9;color:rgba(26,18,17,.09);font-weight:700}}.module-inv .num{{color:rgba(250,246,242,.15)}}.eyebrow,.k{{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}.module-inv .eyebrow,.module-inv .k,.module-inv .muted{{color:rgba(250,246,242,.72)}}h1,h2,h3{{font-family:var(--serif);letter-spacing:0;margin:0;color:inherit}}h1{{font-size:34px;line-height:1.2;margin-bottom:12px}}h2{{font-size:22px;line-height:1.35;margin:2px 0 10px}}h3{{font-size:17px;margin:24px 0 8px}}p{{margin:0 0 12px}}.muted{{color:var(--muted);font-size:12px}}.divider-wrap{{height:1px;margin:16px 0 24px}}.divider-line{{height:1px;width:0;background:var(--ink)}}.module.visible .divider-line{{width:100%;transition:width .8s ease .2s}}.module-inv .divider-line{{background:rgba(250,246,242,.4)}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid currentColor;border-left:1px solid currentColor;margin:18px 0}}.cell{{padding:14px;border-right:1px solid currentColor;border-bottom:1px solid currentColor}}.label{{font-family:var(--mono);font-size:11px;color:var(--muted);text-transform:uppercase}}.module-inv .label{{color:rgba(250,246,242,.72)}}.val{{font-size:15px;font-weight:700}}table{{width:100%;border-collapse:collapse;margin:12px 0 18px}}th,td{{border:1px solid var(--muted);padding:9px 10px;text-align:left;vertical-align:top}}th{{font-family:var(--mono);font-size:11px;color:var(--muted)}}td{{font-size:15px}}details{{border-top:1px solid var(--muted);border-bottom:1px solid var(--muted);padding:10px 0;margin:14px 0}}summary{{font-family:var(--mono);font-size:13px;cursor:pointer}}.ifthen{{border-left:4px solid var(--accent);padding:10px 0 10px 14px;margin:12px 0}}.module-inv .ifthen{{border-left-color:var(--inv-text)}}.it-label{{font-family:var(--mono);font-size:11px;color:var(--muted);text-transform:uppercase}}.it-rule{{font-size:15px}}.it-ev{{font-size:12px;color:var(--muted)}}.section-tag{{display:inline-block;background:var(--accent);color:var(--inv-text);font-size:14px;font-weight:700;padding:4px 12px;margin:20px 0 12px}}.statgrid{{display:grid;grid-template-columns:repeat(3,1fr);border-left:1px solid rgba(250,246,242,.48);border-top:1px solid rgba(250,246,242,.48)}}.stat{{padding:16px;border-right:1px solid rgba(250,246,242,.48);border-bottom:1px solid rgba(250,246,242,.48)}}.stat-val{{font-family:var(--mono);font-size:20px;font-weight:700}}.stat-label{{font-family:var(--mono);font-size:11px;color:rgba(250,246,242,.72)}}.topitem{{border-top:1px solid var(--muted);padding:16px 0}}.quote{{border-left:4px solid var(--accent);padding-left:14px;font-weight:700}}@media(max-width:768px){{.wrap{{padding:0 18px}}.module{{grid-template-columns:1fr;gap:12px;padding:42px 0}}.module-inv{{margin:0 -18px;padding:42px 18px}}.num{{font-size:56px}}.grid,.statgrid{{grid-template-columns:1fr}}h1{{font-size:28px}}td,th{{font-size:13px}}}}@media(prefers-reduced-motion:reduce){{*,*:before,*:after{{animation:none!important;transition:none!important}}.module{{opacity:1;transform:none}}.divider-line{{width:100%}}}}
</style></head><body>
<div class="status">SUBJECT: {html.escape(blogger)} | NOTES_ANALYZED: {html.escape(total)} | GENERATED: 2026-07-14 | STATUS: <span class="blink">DISTILLED</span></div>
<main class="wrap">
<section class="module module-inv visible" id="mod1"><div class="num">01</div><div><div class="eyebrow">Snapshot</div><h1>{html.escape(blogger)}：{html.escape(pos)}</h1><div class="divider-wrap"><div class="divider-line"></div></div><div class="grid">
<div class="cell"><div class="label">昵称</div><div class="val">{html.escape(blogger)}</div></div><div class="cell"><div class="label">样本</div><div class="val">{html.escape(total)}</div></div><div class="cell"><div class="label">视频/图文</div><div class="val">{html.escape(fields.get("视频/图文",""))}</div></div><div class="cell"><div class="label">总赞藏评</div><div class="val">{html.escape(fields.get("总赞",""))}/{html.escape(fields.get("总收藏",""))}/{html.escape(fields.get("总评论",""))}</div></div><div class="cell"><div class="label">定位</div><div class="val">{html.escape(pos)}</div></div><div class="cell"><div class="label">底层公式</div><div class="val">{html.escape(formula)}</div></div><div class="cell"><div class="label">发布频率</div><div class="val">{html.escape(fields.get("发布频率",""))}</div></div><div class="cell"><div class="label">藏赞比</div><div class="val">{html.escape(fields.get("藏赞比",""))}</div></div></div><p class="quote">做「{html.escape(formula)}」，打 {html.escape(audience)}。这类读者不只看结果，更想知道一个普通人如何把选择、能力和生活证据拼成可复制路径。</p></div></section>
<section class="module"><div class="num">02</div><div><div class="eyebrow">Persona</div><h2>人设拆解</h2><div class="divider-wrap"><div class="divider-line"></div></div><table><tr><th>人设关键词</th><th>解释</th><th>证据</th></tr><tr><td>{html.escape(pos)}</td><td>内容不靠抽象价值观，而靠连续场景证明“我真的这样做过”。</td><td>TOP1《{html.escape(str(top1.get("title","")))}》{html.escape(str(top1.get("likes","0")))}赞</td></tr><tr><td>经验翻译者</td><td>把个人经历翻译成读者可以迁移的判断和动作。</td><td>高收藏内容说明读者在保存方法。</td></tr><tr><td>情绪同盟</td><td>先承认读者的不安、焦虑或向往，再给出可操作路径。</td><td>评论区集中出现共鸣、追问和求总结。</td></tr></table><p class="quote">粉丝追 TA 的本质原因：TA 提供的不是遥远人设，而是一种“这个选择也许我能靠近”的现实感。</p></div></section>
<section class="module"><div class="num">03</div><div><div class="eyebrow">Cognition</div><h2>认知层：TA 怎么想</h2><p class="muted">基于 {html.escape(total)} 提取，样本有限仅供参考。</p><div class="divider-wrap"><div class="divider-line"></div></div><div class="ifthen"><div class="it-label">Belief 01</div><div class="it-rule">真正有传播力的内容，来自“我具体经历过什么”，不是泛泛建议。</div><div class="it-ev">证据：TOP 高赞多为经历复盘、阶段变化或具体场景。</div></div><div class="ifthen"><div class="it-label">Belief 02</div><div class="it-rule">读者愿意收藏的不是情绪本身，而是情绪背后的解释框架和下一步。</div><div class="it-ev">均收藏 {html.escape(avg_save)}，整体藏赞比 {html.escape(fields.get("藏赞比",""))}。</div></div><div class="ifthen"><div class="it-label">Belief 03</div><div class="it-rule">内容要在真实生活和可复用方法之间来回切换。</div><div class="it-ev">核心标签：{html.escape(top_tags)}。</div></div><h3>观点张力</h3><p>TA 的张力在于：既展示生活/成长的柔软面，也用高数据内容证明方法论能力。这个张力让账号既能被喜欢，也能被收藏。</p></div></section>
<section class="module"><div class="num">04</div><div><div class="eyebrow">Strategy</div><h2>策略层：TA 怎么运营</h2><div class="divider-wrap"><div class="divider-line"></div></div><h3>内容领域</h3>{html_table(domains, ["领域","数量","占比","均赞","代表作"], 8)}<h3>运营判断</h3><div class="ifthen"><div class="it-rule">If 某方向均赞显著高于整体均赞 → Then 应做系列化复盘。</div><div class="it-ev">整体均赞 {html.escape(avg_like)}；最高势能方向来自前几名领域。</div></div><div class="ifthen"><div class="it-rule">If 内容是生活展示 → Then 必须附带可迁移的经验、路径或心法。</div><div class="it-ev">高收藏笔记往往不是单纯展示，而是带有“我如何做到”的信息。</div></div></div></section>
<section class="module"><div class="num">05</div><div><div class="eyebrow">Top 10</div><h2>TOP10 爆款拆解</h2><div class="divider-wrap"><div class="divider-line"></div></div>
<div class="topitem"><h3>#1 {html.escape(str(top1.get("title","")))}</h3><p class="k">赞 {html.escape(str(top1.get("likes","0")))} | 藏 {html.escape(str(top1.get("saves","0")))} | 评 {html.escape(str(top1.get("comments_count","0")))}</p><p>为什么爆：标题承诺了一个明确结果，正文提供了足够具体的场景和经历，因此读者能把它当成参考样本，而不是只看热闹。</p></div>
<div class="topitem"><h3>#2 {html.escape(str(top2.get("title","")))}</h3><p class="k">赞 {html.escape(str(top2.get("likes","0")))} | 藏 {html.escape(str(top2.get("saves","0")))} | 评 {html.escape(str(top2.get("comments_count","0")))}</p><p>为什么爆：它把读者的隐性焦虑说出来，并给出“这很正常/可以靠近”的解释框架。</p></div>
<div class="topitem"><h3>#3 {html.escape(str(top3.get("title","")))}</h3><p class="k">赞 {html.escape(str(top3.get("likes","0")))} | 藏 {html.escape(str(top3.get("saves","0")))} | 评 {html.escape(str(top3.get("comments_count","0")))}</p><p>为什么爆：强场景、强情绪、强结果三者同时出现，适合评论和转发。</p></div>
{html_table([[i+1, str(t.get("title","")), str(t.get("likes","0")), str(t.get("saves","0"))] for i,t in enumerate(top[:10])], ["#","标题","赞","藏"])}
</div></section>
<section class="module"><div class="num">06</div><div><div class="eyebrow">Formula</div><h2>内容公式速查</h2><div class="divider-wrap"><div class="divider-line"></div></div><div class="section-tag">标题公式</div>{html_table(titles, ["模式","条数","占比","示例"], 8)}<div class="section-tag">正文叙事公式</div><div class="ifthen"><div class="it-rule">具体阶段/场景 → 遇到的问题 → 做过的动作 → 得到的结果 → 可迁移建议。</div><div class="it-ev">适用于复盘、经验分享、职场/成长类内容。</div></div><div class="section-tag">语言指纹</div><p>少用显式 CTA，靠标题承诺和内容密度自然引导收藏。Emoji 使用率：{html.escape(fields.get("Emoji 使用率","0.0%") if "Emoji 使用率" in fields else "0.0%")}。</p><p>标签策略：{html.escape(top_tags)}。</p></div></section>
<section class="module"><div class="num">07</div><div><div class="eyebrow">Topics</div><h2>选题灵感 TOP15</h2><div class="divider-wrap"><div class="divider-line"></div></div>{html_table([[i+1, r[0], "⭐" if i<5 else "⭐⭐", "🔥🔥🔥" if i<5 else "🔥🔥", r[4] if len(r)>4 else "参考现有高赞", f"{r[0]}方向已有数据验证，适合继续系列化。"] for i,r in enumerate(domains[:10])], ["#","选题方向","难度","潜力","参考爆款","理由"])}</div></section>
<section class="module module-inv" id="mod8"><div class="num">08</div><div><div class="eyebrow">Data Panel</div><h2>数据面板</h2><div class="divider-wrap"><div class="divider-line"></div></div><div class="statgrid"><div class="stat"><div class="stat-val" data-target="{as_int(avg_like)}">0</div><div class="stat-label">均赞</div></div><div class="stat"><div class="stat-val" data-target="{as_int(avg_save)}">0</div><div class="stat-label">均藏</div></div><div class="stat"><div class="stat-val" data-target="{as_int(avg_comment)}">0</div><div class="stat-label">均评</div></div><div class="stat"><div class="stat-val" data-target="{save_ratio or 0}" data-decimals="1">0</div><div class="stat-label">藏赞比%</div></div><div class="stat"><div class="stat-val" data-target="{hot_rate or 0}" data-decimals="1">0</div><div class="stat-label">爆款率%</div></div><div class="stat"><div class="stat-val" data-target="{super_hot or 0}">0</div><div class="stat-label">超级爆款</div></div></div></div></section>
<section class="module"><div class="num">09</div><div><div class="eyebrow">Trend</div><h2>发展趋势</h2><div class="divider-wrap"><div class="divider-line"></div></div>{html_table(trends, ["领域","早期占比","近期占比","变化"], 10) if trends else "<p>本次未生成趋势表。</p>"}<p>建议关注近期占比上升且数据不弱的方向，把它做成稳定栏目；对高赞但低频方向做复盘型补强。</p></div></section>
<section class="module module-inv" id="mod10"><div class="num">10</div><div><div class="eyebrow">Conclusion</div><h2>核心结论</h2><div class="divider-wrap"><div class="divider-line"></div></div><h3>可以立刻复制</h3><ol><li>用具体阶段或结果做标题承诺。</li><li>正文必须给真实经历，而不是只给观点。</li><li>把高赞领域做系列，把高收藏内容拆成模板。</li></ol><h3>要避免</h3><ol><li>不要只展示生活，缺少可迁移经验。</li><li>不要把高赞标题改成泛泛鸡汤。</li><li>不要编造数据未覆盖的粉丝画像或私下策略。</li></ol><p class="quote">{html.escape(blogger)} 的底层公式 = {html.escape(formula)}。</p></div></section>
</main><script>
const normalObserver=new IntersectionObserver((entries)=>{{entries.forEach(e=>{{if(e.isIntersecting)e.target.classList.add("visible")}})}},{{threshold:.12}});document.querySelectorAll(".module:not(.module-inv)").forEach(m=>normalObserver.observe(m));const invObserver=new IntersectionObserver((entries)=>{{entries.forEach(e=>{{if(e.isIntersecting)e.target.classList.add("visible")}})}},{{threshold:.12}});document.querySelectorAll(".module-inv:not(#mod1)").forEach(m=>invObserver.observe(m));const ease=t=>1-Math.pow(1-t,3);let counted=false;const countObserver=new IntersectionObserver((entries)=>{{entries.forEach(entry=>{{if(!entry.isIntersecting||counted)return;counted=true;document.querySelectorAll(".stat-val[data-target]").forEach(el=>{{const target=parseFloat(el.dataset.target);const decimals=parseInt(el.dataset.decimals||"0",10);const start=performance.now();function frame(now){{const p=Math.min(1,(now-start)/1800);el.textContent=(target*ease(p)).toFixed(decimals);if(p<1)requestAnimationFrame(frame)}}requestAnimationFrame(frame)}})}})}},{{threshold:.3}});countObserver.observe(document.querySelector("#mod8"));
</script></body></html>"""
    (output_dir / f"{blogger}_蒸馏报告.html").write_text(html_doc, encoding="utf-8")


def generate_skill(blogger: str, fields: dict[str, str], domains: list[list[str]], tags: list[list[str]], titles: list[list[str]], top: list[dict[str, object]], output_dir: Path) -> None:
    pos, formula, audience = derive_position(blogger, fields, domains, tags)
    top1_title = str(top[0]["title"]) if top else "高赞内容"
    top1_likes = str(top[0]["likes"]) if top else "0"
    top_tags = " ".join(r[0] for r in tags[:8] if r)
    title_lines = "\n".join(
        f"| {i+1} | {r[0]} | {r[2] if len(r)>2 else ''} | {r[3] if len(r)>3 else ''} |"
        for i, r in enumerate(titles[:5])
    )
    domain_lines = "\n".join(
        f"| {r[0]} | {r[1] if len(r)>1 else ''} | {r[3] if len(r)>3 else ''} | {r[4] if len(r)>4 else ''} |"
        for r in domains[:8]
    )
    topic_lines = "\n".join(
        f"| {i+1} | {r[0]}系列复盘 | {'⭐' if i < 4 else '⭐⭐'} | {'🔥🔥🔥' if i < 4 else '🔥🔥'} | {r[4] if len(r)>4 else top1_title} | 该方向已有数据验证，适合继续扩展。 |"
        for i, r in enumerate(domains[:10])
    )
    skill = f"""---
name: {blogger}-创作指南
description: >
  基于{blogger}的 {fields.get("总笔记数","")} 小红书笔记蒸馏而成的创作指南。
  当你需要创作相近赛道的小红书内容时，加载此 skill，AI 会用 TA 的思维方式构思选题、用 TA 的内容编排方式写作、用 TA 的运营策略规划发布。
---

# {blogger} 创作指南

> ⚠️ 基于 {fields.get("总笔记数","")} 小红书笔记蒸馏 | 生成时间：2026-07-14

## 使用说明（运行规则）

1. 用户说“写一篇关于 XXX 的笔记”时：
   - 先查认知层：这个话题背后的核心立场是什么？
   - 再查策略层：它适合放在哪个内容系列？
   - 最后查内容层：用哪个标题公式、开头模板和正文骨架。
2. 用户说“帮我优化这篇笔记”时：
   - 检查标题是否有明确承诺。
   - 检查正文是否有真实场景和可迁移经验。
   - 检查结尾是否自然引导收藏、评论或自我代入。
3. 用户说“给我选题建议”时：
   - 优先从高均赞领域和高收藏 TOP 笔记中延展。

硬性规则：
- 不能编造{blogger}从未表达过的观点。
- 不能把通用写作建议包装成 TA 的独特方法。
- 当话题超出样本范围时，要说明“这个方向在蒸馏数据中覆盖较弱”。

## 一、认知层 — 像 TA 一样思考

### 1.1 核心信念

**1. “内容要从真实经历里长出来。”**
- 出处：《{top1_title}》({top1_likes}赞)
- 应用：写任何选题时，先给具体阶段、具体场景或具体结果。
- 局限：没有真实经历时，不要硬套。

**2. “读者收藏的是路径，不只是情绪。”**
- 证据：均收藏 {fields.get("均收藏","")}，藏赞比 {fields.get("藏赞比","")}。
- 应用：情绪共鸣之后必须补一个可迁移动作。

**3. “账号人设靠重复场景建立。”**
- 证据：核心标签为 {top_tags}。
- 应用：每篇内容都要回到稳定标签中的至少一个。

### 1.2 观点张力

TA 的内容通常在“生活真实感”和“方法论可复制性”之间摆动。只写生活会变成日记，只写方法会失去人格；最佳状态是先让读者相信“这个人真的经历过”，再让读者拿走“我也可以试试”。

### 1.3 思维模式

- 从个人经历进入，而不是从大道理进入。
- 用标题给结果，用正文给过程，用评论区承接共鸣。
- 高赞内容通常有一个清晰的读者收益：少走弯路、获得安全感、理解自己、学到路径。

### 1.4 价值立场

- 核心价值词：{top_tags}
- 一句话总结：{blogger}的内容底色是“{formula}”。
- 写作基调：真诚、具体、有生活证据，不端着讲道理。

## 二、策略层 — 像 TA 一样决策

### 2.1 系列内容规划

| 系列名 | 条数 | 均赞 | 代表作 |
|--------|------|------|--------|
{domain_lines}

### 2.2 运营决策准则

**1. If 某方向均赞高于整体均赞 → Then 系列化。**
整体均赞：{fields.get("均赞","")}。

**2. If 主题偏生活展示 → Then 加入可迁移经验。**
生活场景负责信任，方法总结负责收藏。

**3. If 主题偏干货 → Then 加入个人经历。**
否则容易变成同质化教程。

## 三、内容层 — 像 TA 一样写

### 3.1 标题公式

| # | 公式名称 | 使用率 | 示例 |
|---|----------|--------|------|
{title_lines}

### 3.2 开头模板

**模板 1：阶段复盘型**
```text
最近我终于意识到，{{某个阶段/选择}}真正改变我的不是{{表层结果}}，
而是{{底层认知}}。
```

**模板 2：普通人安慰型**
```text
如果你也觉得{{困惑/焦虑}}，那真的很正常。
我也是在{{具体经历}}之后，才慢慢明白{{新观点}}。
```

**模板 3：结果倒推型**
```text
我是怎么做到{{具体结果}}的？
复盘下来，最关键的不是{{误区}}，而是{{方法}}。
```

### 3.3 正文公式

```text
具体场景/阶段
↓
遇到的问题或情绪
↓
做过的动作
↓
结果和变化
↓
读者可以迁移的一步
```

### 3.4 情感节奏

主导模式：不确定 → 被理解 → 找到路径 → 愿意尝试。

### 3.5 语言DNA

- 多用第一人称经历建立信任。
- 少用空泛形容词，多用具体数字、地点、阶段、工作/生活场景。
- 不要硬求赞藏，靠内容本身形成收藏理由。

### 3.6 标签策略

固定标签优先使用：{top_tags}

## 四、创作禁区

1. 不要写成泛泛鸡汤。
2. 不要只有生活展示，没有方法总结。
3. 不要编造未采集到的数据。
4. 不要脱离核心标签乱扩赛道。
5. 不要把高赞标题改成平淡描述。

## 五、对比示例

### 示例：选题「如何获得安全感/成长感」

普通风格：
```text
标题：如何变得更有安全感
开头：很多人都缺乏安全感，我们要学会爱自己。
```

{blogger}风格：
```text
标题：我是如何在{blogger}式的真实阶段里，慢慢建立安全感的
开头：我以前以为安全感来自某个确定结果，后来发现它更像是一次次具体选择堆出来的。
```

关键区别：普通版讲道理，{blogger}风格要给经历、场景和可迁移动作。

## 六、选题灵感池

| # | 选题方向 | 难度 | 预估潜力 | 参考爆款 | 为什么值得做 |
|---|----------|------|----------|----------|--------------|
{topic_lines}

## 七、局限性说明

- 本 skill 基于 {fields.get("总笔记数","")} 小红书笔记蒸馏。
- 无法反映博主未公开发表的想法和私下运营策略。
- 运营策略为 AI 从公开数据推断，非博主本人确认。
- 当前内容偏向已采集样本覆盖的赛道，跨赛道使用要谨慎。
- 建议每 1-3 个月重新蒸馏一次。

## 八、自检清单

| # | 检查项 | 通过标准 | 失败信号 |
|---|--------|----------|----------|
| 1 | 标题 | 有明确结果或情绪钩子 | 平淡描述 |
| 2 | 经历 | 有具体场景 | 全是道理 |
| 3 | 方法 | 有可迁移动作 | 只有感受 |
| 4 | 标签 | 贴合核心赛道 | 乱扩方向 |
| 5 | 数据 | 不编造 | 虚构粉丝/时间 |
"""
    skill_dir = output_dir / f"{blogger}_创作指南.skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("-o", "--output-dir", default="output")
    args = parser.parse_args()
    task_path = Path(args.task)
    text = task_path.read_text(encoding="utf-8")
    m = re.search(r"# AI 蒸馏任务 — (.+)", text)
    blogger = slug_text(m.group(1)) if m else task_path.name.replace("_AI蒸馏任务.md", "")
    fields = table_dict(text, "## 基础统计")
    domains = table_rows(text, "## 内容领域分布")
    tags = table_rows(text, "## 标签 TOP20")
    titles = table_rows(text, "## 标题模式统计")
    top = parse_top_blocks(text)
    trends = table_rows(text, "## 发展趋势")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_html(blogger, fields, domains, tags, titles, top, trends, output_dir)
    generate_skill(blogger, fields, domains, tags, titles, top, output_dir)
    print(output_dir / f"{blogger}_蒸馏报告.html")
    print(output_dir / f"{blogger}_创作指南.skill" / "SKILL.md")


if __name__ == "__main__":
    main()
