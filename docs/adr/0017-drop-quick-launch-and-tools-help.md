# 0017：右键菜单的「快捷启动」和「工具与帮助」整个删掉

日期：2026-11-18

## 背景

右键菜单里有两项用户不再需要：

- 「快捷启动」：在设置里配几个程序（默认只有「默认浏览器」），右键一点就打开。有自己的模块、一页设置
  （带拖动排序的编辑器）和配置键 `quick_launch_apps`。
- 「工具与帮助」：一个子菜单，里面只剩「GitHub 项目页」，打开的还是 fork 之前的上游仓库地址。

用户说这两个选项和用到的代码都清掉。

## 决定

照 [0016](0016-drop-screen-watching-and-file-interpret.md) 的做法整块删，不按 [0012](0012-retire-the-entry-keep-the-code.md) 只摘入口：

- 删 `pet/context_menus/quick_launch.py`、设置页「菜单 → 快捷启动」一栏和它的编辑器、配置键 `quick_launch_apps`
  （旧配置读进来就丢，下次保存消失）、「GitHub 项目页」和上游地址常量；
- 三个菜单 id 进丢弃清单：动作 `quick_launch`、`github_project`，子菜单 `tools_help`（连壳清掉），
  旧的菜单编排加载时自动去掉；
- 别处还在用的裁图标函数 `fitted_application_icon` 挪到 `pet/context_menus/icons.py`；
- `tests/test_retired_features.py` 守着这些不回来。

## 后果

- 想快速打开某个程序，只能走系统自己的入口；肥鱼不再管程序列表。
- 用户在旧编排里放进「工具与帮助」的别的菜单项，会随这个子菜单一起被清掉（默认编排里它只有项目页一项）。
- 默认菜单只剩一个子菜单「肥鱼控制」。
