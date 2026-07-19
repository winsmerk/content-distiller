# 任务流程：YouTube 单视频画面与剧本蒸馏

## 目标

输入一条 YouTube 视频链接，生成完整逐字稿、带时间码的文字剧本、关键帧分镜表、HTML 蒸馏报告和创作指南 Skill。

## 一键执行

```bash
cd /Users/lww/Desktop/project/deepdata/blogger-distiller
.venv/bin/python run_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID" --name "视频名称"
```

不需要 TikHub Token。首次运行如缺少 `yt-dlp`，入口脚本会安装到当前 Python 环境；系统仍需有 `ffmpeg`。

## 处理顺序

1. 用 `yt-dlp` 读取单条视频元数据并下载最高 1080p 的可用媒体。
2. 优先选择中文字幕，其次英文字幕；优先作者字幕，再使用自动字幕。
3. 没有可用字幕时，调用本地 Whisper 生成带时间码的口播段落。
4. 用 ffmpeg 检测镜头变化，并加入定时采样，避免教程录屏因画面变化较小而漏镜头。
5. 把每段口播按时间范围对齐到关键帧。
6. 存在 `OPENAI_API_KEY` 时，批量分析关键帧的画面主体、场景、景别、机位、构图、屏幕文字、动作、转场与叙事作用。
7. 生成 HTML、Markdown 文字剧本、CSV 分镜表、关键帧素材和 Skill。
8. 检查生成文件中是否存在未完成占位内容。

## 常用参数

```bash
# 限制最多 30 个分镜节点
.venv/bin/python run_youtube.py "URL" --max-shots 30

# 关闭付费视觉分析，只生成关键帧与口播对齐
.venv/bin/python run_youtube.py "URL" --no-vision

# 分析完成后保留下载的视频文件
.venv/bin/python run_youtube.py "URL" --keep-video

# 受限视频读取本机 Chrome 登录状态
.venv/bin/python run_youtube.py "URL" --cookies-from-browser chrome

# 使用指定 Whisper 模型兜底
.venv/bin/python run_youtube.py "URL" --whisper-model small
```

## 产物

```text
output/<名称>_YouTube视频蒸馏报告.html
output/<名称>_YouTube文字剧本.md
output/<名称>_YouTube分镜表.csv
output/<名称>_YouTube分镜素材/frames/*.jpg
output/<名称>_YouTube创作指南.skill/SKILL.md
output/_过程文件/原始素材/<名称>_YouTube视频AI蒸馏任务.md
```

## 使用产物

- HTML：浏览器打开，按“总览、文字剧本、逐镜头分镜、逐字稿、复刻指南”阅读。
- Markdown：交给 AI 改写、压缩、翻译或生成新主题脚本。
- CSV：用 Excel、Numbers 或表格工具继续补充拍摄地点、演员、道具和完成状态。
- 关键帧：作为剪辑复盘和视觉参考，不要直接复用受版权保护的原视频素材。
- Skill：加载 `SKILL.md` 后，让 AI 按相同结构生成新的口播稿与分镜表。

## 使用边界

只处理公开内容或自己有权访问的内容。下载和分析不等于取得再发布授权；二次创作时应替换原视频的独特措辞、案例和视觉素材，并遵守 YouTube 服务条款与版权要求。
