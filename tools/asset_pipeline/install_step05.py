"""把 step04 的透明动画装成一个本项目的角色包（素材链第 5 步，本仓库新增）。

上游的第 5 步是「cp step04/*.webm 进插件包」；本项目的角色包多两样东西：按分类分
子目录（待机 / 转向 / 移动 / 点击 / 拖拽 / 随机池），以及 manifest 里的 body_box
（贴边、碰撞、漫游都拿它当身体的稳定边界）。本脚本把这两样一并做掉：

    <角色根目录>/<角色ID>/
    ├── manifest.json            name + body_box（从待机动画首帧量出来）
    └── videos/
        ├── idle/  turn/  move/  click/  drag/  random/

用法::

    python tools/asset_pipeline/install_step05.py --character mycat --name 我的猫 \\
        --idle 待机呼吸休闲 --click 点击回应-开心跃动 点击回应-害羞惊讶 \\
        --drag 被鼠标拖拽悬空反馈 --move 原地漂浮踏步 --turn 原地左转奔跑

没点名的动画一律进 random/（随机动作池）；一个分类都不点名时按上游的命名习惯猜：
名字含「待机」→ idle、「点击回应」→ click、「拖拽」→ drag、「转」→ turn、
「踏步 / 漂浮 / 奔跑」→ move。

默认装到**用户数据目录**的外部角色根（Windows 是
``%APPDATA%\\big-fat-fish\\characters``）：右键桌宠重开菜单就能切过去，不用
重启也不动仓库。想随仓库 / 安装包分发，用 ``--dest assets/characters``。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from _common import REPO, ffmpeg_exe, step_dir

sys.path.insert(0, str(REPO))
from pet import catalog  # noqa: E402  （取分类目录名、画布尺寸与外部角色根，不重复定义）

CATEGORIES = (catalog.DIR_IDLE, catalog.DIR_TURN, catalog.DIR_MOVE,
              catalog.DIR_CLICK, catalog.DIR_DRAG)
# 没有任何显式分类时的命名猜测（上游提示词配方里的动作名）；顺序即优先级
_NAME_HINTS = (
    ("点击回应", catalog.DIR_CLICK),
    ("拖拽", catalog.DIR_DRAG),
    ("待机", catalog.DIR_IDLE),
    ("踏步", catalog.DIR_MOVE),
    ("漂浮", catalog.DIR_MOVE),
    ("奔跑", catalog.DIR_MOVE),
    ("转", catalog.DIR_TURN),
)
ALPHA_SOLID = 128  # body_box 的取样阈值：与命中 / 视觉边缘同口径（见 AGENTS.md）


def default_dest() -> Path:
    """用户数据目录下的外部角色根（跨安装 / 升级保留）。"""
    from pet import config

    return catalog._data_character_dirs(config.APP_DIR_NAME)[0]


def guess_category(name: str) -> str:
    for hint, category in _NAME_HINTS:
        if hint in name:
            return category
    return catalog.DIR_RANDOM


def plan(names: list[str], explicit: dict[str, list[str]]) -> dict[str, str]:
    """动画名 → 分类目录。点了名的按点名；全都没点名时按名字猜，否则其余进随机池。"""
    assigned: dict[str, str] = {}
    for category, wanted in explicit.items():
        for name in wanted:
            if name not in names:
                raise SystemExit(f"--{category} 指定的动画不在 step04/ 里：{name}")
            assigned[name] = category
    guess = not assigned
    for name in names:
        if name not in assigned:
            assigned[name] = guess_category(name) if guess else catalog.DIR_RANDOM
    return assigned


def measure_body_box(clip: Path) -> list[int] | None:
    """量稳定身体框 ``[x1, y1, x2, y2]``（源像素，右 / 下不含，左右按画布中线对称化）。

    取动画首帧里 alpha ≥ 128 的像素包围盒——首帧按配方就是标准正面站立。
    """
    import numpy as np

    width, height = catalog.CANVAS_W, catalog.CANVAS_H
    result = subprocess.run(
        [ffmpeg_exe(), "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(clip),
         "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo",
         "-pix_fmt", "rgba", "-"], capture_output=True)
    if len(result.stdout) < width * height * 4:
        return None
    alpha = np.frombuffer(result.stdout[:width * height * 4], np.uint8).reshape(
        height, width, 4)[..., 3]
    ys, xs = np.where(alpha >= ALPHA_SOLID)
    if len(xs) == 0:
        return None
    middle = width / 2
    half = max(middle - float(xs.min()), float(xs.max()) + 1 - middle)
    x1 = max(0, int(round(middle - half)))
    x2 = min(width, int(round(middle + half)))
    return [x1, int(ys.min()), x2, int(ys.max()) + 1]


def install(character: str, dest: Path, assigned: dict[str, str], source: Path,
            display_name: str = "") -> Path:
    root = dest / character
    videos = root / "videos"
    for name, category in assigned.items():
        target = videos / category
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / f"{name}.webm", target / f"{name}.webm")
        # 同一个动画换了分类：别在旧分类里留一份
        for other in (*CATEGORIES, catalog.DIR_RANDOM):
            stale = videos / other / f"{name}.webm"
            if other != category and stale.exists():
                stale.unlink()

    manifest_path = root / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    if display_name:
        manifest["name"] = display_name
    idle = next((n for n, c in assigned.items() if c == catalog.DIR_IDLE), None)
    probe = idle or next(iter(assigned), None)
    if probe is not None:
        box = measure_body_box(source / f"{probe}.webm")
        if box is not None:
            manifest["body_box"] = box
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description="把 step04 的透明动画装成角色包")
    parser.add_argument("--character", required=True, help="角色 ID（目录名）")
    parser.add_argument("--name", default="", help="角色显示名（写进 manifest.json）")
    parser.add_argument("--dest", default="", help="角色根目录；默认用户数据目录的 characters/")
    parser.add_argument("--work", default="", help="素材链工作目录（默认仓库根 asset-work/）")
    for category in CATEGORIES:
        parser.add_argument(f"--{category}", nargs="*", default=[], metavar="动画名")
    args = parser.parse_args()

    source = step_dir("step04")
    names = sorted(p.stem for p in source.glob("*.webm"))
    if not names:
        print(f"No WebM files found in {source}")
        return 1
    explicit = {c: list(getattr(args, c)) for c in CATEGORIES if getattr(args, c)}
    assigned = plan(names, explicit)
    dest = Path(args.dest).expanduser().resolve() if args.dest else default_dest()
    root = install(args.character, dest, assigned, source, args.name)

    by_category: dict[str, list[str]] = {}
    for name, category in assigned.items():
        by_category.setdefault(category, []).append(name)
    for category in (*CATEGORIES, catalog.DIR_RANDOM):
        if by_category.get(category):
            print(f"{category:>6}: {'、'.join(by_category[category])}")
    if not by_category.get(catalog.DIR_IDLE):
        print("注意：没有待机动画（idle/）——桌宠平时没有可播的站立动画，建议至少指定一个。")
    print(f"已装到 {root}")
    print("右键桌宠重新打开菜单，在角色列表里选它即可（不用重启）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
