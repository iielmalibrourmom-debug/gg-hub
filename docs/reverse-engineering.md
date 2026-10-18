# 原版静态调查与证据边界

## 当前目标

GG HUB 的当前实现范围是鼠标、键盘的重要功能：DPI、回报率、按键分配、宏、配置文件、灯光、电量；按 Linux 驱动实际暴露的能力显示与启用。完整复刻所有原版设备与功能已不属于本阶段交付承诺。目录记录、界面入口、驱动能力和实物验证是四种不同证据。

## 样本与方法

- 样本版本：Logitech G HUB **2026.6.981214**，本地 build **876190**。
- UI 样本：`resources/app.asar`，**19,435,212 bytes**，SHA-256 `5bcb683032410c4fc35462822751fcb1429d4da7cebfa57cda688d9468401875`。
- REA retained parent evidence：`ev_810ab39ec728c37d0ca55d9dfa1c5bf8e1d83c78b47727b063910d2cef3f90cf`。REA summary 的语义覆盖因 heap 限制为 **partial**，未以此声称完整分析。
- 补充方法：按 ASAR header 的成员 offset/size 只读抽取所需 CSS、JavaScript 的静态文本；不执行原版脚本。仅记录颜色、布局尺寸、功能名称、协议标识符等事实，不将原版 JS、CSS、字体、图片、密钥或用户配置放入项目。
- 静态调查没有启动应用、请求原版本地服务、向外设发报告或观察 Linux 上的硬件行为。

## Observed：UI 与协议

ASAR 共 **267** 个文件。主要成员是 `app.min.js`（7,369,426 B）、`app.min.css`（1,132,853 B）、`main.js`（836,162 B）、`858.min.js`（600,102 B）；另有 `index.html`、`preload.bundle.js`、`marketplace.bundle.js`、DPI tester 与 `assets/`。安装清单只指向一个 UI ASAR；安装缓存另有同大小副本。

CSS 中存在设备卡片、导航、设备画布分配覆盖层、灵敏度与灯光组件。导航 surface 的静态样式宽度为 `20rem`、顶部 padding 为 `4rem`；设备卡片 max-height 为 `450px`。这些数值是局部样式声明，不代表已验证的整页截图尺寸。

静态颜色参考：黑色背景；深灰 `#212225`、`#181818`、`#242424`；白字；次要文字 `#a7a7a8`、`#afb1b4`；蓝色 `#00a9e0`、`#00b8fc`。DLS 默认 token 另含 primary `#1196ff`、secondary `#9e5dff`、tertiary `#ff5e01`、error `#f54155`。多个样式系统共存，不能把频率当作当前页面实际采用的主题。

字体名称引用 BrownLogitechPan、BrownPro Regular/Light/Thin/Bold。项目使用可用的系统字体近似；未复制原字体。

`main.js` 存在 `ws://localhost:9010`、`json` 子协议与 JSON 消息 `path` / `verb` 字段。前端包含下列路径字符串：

| 功能 | 静态标识符示例 |
| --- | --- |
| 设备枚举与信息 | `/devices/list`、`/devices/model/info`、`/devices/state/changed` |
| DPI | `/mouse/%(id)s/dpi_shift`、`/mouse/%(id)s/dpi_tune/start`、`/mouse/%(id)s/dpi_correction` |
| 回报率 | `/report_rate/%(id)s/report_rate_list`、`/wireless/%(id)s/report_rate` |
| 分配与 G-Shift | `/assignment/list`、`/input/gshift` |
| 宏 | `/macros/validate`、`/onboard_profiles/%(id)s/macros/validate` |
| 配置与板载模式 | `/profiles`、`/profile/active`、`/profiles/auto_switching`、`/onboard_profiles/%(id)s/onboard_mode` |
| 灯光 | `/lighting/%(id)s/state`、`/lighting/%(id)s/brightness`、`/lighting/effect/presets` |
| 电量 | `/battery/%(id)s/state`、`/battery/state/changed` |
| 特殊开关 | `/analog/%(id)s/rapid_trigger_state`、`/input/%(id)s/fn_inversion` |

