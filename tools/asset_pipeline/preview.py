"""生成各阶段对照预览页：asset-work/preview.html（step02 / step03 / step04 并排播放）。

上游的 tools/preview.html 把文件清单写死在页面里；这里按工作目录里实际有的动画生成
清单，页面放在工作目录下（视频用相对路径引用），用浏览器打开即可逐个检查抠像边缘、
站位是否统一、缩小后是否还清楚。

用法: python tools/asset_pipeline/preview.py [--work <目录>] [--open]
"""
from __future__ import annotations

import json
import sys
import webbrowser

from _common import HERE, step_dir, work_dir

STAGES = ("step04", "step03", "step02")


def build() -> tuple[str, int]:
    names: list[str] = []
    for stage in STAGES:
        names = sorted(p.name for p in step_dir(stage).glob("*.webm"))
        if names:
            break
    template = (HERE / "preview.html").read_text(encoding="utf-8")
    return template.replace("/*FILES*/[]", json.dumps(names, ensure_ascii=False)), len(names)


def main() -> int:
    page, count = build()
    if not count:
        print(f"No WebM files found under {work_dir()}（先跑素材链）")
        return 1
    out = work_dir() / "preview.html"
    out.write_text(page, encoding="utf-8")
    print(f"{count} 个动画 → {out}")
    if "--open" in sys.argv:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
