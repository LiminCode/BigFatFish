"""Transcode step03 masters into 640x360 playback variants (step04).

素材处理链的第 4 步（转码）：把归一化后的 2160x1215 透明母版（step03/）转成
640x360 / 24fps 的 VP9-alpha 播放变体（step04/）。

完整处理链：
  video/（绿幕源视频）→ watermark_step01.py → chroma_step02.py（或 pr_import_step02.py）
  → step02（透明）→ normalize_step03.py（2160x1215，统一站立居中、脚底对齐）
  → step03（母版）→ 本脚本 → step04（640x360 播放变体）→ install_step05.py（装进角色包）

step04 就是本项目角色包的素材规格：画布 640x360、24fps、VP9 alpha，脚底落在
y≈330（母版 FEET_Y=1115 按 360/1215 缩下来），与 pet/catalog.py 的 FEET_Y 一致。

为什么需要转码：桌宠显示只有两三百像素高，640x360 已经够清晰；母版是它的十一倍
像素，解码内存与切换耗时都按这个倍数涨。
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from _common import ffmpeg_exe, is_valid_output, step_dir

SRC = step_dir("step03")
OUT = step_dir("step04")
FFMPEG = ffmpeg_exe()

PARALLEL = 4
# 转码参数（调这里改画质/分辨率）
TARGET_W = 640    # thumb 宽度（与 2160x1215 母版同 16:9 比例）
TARGET_H = 360    # thumb 高度
CRF = 40       # VP9 质量参数（0-63，越小越清晰越大；40 偏轻，透明区域省码）
FPS = 24       # 帧率（与母版一致，保持动作节奏）


def convert_video(src: Path, dst: Path) -> None:
    """转码单个视频。

    注意：
    - 解码端必须指定 -c:v libvpx-vp9（libvpx 解码才能保留 VP9 alpha，与
      normalize_step03.py 一致）；ffmpeg 自动选解码器会丢 alpha 导致黑底。
    - scale 滤镜默认也会丢 alpha，需 format=yuva420p 强制保留。
    """
    cmd = [
        FFMPEG,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-c:v",
        "libvpx-vp9",  # 关键：libvpx 解码才能保留 VP9 alpha
        "-i",
        str(src),
        "-vf",
        f"scale={TARGET_W}:{TARGET_H},format=yuva420p",
        "-c:v",
        "libvpx-vp9",  # VP9 编码（WebM 标准）
        "-crf",
        str(CRF),
        "-b:v",
        "0",  # 恒定质量模式（CRF）
        "-row-mt",
        "1",  # 多行并行（加速编码）
        "-r",
        str(FPS),
        "-an",  # 丢弃音轨（动画无声音，省体积）
        str(dst),
    ]
    result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())


def _is_valid(dst: Path, src: Path, min_size: int = 20_000) -> bool:
    """断点续跑完整性检查（见 _common.is_valid_output）。"""
    return is_valid_output(dst, src, min_size)


def _process_one(video: Path) -> tuple[str, int, int, bool]:
    """处理单个视频（worker 函数），返回 (名字, 源大小, 输出大小, 是否跳过)。"""
    src_size = video.stat().st_size
    dst = OUT / video.name
    if _is_valid(dst, video):
        return video.name, src_size, 0, True
    convert_video(video, dst)
    return video.name, src_size, dst.stat().st_size, False


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    videos = sorted(SRC.glob("*.webm"))
    if not videos:
        print(f"No WebM masters found in {SRC}")
        return 1

    src_total = 0
    out_total = 0
    total = len(videos)
    with ProcessPoolExecutor(max_workers=PARALLEL) as ex:
        for index, (name, src_size, out_size, skipped) in enumerate(ex.map(_process_one, videos), start=1):
            src_total += src_size
            out_total += out_size
            if skipped:
                print(f"[{index}/{total}] SKIP {name} (already encoded)", flush=True)
            else:
                print(f"[{index}/{total}] {name}  {src_size / 1e6:.1f}MB -> {out_size / 1e6:.1f}MB", flush=True)

    print("\n=== summary ===")
    print(f"masters: {total}")
    print(f"source total: {src_total / 1e6:.1f}MB")
    print(f"thumb total: {out_total / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
