# -*- coding: utf-8 -*-
"""素材生成链（tools/asset_pipeline）：绿幕视频 → 透明动画 → 角色包。

脚本取自上游 PC2005-cloud/dsh-pet，搬进本仓库后要保证的是「在这里真的跑得通，并且
产物就是本项目角色包的规格」。端到端用例用一段合成的绿幕视频把五步真跑一遍——
各步是独立脚本、用进程池并行，所以按真实入口（子进程）调用。

端到端用例需要 numpy / scipy（素材链的额外依赖，不是肥鱼运行时依赖）和 ffmpeg；
缺任何一个就跳过。纯逻辑用例不需要它们。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "tools" / "asset_pipeline"
sys.path.insert(0, str(PIPELINE))


def _run(script: str, work: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(REPO))
    env.pop("PET_ASSET_WORK", None)
    return subprocess.run(
        [sys.executable, str(PIPELINE / script), "--work", str(work), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600)


# ---------------------------------------------------------------- 纯逻辑
def test_work_dir_defaults_to_the_repo_and_follows_the_environment(monkeypatch, tmp_path):
    import _common

    monkeypatch.delenv(_common.WORK_ENV, raising=False)
    assert _common.work_dir() == REPO / "asset-work"
    monkeypatch.setenv(_common.WORK_ENV, str(tmp_path))
    assert _common.work_dir() == tmp_path.resolve()
    assert _common.step_dir("step04") == tmp_path.resolve() / "step04"


def test_work_dir_is_ignored_by_git():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "asset-work/" in ignored, "中间产物动辄几个 GB，绝不能被提交"


def test_scripts_no_longer_point_at_the_upstream_authors_machine():
    for script in PIPELINE.glob("*.py"):
        text = script.read_text(encoding="utf-8")
        for leftover in ('ROOT / ".tools"', "FFPROBE", "essentials_build", "Downloads"):
            assert leftover not in text, f"{script.name} 还留着上游作者本机的 {leftover}"


def test_install_plan_sorts_animations_into_category_folders():
    import install_step05 as step05

    names = ["待机呼吸休闲", "点击回应-开心跃动", "被鼠标拖拽悬空反馈", "原地漂浮踏步", "吃零食"]
    guessed = step05.plan(names, {})
    assert guessed == {"待机呼吸休闲": "idle", "点击回应-开心跃动": "click",
                       "被鼠标拖拽悬空反馈": "drag", "原地漂浮踏步": "move", "吃零食": "random"}

    explicit = step05.plan(names, {"idle": ["吃零食"]})
    assert explicit["吃零食"] == "idle"
    assert {explicit[n] for n in names if n != "吃零食"} == {"random"}, \
        "点了名就不再猜：其余一律进随机池"

    with pytest.raises(SystemExit):
        step05.plan(names, {"idle": ["不存在的动画"]})


def test_preview_page_lists_what_is_actually_in_the_work_dir(monkeypatch, tmp_path):
    import _common
    import preview

    monkeypatch.setenv(_common.WORK_ENV, str(tmp_path))
    (tmp_path / "step04").mkdir()
    (tmp_path / "step04" / "吃零食.webm").write_bytes(b"x")
    page, count = preview.build()
    assert count == 1 and '["吃零食.webm"]' in page
    assert "/*FILES*/" not in page


def test_prompts_ship_with_the_repo_and_carry_their_attribution():
    prompts = REPO / "prompts"
    recipe = (prompts / "桌面宠物 10 秒动作提示词.md").read_text(encoding="utf-8")
    assert recipe.startswith("## 通用前缀") and "#00FF00" in recipe
    assert (prompts / "系统通知图标 AI 生成提示词.md").is_file()
    notice = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for text in ((prompts / "README.md").read_text(encoding="utf-8"), notice):
        assert "https://github.com/PC2005-cloud/dsh-pet" in text
        assert "禁止商用" in text


# ---------------------------------------------------------------- 端到端
@pytest.fixture(scope="module")
def built(tmp_path_factory):
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    import _common

    try:
        ffmpeg = _common.ffmpeg_exe()
    except SystemExit:
        pytest.skip("没有可用的 ffmpeg")
    work = tmp_path_factory.mktemp("asset-work")
    (work / "video").mkdir()
    # 1 秒绿幕：蓝色身体 + 白色头饰，站位按提示词配方（头顶 ~20%、脚底 85%、水平居中）
    source = work / "video" / "待机呼吸休闲.mp4"
    made = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=0x00FF00:s=1280x720:r=24:d=1",
         "-vf", ("drawbox=x=520:y=144:w=240:h=468:color=0x3366CC:t=fill,"
                 "drawbox=x=560:y=100:w=160:h=60:color=white:t=fill"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(f"ffmpeg 生成不了测试视频：{made.stderr[-200:]}")
    (work / "video" / "吃零食.mp4").write_bytes(source.read_bytes())

    for script in ("watermark_step01.py", "chroma_step02.py", "normalize_step03.py",
                   "encode_thumbs.py"):
        result = _run(script, work)
        assert result.returncode == 0, f"{script} 失败：\n{result.stdout}\n{result.stderr}"
    dest = work / "characters"
    result = _run("install_step05.py", work, "--character", "smoke", "--name", "测试鱼",
                  "--dest", str(dest))
    assert result.returncode == 0, result.stdout + result.stderr
    return {"work": work, "dest": dest, "ffmpeg": ffmpeg, "np": np}


def test_pipeline_output_matches_the_character_package_format(built):
    np, ffmpeg = built["np"], built["ffmpeg"]
    clip = built["work"] / "step04" / "待机呼吸休闲.webm"
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(clip)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stderr
    assert "vp9" in info and "640x360" in info and "24 fps" in info

    raw = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-c:v", "libvpx-vp9", "-i", str(clip),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True).stdout
    alpha = np.frombuffer(raw, np.uint8).reshape(360, 640, 4)[..., 3]
    # VP9 的 alpha 平面是有损的：透明区可能是 0~几，远低于命中阈值 16
    assert alpha.min() <= 8 and alpha.max() == 255, "绿幕变透明，角色不透明"
    ys, xs = np.where(alpha >= 128)
    assert abs((int(xs.min()) + int(xs.max())) / 2 - 320) <= 2, "角色水平居中"
    assert abs(int(ys.max()) + 1 - 330) <= 2, "脚底落在 y=330（pet/catalog.FEET_Y）"
    assert alpha[5, 5] <= 8 and alpha[200, 320] == 255


def test_installed_package_is_one_the_app_recognises(built, monkeypatch):
    from pet import catalog

    root = built["dest"] / "smoke"
    assert (root / "videos" / "idle" / "待机呼吸休闲.webm").is_file()
    assert (root / "videos" / "random" / "吃零食.webm").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "测试鱼"
    x1, y1, x2, y2 = manifest["body_box"]
    assert x1 + x2 == 640, "左右按画布中线对称"
    assert 0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 360
    assert abs(y2 - 330) <= 2

    monkeypatch.chdir(built["work"])           # 源码运行时扫描「当前目录/characters」
    catalog.character_body_box.cache_clear()
    try:
        assert catalog.resolve_character_video_dir("smoke") == root / "videos"
        assert catalog.character_body_box("smoke") == (x1, y1, x2, y2)
    finally:
        catalog.character_body_box.cache_clear()


def test_rerun_skips_finished_work_only_when_outputs_are_intact(built):
    """断点续跑：坏文件（中断时写了一半）必须重做，不能因为「存在」就跳过。"""
    import _common

    source = built["work"] / "step03" / "吃零食.webm"
    good = built["work"] / "step04" / "吃零食.webm"
    assert _common.is_valid_output(good, source, min_size=1_000)
    broken = built["work"] / "step04" / "坏的.webm"
    broken.write_bytes(b"\0" * 4_000)
    assert not _common.is_valid_output(broken, source, min_size=1_000)
    broken.unlink()
