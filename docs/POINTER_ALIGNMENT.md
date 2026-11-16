# WSLg 鼠标视觉位置与实际点击位置偏移

记录日期：2026-11-16。当前本机已装载修复并完成下面列出的验证。
该修复是项目自定义 Weston 补丁，不是微软官方发布版本。

## 原因与修复

本次在原生 Wayland、Mesa D3D12 的校准窗口中，点击坐标换算本身准确。
问题位于 `rdp_rail_update_cursor()` 对光标图像和热点的处理：

1. 原代码从光标 buffer 像素尺寸出发，再乘显示器的 client scale。
   客户端已提交高分辨率 buffer 时，会再次放大光标。
2. Wayland 的 `hotspot_x/y` 使用 surface 逻辑坐标。原代码直接将其写入
   RDP 光标 bitmap 的像素坐标字段，没有和图像同步缩放。
3. 只变更热点、没有图像 damage 或尺寸变化时，原代码不一定发送更新。

这会使光标图形显示在实际点击位置的右侧或右下方；用户就会感觉点击偏左。
偏差随光标形状、热点和倍率变化，不宜用固定的鼠标坐标偏移量处理。

补丁 [`0004-rdprail-scale-cursor-hotspot.patch`](../patches/weston/0004-rdprail-scale-cursor-hotspot.patch)：

- 从 surface 逻辑尺寸计算发送到 Windows 的光标 bitmap 尺寸，避免重复计算 buffer scale。
- 将逻辑热点按最终 bitmap 尺寸换算、取整并限制在 RDP bitmap 的有效范围内。
- 缓存上次发送的热点；热点单独变化时也更新光标。
- 保留原来的输入坐标转换，不添加固定偏移量。

新增补丁只修改 `libweston/backend-rdp/rdp.h` 和 `rdprail.c`，
新增 36 行、删除 5 行（包含注释和空行）。前三个 Weston 补丁保持原样。
新增字段位于后端私有 `RdpPeerContext`，未更改 RAIL shell 使用的公开结构布局。

## 测量结果

测试光标逻辑尺寸为 24×24，逻辑热点固定为 (8,8)。

| 输出及光标 buffer scale | 修复前 Windows bitmap / 热点 | 修复后 Windows bitmap / 热点 |
| --- | --- | --- |
| 主屏，buffer scale 1 | 48×48 / (8,8) | 48×48 / (16,16) |
| 主屏，buffer scale 2 | 96×96 / (8,8) | 48×48 / (16,16) |
| 副屏，buffer scale 2 | 48×48 / (8,8) | 24×24 / (8,8) |
| 副屏，buffer scale 1 | 本轮未保留修复前测量 | 24×24 / (8,8) |

主屏为 3840×2160、Windows 200%，当前 Weston clientScale 为 2。
副屏为 1080×1920、Windows 125%，当前 Weston clientScale 为 1。
表格按实际测得的 WSLg clientScale 解释，不能把 Windows 的 125% 直接当作 1.25。
本次没有修改系统缩放设置。

修复后两个光标 buffer scale，分别在两块屏幕各点击 3×3 九点，
合计 **36 点**。Wayland 收到的坐标全部精确符合预期：
`x ∈ {64,240,416}`、`y ∈ {64,160,256}`。
同时用 Windows `GetIconInfo()` 核对每次的 bitmap 尺寸及热点。
测试程序的实际 GL renderer 为 `D3D12 (AMD Radeon 780M Graphics)`。

跨屏使用校准程序顶部拖拽区域，发送真正的 `xdg_toplevel.move`。
不要用 Windows API 的强制移窗作为 WSLg 点击几何的测试依据：
本轮发现它可能只改变 Windows 窗口位置，未同步 Weston 输入几何，造成测量失真。

原版应用补充检查：`dpkg --verify chatgpt` 返回 0 且没有输出；
使用原有 Wayland/IME v1/D3D12 wrapper 启动。
实际鼠标移到应用内最小化按钮后点击，通过 Windows 托盘图标恢复，
恢复后帮助菜单可点击并正常绘制。本轮只覆盖一次这个入口，
不据此声称穷尽了所有最小化、输入法及文件对话框场景。

## 当前装载与生产配置

本次仅将新构建的 **`rdp-backend.so`** 投入使用。
RAIL shell、libweston-desktop、IME relay、Fcitx addon、服务配置和应用 wrapper
继续使用之前的生产版本；未修改应用安装文件。

新后端相对项目根目录：

```text
runtime/wslg-1.0.79-pointer-production-20261116/rdp-backend.so
186688 bytes
SHA256 38c4121ebbecb75f8a069e5886191d09278a85dde57b781036f2cc1a89f6e7ff
```

使用 `-O2` 编译，最终文件经过 strip，无 `.debug_*` 段；
调试符号保留在候选构建的私有 `.build` 目录中，未装载到生产。
已使用 WSLg 系统发行版实际的 `ldd -r` 检查，没有缺失库或未定义符号，
没有新增 RPATH/RUNPATH，GLIBC 要求不高于系统的 2.38。
重启 WSL 后核对了 Weston 的真实进程映射，而非只检查配置文本。

