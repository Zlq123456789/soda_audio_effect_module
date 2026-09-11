# -*- coding: utf-8 -*-
import os
import sys
import shutil
import zipfile
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "v1.0.1"
RELEASE_ROOT = os.path.join(BASE_DIR, f"release_{VERSION}")
TARGET_DIR_NAME = f"音效管理_{VERSION}_免安装绿色版"
TARGET_DIR = os.path.join(RELEASE_ROOT, TARGET_DIR_NAME)
ZIP_OUTPUT = os.path.join(RELEASE_ROOT, f"Soda_Audio_Effect_{VERSION}_Portable.zip")

def main():
    print("=" * 60)
    print(f">> 开始一键自动化打包【音效管理 {VERSION} 纯净绿色版】")
    print("=" * 60)

    # 1. 检查 node.exe 路径
    node_src = None
    possible_runtimes = [
        os.path.join(RELEASE_ROOT, TARGET_DIR_NAME, "runtime", "node.exe"),
        os.path.join(BASE_DIR, "release_v1.0.0", "音效管理_v1.0.0_免安装绿色版", "runtime", "node.exe"),
    ]
    for p in possible_runtimes:
        if os.path.exists(p):
            node_src = p
            break
    if not node_src and shutil.which("node"):
        node_src = shutil.which("node")
    
    print(f"[*] 发现 Node.js 运行时: {node_src}")

    # 2. 清理旧构建产物
    build_dir = os.path.join(BASE_DIR, "build")
    dist_dir = os.path.join(BASE_DIR, "dist")
    for p in [build_dir, dist_dir]:
        if os.path.exists(p):
            print(f"[*] 清理旧构建目录: {p}")
            shutil.rmtree(p, ignore_errors=True)

    # 3. 执行 PyInstaller 打包
    spec_file = os.path.join(BASE_DIR, "音效管理.spec")
    print(f"[*] 正在执行 PyInstaller 构建 (UPX 禁用，无误报模式)...")
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "-y", spec_file]
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[ERROR] PyInstaller 打包失败！")
        sys.exit(1)

    # 4. 组装绿色发布目录
    print(f"[*] 正在组装纯净免安装目录: {TARGET_DIR}")
    if os.path.exists(TARGET_DIR):
        shutil.rmtree(TARGET_DIR, ignore_errors=True)
    os.makedirs(TARGET_DIR, exist_ok=True)

    # 复制 PyInstaller 生成的 exe 和 _internal
    dist_app_dir = os.path.join(dist_dir, "音效管理")
    for item in os.listdir(dist_app_dir):
        s = os.path.join(dist_app_dir, item)
        d = os.path.join(TARGET_DIR, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)

    # 复制必需资源目录（排除临时、日志与脚本文件）
    for folder in ["presets", "wasm", "tools", "assets"]:
        s = os.path.join(BASE_DIR, folder)
        d = os.path.join(TARGET_DIR, folder)
        if os.path.exists(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("*.log", "*.tmp", "__pycache__"), dirs_exist_ok=True)

    # 复制 Node.js 运行时
    runtime_target = os.path.join(TARGET_DIR, "runtime")
    os.makedirs(runtime_target, exist_ok=True)
    if node_src and os.path.exists(node_src):
        shutil.copy2(node_src, os.path.join(runtime_target, "node.exe"))

    # 复制单文件与配置文件
    for fname in ["dsp_server.mjs", "app_icon.ico", "app_icon.png", "config.json"]:
        s = os.path.join(BASE_DIR, fname)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(TARGET_DIR, fname))

    # 生成规范使用说明
    guide_content = f"""================================================================================
音效管理 & 全局系统音频增强器 ({VERSION} 旗舰硬件加速版)
================================================================================

【软件简介】
本软件基于 100% 官方原版 WebAssembly DSP 调音内核与 Qt6 硬件加速图形界面打造。
支持全系统声音接管、9 大官方大师级音效实时渲染、72 频段高精度声学频谱律动与 3D 沉浸式粒子视效。

【主要特性】
1. 9 大官方原版调音预设：智能音效、360环绕、超重低音、清澈人声、3D音效、HIFI现场、动感电音、摇滚音效、复古唱片。
2. 全自动设备感知：智能检测蓝牙耳机、USB耳机与外置音箱插拔；耳机连接时自动选中，断开时自动平滑回退至扬声器。
3. 实时增强无缝热切换：在开启全局增强时拔插耳机，声音平滑转移不卡死、不中断。
4. 全局音量精准级联与平滑过渡：DSP 音频处理循环中实现系统音量与软件音量数学乘积精准叠加，配合一阶平滑过渡滤波器消除拉链音与爆音。
5. 全局音量毫秒级同步：完美支持键盘多媒体音量键与系统任务栏音量联动。
6. 零环境依赖：内置便携式轻量 Node.js DSP 运行环境，开箱即用，无需配置任何 Python 或 Node.js 环境。

【快速上手指南】
1. 首次使用：若未安装过虚拟声卡驱动，请在软件内点击【一键安装驱动】。
2. 双击运行【音效管理.exe】。
3. 在顶部下拉框选择您的物理播放设备（如您的耳机或音箱）。
4. 打开【全局声音实时增强】开关，点击下方任意音效卡片，即可享受震撼音质！

【版本信息】
版本号: {VERSION}
发布日期: 2026-09-11
架构: Windows x64
================================================================================
"""
    with open(os.path.join(TARGET_DIR, "使用说明与快速上手指南.txt"), "w", encoding="utf-8") as f:
        f.write(guide_content)

    # 5. 压缩为发布 ZIP 包
    print(f"[*] 正在生成发布压缩包: {ZIP_OUTPUT}")
    if os.path.exists(ZIP_OUTPUT):
        os.remove(ZIP_OUTPUT)

    with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(TARGET_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, TARGET_DIR)
                zipf.write(file_path, arcname)

    zip_size_mb = os.path.getsize(ZIP_OUTPUT) / (1024 * 1024)
    print(f"[OK] 打包完成！发布包体积: {zip_size_mb:.2f} MB")
    print(f"[*] 输出路径: {ZIP_OUTPUT}")
    print("=" * 60)

if __name__ == "__main__":
    main()
