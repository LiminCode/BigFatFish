# 素材生成链：绿幕视频 → 透明动画 → 角色包

把 AI 生成的绿幕视频做成桌宠能播的角色包。脚本取自
[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的 `scripts/`（提交
`9266219`，2026-10-10，MIT），按本仓库整理过；提示词配方在 [`prompts/`](../../prompts/README.md)，
面向使用者的完整教学在根 [`README.md`](../../README.md) 的「素材生成教学」。

## 准备

```sh
pip install -r requirements.txt                       # 桌宠本体依赖（自带 ffmpeg）
pip install -r tools/asset_pipeline/requirements.txt  # 素材链额外需要 numpy / scipy
```

不用另外装 ffmpeg：用的是 `imageio-ffmpeg` 自带的那份（含 libvpx-vp9 / libx264）。想换一份，
设环境变量 `PET_FFMPEG`。

## 工作目录

默认是仓库根下的 `asset-work/`（已 gitignore）；`--work <目录>` 或环境变量 `PET_ASSET_WORK`
可以换。把源视频放进 `asset-work/video/`，一个动作一个 mp4，文件名就是动画名。

```text
asset-work/
├── video/     AI 生成的绿幕源视频
├── pr/        路线 B：手工抠像导出的透明 .mov（可选）
├── step01/    水印填充后的 mp4
├── step02/    透明 webm（原始分辨率）
├── step03/    归一化母版 2160×1215（站立居中、脚底对齐）+ params.json
└── step04/    640×360 / 24fps / VP9-alpha 播放变体
```

## 五步

```sh
cd tools/asset_pipeline
python watermark_step01.py    # ① 水印填充（没水印可以跳过）
python chroma_step02.py       # ② 路线 A：自动绿幕抠像（HSV 色相）
python pr_import_step02.py    # ② 路线 B：导入手工抠像的 mov，覆盖同名动作（可选）
python normalize_step03.py    # ③ 统一大小与站位
python encode_thumbs.py       # ④ 转成 640×360 播放变体
python install_step05.py --character mycat --name 我的猫 \
    --idle 待机呼吸休闲 --click 点击回应-开心跃动 --drag 被鼠标拖拽悬空反馈
                              # ⑤ 装成角色包（没点名的动画进随机池）
python preview.py --open      # 随时：生成各阶段并排对照的预览页
```

每一步都能断点续跑（输出已存在、比输入新、读得出视频流就跳过），所以加了新动作重跑一遍
只会处理新增的。

| 步骤 | 做什么 | 说明 |
|---|---|---|
| ① `watermark_step01.py` | 用最近的背景色把水印像素填掉 | 自带的 `watermark_mask_v5.mkv` 是**豆包**水印的遮罩。别的工具水印位置不同：让它生成一段 10 秒纯黑视频，用 `make_mask_black.py <纯黑视频>` 做一份新遮罩。源视频没水印就跳过，② 会直接读 `video/`。 |
| ② `chroma_step02.py` | 绿色色相 + 足够饱和 / 明度 → 透明 | 只认绿色方向，蓝 / 白 / 红不会被误抠。含第三方物品、边缘复杂的动作容易残边——上游全部 106 段最后都改用路线 B 手工抠像。 |
| ② `pr_import_step02.py` | 带 alpha 的 `.mov` → 透明 webm | mov 必须真带 alpha（如 ProRes 4444 with Alpha），放 `asset-work/pr/`，文件名与动作名一致。 |
| ③ `normalize_step03.py` | 按首尾站立帧算缩放，站立高 900、水平居中、脚底落在 y=1115 | 这一步决定所有动画切换时角色不跳、不缩放。 |
| ④ `encode_thumbs.py` | 2160×1215 → 640×360，CRF 40 | 脚底落在 y≈330，与 `pet/catalog.py` 的 `FEET_Y` 一致。 |
| ⑤ `install_step05.py` | 按分类拷进角色包，写 `manifest.json` | 本仓库新增。`body_box` 从待机动画首帧按 alpha≥128 量出并左右对称化——贴边、碰撞、漫游都用它。默认装到用户数据目录的 `characters/`（热加载，不动仓库）；`--dest assets/characters` 则随仓库分发。 |

## 相对上游改了什么

- ffmpeg 与各 step 目录原先写死在作者本机路径（`.tools/ffmpeg-9.0.1…/ffmpeg.exe`、仓库根），
  现在统一走 `_common.py`：自带 ffmpeg、可换的工作目录。
- 断点续跑的完整性检查原先用 ffprobe；自带的 ffmpeg 不含 ffprobe，改成用 ffmpeg 读流信息。
- `chroma_step02.py`：`step01/` 为空时直接读 `video/`；解码时统一缩放到 1280×720 / 24fps，
  源视频不是这个规格也能处理。
- `make_mask_black.py`：纯黑视频改成命令行参数（原先是作者本机的下载路径）。
- `encode_thumbs.py` 的文件头说明按现行规格重写（上游注释还停在 360×360 的旧方案）。
- 新增 `install_step05.py`、`preview.py`（上游预览页把文件清单写死在 HTML 里）。
- 没搬的：`encode_hevc_alpha.sh` / `hevc_alpha_encoder.swift` / `check_alpha.py`（给 Safari
  用的 HEVC-alpha 转码，本项目用 Qt 解码，用不上）、`encode_preview_gifs.py`（本仓库已有
  `scripts/convert_to_gif.py`）、`tools/api-tester.*` 与 `probe-dpi.cjs`（DSH 插件 / Electron
  专用）。

## 验证

`tests/test_asset_pipeline.py` 用一段合成的绿幕视频把五步真跑一遍（没装 numpy / scipy 时
跳过），核对产物是 640×360 / 24fps / 带 alpha、角色居中、脚底在 y=330、`body_box` 合理。
