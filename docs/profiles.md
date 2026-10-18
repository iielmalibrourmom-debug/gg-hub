# 配置、导入导出与 X11 自动切换

GG HUB 配置保存的是期望设置。**保存、选为当前配置、驱动接受设置、真实设备行为正确**是不同结果。配置名旁的 Active 表示软件当前选择，不保证所有已保存设备都连接着或已成功应用。

新配置目录默认包含 `id: "desktop"`、`name: "DESKTOP"` 的桌面配置，其 `deviceSettings` 为空，且默认选中。用户可以删除它；删除当前配置后 `activeProfileId` 为 `null`，不会暗中选择另一个配置或重新写入设备。之后只有显式新建/导入才会恢复已删除的配置。

## 在界面中使用

1. 打开 **Games & Profiles → New profile**，填写名称。游戏名是显示标签；自动切换使用 executable 字段。
2. 在设备页面应用并确认需要的设置。点击 **Capture settings**，把当前连接的 ratbagd 设备的活动 DPI 与回报率保存到所选软件配置。
3. 选择 **Activate**，查看应用结果。未连接、无权限、驱动不支持、写入失败时不会报告成功。

当前 Capture settings 只采集 ratbagd 的活动硬件槽位、活动 DPI 档位、DPI 与回报率。它不是设备全部设置的完整备份：不采集灯效、每个按键、其它 DPI 档位或 Solaar 设置。捕获会替换所选配置原来的 `deviceSettings`，不要将它当作追加合并。

设备 ID 来自当前驱动枚举。恢复系统、重新连接或驱动变更后应重新检测设备并核对配置，不要假设旧 ID 一直指向同一实物。是否可写取决于连接设备及驱动能力，与参考设备目录中的产品条目无关。

## 后端配置格式

`profiles.save` 直接接受下列对象。省略 `id` 时生成 UUID，更新时使用原 `id` 并发送完整配置。可选的 `game` 和 `executable` 在不需要时应省略，不传空字符串。

```json
{
  "id": "my-game",
  "name": "Low sensitivity",
  "game": "My Game",
  "executable": "my-game-binary",
  "deviceSettings": {
    "/org/freedesktop/ratbag1/device/example": {
      "profile": 0,
      "resolutionIndex": 1,
      "dpi": [800, 800],
      "reportRate": 1000,
      "activateProfile": true,
      "activateResolution": true
    }
  }
}
```

上例设备 ID 和数值都是结构示例，请使用 `hardware.devices` 返回的实际 ID、索引和支持范围。每个 `deviceSettings` 值是该设备的 `hardware.configure` 参数，不需要再包含 `deviceId`。当前 worker 最多对 32 台设备发起一次配置应用；仅有配置内容不代表这些设置受到设备支持。

`profiles.activate {"id":"my-game"}` 先原子保存软件当前选择，再调用硬件后端。每台设备的结果分别返回，例如：

```json
{
  "activeProfileId": "my-game",
  "saved": true,
  "hardware": {
    "attempted": true,
    "result": {
      "/org/freedesktop/ratbag1/device/example": {
        "applied": false,
        "error": {"code": "DEVICE_NOT_FOUND", "message": "Device is not connected"}
      }
    }
  }
}
```

`hardware.result` 是按设备 ID 索引的对象，不是数组或统一的成功布尔值。没有设备设置时返回 `hardware.applied:false` 与原因。部分设备应用失败不会回滚其它设备已经完成的写入。

硬件 I/O 在配置锁之外执行，宏停止与本地状态读取可以同时响应。停止自动切换不强行取消已经开始的设备写入，避免在驱动暂存与提交之间中断操作；它只停止后续自动匹配。在途应用仍可能完成，因此停止切换并不等于撤销刚刚开始的硬件修改。

## X11 自动切换

