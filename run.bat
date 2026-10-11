@echo off
rem ============================================
rem  dsh-pet 独立桌宠 —— 一键启动
rem  （双击本文件即可；不弹出控制台窗口）
rem ============================================
cd /d "%~dp0"
rem  优先用项目自带的 .venv（依赖装在那里）；没有再退回 PATH 上的 pythonw。
rem  用 start 启动，批处理不等桌宠退出，控制台窗口随即关闭。
rem  从源码跑时进程是 pythonw，任务管理器里显示成 Python、用 Python 的图标。
rem  tools\make_launcher.py 生成一个改了名字和图标的启动器 BigFish.exe（已是最新则
rem  什么都不做）；有它就用它，生成不了照旧用 pythonw。
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" tools\make_launcher.py >nul 2>&1
if exist ".venv\Scripts\BigFish.exe" (
    start "" ".venv\Scripts\BigFish.exe" -m pet
) else if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m pet
) else (
    start "" pythonw -m pet
)
