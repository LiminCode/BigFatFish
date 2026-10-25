from __future__ import annotations
import threading
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from .models import ChatSettings, ProviderConfig, SecretStore
from .anthropic_provider import test_connection
from .themes import CHAT_UI_STYLE_LABELS, CHAT_UI_VIEW_ASPECT, theme_names
from .utils import _safe_emit
from ..i18n import t

# 本对话框只读写经典风格的 chat_background 键（肥鱼版宽屏 走主设置窗的
# modern_chat_background），所以裁切入口按单一风格标注名称；名字取自 themes 的
# 单一来源，不在本模块重复字面量。
_CLASSIC_STYLE_LABEL = CHAT_UI_STYLE_LABELS['classic']


class ChatSettingsDialog(QDialog):
    """AI 对话设置对话框。

    支持多 Provider / API 列表：可以在一个对话框里维护多套模型服务配置，
    通过下拉框快速切换当前要使用/编辑的 API；保存后 active_provider 会切到
    下拉框当前选中的那一项。

    测试连接在 Python daemon 线程中执行真实请求，通过本对象的 Signal
    排队回主线程更新界面——不用 QThread，避免线程对象被提前销毁导致的
    "Destroyed while thread is still running" 崩溃（多次连续测试时偶发）。
    """
    _test_done = Signal(bool, str)
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.settings = config.chat_settings()
        p = self.settings.active_config
        self._test_thread = None
        self._provider_drafts: dict[str, dict] = {}
        self._deleted_provider_ids: set[str] = set()
        self._loading_provider = False
        self._test_done.connect(self._on_test_done)
        self.setWindowTitle(t("chat.settings.ai_chat_settings"))

        # API 列表：管理多套 Provider，快速切换当前 API
        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(220)
        for pid, provider in self.settings.providers.items():
            self.provider_combo.addItem(self._provider_label(provider), pid)
        idx = self.provider_combo.findData(self.settings.active_provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self.add_provider_btn = QPushButton(t("chat.settings.add"))
        self.add_provider_btn.setToolTip(t("chat.settings.duplicate_current_api_profile_so"))
        self.delete_provider_btn = QPushButton(t("chat.settings.delete"))
        self.delete_provider_btn.setToolTip(t("chat.settings.delete_selected_api_profile_at"))
        provider_row = QWidget()
        provider_lay = QHBoxLayout(provider_row)
        provider_lay.setContentsMargins(0, 0, 0, 0)
        provider_lay.setSpacing(6)
        provider_lay.addWidget(self.provider_combo, 1)
        provider_lay.addWidget(self.add_provider_btn)
        provider_lay.addWidget(self.delete_provider_btn)

        form = QFormLayout()
        self.name = QLineEdit(p.name)
        self.url = QLineEdit(p.base_url)
        self.model = QLineEdit(p.model)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText(t("chat.settings.leave_blank_keep_saved_key"))
        self.key_hint = QLabel(self._key_status(p))
        self.key_hint.setObjectName('key-hint')
        self.key_hint.setWordWrap(True)
        self.prompt = QPlainTextEdit(self.settings.default_system_prompt)
        self.prompt.setMinimumHeight(120)
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 600)
        self.timeout.setValue(int(p.timeout))
        self.temp = QDoubleSpinBox()
        self.temp.setRange(0, 2)
        self.temp.setSingleStep(.1)
        self.temp.setValue(p.temperature)
        self.tokens = QSpinBox()
        self.tokens.setRange(1, 32768)
        self.tokens.setValue(p.max_tokens)
        # 视觉模型（看看屏幕）：默认同聊天模型推导；取消勾选可手填（如免费 glm-4.6v-flash）
        self.vmodel = QLineEdit(p.vision_model)
        self.vmodel.setPlaceholderText(t("chat.settings.leave_blank_derive_automatically_zhipu"))
        self.vsame = QCheckBox(t("chat.settings.same_vision_model_as_chat"))
        self.vsame.setChecked(p.vision_same_as_chat)
        self.vurl = QLineEdit(p.vision_base_url)
        self.vurl.setPlaceholderText(t("chat.settings.vision_api_address_leave_blank"))
        self.vkey = QLineEdit()
        self.vkey.setEchoMode(QLineEdit.EchoMode.Password)
        self.vkey.setPlaceholderText(t("chat.settings.vision_api_key_leave_blank"))
        _vextra = [self.vmodel, self.vurl, self.vkey]
        def _vtoggle(c):
            for w in _vextra:
                w.setEnabled(not c)
        _vtoggle(p.vision_same_as_chat)
        self.vsame.toggled.connect(_vtoggle)
        # 聊天背景：纯色 / 内置主题 / 自定义图片 + 裁切取景
        self._bg_keys = [k for k, _ in theme_names()]
        self.bg_mode = QComboBox()
        self.bg_mode.addItems([t("chat.settings.solid_cream")] + [n for _, n in theme_names()] + [t("chat.settings.custom_image")])
        cur = str(config.get('chat_background', '') or '')
        self.bg = QLineEdit(cur if cur and not cur.startswith('builtin:') else '')
        self.bg.setPlaceholderText(t("chat.settings.path_custom_image_click_browse"))
        self.bg_btn = QPushButton(t("chat.settings.browse"))
        self.bg_btn.clicked.connect(self._pick_bg)
        bg_row = QWidget()
        bg_lay = QHBoxLayout(bg_row)
        bg_lay.setContentsMargins(0, 0, 0, 0)
        bg_lay.addWidget(self.bg)
        bg_lay.addWidget(self.bg_btn)
        # 显式父对象：无父时 setVisible(True) 会瞬时建顶层原生窗口，慢机/远程桌面
        # 可能闪一下（下面 addWidget 之后才真正入布局）。
        self.crop_btn = QPushButton(t("chat.settings.crop_framing_classic_style_label", CLASSIC_STYLE_LABEL=_CLASSIC_STYLE_LABEL), self)
        self.crop_btn.clicked.connect(self._crop_bg)
        # contain/stretch 下取景框被渲染路径整体忽略（见 themes.py 的 fill 语义）；
        # 本对话框没有填充方式控件，直接按配置里的经典风格填充值决定入口是否可见。
        self.crop_btn.setVisible(str(config.get('chat_background_fill', 'cover') or 'cover') == 'cover')
        bgmode_row = QWidget()
        bgm_lay = QHBoxLayout(bgmode_row)
        bgm_lay.setContentsMargins(0, 0, 0, 0)
        bgm_lay.addWidget(self.bg_mode)
        bgm_lay.addWidget(self.crop_btn)
        theme_idx = self._bg_keys.index(cur[8:]) + 1 if cur.startswith('builtin:') and cur[8:] in self._bg_keys else None
        self.bg_mode.setCurrentIndex(0 if not cur else (theme_idx if theme_idx is not None else len(self._bg_keys) + 1))
        bg_row.setVisible(bool(cur) and theme_idx is None)
        self.bg_mode.currentIndexChanged.connect(lambda i: bg_row.setVisible(i == len(self._bg_keys) + 1))
        self.skip_ssl = QCheckBox(t("chat.settings.skip_ssl_certificate_verification_tick"))
        self.skip_ssl.setChecked(not p.verify_ssl)
        self.system_notify_check = QCheckBox(t("chat.settings.show_system_notification_at_bottom"))
        self.system_notify_check.setChecked(bool(config.get("system_notifications_enabled", True)))

        form.insertRow(0, t("chat.settings.api_list"), provider_row)
        for label, w in [(t("chat.settings.provider_name"), self.name), (t("chat.settings.api_address"), self.url),
                         (t("chat.settings.model"), self.model), ('', self.vsame), (t("chat.settings.vision_model"), self.vmodel), (t("chat.settings.vision_api_address"), self.vurl), (t("chat.settings.vision_api_key"), self.vkey),
                         ('API Key', self.key), ('', self.key_hint),
                         (t("chat.settings.system_notifications"), self.system_notify_check),
                         ('System Prompt', self.prompt),
                         (t("chat.settings.chat_background"), bgmode_row), ('', bg_row),
                         (t("chat.settings.timeout_seconds"), self.timeout), ('Temperature', self.temp),
                         ('Max Tokens', self.tokens)]:
            form.addRow(label, w)
        form.addRow(self.skip_ssl)
        self.result = QLabel('')
        self.result.setWordWrap(True)
        self.test = QPushButton(t("chat.settings.test_connection"))
        self.test.clicked.connect(self._run_test)
        save = QPushButton(t("chat.settings.save"))
        save.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.test)
        buttons.addStretch(1)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.result)
        layout.addLayout(buttons)

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.add_provider_btn.clicked.connect(self._add_provider)
        self.delete_provider_btn.clicked.connect(self._delete_provider)
        self._update_provider_buttons()

    # ---------------------------------------------------------------- provider 列表
    @staticmethod
    def _provider_label(p) -> str:
        name = str(p.name or p.provider_id)
        model = str(p.model or '').strip()
        return f'{name} · {model}' if model else name

    def _capture_current_draft(self) -> None:
        """把当前表单的非提交态保存到草稿，切换 API 时不会丢编辑。"""
        pid = self.settings.active_provider
        if not pid or pid not in self.settings.providers:
            return
        existing = self._provider_drafts.get(pid, {})
        key_text = self.key.text()
        vkey_text = self.vkey.text()
        self._provider_drafts[pid] = {
            'name': self.name.text().strip(),
            'base_url': self.url.text().strip(),
            'model': self.model.text().strip(),
            # 输入框为空表示“不修改/不覆盖”，保留草稿里已录入但尚未保存的 Key；
            # 否则 _load_provider_ui() 清空输入框后会把草稿 Key 覆盖成空。
            'key': key_text if key_text else existing.get('key', ''),
            'timeout': float(self.timeout.value()),
            'temperature': float(self.temp.value()),
            'max_tokens': int(self.tokens.value()),
            'vision_model': self.vmodel.text().strip(),
            'vision_same_as_chat': self.vsame.isChecked(),
            'vision_base_url': self.vurl.text().strip(),
            'vision_key': vkey_text if vkey_text else existing.get('vision_key', ''),
            'verify_ssl': not self.skip_ssl.isChecked(),
        }

    def _load_provider_ui(self, provider_id: str) -> None:
        p = self.settings.providers.get(provider_id)
        if p is None:
            return
        draft = self._provider_drafts.get(provider_id, {})
        self.settings.active_provider = provider_id
        self.name.setText(draft.get('name') if draft.get('name') is not None else p.name)
        self.url.setText(draft.get('base_url') if draft.get('base_url') is not None else p.base_url)
        self.model.setText(draft.get('model') if draft.get('model') is not None else p.model)
        self.key.clear()
        self.key_hint.setText(self._key_status(p))
        self.timeout.setValue(int(draft.get('timeout', p.timeout)))
        self.temp.setValue(float(draft.get('temperature', p.temperature)))
        self.tokens.setValue(int(draft.get('max_tokens', p.max_tokens)))
        self.vmodel.setText(draft.get('vision_model', p.vision_model))
        self.vsame.setChecked(bool(draft.get('vision_same_as_chat', p.vision_same_as_chat)))
        self.vurl.setText(draft.get('vision_base_url', p.vision_base_url))
        self.vkey.clear()
        self.skip_ssl.setChecked(not bool(draft.get('verify_ssl', p.verify_ssl)))
        self._update_provider_buttons()

    def _on_provider_changed(self, _index: int) -> None:
        if self._loading_provider:
            return
        self._capture_current_draft()
        pid = self.provider_combo.currentData()
        if pid and pid in self.settings.providers:
            self._load_provider_ui(pid)

    def _new_provider_id(self) -> str:
        # 避免复用已删除的 provider_id：否则保存合并时新建项会被删除集合过滤掉。
        used = set(self.settings.providers) | set(self._deleted_provider_ids)
        i = len(self.settings.providers) + 1
        while f'api-{i}' in used:
            i += 1
        return f'api-{i}'

    def _add_provider(self) -> None:
        self._capture_current_draft()
        base = self.settings.active_config
        new_id = self._new_provider_id()
        new = ProviderConfig(
            new_id,
            name=t("chat.settings.name_copy", name=base.name),
            base_url=base.base_url,
            chat_path=base.chat_path,
            model=base.model,
            api_key_ref=f'provider/{new_id}',
            timeout=base.timeout,
            temperature=base.temperature,
            max_tokens=base.max_tokens,
            vision_model=base.vision_model,
            vision_same_as_chat=base.vision_same_as_chat,
            vision_base_url=base.vision_base_url,
            vision_api_key_ref=f'provider/{new_id}/vision',
            verify_ssl=base.verify_ssl,
        )
        self.settings.providers[new_id] = new
        # 复制当前草稿（不含 Key），方便基于同一份参数快速修改
        self._provider_drafts[new_id] = {
            'name': new.name,
            'base_url': new.base_url,
            'model': new.model,
            'key': '',
            'timeout': new.timeout,
            'temperature': new.temperature,
            'max_tokens': new.max_tokens,
            'vision_model': new.vision_model,
            'vision_same_as_chat': new.vision_same_as_chat,
            'vision_base_url': new.vision_base_url,
            'vision_key': '',
            'verify_ssl': new.verify_ssl,
        }
        self.provider_combo.addItem(self._provider_label(new), new_id)
        self.provider_combo.setCurrentIndex(self.provider_combo.count() - 1)
        # setCurrentIndex 会触发 _on_provider_changed，但 active_provider 已在
        # _capture_current_draft 后仍为旧值；这里显式切换并加载新配置。
        self._capture_current_draft()
        self.settings.active_provider = new_id
        self._load_provider_ui(new_id)
        self._update_provider_buttons()

    def _delete_provider(self) -> None:
        if len(self.settings.providers) <= 1:
            return
        pid = self.provider_combo.currentData()
        if not pid or pid not in self.settings.providers:
            return
        self.settings.providers.pop(pid, None)
        self._provider_drafts.pop(pid, None)
        self._deleted_provider_ids.add(pid)
        index = self.provider_combo.currentIndex()
        self._loading_provider = True
        try:
            self.provider_combo.removeItem(index)
            new_pid = next(iter(self.settings.providers))
            new_index = self.provider_combo.findData(new_pid)
            if new_index >= 0:
                self.provider_combo.setCurrentIndex(new_index)
        finally:
            self._loading_provider = False
        self.settings.active_provider = next(iter(self.settings.providers))
        self._load_provider_ui(self.settings.active_provider)

    def _update_provider_buttons(self) -> None:
        self.delete_provider_btn.setEnabled(len(self.settings.providers) > 1)

    # ---------------------------------------------------------------- 保存与测试
    def _pick_bg(self):
        path, _ = QFileDialog.getOpenFileName(self, t("chat.settings.choose_chat_background_image"), '', t("chat.settings.image_files_png_jpg_jpeg"))
        if path:
            self.bg.setText(path)

    def _crop_bg(self):
        from .crop_dialog import CropDialog
        from .themes import get_theme
        from .widgets import resolve_bg_pixmap
        i = self.bg_mode.currentIndex()
        value = '' if i == 0 else ('builtin:' + self._bg_keys[i - 1] if i <= len(self._bg_keys) else self.bg.text().strip())
        pix = resolve_bg_pixmap(value)
        if pix is None:
            self.crop_btn.setText(t("chat.settings.no_background_crop_classic_style", CLASSIC_STYLE_LABEL=_CLASSIC_STYLE_LABEL))
            return
        crops = dict(self.config.get('chat_bg_crops', {}) or {})
        initial = crops.get(value)
        if initial is None and value.startswith('builtin:'):
            theme = get_theme(value[8:])
            initial = tuple(theme['focus']) if theme else None
        dlg = CropDialog(pix, initial, self, _CLASSIC_STYLE_LABEL, CHAT_UI_VIEW_ASPECT['classic'])
        accepted = dlg.exec()
        reset, box = dlg.result_box() if accepted else (False, None)
        dlg.deleteLater()  # exec 后即释放：对话框持有整张背景 QPixmap，不随使用次数累积
        if accepted:
            if reset:
                crops.pop(value, None)
            else:
                crops[value] = [round(float(v), 4) for v in box]
            self.config.set('chat_bg_crops', crops)
            self.config.save()

    @staticmethod
    def _key_status(p) -> str:
        """当前是否已保存 API Key（提示用户留空不修改，无需每次重输）。"""
        saved = p.api_key or SecretStore().get(p.api_key_ref)
        if saved:
            return t("chat.settings.api_key_saved_leave_blank")
        return t("chat.settings.no_api_key_yet_enter")

    def _provisional_config(self) -> ProviderConfig:
        """用表单当前值构造一份临时配置（不保存），供测试连接使用。"""
        p = self.settings.active_config
        return ProviderConfig(
            p.provider_id,
            self.name.text().strip() or p.name,
            self.url.text().strip(),
            p.chat_path,
            self.model.text().strip(),
            p.api_key_ref,
            # 表单未填时回退钥匙串：凭据默认存系统钥匙串，直接读 api_key 为空
            self.key.text() or p.api_key or SecretStore().get(p.api_key_ref),
            float(self.timeout.value()),
            float(self.temp.value()),
            int(self.tokens.value()),
            verify_ssl=not self.skip_ssl.isChecked(),
        )

    def _run_test(self):
        if self._test_thread is not None and self._test_thread.is_alive():
            return
        self.test.setEnabled(False)
        self.test.setText(t("chat.settings.testing"))
        self.result.setText('')
        self.result.setStyleSheet('color: #666666;')
        self._test_thread = threading.Thread(
            target=self._run_test_worker,
            args=(self._provisional_config(),),
            daemon=True,
            name='pet-chat-connection-test',
        )
        self._test_thread.start()

    def _run_test_worker(self, provider_config: ProviderConfig):
        ok, message = test_connection(provider_config, timeout=10.0)
        # 对话框可能在测试在飞时被关闭销毁（WA_DeleteOnClose）：直接
        # self._test_done.emit 会对已删 C++ 对象 RuntimeError。
        _safe_emit(self, "_test_done", ok, message)

    def _on_test_done(self, ok: bool, message: str):
        self.test.setEnabled(True)
        self.test.setText(t("chat.settings.test_connection"))
        self.result.setText(message)
        self.result.setStyleSheet('color: #16a34a;' if ok else 'color: #dc2626;')
        self._test_thread = None

    def _apply_draft_to_provider(self, provider_id: str) -> None:
        p = self.settings.providers.get(provider_id)
        draft = self._provider_drafts.get(provider_id)
        if p is None or not draft:
            return
        if draft.get('name'):
            p.name = draft['name']
        p.base_url = draft.get('base_url') or p.base_url
        p.model = draft.get('model') or p.model
        p.timeout = float(draft.get('timeout', p.timeout))
        p.temperature = float(draft.get('temperature', p.temperature))
        p.max_tokens = int(draft.get('max_tokens', p.max_tokens))
        p.vision_model = draft.get('vision_model', p.vision_model)
        p.vision_same_as_chat = bool(draft.get('vision_same_as_chat', p.vision_same_as_chat))
        p.vision_base_url = draft.get('vision_base_url', p.vision_base_url)
        p.verify_ssl = bool(draft.get('verify_ssl', p.verify_ssl))
        key = str(draft.get('key') or '')
        if key:
            p.api_key_ref = p.api_key_ref or f'provider/{provider_id}'
            if not SecretStore().set(p.api_key_ref, key):
                p.api_key = key
                QMessageBox.warning(self, t("chat.settings.secure_storage_unavailable"), t("chat.settings.system_keychain_can_t_used"))
        vkey = str(draft.get('vision_key') or '')
        if vkey:
            p.vision_api_key_ref = p.vision_api_key_ref or f'provider/{provider_id}/vision'
            if not SecretStore().set(p.vision_api_key_ref, vkey):
                p.vision_api_key = vkey
                QMessageBox.warning(self, t("chat.settings.secure_storage_unavailable"), t("chat.settings.system_keychain_can_t_used"))

    def save(self):
        # 保存前基于磁盘最新配置重取快照：另一个设置窗口可能在本窗口打开期间
        # 写入结构性改动。先保留本窗口的 provider 草稿/新增/删除，再与磁盘快照合并。
        old_settings = self.settings
        self.config.reload()
        self._capture_current_draft()
        self.settings = self.config.chat_settings()
        # 合并 provider 结构：保留磁盘中其它窗口新增的项，应用本窗口删除/新增的项。
        for pid in list(self.settings.providers):
            if pid in self._deleted_provider_ids:
                self.settings.providers.pop(pid, None)
        for pid, provider in old_settings.providers.items():
            if pid not in self.settings.providers and pid not in self._deleted_provider_ids:
                self.settings.providers[pid] = provider
        active_pid = self.provider_combo.currentData()
        if active_pid in self.settings.providers:
            self.settings.active_provider = active_pid
        elif self.settings.providers:
            self.settings.active_provider = next(iter(self.settings.providers))
        for pid in list(self.settings.providers):
            self._apply_draft_to_provider(pid)
        self.settings.default_system_prompt = self.prompt.toPlainText().strip()
        i = self.bg_mode.currentIndex()
        bg_val = '' if i == 0 else ('builtin:' + self._bg_keys[i - 1] if i <= len(self._bg_keys) else self.bg.text().strip())
        self.config.set('chat_background', bg_val)
        self.config.set('system_notifications_enabled', self.system_notify_check.isChecked())
        self.config.set_chat_settings(self.settings)
        if not self.config.save():
            QMessageBox.warning(self, t("chat.settings.save_failed"), t("chat.settings.settings_could_not_written_disk") + str(self.config.path))
        self.accept()
