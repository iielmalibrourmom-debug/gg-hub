# 宏的使用与执行边界

GG HUB 提供软件播放和兼容设备的按钮宏。**Macros → Run** 通过 `python-evdev` 创建 `/dev/uinput` 虚拟输入设备，发送实际按键；用 **Stop** 停止。没有完整 G-key 监听器或全局快捷键。

**Devices → Assignments → Saved macros** 可以将单次宏绑定到 ratbagd 声明支持 MACRO 动作的按钮，编译为驱动事件并提交到设备。仅支持 `noRepeat` / `sequence`，最多 512 个展开事件及 300 秒延时，必须成对释放按键。驱动读回不证明实际触发或断电持久性，仍需实物验证。循环/toggle 使用软件播放。

浏览器与 `--preview` 模式只提供编辑预览，不执行宏。Windows 上的执行请求会明确失败。界面保存成功只表示宏已保存在本地，不能证明输入已发送。

## 权限与准备

- 按仓库安装说明安装 Linux 后端依赖，包括 `python-evdev`，并使 `uinput` 内核模块与 `/dev/uinput` 可用。
- 管理员安装设备权限规则后，按说明重新登录或重新加载设备，使当前用户获得规则授权。**使用普通用户启动 GG HUB**，不要用 `sudo` 启动 Electron，也不要通过禁用 Electron sandbox 解决输入权限。
- 规则配置完成后，普通用户可以用 `test -w /dev/uinput` 检查是否具有写入权限。可写仍不代表所有 uinput 操作一定成功；GG HUB 会报告实际打开或写入错误。
- 宏输入发给当前会话中的前台应用，不会按 GG HUB 配置的游戏名定向投递。先在可以丢弃内容的文本编辑器中验证自己的序列。

设备硬件支持和软件宏执行是两个独立条件。鼠标出现在设备目录中，不代表它支持板载宏或已经通过实物测试。

## 创建与播放

1. 打开 **Macros → Create macro**，输入名字。
2. 添加 **Key**、**Delay** 或 **Text** 步骤，保存。
3. 选择播放模式，点击 **Run**。运行期间可以点击 **Stop**。
4. 查看状态与错误。`completed` 表示输入步骤执行完并完成清理；它不证明目标游戏接受了这些输入。

按键名使用 Linux evdev 名称，例如 `KEY_A`、`KEY_LEFTCTRL`、`KEY_F1` 和 `BTN_LEFT`；`A` 也会规范化为 `KEY_A`。实际播放前会检查键名是否为本机 evdev 支持的输入键。

| 模式 | 当前行为 |
| --- | --- |
| `noRepeat` | 按顺序执行所有步骤一次 |
| `sequence` | 按顺序执行所有步骤一次；不是原版按下/释放分段序列的完整兼容实现 |
| `repeat` | 重复执行，直到手动停止、时间上限或 1000 次循环上限 |
| `toggle` | 首次启动持续循环；运行中再次调用 `macros.run` 会停止。界面运行时提供 Stop 按钮 |

默认执行时间上限为 60 秒。在 **Settings → Macro execution limit** 中可以保存 1–300 秒的上限。循环之间会释放本宏仍按下的键，并至少让出 10 ms；循环宏不能无限运行。

## 步骤格式

后端 `macros.save` 的参数直接是宏对象。没有 `id` 时生成 UUID；更新已有宏时使用原来的 `id` 并提交完整对象。

```json
{
  "id": "copy-example",
  "name": "Copy selection",
  "mode": "noRepeat",
  "steps": [
    {"type": "key", "key": "KEY_LEFTCTRL", "action": "down"},
    {"type": "key", "key": "KEY_C", "action": "tap"},
    {"type": "key", "key": "KEY_LEFTCTRL", "action": "up"},
    {"type": "delay", "ms": 100}
  ]
}
```

- `key` 的 `action` 为 `down`、`up` 或 `tap`。`tap` 会发送按下和释放。
- `delay` 的 `ms` 必须是 0–60000 的整数。单次完整序列的延时总和最多 300 秒，实际执行仍受配置的时间上限约束。
- `text` 为 `{"type":"text","text":"Hello!"}`，只支持 1–1024 个可打印 ASCII 字符。按键按 **美式键盘物理布局** 映射，不能保证非 US 布局、Caps Lock 或外部修饰键状态下输出相同文本；不支持中文、Unicode、换行、Tab 或剪贴板注入。需要 Enter/Tab 时分别使用 `KEY_ENTER` / `KEY_TAB` 步骤。
- 每个宏为 1–512 步，最多保存 256 个宏，最多同时运行 8 个。
- 不接受 Lua、Shell 命令、启动程序或任意脚本步骤。

`macros.run {"id":"copy-example"}` 只有在 uinput 输入设备已经打开、所有键名校验通过后才返回 `started:true`。后台任务稍后仍可能因输入错误或超时失败，请通过 `macros.list` 的 `runs` 查看最终状态。

```json
{
  "macros": [],
  "runs": [
    {"id":"copy-example","state":"completed","error":null,
     "iterations":1,"startedAt":0,"endedAt":1}
  ]
}
```

时间字段为 Unix 秒，上面的 0/1 仅演示结构。运行记录留在当前后端进程的内存中，不跨重启保存。

## 停止与错误

取消、正常完成、超时和写入失败都会进入清理流程，尝试释放本次宏按下的全部键并关闭专用虚拟输入设备。某个键释放失败时仍继续清理其它键，并记录错误。`failed` 与错误消息会显示在宏列表中，不会把执行失败报告为完成。

应用正常退出时先停止宏、释放输入，再等待在途硬件配置结束。操作系统强制终止进程与设备拔除无法由单元测试证明其所有实际行为。

当前回归测试使用注入的输入接收器验证取消释放、写入失败清理、即时停止、文本映射、上限和并发响应；它们不会向测试宿主发送真实输入，也不构成 Linux uinput 或游戏兼容性实测。
