# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import shutil

def find_python_executable():
    # 1. 检查环境变量中的 pythonw.exe
    pyw = shutil.which("pythonw.exe")
    if pyw and os.path.exists(pyw):
        return pyw

    # 2. 检查当前运行环境的目录 (如果在特定 python 环境下打包)
    if hasattr(sys, 'base_prefix') and os.path.exists(os.path.join(sys.base_prefix, 'pythonw.exe')):
        return os.path.join(sys.base_prefix, 'pythonw.exe')
    if hasattr(sys, 'exec_prefix') and os.path.exists(os.path.join(sys.exec_prefix, 'pythonw.exe')):
        return os.path.join(sys.exec_prefix, 'pythonw.exe')

    # 3. 检查常见默认安装路径
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    if local_app_data:
        py38_path = os.path.join(local_app_data, 'Programs', 'Python', 'Python38', 'pythonw.exe')
        if os.path.exists(py38_path):
            return py38_path

    # 4. 回退检查 python.exe
    py = shutil.which("python.exe")
    if py and os.path.exists(py):
        return py

    return "pythonw.exe"

def main():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    script_path = os.path.join(base_dir, 'soda_player_gui_qt.py')
    if not os.path.exists(script_path):
        # 兜底：如果直接打包运行在其他目录
        script_path = 'soda_player_gui_qt.py'

    py_exe = find_python_executable()
    cmd = [py_exe, script_path]
    if len(sys.argv) > 1:
        cmd.extend(sys.argv[1:])

    # 注意：千万不要设置 startupinfo.wShowWindow = 0 (SW_HIDE)
    # 因为 Windows 会将父进程的 STARTUPINFO 传递给子进程的首个顶级窗口，导致 Qt 窗口直接隐藏到后台
    subprocess.Popen(
        cmd,
        cwd=base_dir
    )

if __name__ == '__main__':
    main()
