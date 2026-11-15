# PR report: session fish — live conversations never show as frozen; desktop jump never opens a terminal

> **Base**: `177b256c` (Island display name, #42)
> **Branch**: `claude/session-fish-desktop-jump-and-thaw`  **Date**: `2026-11-14`
> **Scope**: 9 files (implementation 6, tests 3) + this report
> **Related**: [`PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md`](PR-REPORT-SESSION-FISH-PERSIST-2026-11-02.md) (fish = an open conversation, frozen = process gone), [`PR-REPORT-CONFIG-CRASH-SAFE-SAVE-2026-11-13.md`](PR-REPORT-CONFIG-CRASH-SAFE-SAVE-2026-11-13.md) (the crash that reset the config)

## 一、核心特性

User report (2026-11-14): "我点击这个小肥鱼的「跳到对话」，为什么跳到了 cmd？应该跳到当前对话啊，还有，他的状态不应该是冻结". The fish belonged to a Claude desktop (Code tab) conversation the user had typed into minutes earlier.

Both symptoms come from one chain:

1. **Why frozen.** The 2026-11-13 blue screen zeroed `config.json`; it was rebuilt from defaults, which have `agent_link.claude = false`. With the Claude Code link off, no monitor feeds live sessions or adopts them from the run list, so the fish layer's "in use" table stays empty and every conversation of the last 3 days lands on the frozen roster, including ones whose `claude.exe` is running. The pet log after the 19:43 restart shows only `冻结的会话小鱼出场` lines and not a single live `会话小鱼出场`.
2. **Why cmd.** For a frozen fish, 「跳到对话」 becomes "resume". The history row for this conversation came from a transcript scan, which records `entrypoint=claude-desktop` but never the desktop-side id (`hostSessionId` is only in the live run list). `resume_key` only took the desktop path when it had that id, so it fell through to the history runner's default action, `claude --resume` in a terminal.

| # | Change | What the user sees |
|---|---|---|
| 1 | The fish controller reads the local run list (`~/.claude/sessions`) on each reconcile and adopts live sessions no channel is feeding | A running conversation shows 休息中 / 工作中 / 等你批准 from the run list's `status`, follows it, and only freezes after its process exits. The island counts these sessions too |
| 2 | Adopted sessions are recorded into 最近的对话, including `host_session` | If such a conversation later freezes, its resume deep-links straight back to it |
| 3 | A frozen desktop conversation with no desktop-side id brings up the Claude desktop window (or launches it via `claude://`) | Never a cmd window. The bubble says to pick the conversation in the sidebar, and the menu item reads 「在 Claude 桌面版重开这个对话」 |

**Invariants**: sessions a live channel feeds are never touched by the run-list pass (their phase and their end belong to the channel). Frozen still means the process is gone. 关闭这只 decisions behave as before: a run-list adoption counts as resting, and only working/waiting revives a closed fish. The machine's Claude Code link setting is **not** changed by this PR (see §五).

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/overlay_session_pets.py` | +66 / −4 | New `registry` constructor argument (callable → `{(agent, sid): adoptable item}`). `reconcile()` now runs `_sync_registry()` and then `_reconcile_roster()` (the old body). `_sync_registry` adopts live run-list sessions not in `_sessions` (or already self-adopted), refreshes them only when the item changed, sends `gone` when they leave the list, falls back to the history title when the run list has only an auto name, and forwards each change to the history service. `on_session_update` (the channel slot) drops a key from the self-adopted set and delegates to `_apply_update` (the old body). `_after_update` runs only the roster and skips it during sync. `reconcile` is a no-op during sync, because the history's `changed` signal is synchronous and would otherwise recurse |
| `pet/overlay_shell.py` | +12 / −1 | Wires `registry=lambda: _local_run_list()` (late-bound so tests can stub the module function). `_local_run_list()` maps `claude_session_info.local_registry_sessions()` to `("claude", sid)` keys. WSL is not read here, since it needs `wsl.exe` |
| `pet/session_pet_ui.py` | +12 / −5 | `resume_key`: a desktop entrypoint without a host id calls `self.desktop_raiser()` instead of falling through to the terminal runner. `resume_label`: desktop conversations always read "reopen in Claude desktop". New injectable `desktop_raiser` |
| `pet/claude_session_jump.py` | +25 / 0 | `raise_desktop()`: focuses the `claude.exe` window titled `Claude` (any `claude.exe` window as a fallback). If there is none, opens `claude://` to launch the app. Never a terminal |
| `pet/locale/zh.json`, `pet/locale/en.json` | +2 / 0 each | `session_jump.ui.switched_desktop_pick_conversation`, `session_jump.ui.could_not_bring_desktop` |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_overlay_session_pets.py` | +108 / 0 | New `running` fixture with a stand-in run list. `test_a_recent_conversation_whose_process_is_still_running_is_not_frozen` (not frozen, shows resting, carries and records `host_session`, follows working, freezes once gone). `test_the_run_list_never_overrides_what_the_live_channel_reports`. `test_the_shell_feeds_the_fish_the_local_run_list` (wiring). `test_a_frozen_desktop_fish_without_its_host_id_brings_up_claude_desktop_not_a_terminal` (menu label, no terminal runner, the desktop raiser is called) |
| `tests/test_session_jump_desktop.py` | +21 / 0 | `raise_desktop` picks the `Claude` window over terminals and browsers, and launches via `claude://` when no window is up |
| `tests/conftest.py` | +7 / 0 | The existing `_no_real_session_history_scan` autouse fixture also stubs `overlay_shell._local_run_list` → `{}`, so shell fixtures never read this machine's `~/.claude/sessions`. I extended the existing fixture rather than adding one, because adding an autouse fixture triggers the known latent native crash in the full suite |

### 未改动

- `pet/agent_link.py`: the monitor's own run-list adoption (`_adopt_registry_sessions`) is unchanged. With the link on, it still owns adoption, and the fish layer defers to it.
- `pet/claude_session_history.py`: the transcript scan still can't know the desktop id. It now gets the id from live adoption instead.
- Claude desktop's private session store (`Claude-Data/.../claude-code-sessions/**/local_*.json`, which maps `cliSessionId` → `local_…`): deliberately **not** read. It is undocumented, about 650 KB per file, and could change shape with any app update.

## 三、实现要点

- **Who owns a session.** `_self_adopted` maps `key → last update given`. A key enters it only through `_sync_registry`, and any channel update for that key removes it. The sync skips keys in `_sessions` that aren't self-adopted, so channel-fed sessions never get a run-list phase or a run-list `gone`.
- **Recursion guard.** `_apply_update → _after_update → reconcile` used to be the path that re-checked the roster on every update. During sync that would re-enter sync. It would also re-enter through `SessionHistoryService.changed`, which `_touched` emits synchronously. A single `_syncing` flag makes both paths wait, and `reconcile` runs the roster once at the end.
- **Writes only on change.** Each item is compared with the last one given, so an idle session costs nothing per tick and the history isn't touched every minute.
- **Alternative considered**: just excluding live sessions from the frozen roster. Rejected, because with the link off the user's live conversations would simply have no fish (the user wants fish = open conversation). Re-enabling the link for the user would fix this machine but not the code, and it is the user's setting to choose.

## 四、性能分析

**Method**: `.venv\Scripts\python.exe -c "…claude_session_info.local_registry_sessions() ×20…"` on the user's machine (Windows 11, Python 3.13, 4 live Claude Code sessions in `~/.claude/sessions`, warm cache, n = 20).

| Metric | Measured | Attribution |
|---|---|---|
| `local_registry_sessions()` (glob + 4 JSON reads + `psutil` create-time check + transcript glob) | p50 2.0 ms, p95 2.2 ms, max 2.2 ms | new, GUI thread |
| Frequency | once per `RECONCILE_MS` (60 s) + once per 最近的对话 change + the first pass 1.5 s after start | new |
| Per-update path (`_after_update`) | unchanged: roster only, no run-list read | existing |
| Focused test families (14 files, 377 tests) | 8.1 s | — |

**Conclusions**: ① Steady state: about 2 ms of GUI-thread work per minute (≈0.003 % duty). The per-session-update path is unchanged. ② New paths: the run-list read above; `_apply_update` / history record only when a run-list item actually changes. `raise_desktop` runs only on a user click (one `EnumWindows` + focus, the same calls the existing jump already makes). ③ New system calls: directory glob + small file reads + `psutil.Process(pid).create_time()` for each run-list entry every 60 s. No network, no new threads, no disk writes beyond the existing debounced history save. ④ Memory: one dict entry (≈8 short strings) per self-adopted live session, removed when it leaves.

## 五、实机运行记录

**Root cause, captured live** (before the fix, pet pid 53396 started 19:43:38):

```
$ tasklist /FI "PID eq 41000"         → claude.exe 41000  (the conversation's process is alive)
~/.claude/sessions/41000.json         → sessionId 9f597df0-…, entrypoint claude-desktop,
                                        hostSessionId local_1cf14c8e-…, status idle
config.json agent_link                → "claude": false, "claude_wsl": false, "session_pets": true
                                        (same in config.json.bak; config.json.corrupt-* from 2026-11-13 22:06 are all-zero)
claude-session-history.json 9f597df0  → entrypoint claude-desktop, host_session ""   ← why resume went to cmd
pet-53396.log                         → 12 × "冻结的会话小鱼出场", 0 × "会话小鱼出场"
```

**Red before the fix** (`pytest -k "raising or running or run_list or frozen_desktop_fish_without or shell_feeds"`): 4 failed, 2 errors. The desktop test failed on the menu showing `在终端里恢复这个对话` (the bug itself), and the `running` fixture failed with `TypeError: unexpected keyword argument 'registry'`. **After the fix**: 6 passed.

**After the fix, on this machine** (pet restarted from this branch's worktree at 19:57:05; gate log `acquired pid=55716`; settings window pid 14884 left running; the link setting still `claude: false`):

```
pet-55716.log
19:57:06,826 从运行清单认领会话小鱼 agent=claude session=9f597df0 phase=resting
19:57:06,877 会话小鱼出场 agent=claude session=9f597df0（在场 1 只）
19:57:06,946 从运行清单认领会话小鱼 agent=claude session=e2df8bdc phase=working
19:57:07,053 从运行清单认领会话小鱼 agent=claude session=f2cf815a phase=working
19:57:07,127 冻结的会话小鱼出场 agent=claude session=250f0db9      (genuinely closed ones still freeze)
```

Screen: the fish for "Island display name configuration" carries the dark resting caption (… · 休息中) instead of the grey frozen one. The island bar went from empty to 「2 工作中 · 2 休息中」.

**Clicking this session's fish** (synthetic Win32 click via `SetCursorPos` + `mouse_event`, sent only after the cursor had been still for 2.5 s; pet pid re-checked as 55716 afterwards):

- The detail card opened with state **休息中** (Opus 5.5 · high · context 220k / 1M · 22%). The last question shown is the user's own report message; cwd `…\worktrees\silly-knuth-a6a8db`, branch `…and-display-name-config-6cf145`.
- 「→ 跳到对话」 → `pet-55716.log`: `20:02:30,833 会话跳转 agent=claude session=9f597df0 ok=True：已跳到 Claude 桌面版里的这个对话`. The foreground window became `Claude`, and its title bar switched to the conversation **"Island display name configuration"**.
- No terminal: `Win32_Process` shows no `cmd.exe` or `WindowsTerminal.exe` created in the 3 minutes around the click (only background `conhost.exe` from concurrently running tool commands).

A first attempt at 20:00 hit nothing: the user moved the mouse between the two clicks and the card closed. It is recorded here because it explains the two clicks a few minutes apart in the log.

### Tests run, and why the full suite was skipped

Ruff: `ruff check pet tests` → All checks passed.

Focused + affected families (offscreen, temporary `APPDATA`): `test_overlay_session_pets`, `test_session_jump_desktop`, `test_session_jump_terminal_tab`, `test_session_jump_workspaces`, `test_session_pet_details`, `test_session_history_service`, `test_island_session_history`, `test_claude_session_history`, `test_session_card_metro`, `test_session_fish_decisions`, `test_claude_link`, `test_i18n`, `test_overlay_spawn` (shell construction path), `test_architecture` → **376 passed, 1 failed**. The failure, `test_session_card_metro.py::test_host_icons_are_warmed_at_the_cards_size`, also fails on a clean checkout of base `177b256c` (re-run there in a throwaway worktree), so it is pre-existing.

The full suite was skipped per the user's standing rule (2026-11-14: run only the new tests plus the families the change affects). The change is confined to the session-fish controller, its UI actions, the desktop jump helper, two locale strings and one shell wiring line. No shared config schema, persisted format, threading model or platform branch changed. The conftest change only extends an existing fixture's body, so the fixture count, the known trigger of the latent full-suite crash, stays the same.

**Not verified here**: WSL sessions. `claude_wsl` is also off on this machine, and the run-list pass reads only the local list (WSL needs `wsl.exe`), so a running WSL conversation still shows as frozen while that link is off. The `claude://` launch fallback (no Claude window up) was not exercised live, because the desktop app is always running on this machine.
