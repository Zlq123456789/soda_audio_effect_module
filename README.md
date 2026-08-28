# 🎵 音效管理 & 全局系统音频增强器 (v1.0.0 旗舰硬件加速版)

> **基于 100% 官方原版 WebAssembly DSP 调音内核 与 Qt6 硬件加速图形界面打造的 Windows 全局音频音效增强系统**

[![Release](https://img.shields.io/badge/Release-v1.0.0-blue.svg)](https://github.com/Zlq123456789/soda_audio_effect_module/releases)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20x64-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)]()
[![GUI](https://img.shields.io/badge/GUI-Qt6%20%2F%20PySide6-purple.svg)]()

---

## 🌟 核心特性

- 🎛️ **9 大官方原版调音音效**：智能音效、360环绕、超重低音、清澈人声、3D音效、HIFI现场、动感电音、摇滚音效、复古唱片，支持 0%~200% 双级强度调节。
- 🎧 **全自动设备感知与即插即用**：
  - 基于 Windows Core Audio (IMMNotificationClient) + WM_DEVICECHANGE 广播与防抖巡检。
  - 耳机（蓝牙/USB/3.5mm）连接时自动设为当前输出，断开时自动平滑回退至可用扬声器/显示器音频。
- ⚡ **实时增强无缝热切换 (Live Hot-swap)**：开启全局增强时拔插耳机或切换输出设备，底层音频流自动热重绑，不中断、不卡死、无爆音。
- 🔊 **Windows 全局音量毫秒级同步**：实时响应键盘多媒体音量键与系统任务栏滑块。
- 📊 **72 频段高精度声学频谱律动** + **3D 沉浸式粒子背景视效**（星河/星球/滚筒/微粒/深浅色主题）。
- 🚀 **纯净免安装，开箱即用**：内置便携式轻量 Node.js DSP 运行环境，目标电脑**无需安装 Python 或 Node.js**。

---

## 📦 9 大官方原版音效一览

| 音效名称 | 特性描述 | 推荐场景 |
| :--- | :--- | :--- |
| **智能音效** | 跟随曲风智能自适应多频段动态平衡 | 综合听歌、日常流行曲 |
| **360环绕** | 展开超大声场空间定位与多角度环绕立体声 | 电影大片、空间音频、交响乐 |
| **超重低音** | 强劲澎湃低频下潜与动态冲击力增强 | 电子舞曲、摇滚、DJ、电影重低音 |
| **清澈人声** | 人声频段精准增强与穿透力提纯 | 播客、民谣、流行人声、网课解说 |
| **3D音效** | 足不出户享受置身舞台中心的现场感 | 沉浸式游戏、现场录音 |
| **HIFI现场** | 还原音乐现场 Live 震撼氛围与高动态解析 | 演唱会、现场 Live 音乐 |
| **动感电音** | 独具一格的电子音乐动态渲染与节奏强化 | EDM、合成器流行、电音节录音 |
| **摇滚音效** | 再现饱含激情的电吉他与打击乐金属质感 | 摇滚乐、重金属、朋克乐队 |
| **复古唱片** | 复古怀旧年代感黑胶模拟与温润模拟滤波 | 爵士乐、老歌、古典经典名曲 |

---

## 🚀 快速上手指南

### 1. 下载即用
从 [Releases 页面](https://github.com/Zlq123456789/soda_audio_effect_module/releases) 下载最新发行包：
- **音效管理_v1.0.0_免安装绿色版.zip**（推荐，解压即用，零启动延迟）
- **音效管理_v1.0.0_单文件独立EXE版.zip**（单文件可执行封装）

### 2. 运行与接管
1. 解压后双击运行 **音效管理.exe**。
2. 首次使用：若未安装过虚拟声卡通道，请在软件界面点击【⚡ 一键安装驱动】（或运行 install_virtual_soundcard.bat）。
3. 在顶部下拉框选择您的物理耳机或扬声器。
4. 打开【全局声音实时增强】开关，点击任意音效卡片即可体验大师级音效！

---

## 🛠️ 项目架构

`
soda_audio_effect_module/
├── presets/                 # 9 大官方音效 DSP 配置文件
├── tools/                   # 内置工具 (vbcable 虚拟声卡 / nircmd 系统声卡控制)
├── wasm/                    # WebAssembly 官方调音核心模块
├── runtime/                 # 便携式轻量 Node.js 运行环境
├── soda_player_gui_qt.py    # Qt6 旗舰版主界面与音频管理流引擎
├── dsp_server.mjs           # 本地高性能二进制 DSP TCP 调音服务端
├── config.json              # 用户持久化配置
└── release_v1.0.0/          # 发布包产物
`

---

## 📄 开源许可证

本项目基于 MIT 协议分发与使用。