在 **Settings → Automatic profile switching → Start** 显式启动。保存 `autoSwitch:true` 只是保存偏好，不会在后台悄悄启动；重新打开应用或导入配置后仍需手动 Start。

条件为 Linux、有效 X11 `DISPLAY` 与已安装的 `xprop`（Arch 包 `xorg-xprop`）。后端通过固定参数调用 `xprop`，读取活动窗口的 `_NET_WM_PID`，再读取 `/proc/<pid>/exe`。配置中没有任何内容会被当作命令执行。

- executable 填 Linux 程序**文件名**或**绝对路径**，例如 `cs2` 或 `/opt/game/bin/game`。不填启动参数、Shell 语法或启动器命令。
- 文件名与当前前台程序路径末段精确匹配；绝对路径精确匹配整个路径。比较区分大小写，不按显示的游戏名模糊搜索。
- 多个配置匹配同一程序时，选择保存顺序中第一个匹配项。
- 离开匹配程序后，若仍存在未设置 executable 的 `desktop` 配置，返回该桌面配置；没有它时保留当前选择。
- 默认每 1000 ms 检查一次。`settings.update {"pollIntervalMs":250}` 等可设置 250–10000 ms 的整数间隔。
- 窗口没有可读 PID、权限限制、容器、Wine/启动器等场景可能无法识别预期程序，应手动选择配置，不保证所有游戏都被识别。

Wayland 的 KDE、Sway、Hyprland 等前台程序协议当前未实现。检测到 `WAYLAND_DISPLAY` 时 Start 明确拒绝，不使用 Xwayland 的不完整窗口列表冒充完整支持。手动配置与驱动设备设置仍可独立使用。

`automation.status` 提供 `running`、`enabled`、`protocol`、`foregroundExecutable`、`lastError` 与 `activeProfileId`。`running` 只表示监视任务运行；具体设备应用失败会写入 `lastError`。不会对同一前台配置持续重试失败的写入；修复连接后可手动重新应用，或停止/重新启动自动切换。

## 本地存储与导入导出

配置以 schema version 1 的 JSON 文档写入 `automation.json`。Electron 使用它的 userData 目录下的 `config/`；单独运行 Python worker 时使用 `GG_HUB_CONFIG_DIR`，未指定则为 `$XDG_CONFIG_HOME/gg-hub` 或 `~/.config/gg-hub`。请用应用的 **Export** 导出，避免依赖特定安装方式的路径。

写入先在同目录创建临时文件、flush/fsync，再以原子替换提交。无效现有配置不会被自动重置覆盖；后端会明确报告加载失败。原子替换能避免部分写入，不替代备份，也不保证磁盘故障时数据永远不丢失。

**Export** 输出整个配置文档，包括所有软件配置、宏、当前软件选择与偏好。**Import** 完整替换这些内容，**不合并**。导入会停止正在执行的宏和自动切换；不会自动应用新配置到设备，也不会根据导入的 autoSwitch 偏好自动重启监视任务。已经开始的硬件写入仍可完成。导入前可先 Export 保留旧配置。

```json
{
  "schemaVersion": 1,
  "profiles": [{"id":"desktop","name":"DESKTOP","deviceSettings":{}}],
  "macros": [],
  "activeProfileId": "desktop",
  "settings": {"autoSwitch":false,"pollIntervalMs":1000,"macroTimeoutSeconds":60}
}
```

导入验证字段、版本、重复 ID、引用与大小。ID 为 1–64 个 ASCII 字母/数字、下划线或连字符，首字符必须为字母或数字；不能携带路径。名称为 1–120 个可打印字符，最多 256 个配置、256 个宏。文档和 RPC 都有 1 MiB 限额，接近限制的导出文件也可能因请求编码开销超过 RPC 限额。原版 G HUB 数据库、Lua 文件和其它 schema 不兼容。

配置/宏回归测试验证存储、边界与状态机；X11 和硬件均未在当前 Windows 构建宿主上完成 Linux 实机验证。
