"""从纯黑视频生成精确水印 mask：亮度>阈值 = 水印像素（黑背景无干扰）

做法：让你用的 AI 视频工具生成一段「10 秒纯黑视频」（1280x720），画面上唯一发亮的
就是它盖的水印；本脚本把亮度超过阈值的像素标成 255，得到逐帧的水印遮罩，供
watermark_step01.py 填充。仓库自带的 watermark_mask_v5.mkv 是豆包的；换工具才需要重做。

用法: python make_mask_black.py <纯黑视频.mp4> [输出.mkv] [阈值]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _common import HERE, ffmpeg_exe

FFMPEG = ffmpeg_exe()

W, H = 1280, 720
FPS = 24
DEFAULT_LUM_THRESH = 20


def make_mask(black_video: Path, dst: Path, lum_thresh: int = DEFAULT_LUM_THRESH) -> None:
    cmd = [FFMPEG, "-i", str(black_video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_size = W * H * 3
    mask_size = W * H
    frames = 0
    with open(dst.with_suffix(".raw"), "wb") as fw:
        while True:
            buf = proc.stdout.read(frame_size)
            if len(buf) < frame_size:
                break
            mask = bytearray(mask_size)
            for y in range(H):
                row = y * W * 3
                mrow = y * W
                for x in range(W):
                    i = row + x * 3
                    if (buf[i] + buf[i + 1] + buf[i + 2]) // 3 > lum_thresh:
                        mask[mrow + x] = 255
            fw.write(mask)
            frames += 1
    proc.stdout.close()
    proc.wait()
    print(f"分析帧数: {frames}")

    enc = [FFMPEG, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", str(dst.with_suffix(".raw")),
           "-c:v", "ffv1", "-pix_fmt", "gray", str(dst)]
    r = subprocess.run(enc)
    if r.returncode != 0:
        raise RuntimeError("mask 编码失败")
    dst.with_suffix(".raw").unlink()
    print(f"mask 已生成: {dst} ({dst.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    black = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "watermark_mask_custom.mkv"
    thresh = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_LUM_THRESH
    print(f"阈值: {thresh}")
    make_mask(black, dst, thresh)
