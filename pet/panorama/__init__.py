# -*- coding: utf-8 -*-
"""配置全景：把这台机器上和 AI 有关的配置画成一张地图（本地 HTML，用默认浏览器看）。

三层，页面对具体功能一无所知：
- ``probes``（+ ``claude_home_probe``）只读地把本机事实读成 ``facts``；
- ``sources``（+ ``features`` 功能表）把 ``facts`` 翻译成 ``model.Graph`` 里的节点、连线、待处理；
- ``render`` 把图嵌进 ``template.html``，位置和走线由页面按图的结构算出来。

命令行：``python -m pet.panorama [--no-wsl] [--no-open]``。
"""