静态常量还含 `RAPID_TRIGGER`、`ACTUATION_POINT`、`MOUSE_SENSITIVITY`、`ONBOARD_LIGHTSYNC_CONFIG_UPDATED`。以上证明程序包含这些标识符，不能证明每款设备具备功能、请求参数、写入成功或 Linux 可使用原版服务。GG HUB 的 Linux 后端独立使用驱动实际提供的接口。

## Observed：目录抽取

输入是安装资源 `core/data/devices.json` 与它列出的相对文件，未读取用户数据库。运行：

```sh
node tools/extract-catalog.cjs --source /path/to/core/data --output data/device-catalog.json --source-version 2026.6.981214 --build-id 876190
```

工具依赖 Node 标准库。所有输入均限制在 source 下，拒绝路径逃逸；输出只含相对资源名、SHA-256、事实字段、抽取时间与版本。可在不同机器复核 `metadata.sourceDigest`；生成时间不同不会改变该输入摘要。

本次结果：

| 项目 | 数量 / 状态 |
| --- | --- |
| 索引引用 | **77** |
| 可解析 JSON 文件 | **7** |
| 不透明二进制封套 | **69** |
| 缺失引用 | **1**：`devices/devices_0073.json` |
| 明文设备声明（所有类型） | **70** |
| 筛选后的 MOUSE | **28** |
| 筛选后的 KEYBOARD | **14** |
| `catalogKnown` 条目合计 | **42**，包括 G502 HERO |
| Linux 实物验证 | **0** |
| 目录完整性 | **incomplete** |

源摘要：`a6736591bab8a46bb92ba0d021bb00845f317f6adf2201733105f84b253262d2`。

每项提取型号、名称、类型、接口 ID、能力 key，以及声明中存在的 DPI 范围/档位、回报率、灯光效果、输入类别与层、板载模式等简明设置事实。未声明的范围保持缺失，不从其他型号猜测。衍生型号放入 `variants`，不默认为已经实测。`catalogKnown: true` 仅表示来自可读原版目录；`hardwareSupport: unverified` 明确表示目录没有提供 Linux 支持证明。

## Inferred：封套格式

不透明文件的已观察结构是：4 bytes magic `21 05 21 20`，LE uint32 JSON header 长度，JSON header（字段 `key-id`、`file-sha`），再接一个 LE uint32 payload 长度和 payload。抽样文件的长度字段与实际剩余长度相符。

原版 agent 的相邻静态字符串包含封套解析错误、AES-128-GCM 错误和 LZMA 解压错误。**推断**这些组件可能用于资源解码，但尚未通过得到有效 JSON 且匹配 `file-sha` 的结果确认具体 cipher、IV、压缩顺序或完整格式。有限的离线候选未获得符合双重验证条件的结果。本阶段抽取器明确将其标为 opaque，不尝试未经确认的解密，也不读取或公开资产密钥。

## Unknown 与后续验证

- 69 个封套及缺失文件中的设备/功能内容；42 条目录不是全体原版支持清单。
- 原版路径的完整参数、状态机与硬件协议；字符串不是协议实现。
- 不同鼠标/键盘在 ratbagd、Solaar 或 hidraw 下的实际可读写能力与版本差异。
- 当前 Windows 环境不能提供 Arch/Linux 硬件运行证据；WSL 未安装。测试或 CI 能验证构建与解析逻辑，不能替代鼠标/键盘实物写入、回读及持久化测试。
- 原版字体、图像与完整 UI 行为没有随项目发布；界面为独立实现。

Linux 能力核对入口：[Solaar features](https://pwr-solaar.github.io/Solaar/features/)、[Solaar devices](https://pwr-solaar.github.io/Solaar/devices/)、[libratbag](https://github.com/libratbag/libratbag)。产品展示与写入权限以实际连接设备和后端探测结果为准。
