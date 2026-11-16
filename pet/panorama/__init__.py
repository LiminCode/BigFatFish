# -*- coding: utf-8 -*-
"""配置全景：把这台机器上和 AI 有关的配置画成一张地图（用默认浏览器看）。

三层，页面对具体功能一无所知：
- ``probes``（+ ``claude_home_probe``）只读地把本机事实读成 ``facts``；
- ``sources``（+ ``features`` 功能表）把 ``facts`` 翻译成 ``model.Graph`` 里的节点、连线、待处理；
- ``render`` 把图交给 ``page/`` 目录里的页面代码，位置和走线由页面按图的结构算出来。

页面有两种交付方式：肥鱼里点开的走本机回环服务（``server`` 守门、``routes`` 登记网址、``service`` 采集并发布）；
同时写一份自带数据的离线快照，肥鱼没开时也能看。

命令行：``python -m pet.panorama [--no-wsl] [--no-open]``。
"""
