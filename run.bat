@echo off
rem ============================================
rem  dsh-pet 独立桌宠 —— 一键启动
rem  （双击本文件即可；不弹出控制台窗口）
rem ============================================
cd /d "%~dp0"
rem  优先用项目自带的 .venv（依赖装在那里）；没有再退回 PATH 上的 pythonw。
rem  用 start 启动，批处理不等桌宠退出，控制台窗口随即关闭。
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m pet
) else (
    start "" pythonw -m pet
)
