from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .models import ChatMessage, ChatSettings
from ..i18n import t

def load_character_manifest(root:Path,character_id:str):
    try: raw=json.loads((Path(root)/character_id/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}
    return raw if isinstance(raw,dict) else {}

def load_character_prompt(root:Path,character_id:str):
    chat=load_character_manifest(root,character_id).get('chat',{})
    return str(chat.get('system_prompt','')) if isinstance(chat,dict) else ''

# ---------------------------------------------------------------- 时间感知（上游 fa6b7423，落点按本仓库改过）
# 上游把「当前时间」写进 system；本仓库的 Claude 通道对 system / 消息前缀开着提示缓存，system 每分钟
# 变一次会让整段历史每轮重新写缓存。所以：现在的时间由**本轮用户消息**上的标记带过去（和历史消息
# 同一种标记），system 只放说明 + 距上条消息的间隔（10 分钟以内不写，连续对话里 system 逐字不变）。
# 文案全部走 i18n（chat.time.*），跟界面语言。

def _local_time(iso):
    """created_at（ISO 字符串，通常为 UTC）→ 本地时区 datetime；无法解析返回 None。"""
    try: dt=datetime.fromisoformat(str(iso))
    except (TypeError,ValueError): return None
    return dt.astimezone()  # naive 视为本地时间

def format_time(dt):
    weekdays=t('chat.time.weekdays').split()
    return t('chat.time.stamp',date=f'{dt:%Y-%m-%d}',weekday=weekdays[dt.weekday()],time=f'{dt:%H:%M}')

def format_elapsed(seconds):
    minutes=int(seconds//60); days,rest=divmod(minutes,1440); hours,mins=divmod(rest,60)
    if days: return t('chat.time.days',n=days)+(' '+t('chat.time.hours',n=hours) if hours else '')
    if hours: return t('chat.time.hours',n=hours)+(' '+t('chat.time.minutes',n=mins) if mins else '')
    return t('chat.time.minutes',n=mins)

def stamp_text(text,dt): return f'[{format_time(dt)}] {text}'

def stamp_message(message):
    """用户消息前加「[日期 周X 时:分] 」；助手消息不加，避免模型在回复里模仿时间标记。"""
    if message.role!='user': return message.content
    dt=_local_time(message.created_at)
    return stamp_text(message.content,dt) if dt else message.content

def time_context(history,now):
    gap=''; last=None
    for m in reversed(history or []):
        last=_local_time(m.created_at)
        if last is not None: break
    if last is not None and (now-last).total_seconds()>=600:  # 10 分钟以内视为连续对话，不额外提示
        gap=t('chat.time.gap',when=format_time(last),elapsed=format_elapsed((now-last).total_seconds()))
    return t('chat.time.note',gap=gap)

class PromptBuilder:
    def __init__(self,characters_root=None): self.characters_root=Path(characters_root) if characters_root else None
    def effective_system_prompt(self,settings,character_id,role_prompt=None):
        if role_prompt and role_prompt.strip(): return role_prompt.strip()
        if self.characters_root:
            prompt=load_character_prompt(self.characters_root,character_id)
            if prompt.strip(): return prompt.strip()
        return settings.default_system_prompt.strip()
    def build_messages(self,settings,character_id,history,user_text,role_prompt=None,now=None):
        # 人设三选一（调用方给的 > 角色包自带的 > 设置页的），「关于我」不属于人设：
        # 无论用了哪一个都追加在后面。只在对话消息里加，effective_system_prompt 不变。
        # 时间感知：历史用户消息与本轮消息前加发送时间标记，system 末尾附说明与间隔（见上面注释）。
        # 时间取自已落盘的 ChatMessage.created_at，只在发给模型时附加，不改动会话文件。
        now=(now or datetime.now().astimezone()).astimezone()
        system=self.effective_system_prompt(settings,character_id,role_prompt)
        about=str(getattr(settings,'about_user','') or '').strip()
        if about: system=f'{system}\n\n{about}' if system else about
        system=(system+'\n\n'+time_context(history,now)).strip()
        trimmed=self.trim_history(history,settings.history_message_limit,settings.history_char_limit)
        return [{'role':'system','content':system},*({'role':m.role,'content':stamp_message(m)} for m in trimmed),{'role':'user','content':stamp_text(user_text.strip(),now)}]
    @staticmethod
    def trim_history(history,message_limit,char_limit):
        result=[]; used=0; limit=max(100,char_limit)
        for m in reversed(history):
            if result and (len(result)>=max(1,message_limit) or used+len(m.content)>limit): break
            if not result and len(m.content)>limit:
                result.append(ChatMessage(m.role,m.content[-limit:],m.created_at,m.message_id)); break
            result.append(m); used+=len(m.content)
        return list(reversed(result))