`.wslgconfig` 只替换一个后端路径。用实际绝对路径替换以下占位符：

```ini
[system-distro-env]
XDG_CONFIG_HOME=<ACCEPTED_IME_RUNTIME>/config
WSLG_IME_BRIDGE_SOCKET=/mnt/wslg/runtime-dir/wslg-ime-v1/bridge.sock
WESTON_MODULE_MAP=rdp-backend.so=<POINTER_RUNTIME>/rdp-backend.so;rdprail-shell.so=<ACCEPTED_IME_RUNTIME>/rdprail-shell.so
WESTON_RDP_DEBUG_LEVEL=2
WESTON_RDPRAIL_SHELL_DEBUG_LEVEL=2
WESTON_RDP_DEBUG_CLIPBOARD_LEVEL=0
```

`<POINTER_RUNTIME>` 对应上面的新目录；`<ACCEPTED_IME_RUNTIME>` 对应
`runtime/wslg-1.0.79-ime-production-20261114`。
配置值中的占位符是文档语法，WSLg 不会自动展开。
日常启动应用无需增加鼠标参数。

## 复现与回归

按顺序应用 Weston 补丁 0001–0004 后，在 Ubuntu 中：

本轮还核对了四个补丁的完整复现：将历史源文件及补丁暂存副本统一为 LF
后，使用 `patch --fuzz=0` 顺序应用；所有被修改文件与实际构建源码一致
（忽略 CRLF/LF 的字节差异）。根目录历史补丁保留原样，
如果直接应用时出现 `different line endings`，先统一暂存副本的行尾，
不要通过增加 fuzz 或手工跳过 hunk 掩盖失败。

```bash
WESTON_CURSOR_SOURCE=/absolute/path/to/patched/weston \
  python3 -m unittest discover -s tests -p test_weston_cursor.py -v
```

该测试从真实 `rdprail.c` 提取热点换算及完整 cursor-update 函数，
用可控 RDP/renderer 边界执行 8 类场景：包括两种输出倍率和 buffer scale、
未变化时不重复发送、只改变热点、无 output、热点边界、隐藏光标和读回失败。
它是函数级回归，GPU/Wayland 接受测试使用独立的真实窗口。

[`tests/wslg_pointer_probe.c`](../tests/wslg_pointer_probe.c) 是真实窗口的源码。
在独立构建目录生成 `xdg-shell-client-protocol.h` 和 `xdg-shell-protocol.c`：

```bash
wayland-scanner client-header \
  /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml \
  xdg-shell-client-protocol.h
wayland-scanner private-code \
  /usr/share/wayland-protocols/stable/xdg-shell/xdg-shell.xml \
  xdg-shell-protocol.c
cc -O2 -Wall -Wno-missing-field-initializers -I. \
  /absolute/path/to/project/tests/wslg_pointer_probe.c xdg-shell-protocol.c \
  -o pointer-probe $(pkg-config --cflags --libs egl glesv2 wayland-egl wayland-client)
GALLIUM_DRIVER=d3d12 ./pointer-probe --cursor-scale 1
# 退出后，以 --cursor-scale 2 重测。
```

该窗口只记录自身的 pointer 事件，不记录键盘或剪贴板。
若 GL renderer 不是 D3D12，它会退出，避免将软件渲染结果算作接受测试。
鼠标拖动顶部橙色区域可以跨屏测试；程序最多运行 20 分钟。
本轮覆盖普通方向、无裁剪的光标；旋转光标 buffer、viewport 裁剪、
远程桌面重连及其他 DPI 配置未逐项验证。

## 版本、后续更新与回退

本轮基线：WSL 3.0.5.0，WSLg 1.0.79，MSRDC 1.2.7391，
Ubuntu kernel `6.18.58.1-microsoft-standard-WSL2`，Weston 9.0.0，
Weston commit `a7e35fdab455dce5774b43b8aff682f748307e31`，
FreeRDP commit `c4030980b29322a9cb2190711a5fadeeeb8b6a33`。

Private measurements, build commands, configuration backups and live module
maps were saved locally. The initial maintenance snapshot was healthy and the
final fingerprint/mapping check was unchanged. Raw records are not published.

Other deployments should create their own private baseline using the
[WSL update maintenance guidance](MAINTENANCE.md). Review WSLg/Weston/FreeRDP
versions, component hashes, actual loaded paths and behavior after updates.
Successful loading alone does not establish ABI or behavioral compatibility.

This deployment changes only the RDP backend path in `.wslgconfig`.
To roll back, restore your own previously accepted backend path, preserve the
other module mappings and IME settings, save WSL work, and restart WSL.
Do not overwrite unrelated configuration changes made since your backup.
Machine-specific rollback scripts, configuration backups and runtime modules
are not included in this public repository.
