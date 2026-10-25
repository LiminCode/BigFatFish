# -*- coding: utf-8 -*-
"""设置页「自定义台词」里的事件名与模板参数说明（从 modern_settings_dialog 拆出，2026-10-16）。

两张表的中文是 zh 文案的原文：表的键是内部标识（保存与渲染用，测试按键核对），显示时经
``dialogue_label`` / ``dialogue_param`` 取 ``settings.dialogue.*`` 文案，跟随界面语言。
"""

from __future__ import annotations

import re

from .i18n import t

# 语言配置页只展示用户能理解的事件名称；内部 key 仍用于保存和渲染。
# 下面两张表的中文是 zh 文案的原文（测试与模板按键核对）；显示时经 dialogue_label / dialogue_param 跟随界面语言。
DIALOGUE_LABELS = {
    "start": "开始工作",
    "thinking": "思考",
    "activity.read": "读取文件",
    "activity.search": "搜索或查找",
    "activity.edit": "编辑代码",
    "activity.run": "运行或测试",
    "activity.default": "其他工具操作",
    "agent.attention": "需要用户处理",
    "agent.error": "Agent 出错",
    "agent.missing": "未找到 Agent",
    "bridge.install.pending": "安装桥接中",
    "bridge.install.success": "桥接安装成功",
    "bridge.install.failed": "桥接安装失败",
    "bridge.uninstall.failed": "桥接卸载失败",
    "approval.tool": "审批工具",
    "approval.generic": "审批提示",
    "question.empty": "等待选择",
    "question.one": "单个用户问题",
    "question.many": "多个用户问题",
    "model_access.one": "模型访问失败（单次）",
    "model_access.many": "模型访问失败（连续）",
    "llm_error.api": "AI 服务错误",
    "done.success": "任务完成",
    "done.attention": "任务暂停待确认",
    "failure.retry": "重试后失败",
    "failure.tool": "工具执行失败",
    "failure.generic": "执行失败",
    "balance.loading": "查询余额中",
    "balance.result": "余额结果",
}

DIALOGUE_PARAMS = {
    "name": "Agent 名称",
    "command": "命令文本（已退役：恒隐藏）",
    "label": "标签（工具标签/会话标签随事件而定）",
    "body": "问题内容",
    "count": "数量",
    "reasons": "判断原因（已退役：恒隐藏）",
    "detail": "错误详情",
    "text": "显示文本",
    "event": "未知事件名（bridge.unknown）",
    "tool": "原始工具名",
    "callId": "工具调用 ID",
    "step": "步骤序号",
    "toolName": "审批原始工具名",
    "argsKey": "工具参数摘要键（已退役：恒隐藏）",
    "sessionName": "会话显示名",
    "projectName": "项目名",
    "errorCode": "错误码（llm_error 为上游真实码，如 bad_response_status_code）",
    "errorMessage": "错误信息原文",
    "errorKind": "错误分类（api=AI API 请求失败）",
    "consecutiveRetryCount": "连续模型访问失败次数",
    "retry": "重试序号",
    "retries": "已重试次数",
    "retryExhausted": "是否重试耗尽",
    "failureType": "失败类型",
}


def _i18n_ident(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", re.sub(r"(?<=[a-z])(?=[A-Z])", "_", key).lower()).strip("_")


def dialogue_label(key: str) -> str:
    """事件的展示名（跟随界面语言）；表外的键原样返回。"""
    return t(f"settings.dialogue.event.{_i18n_ident(key)}") if key in DIALOGUE_LABELS else key


def dialogue_param(key: str) -> str:
    """模板参数的说明（跟随界面语言）；表外的键原样返回。"""
    return t(f"settings.dialogue.param.{_i18n_ident(key)}") if key in DIALOGUE_PARAMS else key
