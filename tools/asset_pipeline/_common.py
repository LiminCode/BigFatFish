"""素材生成链的公共部分：工作目录、ffmpeg 定位、断点续跑检查。

上游（PC2005-cloud/dsh-pet 的 scripts/）把 ffmpeg 路径和各 step 目录写死在仓库根下；
搬进本仓库后统一从这里取，各 step 脚本只管自己的处理逻辑。

工作目录（默认仓库根下的 ``asset-work/``，已 gitignore）::

    asset-work/
    ├── video/     ① AI 生成的绿幕源视频（每个动作一个 mp4）
    ├── pr/        路线 B：PR 手工抠像导出的透明 .mov（可选）
    ├── step01/    水印填充后的 mp4
    ├── step02/    透明 webm（原始分辨率）
    ├── step03/    归一化母版（2160×1215，站立居中、脚底对齐）
    └── step04/    640×360 播放变体 —— 本项目角色包用的就是这一级

换目录：命令行 ``--work <目录>``，或环境变量 ``PET_ASSET_WORK``。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
WORK_ENV = "PET_ASSET_WORK"
FFMPEG_ENV = "PET_FFMPEG"


def _apply_cli_work_dir() -> None:
    """把 ``--work <目录>`` 写进环境变量。

    各 step 脚本在模块顶层就要算出输入 / 输出目录，而且用进程池并行——子进程是
    重新导入模块的，只有环境变量能原样传过去。
    """
    argv = sys.argv
    for index, arg in enumerate(argv):
        if arg == "--work" and index + 1 < len(argv):
            os.environ[WORK_ENV] = argv[index + 1]
        elif arg.startswith("--work="):
            os.environ[WORK_ENV] = arg.split("=", 1)[1]


_apply_cli_work_dir()


def work_dir() -> Path:
    raw = os.environ.get(WORK_ENV, "").strip()
    return Path(raw).expanduser().resolve() if raw else REPO / "asset-work"


def step_dir(name: str) -> Path:
    return work_dir() / name


def ffmpeg_exe() -> str:
    """ffmpeg 可执行文件：``PET_FFMPEG`` → 本项目依赖自带的那份 → PATH。

    本项目运行时依赖 imageio-ffmpeg，它自带一份带 libvpx / libx264 的 ffmpeg，
    所以装好 requirements.txt 就能跑，不用另外下载。
    """
    explicit = os.environ.get(FFMPEG_ENV, "").strip()
    if explicit:
        return explicit
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise SystemExit(
        "找不到 ffmpeg：请先 `pip install -r requirements.txt`（自带 ffmpeg），"
        f"或把 ffmpeg 加进 PATH，或设置环境变量 {FFMPEG_ENV}。")


def has_video_stream(path: Path) -> bool:
    """文件能否被 ffmpeg 读出视频流（上游用 ffprobe；自带的那份 ffmpeg 不含 ffprobe）。"""
    result = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    return "Video:" in result.stderr


def is_valid_output(dst: Path, src: Path, min_size: int = 50_000) -> bool:
    """断点续跑完整性检查：存在、够大、不比源旧、且读得出视频流。

    最后一条防的是「中断时正在写、大小看似足够但已损坏」的文件被当成已完成。
    """
    if not dst.exists() or dst.stat().st_size <= min_size:
        return False
    if dst.stat().st_mtime < src.stat().st_mtime:
        return False
    return has_video_stream(dst)
