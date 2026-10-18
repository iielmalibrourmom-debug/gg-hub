# 重要功能与验证范围

本阶段实现鼠标和键盘的重要功能。所有物理设备均尚未实测。目录、设计预览、单元测试和协议测试不代表全部型号兼容。

| 功能 | 已实现 | 当前边界 |
| --- | --- | --- |
| 设备发现 | ratbagd 系统 D-Bus、Solaar CLI、Linux sysfs 诊断 | Refresh 更新；不同后端可能分别显示同一设备。检测到不等于可配置 |
| DPI / DPI 档位 | ratbagd 分辨率及活动档位；Solaar 实际可查询的 DPI / X / Y / LOD | 校验驱动枚举值，写后读回；主编辑器使用相同 X/Y，分轴通过 Solaar |
| 回报率 | ratbagd 枚举速率、Solaar 实际可查询设置 | 不提供设备未声明的 8 kHz 选项 |
| 按键映射 | 鼠标按钮、Linux 键码、DPI/profile 特殊动作 | 按钮动作类型必须由 ratbagd 声明；不是完整 G-Shift / KEYCONTROL |
| 按钮宏 | 保存的单次宏编译为 ratbagd `a(uu)` 映射并提交 | 仅支持 MACRO 动作的按钮；平衡按下/释放；实际触发和持久性需实测 |
| 软件宏 | 按键、延时、US ASCII 文本、单次/循环/toggle；停止与释放 | Linux evdev/uinput 权限；最长 300 秒及循环上限；sequence 为单次顺序播放 |
| 灯光 | ratbagd 颜色/亮度/关闭/固定/循环/呼吸；部分 Solaar 背光 | 逐键 RGB 画布、屏幕取色、跨设备同步未实现 |
| 板载配置 | ratbagd 暴露的硬件 profile 激活；Solaar 可查询的板载模式 | 无固件升级；掉电持久性未实测 |
| 本地配置 | 创建、编辑、删除、导入导出、激活、原子保存 | Capture 保存 DPI/回报率及活动 profile/stage，尚未捕获全部按键/灯光 |
| 应用切换 | X11 前台进程匹配、离开游戏回退桌面、设备失败状态 | Wayland 前台识别未实现；手动配置可独立使用 |
| 键盘选项 | Solaar 成功查询的背光、Fn、部分 G-key 选项 | diversion 不等于完整事件到宏绑定；取决于设备和驱动版本 |
| 电量 | Solaar 返回的实际百分比 | 不可读时不填假数值 |
| SUPERSTRIKE 调校 | 原版和 Solaar 能力已调查 | 动态 AnalogButtonTuning 名称与 CLI 查询兼容性未解决，不宣称可控制 |
| 参考目录 | 42 个主型号、78 个衍生型号事实 | 69 个封装分片及 1 个缺失引用未解析，非完整支持列表 |
| Linux 分发 | Arch PKGBUILD、AppImage/tar 的 Actions 流程 | Arch 安装未在本机执行；软件 CI 与发布结果见 GitHub Actions |

## 软件验证

- Python 测试覆盖过滤、类型、错误/Resync/读回、原子保存、宏取消释放与并发。
- Linux 专用测试在一次性 D-Bus 上导出测试服务，验证真实 dbus-next 消息；不访问 HID 硬件，不是实际驱动验收。
- Electron 联调验证 renderer → preload → main → Python → 本地配置，并拒绝未知 RPC。
- 浏览器测试验证预览禁用硬件、配置与宏编辑、目录搜索；截图均为明确标注的样例。

实物验收需记录型号、连接方式、内核、驱动版本和会话类型，检查读取/写入/实际行为/拔插恢复，涉及板载存储时再查断电恢复。通过后才能为对应型号和连接方式声明验证。

固件、云社区/账号、完整 Lua、完整逐键灯效及所有原版游戏集成已按最新的重要功能范围延后。
