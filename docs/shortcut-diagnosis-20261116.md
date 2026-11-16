# WSLg 原生 Wayland 下 Ctrl 快捷键丢失：2026-11-16

## 原因与验证

测试环境使用 Ubuntu 和 Fcitx5 `5.1.7-1build3`。在已经部署的可信 Wayland
输入法连接中，应用启用 text-input-v1 后，键盘先由 Fcitx 处理，未被消费的
按键再交回 Weston。旧版 WaylandIM 模块交回了 `c`、`z` 的按下/抬起事件，
却没有交回 Ctrl 等修饰键状态，应用因此无法把它们识别为 Ctrl+C、Ctrl+Z。

同一实时 WSLg 会话、同一个原生 Wayland 诊断客户端，对比结果如下：

| 路径 | c/z 按下时的 Ctrl 状态 |
| --- | --- |
| 不启用原生输入法协议 | true |
| 启用 v1 输入法，原始 Fcitx 5.1.7 | false |
| 启用 v1 输入法，回补后 | true |

本轮未发现需要调整的 Ctrl+C/Z 输入法热键冲突。上述对比将已经复现的问题
定位在修饰键转发链路，不能据此断言所有 Windows 保留快捷键都能透传。

## 实际改动

回补 Fcitx 上游 5.1.13 源码中已有的请求，在
`WaylandIMInputContextV1::modifiersCallback()` 末尾增加：

```cpp
ic_->modifiers(serial_, mods_depressed, mods_latched, mods_locked, group);
```

补丁见 `patches/fcitx5/0001-waylandim-v1-forward-modifiers.patch`。
本轮没有重新编译 Weston，也没有修改 ChatGPT 包文件、wrapper、GPU 参数、
`.wslgconfig`，也没有直接改写 Fcitx 的 profile/词库文件。

仅为该 Fcitx 5.1.7 版本编译 WaylandIM 模块及其私有协议封装，继续链接 Ubuntu
已经安装的 Fcitx core/config/utils。将 stripped Release 模块放在：

```text
~/.local/lib/wslg-ime/fcitx5-5.1.7-shortcuts-20261116/
```

模块大小 651,680 字节，约 636 KiB；没有 `.debug*` 或 `.gnu_debuglink` 段。
这是定制回补构建，不是官方 release 二进制。系统包原有
`/usr/lib/x86_64-linux-gnu/fcitx5/libwaylandim.so` 的哈希保持不变。

新增用户服务 drop-in：

```text
~/.config/systemd/user/wslg-ime.service.d/20-shortcut-modifiers.conf
```

它在原 supervisor 前增加 `guarded_session.py`，仅向该服务提供
`FCITX_ADDON_DIRS`。守卫核对 Fcitx 相关包版本和本地模块 SHA-256；版本或
哈希不一致时记录提示，并使用系统模块启动，避免升级后强行加载旧模块。
原 `wslg-ime.service` 文件及生产 supervisor 快照未改写。

启用时只执行了用户服务的 daemon-reload/restart，没有关闭 WSL。部署验证时服务为
active，自动重启次数为 0，进程 maps 已确认加载用户目录中的新模块。
默认日志级别和 `key_trace=0` 保持原生产设置。

为了编译新增了 8 个开发/构建依赖包，共约 50.7 MB 安装空间：
`cmake`、`cmake-data`、`extra-cmake-modules`、`libjsoncpp25`、`librhash0`、
`libfcitx5core-dev`、`libfcitx5config-dev`、`libfcitx5utils-dev`。
没有升级既有运行时包。

## 已完成与尚未完成的验证

- 实时按键日志确认 Ctrl+C、Ctrl+Z、Ctrl+A、Ctrl+Shift+Z 的修饰状态正确；
  抬起按键后状态恢复。
- 同一 v1 输入窗口启用拼音后成功提交固定测试文本“你好”，随后
  Ctrl+C/Z/A/X/V 仍带有 Ctrl 状态。测试后恢复原输入法选择和启用状态。
- 4 项守卫自动化测试通过，另以独立进程确认异常回退会清除继承的 addon 覆盖。
- 原版 ChatGPT 窗口未能通过 Windows 自动化取得前台，因此自动化未向其内容
  发送编辑按键。用户后续反馈 Ctrl+C 等 Ctrl 组合键已正常；这属于用户验证，
  不应表述为自动化完成了原版应用的复制/撤销验收。

诊断客户端采用 SHM 绘制纯色窗口，用于隔离输入问题。这些是按键协议验证，
不是 GPU 渲染验收。原版应用原有 Wayland+D3D12 启动设置保持原样。
升级后的回归检查可在实际 ChatGPT 空白输入框验证 Ctrl+A/C/V、Ctrl+Z、
Ctrl+Shift+Z 及中文输入，无需发送消息。

### Ctrl+空格与宿主系统的热键冲突

用户随后反馈，只有 Ctrl+空格不能触发，改成 Ctrl+Shift 后正常。对 Windows
IME 的只读接口查询确认，宿主输入法已将 Ctrl+空格注册为输入法开关热键。
这与此前 Fcitx 修饰键丢失是两个不同层面的问题；被 Windows 消费的按键，
WSLg 中的 Fcitx 无法继续处理。本次没有修改 Windows 热键配置，也没有额外
发送 Ctrl+空格做宿主拦截实测。保留用户已验证可用的触发键即可。

原始日志只记录白名单按键、修饰键掩码和固定测试文本是否匹配的布尔值，
没有记录任意输入内容或读取剪贴板。截图、原始日志、二进制和本地清单
不随源码发布；公开仓库仅保留源码、测试和经过隐私检查的技术说明。

## 回退

```sh
rm -- "$HOME/.config/systemd/user/wslg-ime.service.d/20-shortcut-modifiers.conf"
systemctl --user daemon-reload
systemctl --user restart wslg-ime.service
```

仅删除本轮新增的 drop-in；不应使用会清空其他用户配置的 `systemctl revert`。
回退后 5.1.7 的快捷键问题可能再次出现。以后升级 Fcitx 时，应核对系统版本、
守卫提示、实际加载路径和按键/中文回归结果，再决定是否移除此回补。

完整构建、部署配置模板与上游源码依据见
[WaylandIM 回补说明](../tools/ime/fcitx-waylandim/README.md)。
