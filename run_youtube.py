"""One-command YouTube video distillation entry point."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"


def run_phase(name: str, command: list[str], env: dict[str, str] | None = None) -> None:
    print(flush=True)
    print("=" * 64, flush=True)
    print(name, flush=True)
    print("=" * 64, flush=True)
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def prepare_environment(python: str) -> None:
    if importlib.util.find_spec("yt_dlp") is None:
        print("  未检测到 yt-dlp，正在安装...")
        subprocess.check_call([python, "-m", "pip", "install", "-U", "yt-dlp"])
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("未检测到 ffmpeg/ffprobe。macOS 可运行：brew install ffmpeg")
    print("  Python / yt-dlp / ffmpeg 已就绪")


def newest_details(data_dir: Path, before: set[Path]) -> Path:
    candidates = [path for path in data_dir.glob("*_youtube_details.json") if path not in before]
    if not candidates:
        candidates = list(data_dir.glob("*_youtube_details.json"))
    if not candidates:
        raise FileNotFoundError("未找到 *_youtube_details.json")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def scan_placeholders(paths: list[Path]) -> list[str]:
    patterns = ("TODO", "{X}", "待填", "占位符")
    hits: list[str] = []
    for path in paths:
        if not path.exists() or path.suffix.lower() == ".csv":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if any(pattern in line for pattern in patterns):
                hits.append(f"{path}:{line_number}: {line[:100]}")
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(
        description="YouTube 单视频蒸馏：下载、字幕/Whisper、关键帧、文字剧本、分镜表、HTML 和 Skill"
    )
    parser.add_argument("url", help="单条 YouTube 视频链接")
    parser.add_argument("--name", help="自定义产物名称，默认使用视频标题")
    parser.add_argument("--data-dir", default="./data", help="数据目录")
    parser.add_argument("--output-dir", default="./output", help="产物目录")
    parser.add_argument("--skip-env", action="store_true", help="跳过 yt-dlp/ffmpeg 自动检查")
    parser.add_argument("--languages", default="zh-Hans,zh-CN,zh,zh-Hant,en,en-US", help="字幕语言优先级")
    parser.add_argument("--max-duration", type=int, default=3600, help="最大视频时长（秒）")
    parser.add_argument("--max-shots", type=int, default=48, help="最多保留关键帧数")
    parser.add_argument("--scene-threshold", type=float, default=0.32, help="镜头变化阈值，0-1")
    parser.add_argument("--no-transcript", action="store_true", help="跳过字幕和 Whisper")
    parser.add_argument("--whisper-model", help="字幕不可用时使用的 Whisper 模型")
    parser.add_argument("--cookies-from-browser", help="受限视频使用的浏览器，如 chrome/safari/firefox")
    parser.add_argument("--keep-video", action="store_true", help="分析后保留原视频")
    parser.add_argument("--no-vision", action="store_true", help="不调用视觉模型，只输出关键帧和口播对齐")
    parser.add_argument("--openai-key", help="OpenAI API Key，推荐改用 OPENAI_API_KEY 环境变量")
    parser.add_argument("--vision-model", default="gpt-5.4-nano", help="关键帧视觉分析模型")
    parser.add_argument("--vision-batch-size", type=int, default=6, help="单次视觉分析图片数")
    args = parser.parse_args()

    python = sys.executable
    data_dir = Path(args.data_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nYouTube 单视频蒸馏", flush=True)
    print(f"  链接: {args.url}")
    print(f"  口播: {'关闭' if args.no_transcript else '字幕优先，Whisper 兜底'}")
    print(f"  画面语义: {'关闭' if args.no_vision else '有 OPENAI_API_KEY 时开启'}")
    if not args.skip_env:
        prepare_environment(python)

    before = set(data_dir.glob("*_youtube_details.json"))
    crawl = [
        python,
        str(SCRIPTS / "crawl_youtube_video.py"),
        args.url,
        "-o",
        str(data_dir),
        "--languages",
        args.languages,
        "--max-duration",
        str(args.max_duration),
        "--max-shots",
        str(max(2, args.max_shots)),
        "--scene-threshold",
        str(min(1.0, max(0.01, args.scene_threshold))),
    ]
    if args.name:
        crawl.extend(["--name", args.name])
    if args.no_transcript:
        crawl.append("--no-transcript")
    if args.whisper_model:
        crawl.extend(["--whisper-model", args.whisper_model])
    if args.cookies_from_browser:
        crawl.extend(["--cookies-from-browser", args.cookies_from_browser])
    if args.keep_video:
        crawl.append("--keep-video")
    run_phase("Phase 1: YouTube 下载、字幕/口播与关键帧", crawl)

    details_path = newest_details(data_dir, before)
    generate = [
        python,
        str(SCRIPTS / "generate_youtube_final.py"),
        str(details_path),
        "-o",
        str(output_dir),
        "--vision-model",
        args.vision_model,
        "--vision-batch-size",
        str(max(1, args.vision_batch_size)),
    ]
    if args.name:
        generate.extend(["--name", args.name])
    if args.no_vision:
        generate.append("--no-vision")
    child_env = os.environ.copy()
    if args.openai_key:
        child_env["OPENAI_API_KEY"] = args.openai_key
    run_phase("Phase 2: 画面分析、剧本、分镜表、HTML 与 Skill", generate, env=child_env)

    from scripts.generate_youtube_final import load_details

    final_data = load_details(details_path, explicit_name=args.name)
    safe_name = final_data["safe_name"]
    products = [
        output_dir / f"{safe_name}_YouTube视频蒸馏报告.html",
        output_dir / f"{safe_name}_YouTube文字剧本.md",
        output_dir / f"{safe_name}_YouTube分镜表.csv",
        output_dir / f"{safe_name}_YouTube创作指南.skill" / "SKILL.md",
        output_dir / "_过程文件" / "原始素材" / f"{safe_name}_YouTube视频AI蒸馏任务.md",
    ]
    hits = scan_placeholders(products)
    print("\n占位符检查")
    if hits:
        for hit in hits:
            print(f"  {hit}")
        raise SystemExit("生成文件中发现未完成占位符。")
    print("  未发现未完成占位符")

    print("\nYouTube 视频蒸馏完成")
    for path in products:
        print(f"  {path}")


if __name__ == "__main__":
    main()
