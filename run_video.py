"""
小红书单视频蒸馏 — 一键运行入口

用法：
    python run_video.py "http://xhslink.com/o/xxxx"
    python run_video.py "整段小红书分享文案" --name "Codex Obsidian 工作流"
    python run_video.py "http://xhslink.com/o/xxxx" --no-transcript
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(SKILL_ROOT, "scripts")


def run_phase(phase_name: str, cmd: list[str]) -> None:
    print()
    print("=" * 60)
    print(f"▶ {phase_name}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=SKILL_ROOT)
    if result.returncode != 0:
        print(f"\n❌ {phase_name} 失败（退出码 {result.returncode}）")
        sys.exit(result.returncode)
    print(f"✅ {phase_name} 完成")


def newest_video_details(data_dir: str, before: set[str]) -> str:
    candidates = []
    for name in os.listdir(data_dir):
        if not name.endswith("_video_details.json"):
            continue
        path = os.path.join(data_dir, name)
        if path not in before:
            candidates.append(path)
    if not candidates:
        for name in os.listdir(data_dir):
            if name.endswith("_video_details.json"):
                candidates.append(os.path.join(data_dir, name))
    if not candidates:
        raise FileNotFoundError("未找到 *_video_details.json")
    return max(candidates, key=os.path.getmtime)


def scan_placeholders(paths: list[str]) -> bool:
    patterns = ("TODO", "{X}", "待填", "占位符")
    found = False
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if any(p in line for p in patterns):
                        print(f"  ⚠️ {path}:{i}: {line.strip()[:120]}")
                        found = True
        except OSError:
            pass
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书单视频蒸馏 — 一键生成报告和 Skill")
    parser.add_argument("link", nargs="+", help="小红书视频链接或整段分享文案")
    parser.add_argument("--name", help="产物名称，默认使用视频标题")
    parser.add_argument("--token", help="TikHub API Token（也可使用配置文件或环境变量）")
    parser.add_argument("--data-dir", default="./data", help="数据目录")
    parser.add_argument("--output-dir", default="./output", help="输出目录")
    parser.add_argument("--skip-env", action="store_true", help="跳过环境检查")
    parser.add_argument("--no-transcript", action="store_true", help="跳过视频口播转写")
    parser.add_argument("--note-id", help="短链无法解析时手动指定 note_id")
    parser.add_argument("--xsec-token", help="手动指定 xsec_token")
    args = parser.parse_args()

    python = sys.executable
    link_text = " ".join(args.link)

    print()
    print("🚀 小红书单视频蒸馏 — 一键运行")
    print(f"   视频链接/文案: {link_text[:90]}")
    print(f"   数据目录: {args.data_dir}")
    print(f"   输出目录: {args.output_dir}")
    print(f"   视频转写: {'关闭' if args.no_transcript else '开启'}")

    if not args.skip_env:
        env_cmd = [python, os.path.join(SCRIPTS_DIR, "check_env.py")]
        if args.token:
            env_cmd.extend(["--token", args.token])
        run_phase("Phase 0: 环境自动准备", env_cmd)
    else:
        print("\n⏭️  跳过 Phase 0（--skip-env）")

    os.makedirs(args.data_dir, exist_ok=True)
    before = {
        os.path.join(args.data_dir, name)
        for name in os.listdir(args.data_dir)
        if name.endswith("_video_details.json")
    }

    crawl_cmd = [
        python,
        os.path.join(SCRIPTS_DIR, "crawl_xhs_video.py"),
        link_text,
        "-o",
        args.data_dir,
    ]
    if args.token:
        crawl_cmd.extend(["--token", args.token])
    if args.name:
        crawl_cmd.extend(["--name", args.name])
    if args.no_transcript:
        crawl_cmd.append("--no-transcript")
    if args.note_id:
        crawl_cmd.extend(["--note-id", args.note_id])
    if args.xsec_token:
        crawl_cmd.extend(["--xsec-token", args.xsec_token])

    run_phase("Phase 1: 单视频采集 + 评论 + 口播", crawl_cmd)

    details_path = newest_video_details(args.data_dir, before)
    gen_cmd = [
        python,
        os.path.join(SCRIPTS_DIR, "generate_video_final.py"),
        details_path,
        "-o",
        args.output_dir,
    ]
    if args.name:
        gen_cmd.extend(["--name", args.name])
    run_phase("Phase 2: 生成视频蒸馏报告 + Skill", gen_cmd)

    # Derive paths from the generator's naming rules.
    from scripts.generate_video_final import build_analysis

    data = build_analysis(
        __import__("pathlib").Path(details_path),
        explicit_name=args.name,
    )
    html_path = os.path.join(args.output_dir, f"{data['safe_name']}_视频蒸馏报告.html")
    skill_path = os.path.join(args.output_dir, f"{data['safe_name']}_视频创作指南.skill", "SKILL.md")

    print()
    print("=" * 60)
    print("🔍 占位符检查")
    print("=" * 60)
    has_placeholder = scan_placeholders([html_path, skill_path])
    if has_placeholder:
        print("⚠️ 发现疑似占位符，请检查上方行号。")
    else:
        print("✅ 未发现 TODO / {X} / 待填 / 占位符")

    print()
    print("=" * 60)
    print("🎉 单视频蒸馏完成")
    print("=" * 60)
    print(f"  🌐 HTML 报告: {html_path}")
    print(f"  🧠 Skill 文件: {skill_path}")
    print(f"  📦 数据详情: {details_path}")


if __name__ == "__main__":
    main()
