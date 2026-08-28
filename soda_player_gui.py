# -*- coding: utf-8 -*-
import sys
import ctypes

# 无论如何启动，0 延迟彻底隐藏并脱离任何黑框控制台
try:
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 0) # SW_HIDE
        ctypes.windll.kernel32.FreeConsole()
    ctypes.windll.winmm.timeBeginPeriod(1)

    # 注册独立 Windows App ID，确保任务栏 100% 呈现专属高清图标
    myappid = 'soda.audio.effect.manager.v2'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass


"""
音效管理 & 全局系统音频增强器 (官方原生完整旗舰版)
Native Windows Desktop Audio Player & Plan B System-wide Audio DSP Enhancer
"""

import os
import sys
import json
import time
import socket
import struct
import logging
import traceback
import threading
import queue
import collections
import subprocess
import ctypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk
import math
import numpy as np
import pyaudiowpatch as pyaudio
import soundfile as sf

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PRESETS_DIR = os.path.join(BASE_DIR, 'presets')
DSP_SERVER_PATH = os.path.join(BASE_DIR, 'dsp_server.mjs')
VBCABLE_SETUP_EXE = os.path.join(BASE_DIR, 'tools', 'vbcable', 'VBCABLE_Setup_x64.exe')
NIRCMD_EXE = os.path.join(BASE_DIR, 'tools', 'nircmd', 'nircmdc.exe')
ICON_PATH = os.path.join(BASE_DIR, 'app_icon.ico')
PNG_PATH = os.path.join(BASE_DIR, 'app_icon.png')
LOG_FILE = os.path.join(BASE_DIR, 'soda_player.log')
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# 配置本地日志持久化记录
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)
fh = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
root_logger.addHandler(fh)

EFFECT_DEFS = [
    {"key": "none", "name": "原声直通", "desc": "完全绕过 DSP，纯净直通输出"},
    {"key": "1_intelligent", "name": "智能音效", "desc": "跟随曲风智能适配（官方 10段EQ + DRC + 动态限制）"},
    {"key": "2_surround_360", "name": "360环绕", "desc": "多角度超大声场体验（官方 circle_360 空间轨道算法）"},
    {"key": "3_deep_bass", "name": "超重低音", "desc": "澎湃低音带来更多震撼（官方 50~200Hz 次低频重构）"},
    {"key": "4_clear_vocal", "name": "清澈人声", "desc": "更具穿透力的人声体验（官方 人声清晰度提升 + 5dB 增益）"},
    {"key": "5_sound_3d", "name": "3D音效", "desc": "足不出户享受现场（官方 MS Crossfeed 2倍宽声场拓宽）"},
    {"key": "6_hifi_live", "name": "HIFI现场", "desc": "亲临最high音乐现场（官方 6段EQ + env_acoustic 物理环境声学）"},
    {"key": "7_dynamic_electro", "name": "动感电音", "desc": "独具一格电子音乐风格（官方 FIR 脉冲卷积 + 10dB 强劲增益）"},
    {"key": "8_rock_music", "name": "摇滚音效", "desc": "再现饱含激情音乐节奏（官方 10段经典 W 曲线强力均衡）"},
    {"key": "9_vintage_record", "name": "复古唱片", "desc": "复古怀旧年代感来袭（官方 2.7kHz 黑胶滚降 + 960Hz 模拟染色）"}
]

class DspClient:
    """与本地 WebAssembly DSP 调音内核通信的高性能二进制客户端"""
    def __init__(self, host='127.0.0.1', port=9988):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False
        self.lock = threading.Lock()

    def connect(self, retries=25, delay=0.25):
        for i in range(retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock.settimeout(2.0)
                self.sock.connect((self.host, self.port))
                self.sock.settimeout(None)
                self.connected = True
                logging.info(f"DSP TCP Client connected to {self.host}:{self.port}")
                return True
            except Exception:
                time.sleep(delay)
        return False

    def load_effect(self, config_obj, sample_rate, intensity=100):
        if not self.connected:
            return False
        with self.lock:
            try:
                payload = json.dumps({"config": config_obj, "sampleRate": sample_rate, "intensity": intensity}).encode('utf-8')
                header = struct.pack('<II', 1, len(payload))
                self.sock.sendall(header + payload)
                resp = self._recv_exact(8)
                cmd, status = struct.unpack('<II', resp)
                return status == 1
            except Exception as e:
                logging.error(f"DSP load_effect error: {e}")
                self.connected = False
                return False

    def set_intensity(self, intensity_pct):
        """实时设置 DSP 0%~200% 双级级联强度 (CMD 3)"""
        if not self.connected:
            return False
        with self.lock:
            try:
                payload = json.dumps({"intensity": float(intensity_pct)}).encode('utf-8')
                header = struct.pack('<II', 3, len(payload))
                self.sock.sendall(header + payload)
                resp = self._recv_exact(8)
                cmd, status = struct.unpack('<II', resp)
                return status == 1
            except Exception as e:
                logging.warning(f"DSP set_intensity error: {e}")
                return False

    def process_chunk(self, float_array):
        if not self.connected or float_array is None or len(float_array) == 0:
            return float_array
        with self.lock:
            try:
                raw_bytes = float_array.tobytes()
                header = struct.pack('<II', 2, len(raw_bytes))
                self.sock.sendall(header + raw_bytes)
                resp_hdr = self._recv_exact(8)
                cmd, length = struct.unpack('<II', resp_hdr)
                if length == 0:
                    return float_array
                processed_bytes = self._recv_exact(length)
                res = np.frombuffer(processed_bytes, dtype=np.float32).reshape(-1, 2)
                if len(res) != len(float_array):
                    return float_array
                return res
            except Exception as e:
                logging.warning(f"DSP process_chunk error: {e}")
                self.connected = False
                return float_array

    def _recv_exact(self, n):
        data = bytearray()
        while len(data) < n:
            packet = self.sock.recv(n - len(data))
            if not packet:
                raise ConnectionResetError("DSP connection closed")
            data.extend(packet)
        return bytes(data)

def apply_studio_soft_limiter(audio_chunk):
    """录音室级模拟软饱和防爆音限幅器 (0 破音、0 杂音、饱满圆润)"""
    threshold = 0.85
    abs_audio = np.abs(audio_chunk)
    mask = abs_audio > threshold
    if np.any(mask):
        excess = abs_audio[mask] - threshold
        compressed = threshold + (1.0 - threshold) * np.tanh(excess / (1.0 - threshold))
        audio_chunk[mask] = np.sign(audio_chunk[mask]) * compressed
    return audio_chunk

def generate_spectrum_palette(num_bars=32):
    """生成 32 频段高保真彩虹渐变色谱 (黑金 -> 翡翠 -> 天蓝 -> 梦幻紫)"""
    colors = []
    for i in range(num_bars):
        t = i / (num_bars - 1)
        if t < 0.35:
            r = int(245 + t * 25)
            g = int(158 + t * 90)
            b = int(11 + t * 60)
        elif t < 0.7:
            t_rel = (t - 0.35) / 0.35
            r = int(16 - t_rel * 10)
            g = int(185 - t_rel * 3)
            b = int(129 + t_rel * 83)
        else:
            t_rel = (t - 0.7) / 0.3
            r = int(56 + t_rel * 73)
            g = int(189 - t_rel * 49)
            b = int(248 + t_rel * 0)
        colors.append(f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}")
    return colors

def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

class ToggleSwitch(tk.Label):
    """Retina 级别 4x 超采样抗锯齿 (SSAA) 苹果/Fluent 风格丝滑开关 (0 锯齿·超清晰)"""
    def __init__(self, parent, command=None, width=58, height=30, bg="#242429"):
        super().__init__(parent, bg=bg, cursor="hand2", bd=0, highlightthickness=0)
        self.w = width
        self.h = height
        self.parent_bg = bg
        self.bg_rgb = hex_to_rgb(bg)
        self.command = command
        self.state = "off"
        self.thumb_pos = 0.0
        self.target_pos = 0.0
        self.spinner_angle = 0
        self.loading_task = False
        self.scale = 4

        self.bind("<Button-1>", self._on_click)
        self._update_image()

    def _on_click(self, event=None):
        if self.state == "loading":
            return
        if self.command:
            self.command()

    def set_state(self, state):
        self.state = state
        if state == "on":
            self.target_pos = 1.0
            self.loading_task = False
            self._animate()
        elif state == "off":
            self.target_pos = 0.0
            self.loading_task = False
            self._animate()
        elif state == "loading":
            self.loading_task = True
            self._animate_spinner()

    def _animate(self):
        diff = self.target_pos - self.thumb_pos
        if abs(diff) > 0.02:
            self.thumb_pos += diff * 0.45
            self._update_image()
            self.after(16, self._animate)
        else:
            self.thumb_pos = self.target_pos
            self._update_image()

    def _animate_spinner(self):
        if not self.loading_task or self.state != "loading":
            return
        self.spinner_angle = (self.spinner_angle + 24) % 360
        self._update_image()
        self.after(30, self._animate_spinner)

    def _update_image(self):
        S = self.scale
        W = self.w * S
        H = self.h * S
        R = H // 2

        img = Image.new("RGBA", (W, H), self.bg_rgb + (255,))
        draw = ImageDraw.Draw(img)

        if self.state == "on":
            track_col = (16, 185, 129, 255)
            border_col = (5, 150, 105, 255)
        elif self.state == "loading":
            track_col = (217, 119, 6, 255)
            border_col = (180, 83, 9, 255)
        else:
            track_col = (63, 63, 70, 255)
            border_col = (82, 82, 91, 255)

        draw.rounded_rectangle([2*S, 2*S, W - 2*S, H - 2*S], radius=R - 2*S, fill=track_col, outline=border_col, width=1*S)

        if self.state == "loading":
            cx, cy = W / 2, H / 2
            spin_r = 7.5 * S
            for i in range(8):
                rad = math.radians(self.spinner_angle + i * 45)
                px = cx + spin_r * math.cos(rad)
                py = cy + spin_r * math.sin(rad)
                alpha = int(70 + (i / 7.0) * 185)
                dot_r = (2.2 if i >= 4 else 1.6) * S
                draw.ellipse([px - dot_r, py - dot_r, px + dot_r, py + dot_r], fill=(255, 255, 255, alpha))
        else:
            min_x = R
            max_x = W - R
            cx = min_x + (max_x - min_x) * self.thumb_pos
            cy = H / 2
            tr = R - 4.5 * S

            shadow_offset = 1.8 * S
            draw.ellipse([cx - tr, cy - tr + shadow_offset, cx + tr, cy + tr + shadow_offset], fill=(0, 0, 0, 50))
            draw.ellipse([cx - tr, cy - tr, cx + tr, cy + tr], fill=(255, 255, 255, 255))

        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.LANCZOS

        smooth_img = img.resize((self.w, self.h), resample=resample_filter)
        self.photo = ImageTk.PhotoImage(smooth_img)
        self.config(image=self.photo)

class SmoothVolumeSlider(tk.Canvas):
    """原生矢量 Canvas 极速滑块 (始终高亮金色/纯白触点 + 进度高亮槽)"""
    def __init__(self, parent, from_=0, to=200, initial=100, command=None, height=28, bg="#1a1a1e"):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.min_val = from_
        self.max_val = to
        self.val = initial
        self.command = command
        self.bg_color = bg
        self.h = height
        self.w = 300

        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<MouseWheel>", self._on_wheel)

        self.draw()

    def _on_resize(self, event):
        if event.width > 20:
            self.w = event.width
            self.draw()

    def _pos_to_val(self, x):
        padding = 14
        usable_w = max(10, self.w - 2 * padding)
        ratio = max(0.0, min(1.0, (x - padding) / usable_w))
        return self.min_val + ratio * (self.max_val - self.min_val)

    def _val_to_ratio(self):
        return max(0.0, min(1.0, (self.val - self.min_val) / (self.max_val - self.min_val)))

    def _on_click(self, event):
        self.set(self._pos_to_val(event.x))

    def _on_drag(self, event):
        self.set(self._pos_to_val(event.x))

    def _on_wheel(self, event):
        delta = 5 if event.delta > 0 else -5
        self.set(self.val + delta)
        return "break"

    def get(self):
        return self.val

    def set(self, val):
        new_val = max(self.min_val, min(self.max_val, val))
        if abs(new_val - self.val) > 0.01:
            self.val = new_val
            self.draw()
            if self.command:
                self.command(self.val)

    def draw(self):
        self.delete("all")
        padding = 14
        w = max(40, self.w)
        cy = self.h / 2
        usable_w = w - 2 * padding
        ratio = self._val_to_ratio()
        cx = padding + usable_w * ratio

        # 1. 轨道底槽
        self.create_line(padding, cy, w - padding, cy, fill="#26262e", width=6, capstyle=tk.ROUND)

        # 2. 进度已填满部分
        progress_color = "#ef4444" if self.val > 100 else "#f59e0b"
        if cx > padding + 1:
            self.create_line(padding, cy, cx, cy, fill=progress_color, width=6, capstyle=tk.ROUND)

        # 3. 触点 (始终高亮)
        r = 8
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=progress_color, outline="")
        self.create_oval(cx - r + 2.5, cy - r + 2.5, cx + r - 2.5, cy + r - 2.5, fill="#ffffff", outline="")

class MiniEffectSlider(tk.Canvas):
    """卡片内精致极简微型滑块 (0% ~ 200% 范围，中间 100% 刻度节点，磁吸对齐)"""
    def __init__(self, parent, initial=100, command=None, height=18, bg="#242429", is_active=False):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.val = initial
        self.command = command
        self.bg_color = bg
        self.is_active = is_active
        self.h = height
        self.w = 160

        self.bind("<Configure>", self._on_resize)
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)

        self.draw()

    def set_active(self, is_active, bg_color):
        self.is_active = is_active
        self.bg_color = bg_color
        self.config(bg=bg_color)
        self.draw()

    def _on_resize(self, event):
        if event.width > 20:
            self.w = event.width
            self.draw()

    def _pos_to_val(self, x):
        padding = 8
        usable_w = max(10, self.w - 2 * padding)
        ratio = max(0.0, min(1.0, (x - padding) / usable_w))
        raw_val = int(round(ratio * 200))
        # 100% 节点磁吸 (96% ~ 104% 自动吸附至 100%)
        if 96 <= raw_val <= 104:
            return 100
        return raw_val

    def _on_click(self, event):
        self.set(self._pos_to_val(event.x))

    def _on_drag(self, event):
        self.set(self._pos_to_val(event.x))

    def get(self):
        return self.val

    def set(self, val):
        new_val = max(0, min(200, int(val)))
        if new_val != self.val:
            self.val = new_val
            self.draw()
            if self.command:
                self.command(self.val)

    def draw(self):
        self.delete("all")
        padding = 8
        w = max(20, self.w)
        cy = self.h / 2
        usable_w = w - 2 * padding
        ratio = self.val / 200.0
        cx = padding + usable_w * ratio
        mid_x = padding + usable_w * 0.5

        if self.is_active:
            track_base = "#221c10"
            fill_col = "#ef4444" if self.val > 100 else "#f59e0b"
            thumb_outer = fill_col
            thumb_inner = "#ffffff"
            notch_col = "#ffffff" if self.val >= 100 else "#855810"
        else:
            track_base = "#18181c"
            fill_col = "#383842"
            thumb_outer = "#4b4b58"
            thumb_inner = "#3f3f4a"
            notch_col = "#2a2a32"

        # 1. 轨道底槽
        self.create_line(padding, cy, w - padding, cy, fill=track_base, width=4, capstyle=tk.ROUND)

        # 2. 进度已填满部分
        if cx > padding + 1:
            self.create_line(padding, cy, cx, cy, fill=fill_col, width=4, capstyle=tk.ROUND)

        # 3. 绘制中间 100% 刻度节点
        self.create_line(mid_x, cy - 3, mid_x, cy + 3, fill=notch_col, width=2)

        # 4. 触点
        r = 5
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=thumb_outer, outline="")
        self.create_oval(cx - r + 1.5, cy - r + 1.5, cx + r - 1.5, cy + r - 1.5, fill=thumb_inner, outline="")

class SodaMusicPlayerApp:

    def _start_sys_volume_tracker(self):
        """完全隔离的 Windows 系统总音量后台追踪线程 (0 跨线程 COM 交互，100% 零奔溃)
        使 Windows 键盘音量键 / 任务栏音量条与软件内音量滑块双轨并行、互不干扰！"""
        def _poller():
            try:
                ctypes.windll.ole32.CoInitialize(None)
            except Exception:
                pass
            vol_ctrl = None

            while getattr(self, '_sys_vol_tracking_active', True):
                try:
                    if vol_ctrl is None:
                        from pycaw.pycaw import AudioUtilities
                        dev = AudioUtilities.GetSpeakers()
                        if dev and hasattr(dev, 'EndpointVolume'):
                            vol_ctrl = dev.EndpointVolume

                    if vol_ctrl:
                        if vol_ctrl.GetMute():
                            self.sys_master_volume = 0.0
                        else:
                            self.sys_master_volume = float(vol_ctrl.GetMasterVolumeLevelScalar())
                except Exception:
                    vol_ctrl = None
                time.sleep(0.04)

            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

        self._sys_vol_tracking_active = True
        t = threading.Thread(target=_poller, daemon=True)
        t.start()

    def load_user_config(self):
        """读取用户配置，首次启动默认音量 100%"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {"volume": 100, "effect": "none"}

    def save_user_config(self):
        """持久化保存用户最新音量及音效偏好"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.user_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def __init__(self, root):
        self.root = root
        self.root.title("音效管理")
        self.root.geometry("980x760")
        self.root.configure(bg="#121214")
        self.root.minsize(900, 540)
        self.log_text = None

        # 设置高清窗口与任务栏图标
        if os.path.exists(ICON_PATH):
            try: self.root.iconbitmap(ICON_PATH)
            except Exception: pass
        if os.path.exists(PNG_PATH):
            try:
                self.app_icon_img = ImageTk.PhotoImage(file=PNG_PATH)
                self.root.iconphoto(True, self.app_icon_img)
            except Exception: pass

        # 全局配置 Combobox 弹出菜单暗黑主题
        self.root.option_add('*TCombobox*Listbox.background', '#242429')
        self.root.option_add('*TCombobox*Listbox.foreground', '#f3f4f6')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#f59e0b')
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#000000')
        self.root.option_add('*TCombobox*Listbox.font', ('Microsoft YaHei', 9))

        style = ttk.Style()
        try: style.theme_use('clam')
        except: pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground="#1a1a1e",
            background="#2a2a30",
            foreground="#ffffff",
            darkcolor="#3f3f46",
            lightcolor="#3f3f46",
            bordercolor="#3f3f46",
            arrowcolor="#f59e0b",
            arrowsize=14,
            padding=5
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", "#1a1a1e"), ("focus", "#1a1a1e")],
            foreground=[("readonly", "#ffffff"), ("focus", "#ffffff")],
            bordercolor=[("focus", "#f59e0b")]
        )

        self.pa = pyaudio.PyAudio()
        self.dsp_process = None
        self.dsp_client = DspClient()

        self.work_mode = 'system_live'
        self.audio_data = None
        self.sample_rate = 44100
        self.total_frames = 0
        self.current_frame = 0
        self.is_playing = False
        self.is_paused = False
        self.local_stream = None

        # 方案 B 状态
        self.is_live_capturing = False
        self.live_thread = None
        self.in_thread = None
        self.live_in_stream = None
        self.live_out_stream = None
        self.original_default_audio_name = None
        self.has_cable_installed = False
                

        # 读取用户持久化配置
        self.user_cfg = self.load_user_config()
        self.saved_vol = int(self.user_cfg.get("volume", 100))
        self.volume = self.saved_vol / 100.0
        self.prev_volume = self.volume if self.volume > 0 else 1.0
        self.is_muted = False
        self.current_effect_key = self.user_cfg.get("effect", "none")
        self.effect_intensities = self.user_cfg.get("intensities", {})
        self.fft_magnitudes = np.zeros(32, dtype=np.float32)
        self.smooth_bars = np.zeros(32, dtype=np.float32)
        self.peak_heights = np.zeros(32, dtype=np.float32)

        # 优先瞬间绘制精美暗黑界面，彻底消除白屏与未响应
        self.build_ui()
        self.bind_shortcuts()
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

        # 启动后台 DSP 引擎
        self.start_dsp_backend()
        self.update_visualizer_loop()

        # 启动时默认处于方案 B
        self.switch_mode('system_live')

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, msg):
        logging.info(msg)

    def start_dsp_backend(self):
        try:
            startupinfo = None
            if sys.platform == 'win32':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            dsp_log_path = os.path.join(BASE_DIR, "dsp_server.log")
            self.dsp_log_file = open(dsp_log_path, "a", encoding="utf-8")
            portable_node = os.path.join(BASE_DIR, 'runtime', 'node.exe')
            node_exec = portable_node if os.path.exists(portable_node) else 'node'
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

            self.dsp_process = subprocess.Popen(
                [node_exec, DSP_SERVER_PATH],
                cwd=BASE_DIR,
                startupinfo=startupinfo,
                creationflags=creationflags,
                stdout=self.dsp_log_file,
                stderr=self.dsp_log_file
            )
            connected = self.dsp_client.connect(retries=20)
            if connected:
                logging.info(f"DSP Backend connected successfully! (PID={self.dsp_process.pid}, log={dsp_log_path})")
                self.apply_current_effect_to_dsp()
            else:
                logging.error("Failed to connect to local DSP core!")
                messagebox.showerror("错误", "无法连接本地 DSP 音频核心，请确保系统已安装 Node.js！")
        except Exception as e:
            logging.error(f"Failed to launch DSP backend: {e}")
            messagebox.showerror("启动异常", f"启动 DSP 引擎失败: {e}")

    def build_ui(self):
        # 0. 全局流畅可滚动视口 (支持鼠标滚轮与不同屏幕尺寸完美自适应)
        self.main_canvas = tk.Canvas(self.root, bg="#121214", highlightthickness=0, bd=0)
        self.content_frame = tk.Frame(self.main_canvas, bg="#121214")

        self.content_frame.bind(
            "<Configure>",
            lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        )
        self.canvas_window = self.main_canvas.create_window((0, 0), window=self.content_frame, anchor="nw")

        def _on_canvas_configure(event):
            if event.width > 50:
                self.main_canvas.itemconfig(self.canvas_window, width=event.width)

        self.main_canvas.bind("<Configure>", _on_canvas_configure)
        self.main_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_global_mousewheel(event):
            if self.content_frame.winfo_height() > self.main_canvas.winfo_height():
                self.main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.root.bind_all("<MouseWheel>", _on_global_mousewheel)

        # 1. 核心控制区 Card (极简开关 + 美化设备下拉菜单)
        self.live_card = tk.Frame(self.content_frame, bg="#1a1a1e", bd=1, relief="solid")
        self.live_card.pack(fill=tk.X, padx=24, pady=(16, 4))

        # 仅未安装驱动时动态显示的轻量提示条 (平时默认隐藏)
        self.vbcable_bar = tk.Frame(self.live_card, bg="#3f2305", padx=12, pady=6)
        self.vbcable_status_lbl = tk.Label(self.vbcable_bar, text="💡 首次使用提示：需要安装一次虚拟音频驱动 (仅需10秒)", font=("Microsoft YaHei", 9), fg="#fed7aa", bg="#3f2305")
        self.vbcable_status_lbl.pack(side=tk.LEFT)
        self.btn_install_driver = tk.Button(self.vbcable_bar, text="⚡ 一键安装驱动", font=("Microsoft YaHei", 9, "bold"), fg="#000000", bg="#f59e0b", relief="flat", padx=8, pady=2, cursor="hand2", command=self.install_vbcable_driver)
        self.btn_install_driver.pack(side=tk.RIGHT)

        self.live_inner = tk.Frame(self.live_card, bg="#1a1a1e")
        self.live_inner.pack(fill=tk.X, padx=16, pady=12)

        # 左侧：现代极简滑动开关组件区
        switch_box = tk.Frame(self.live_inner, bg="#242429", padx=16, pady=10, bd=1, relief="solid")
        switch_box.pack(side=tk.LEFT, padx=(0, 16))

        self.toggle_sw = ToggleSwitch(switch_box, command=self.toggle_live_capture, width=58, height=30, bg="#242429")
        self.toggle_sw.pack(side=tk.LEFT, padx=(0, 12))

        switch_info_box = tk.Frame(switch_box, bg="#242429")
        switch_info_box.pack(side=tk.LEFT)

        self.sw_title_lbl = tk.Label(switch_info_box, text="全局声音实时增强", font=("Microsoft YaHei", 11, "bold"), fg="#ffffff", bg="#242429")
        self.sw_title_lbl.pack(anchor="w")

        self.sw_status_lbl = tk.Label(switch_info_box, text="● 未开启 (点击开启)", font=("Microsoft YaHei", 9), fg="#9ca3af", bg="#242429")
        self.sw_status_lbl.pack(anchor="w", pady=(2, 0))

        # 右侧：监听输出设备下拉菜单区
        out_box = tk.Frame(self.live_inner, bg="#242429", padx=16, pady=8, bd=1, relief="solid")
        out_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        dev_head_row = tk.Frame(out_box, bg="#242429")
        dev_head_row.pack(fill=tk.X)

        tk.Label(dev_head_row, text="🎧 监听输出设备 (耳机 / 音箱):", font=("Microsoft YaHei", 9, "bold"), fg="#f59e0b", bg="#242429").pack(side=tk.LEFT)
        self.btn_refresh_devs = tk.Button(dev_head_row, text="🔄 刷新", font=("Microsoft YaHei", 8), fg="#d4d4d8", bg="#33333b", activebackground="#44444f", activeforeground="#ffffff", relief="flat", padx=6, pady=1, cursor="hand2", command=self.populate_audio_devices)
        self.btn_refresh_devs.pack(side=tk.RIGHT)

        self.output_dev_combo = ttk.Combobox(out_box, width=38, state="readonly", style="Dark.TCombobox")
        self.output_dev_combo.pack(anchor="w", fill=tk.X, pady=(4, 0))

        # 3. 模式 A 控制区 Card (本地播放模式)
        self.local_card = tk.Frame(self.content_frame, bg="#1a1a1e", bd=1, relief="solid")

        btn_row = tk.Frame(self.local_card, bg="#1a1a1e")
        btn_row.pack(fill=tk.X, padx=16, pady=(10, 4))

        self.btn_open = tk.Button(btn_row, text="📁 打开本地音乐 (MP3/WAV/FLAC)", font=("Microsoft YaHei", 10, "bold"), fg="#ffffff", bg="#2a2a30", activebackground="#3a3a40", activeforeground="#ffffff", relief="flat", padx=14, pady=5, cursor="hand2", command=self.choose_file)
        self.btn_open.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_tone = tk.Button(btn_row, text="🎹 播放测试乐段", font=("Microsoft YaHei", 10), fg="#ffffff", bg="#2a2a30", activebackground="#3a3a40", activeforeground="#ffffff", relief="flat", padx=12, pady=5, cursor="hand2", command=self.play_synth_tone)
        self.btn_tone.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_play = tk.Button(btn_row, text="▶ 播放", font=("Microsoft YaHei", 11, "bold"), fg="#000000", bg="#f59e0b", activebackground="#d97706", activeforeground="#000000", relief="flat", padx=16, pady=4, cursor="hand2", command=self.toggle_play_pause)
        self.btn_play.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = tk.Button(btn_row, text="⏹ 停止", font=("Microsoft YaHei", 10), fg="#ffffff", bg="#2a2a30", activebackground="#3a3a40", activeforeground="#ffffff", relief="flat", padx=12, pady=5, cursor="hand2", command=self.stop_audio)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 8))

        self.track_name_lbl = tk.Label(btn_row, text="未选择文件", font=("Microsoft YaHei", 10, "bold"), fg="#38bdf8", bg="#1a1a1e")
        self.track_name_lbl.pack(side=tk.LEFT, padx=8)

        progress_row = tk.Frame(self.local_card, bg="#1a1a1e")
        progress_row.pack(fill=tk.X, padx=16, pady=(4, 8))

        self.time_cur_lbl = tk.Label(progress_row, text="00:00", font=("Consolas", 10), fg="#888890", bg="#1a1a1e")
        self.time_cur_lbl.pack(side=tk.LEFT, padx=(0, 8))

        self.seek_scale = ttk.Scale(progress_row, from_=0, to=1000, orient=tk.HORIZONTAL, command=self.on_seek)
        self.seek_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.time_dur_lbl = tk.Label(progress_row, text="00:00", font=("Consolas", 10), fg="#888890", bg="#1a1a1e")
        self.time_dur_lbl.pack(side=tk.RIGHT, padx=(8, 0))

        # 4. 专设：全局音量控制系统面板 (现代化极简美化布局)
        vol_panel = tk.Frame(self.content_frame, bg="#1a1a1e", bd=1, relief="solid")
        vol_panel.pack(fill=tk.X, padx=24, pady=4)

        vol_inner = tk.Frame(vol_panel, bg="#1a1a1e")
        vol_inner.pack(fill=tk.X, padx=16, pady=8)

        self.btn_mute = tk.Button(
            vol_inner, text="🔊 静音", font=("Microsoft YaHei", 9, "bold"),
            fg="#ffffff", bg="#2a2a32", activebackground="#3a3a44", activeforeground="#ffffff",
            relief="flat", padx=14, pady=4, cursor="hand2", command=self.toggle_mute
        )
        self.btn_mute.pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(vol_inner, text="🔈", font=("Segoe UI Emoji", 10), fg="#71717a", bg="#1a1a1e").pack(side=tk.LEFT, padx=(0, 6))

        self.vol_scale = SmoothVolumeSlider(
            vol_inner, from_=0, to=200, initial=self.saved_vol, command=self.on_volume_change,
            height=26, bg="#1a1a1e"
        )
        self.vol_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        tk.Label(vol_inner, text="🔊", font=("Segoe UI Emoji", 10), fg="#71717a", bg="#1a1a1e").pack(side=tk.LEFT, padx=(6, 12))

        self.vol_badge_frame = tk.Frame(vol_inner, bg="#26262e", padx=10, pady=4, bd=1, relief="solid")
        self.vol_badge_frame.pack(side=tk.RIGHT)

        self.vol_lbl = tk.Label(
            self.vol_badge_frame, text=f"音量 {self.saved_vol}%",
            font=("Consolas", 10, "bold"), fg="#f59e0b" if self.saved_vol <= 100 else "#ef4444",
            bg="#26262e", width=9, anchor="center"
        )
        self.vol_lbl.pack()

        # 实时动态声学频谱卡片面板 (现代化精美暗黑磨砂面板)
        vis_panel = tk.Frame(self.content_frame, bg="#1a1a1e", bd=1, relief="solid")
        vis_panel.pack(fill=tk.X, padx=24, pady=4)

        vis_header = tk.Frame(vis_panel, bg="#1a1a1e")
        vis_header.pack(fill=tk.X, padx=14, pady=(6, 4))

        tk.Label(vis_header, text="✨ 实时动态声学频谱律动", font=("Microsoft YaHei", 9, "bold"), fg="#a1a1aa", bg="#1a1a1e").pack(side=tk.LEFT)
        self.dsp_indicator_lbl = tk.Label(vis_header, text="● 48kHz Hi-Res Hi-Fi 引擎", font=("Consolas", 8, "bold"), fg="#10b981", bg="#1a1a1e")
        self.dsp_indicator_lbl.pack(side=tk.RIGHT)

        self.visualizer_canvas = tk.Canvas(vis_panel, height=48, bg="#0e0e11", highlightthickness=0)
        self.visualizer_canvas.pack(fill=tk.X, padx=12, pady=(0, 8))

        palette = generate_spectrum_palette(32)
        self.visualizer_bars = []
        self.visualizer_peaks = []
        for i in range(32):
            bar_id = self.visualizer_canvas.create_rectangle(0, 0, 0, 0, fill=palette[i], outline="")
            self.visualizer_bars.append(bar_id)
            peak_id = self.visualizer_canvas.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline="")
            self.visualizer_peaks.append(peak_id)

        # 5. 9 款音效卡片网格 Card
        effect_card = tk.Frame(self.content_frame, bg="#1a1a1e", bd=1, relief="solid")
        effect_card.pack(fill=tk.BOTH, expand=True, padx=24, pady=4)

        grid_title = tk.Label(effect_card, text="全部音效", font=("Microsoft YaHei", 12, "bold"), fg="#ffffff", bg="#1a1a1e")
        grid_title.pack(anchor="w", padx=16, pady=(8, 4))

        grid_frame = tk.Frame(effect_card, bg="#1a1a1e")
        grid_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        for c in range(3):
            grid_frame.columnconfigure(c, weight=1, uniform="col")

        self.effect_buttons = {}
        for idx, eff in enumerate(EFFECT_DEFS):
            r = idx // 3
            c = idx % 3

            k = eff["key"]
            is_active = (k == self.current_effect_key)
            card_bg = "#382e18" if is_active else "#242429"

            btn_box = tk.Frame(grid_frame, bg=card_bg, bd=1, relief="solid", cursor="hand2")
            btn_box.grid(row=r, column=c, padx=5, pady=4, sticky="nsew")

            name_lbl = tk.Label(btn_box, text=eff["name"], font=("Microsoft YaHei", 11, "bold"), fg="#f59e0b" if is_active else "#ffffff", bg=card_bg)
            name_lbl.pack(anchor="w", padx=10, pady=(6, 0))

            check_lbl = tk.Label(btn_box, text="✓" if is_active else "", font=("Microsoft YaHei", 11, "bold"), fg="#f59e0b", bg=card_bg)
            check_lbl.place(relx=1.0, rely=0.0, x=-10, y=6, anchor="ne")

            desc_lbl = tk.Label(btn_box, text=eff["desc"], font=("Microsoft YaHei", 8), fg="#909099", bg=card_bg, justify=tk.LEFT, wraplength=250)
            desc_lbl.pack(anchor="w", padx=10, pady=(2, 4))

            # 底部音效强度滑块调节行 (0% ~ 200% 范围，中间 100% 刻度节点)
            int_row = tk.Frame(btn_box, bg=card_bg)
            int_row.pack(fill=tk.X, padx=10, pady=(0, 6))

            if k == "none":
                int_title_lbl = tk.Label(int_row, text="原声直通 (100% 原始信号)", font=("Microsoft YaHei", 8), fg="#71717a", bg=card_bg)
                int_title_lbl.pack(side=tk.LEFT)
                int_val_lbl = None
                slider = None
            else:
                int_title_lbl = tk.Label(int_row, text="强度", font=("Microsoft YaHei", 8, "bold"), fg="#d97706" if is_active else "#71717a", bg=card_bg)
                int_title_lbl.pack(side=tk.LEFT, padx=(0, 4))

                init_int = self.effect_intensities.get(k, 100)
                val_fg = ("#ef4444" if init_int > 100 else "#f59e0b") if is_active else "#71717a"
                int_val_lbl = tk.Label(int_row, text=f"{init_int}%", font=("Consolas", 8, "bold"), fg=val_fg, bg=card_bg, width=4, anchor="e")
                int_val_lbl.pack(side=tk.RIGHT, padx=(4, 0))

                def _make_int_cmd(eff_k, lbl_widget):
                    def _cmd(val):
                        is_cur_act = (self.current_effect_key == eff_k)
                        fg_c = ("#ef4444" if int(val) > 100 else "#f59e0b") if is_cur_act else "#71717a"
                        lbl_widget.config(text=f"{int(val)}%", fg=fg_c)
                        self.on_effect_intensity_change(eff_k, int(val))
                    return _cmd

                slider = MiniEffectSlider(int_row, initial=init_int, command=_make_int_cmd(k, int_val_lbl), height=18, bg=card_bg, is_active=is_active)
                slider.pack(side=tk.LEFT, fill=tk.X, expand=True)

            for w in (btn_box, name_lbl, desc_lbl, check_lbl, int_row, int_title_lbl):
                if w:
                    w.bind("<Button-1>", lambda e, cur_k=k: self.switch_effect(cur_k))

            self.effect_buttons[k] = {
                "box": btn_box,
                "name_lbl": name_lbl,
                "desc_lbl": desc_lbl,
                "check_lbl": check_lbl,
                "int_row": int_row,
                "int_title_lbl": int_title_lbl,
                "int_val_lbl": int_val_lbl,
                "slider": slider
            }

        # 填充设备下拉框并更新状态
        self.populate_audio_devices()

    def install_vbcable_driver(self):
        """一键管理员提权安装内置合法签名的虚拟音频驱动"""
        if not os.path.exists(VBCABLE_SETUP_EXE):
            messagebox.showerror("错误", f"未找到驱动安装包: {VBCABLE_SETUP_EXE}")
            return

        try:
            self.log("⚡ 正在启动虚拟音频驱动安装程序 (请在系统弹窗中点击【是】)...")
            ctypes.windll.shell32.ShellExecuteW(None, "runas", VBCABLE_SETUP_EXE, None, None, 1)
            messagebox.showinfo(
                "安装提示",
                "驱动安装器已启动！\n\n1. 请在弹出的窗口中点击【Install Driver】；\n2. 安装成功后点击确定；\n3. 返回本软件点击【🔄 刷新】即可！"
            )
        except Exception as e:
            logging.error(f"Failed to launch driver setup: {e}")
            messagebox.showerror("启动异常", f"无法启动安装程序: {e}")
            self.log(f"❌ 启动驱动安装失败: {e}")

    def set_windows_default_playback_device(self, dev_name):
        """调用 nircmdc 自动切换 Windows 系统默认播放设备（彻底消除任何控制台黑框/弹窗闪烁）"""
        if os.path.exists(NIRCMD_EXE):
            try:
                startupinfo = None
                creationflags = 0
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

                subprocess.run(
                    [NIRCMD_EXE, "setdefaultsounddevice", dev_name],
                    capture_output=True,
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
                logging.info(f"Windows default sound device switched to: {dev_name}")
                return True
            except Exception as e:
                logging.error(f"Failed to set default sound device via nircmd: {e}")
        return False

    def populate_audio_devices(self):
        """枚举声卡设备并动态识别 CABLE 与物理耳机（支持运行中安全刷新，绝不崩溃）"""
        try:
            prev_sel_name = None
            try:
                cur_idx = self.output_dev_combo.current()
                if cur_idx >= 0 and cur_idx < len(self.output_dev_list):
                    prev_sel_name = self.output_dev_list[cur_idx][4]
            except Exception:
                pass

            if not self.is_live_capturing and not self.is_playing:
                try: self.pa.terminate()
                except: pass
                self.pa = pyaudio.PyAudio()

            self.output_dev_list = []
            self.has_cable_installed = False

            for i in range(self.pa.get_device_count()):
                dev = self.pa.get_device_info_by_index(i)
                host_info = self.pa.get_host_api_info_by_index(dev["hostApi"])
                name = dev["name"]
                sr = int(dev["defaultSampleRate"])

                if "wasapi" in host_info["name"].lower():
                    if ('cable' in name.lower() or 'vb-audio' in name.lower()):
                        self.has_cable_installed = True

                    if dev["maxOutputChannels"] > 0 and not dev.get("isLoopbackDevice", False):
                        if 'cable' not in name.lower() and 'vb-audio' not in name.lower():
                            self.output_dev_list.append((i, f"🎧 {name}", sr, dev["maxOutputChannels"], name))

            self.output_dev_combo['values'] = [item[1] for item in self.output_dev_list]

            if self.has_cable_installed:
                self.vbcable_bar.pack_forget()
                self.log("✅ 成功检测到系统虚拟音频通道 (已就绪)！")
            else:
                self.vbcable_bar.pack(fill=tk.X, padx=16, pady=(10, 0), before=self.live_inner)

            matched_idx = 0
            if prev_sel_name:
                for idx, item in enumerate(self.output_dev_list):
                    if item[4] == prev_sel_name:
                        matched_idx = idx
                        break
            else:
                for idx, item in enumerate(self.output_dev_list):
                    if 'xiaomi' in item[1].lower() or 'buds' in item[1].lower() or '耳机' in item[1]:
                        matched_idx = idx
                        break

            if self.output_dev_list:
                self.output_dev_combo.current(matched_idx)

            self.log(f"🔄 声卡设备列表已刷新，发现 {len(self.output_dev_list)} 个可用输出设备")

        except Exception as e:
            logging.error(f"Device enumeration exception: {e}")
            self.log(f"⚠️ 枚举声卡设备异常: {e}")

    def switch_mode(self, mode):
        self.work_mode = mode

    def toggle_live_capture(self):
        """开启/停止系统实时声音增强 (全异步 0 阻断·动态 Loading 动画架构)"""
        if self.is_live_capturing:
            self.toggle_sw.set_state("loading")
            self.sw_status_lbl.config(text="⏳ 正在还原系统声音...", fg="#f59e0b")
            self.log("⏳ 正在平稳停止系统音频流并还原默认设备...")

            def _async_stop():
                try:
                    self.is_live_capturing = False

                    if self.in_thread and self.in_thread.is_alive():
                        try: self.in_thread.join(timeout=0.3)
                        except: pass
                        self.in_thread = None

                    if self.live_thread and self.live_thread.is_alive():
                        try: self.live_thread.join(timeout=0.3)
                        except: pass
                        self.live_thread = None

                    if self.live_in_stream:
                        try:
                            self.live_in_stream.stop_stream()
                            self.live_in_stream.close()
                        except: pass
                        self.live_in_stream = None

                    if self.live_out_stream:
                        try:
                            self.live_out_stream.stop_stream()
                            self.live_out_stream.close()
                        except: pass
                        self.live_out_stream = None

                    if self.original_default_audio_name:
                        self.set_windows_default_playback_device(self.original_default_audio_name)

                    self.root.after(0, lambda: self.toggle_sw.set_state("off"))
                    self.root.after(0, lambda: self.sw_status_lbl.config(text="● 未开启 (点击开启)", fg="#9ca3af"))
                    self.log("⏹️ 系统全局声音实时增强已停止，默认播放设备已还原。")
                except Exception as e:
                    logging.error(f"Async stop capture error: {e}")
                    self.root.after(0, lambda: self.toggle_sw.set_state("off"))

            threading.Thread(target=_async_stop, daemon=True).start()

        else:
            if not self.has_cable_installed:
                messagebox.showwarning("提示", "未检测到虚拟音频通道，请先点击【一键安装驱动】！")
                return

            if not self.output_dev_list:
                messagebox.showerror("错误", "未找到可用的物理耳机/音箱输出设备！")
                return

            self.toggle_sw.set_state("loading")
            self.sw_status_lbl.config(text="⏳ 正在启动增强引擎...", fg="#f59e0b")
            self.log("⏳ 正在初始化声卡并接管 Windows 声音输出...")

            def _async_start():
                try:
                    cable_in_name = "CABLE Input"
                    cable_out_idx = None
                    cable_out_sr = 48000
                    cable_out_channels = 2

                    # 严格锁定与物理耳机同一 WASAPI 架构的 CABLE 录音通道 (彻底杜绝 MME 混合模式死锁卡死)
                    for i in range(self.pa.get_device_count()):
                        dev = self.pa.get_device_info_by_index(i)
                        host_info = self.pa.get_host_api_info_by_index(dev["hostApi"])
                        name = dev["name"].lower()
                        if "wasapi" in host_info["name"].lower():
                            if ('cable' in name or 'vb-audio' in name) and dev["maxInputChannels"] > 0 and not dev.get("isLoopbackDevice", False):
                                cable_out_idx = i
                                cable_out_sr = int(dev["defaultSampleRate"])
                                cable_out_channels = min(2, dev["maxInputChannels"])
                                break

                    if cable_out_idx is None:
                        self.root.after(0, lambda: self.toggle_sw.set_state("off"))
                        self.root.after(0, lambda: messagebox.showerror("错误", "未找到 CABLE 录音设备，请检查驱动是否正常安装！"))
                        return

                    sel_idx = self.output_dev_combo.current()
                    if sel_idx < 0 or sel_idx >= len(self.output_dev_list):
                        sel_idx = 0
                    out_dev_info = self.output_dev_list[sel_idx]
                    phys_out_idx = out_dev_info[0]
                    phys_out_name = out_dev_info[4]
                    phys_out_sr = out_dev_info[2]
                    phys_out_channels = min(2, out_dev_info[3])

                    self.original_default_audio_name = phys_out_name

                    self.live_rate = phys_out_sr
                    self.sample_rate = self.live_rate
                    self.live_chunk_size = 1024

                    self.apply_current_effect_to_dsp()

                    self.set_windows_default_playback_device(cable_in_name)
                    self.log("⚡ [全自动接管] Windows 声音输出已自动重定向至 DSP 调音引擎 (CABLE Input)")

                    self.live_in_stream = self.pa.open(
                        format=pyaudio.paFloat32,
                        channels=cable_out_channels,
                        rate=self.live_rate,
                        input=True,
                        input_device_index=cable_out_idx,
                        frames_per_buffer=self.live_chunk_size
                    )
                    self.log(f"Opening live_in_stream: index={cable_out_idx}, rate={self.live_rate}")

                    self.live_out_stream = self.pa.open(
                        format=pyaudio.paFloat32,
                        channels=phys_out_channels,
                        rate=self.live_rate,
                        output=True,
                        output_device_index=phys_out_idx,
                        frames_per_buffer=self.live_chunk_size
                    )
                    self.log(f"Opening live_out_stream: index={phys_out_idx}, rate={self.live_rate}")

                    self.is_live_capturing = True
                    self.live_ring_buffer = queue.Queue(maxsize=16)

                    self.in_thread = threading.Thread(target=self._in_capture_and_dsp_worker, daemon=True)
                    self.in_thread.start()

                    self.live_thread = threading.Thread(target=self._out_playback_worker, daemon=True)
                    self.live_thread.start()

                    self.root.after(0, lambda: self.toggle_sw.set_state("on"))
                    self.root.after(0, lambda: self.sw_status_lbl.config(text="● 实时增强运行中 (已接管)", fg="#34d399"))
                    self.log("🎙️ 系统全局声音实时增强已成功启动！")
                    self.log(f"   -> 捕获源: CABLE Output (Index {cable_out_idx}, {self.live_rate}Hz)")
                    self.log(f"   -> 监听耳机: {out_dev_info[1]} (Index {phys_out_idx}, {self.live_rate}Hz)")

                except Exception as e:
                    logging.error(f"Failed to start live capture: {e}\n{traceback.format_exc()}")
                    self.is_live_capturing = False
                    self.root.after(0, lambda: self.toggle_sw.set_state("off"))
                    self.root.after(0, lambda: self.sw_status_lbl.config(text="● 启动失败", fg="#ef4444"))
                    if self.original_default_audio_name:
                        self.set_windows_default_playback_device(self.original_default_audio_name)
                    self.root.after(0, lambda: messagebox.showerror("启动失败", f"无法启动系统声音接管: {e}"))

            threading.Thread(target=_async_start, daemon=True).start()

    def _in_capture_and_dsp_worker(self):
        logging.info("Entering zero-stutter Ingest-DSP live_capture_worker with REALTIME TELEMETRY...")
        chunk_counter = 0
        last_log_time = time.time()

        while self.is_live_capturing:
            try:
                if not self.live_in_stream:
                    break
                data = self.live_in_stream.read(self.live_chunk_size, exception_on_overflow=False)
                if not data:
                    time.sleep(0.001)
                    continue

                floats = np.frombuffer(data, dtype=np.float32).copy()
                if len(floats) == 0:
                    continue
                if floats.ndim == 1:
                    floats = floats.reshape(-1, 2)
                if len(floats) == 0:
                    continue

                peak_in = float(np.max(np.abs(floats))) if len(floats) > 0 else 0.0
                rms_in = float(np.sqrt(np.mean(floats ** 2))) if len(floats) > 0 else 0.0

                fft_data = np.abs(np.fft.rfft(floats[:, 0]))
                if len(fft_data) >= 32:
                    step = len(fft_data) // 32
                    if step > 0:
                        self.fft_magnitudes = fft_data[:32*step:step][:32]

                # 极速 DSP 滤波与双级级联处理
                t0 = time.time()
                processed = self.dsp_client.process_chunk(floats)
                dsp_latency_ms = (time.time() - t0) * 1000.0

                effective_vol = self.volume
                out = processed * effective_vol
                if effective_vol > 1.0:
                    apply_studio_soft_limiter(out)

                peak_out = float(np.max(np.abs(out))) if len(out) > 0 else 0.0
                out_bytes = out.astype(np.float32).tobytes()

                try:
                    self.live_ring_buffer.put(out_bytes, block=False)
                except queue.Full:
                    try:
                        self.live_ring_buffer.get_nowait()
                        self.live_ring_buffer.put_nowait(out_bytes)
                    except: pass

                chunk_counter += 1
                now = time.time()
                if now - last_log_time >= 1.0:
                    logging.info(f"[AUDIO TELEMETRY] Chunks={chunk_counter}, In-Peak={peak_in:.4f}, In-RMS={rms_in:.4f}, DSP={dsp_latency_ms:.2f}ms, Out-Peak={peak_out:.4f}, Vol={effective_vol*100:.0f}%, Queue={self.live_ring_buffer.qsize()}")
                    last_log_time = now

            except Exception as e:
                if not self.is_live_capturing:
                    break
                logging.error(f"Live Ingest Worker Exception: {e}")
                time.sleep(0.01)

    def _out_playback_worker(self):
        logging.info("Entering zero-stutter Out-Playback live_capture_worker...")
        while self.is_live_capturing:
            try:
                if not self.live_out_stream:
                    break
                try:
                    chunk_bytes = self.live_ring_buffer.get(timeout=0.05)
                except queue.Empty:
                    chunk_bytes = b'\x00' * (self.live_chunk_size * 2 * 4)

                self.live_out_stream.write(chunk_bytes)
            except Exception as e:
                if not self.is_live_capturing:
                    break
                logging.error(f"Live Out Playback Worker Exception: {e}")
                time.sleep(0.01)

    def on_volume_change(self, val):
        val_int = int(float(val))
        self.volume = val_int / 100.0
        if not self.is_muted:
            self.prev_volume = self.volume if self.volume > 0 else 1.0

        if val_int > 100:
            self.vol_lbl.config(text=f"增强 {val_int}%", fg="#ef4444")
        else:
            self.vol_lbl.config(text=f"音量 {val_int}%", fg="#f59e0b")
        self.user_cfg["volume"] = val_int
        self.save_user_config()

    def adjust_volume(self, delta):
        cur = self.vol_scale.get()
        new_val = max(0, min(200, cur + delta))
        self.vol_scale.set(new_val)
        self.on_volume_change(new_val)

    def toggle_mute(self):
        if self.is_muted:
            self.is_muted = False
            restore_val = int(self.prev_volume * 100) if self.prev_volume > 0 else 100
            self.vol_scale.set(restore_val)
            self.volume = restore_val / 100.0
            if restore_val > 100:
                self.vol_lbl.config(text=f"增强 {restore_val}%", fg="#ef4444")
            else:
                self.vol_lbl.config(text=f"音量 {restore_val}%", fg="#f59e0b")
            self.btn_mute.config(text="🔊 静音", bg="#2a2a32", fg="#ffffff")
            self.log(f"🔊 软件音量已恢复 ({restore_val}%)")
        else:
            self.prev_volume = self.volume if self.volume > 0 else 1.0
            self.is_muted = True
            self.vol_scale.set(0)
            self.volume = 0.0
            self.vol_lbl.config(text="已静音 0%", fg="#71717a")
            self.btn_mute.config(text="🔇 恢复声音", bg="#ef4444", fg="#ffffff")
            self.log("🔇 软件音量已静音")

    def choose_file(self):
        file_path = filedialog.askopenfilename(
            title="选择音乐文件",
            filetypes=[("音频文件", "*.mp3 *.wav *.flac *.ogg *.aac *.m4a"), ("所有文件", "*.*")]
        )
        if file_path:
            self.load_audio_file(file_path)

    def load_audio_file(self, file_path):
        try:
            self.log(f"正在加载音频文件: {os.path.basename(file_path)} ...")
            data, sr = sf.read(file_path, dtype='float32')

            if data.ndim == 1:
                data = np.column_stack((data, data))
            elif data.shape[1] > 2:
                data = data[:, :2]

            self.audio_data = data
            self.sample_rate = sr
            self.total_frames = len(data)
            self.current_frame = 0

            self.track_name_lbl.config(text=os.path.basename(file_path))
            dur_sec = self.total_frames / self.sample_rate
            self.time_dur_lbl.config(text=self.format_time(dur_sec))
            self.seek_scale.config(to=self.total_frames)
            self.seek_scale.set(0)

            self.log(f"已加载: {os.path.basename(file_path)} | 采样率: {sr}Hz | 时长: {self.format_time(dur_sec)}")
            self.apply_current_effect_to_dsp()
            self.play_audio()
        except Exception as e:
            logging.error(f"Failed to load audio: {e}")
            messagebox.showerror("错误", f"无法加载音频文件: {e}")

    def play_synth_tone(self):
        sr = 44100
        dur = 12.0
        t = np.linspace(0, dur, int(sr * dur), endpoint=False)

        chord_c = 0.25 * np.sin(2 * np.pi * 261.63 * t)
        chord_e = 0.20 * np.sin(2 * np.pi * 329.63 * t)
        chord_g = 0.20 * np.sin(2 * np.pi * 392.00 * t)
        base = chord_c + chord_e + chord_g

        pan = np.sin(2 * np.pi * 0.25 * t) * 0.45 + 0.5
        left = base * np.sqrt(1 - pan)
        right = base * np.sqrt(pan)

        synth_data = np.column_stack((left, right)).astype(np.float32)

        self.audio_data = synth_data
        self.sample_rate = sr
        self.total_frames = len(synth_data)
        self.current_frame = 0

        self.track_name_lbl.config(text="立体声合成乐段 (C-Major Chord)")
        self.time_dur_lbl.config(text=self.format_time(dur))
        self.seek_scale.config(to=self.total_frames)
        self.seek_scale.set(0)

        self.log("🎹 正在播放空间测试乐段，可点击下方音效卡片实时对比！")
        self.apply_current_effect_to_dsp()
        self.play_audio()

    def apply_current_effect_to_dsp(self):
        target_key = self.current_effect_key
        sr = getattr(self, 'sample_rate', 48000)
        cur_int = self.effect_intensities.get(target_key, 100)

        def _async_loader():
            try:
                if target_key == "none":
                    self.dsp_client.load_effect(None, sr, 0)
                    return

                preset_file = os.path.join(PRESETS_DIR, f"{target_key}.json")
                if os.path.exists(preset_file):
                    with open(preset_file, 'r', encoding='utf-8') as fp:
                        cfg_obj = json.load(fp)
                    ok = self.dsp_client.load_effect(cfg_obj, sr, cur_int)
                    if ok:
                        self.log(f"🎛️ 100% 官方 DSP 核心已加载: 【{self.get_effect_name(target_key)}】(强度: {cur_int}%)")
            except Exception as e:
                logging.error(f"Async load effect error: {e}")

        threading.Thread(target=_async_loader, daemon=True).start()

    def switch_effect(self, key):
        self.current_effect_key = key
        self.user_cfg["effect"] = key
        self.save_user_config()

        for k, widgets in self.effect_buttons.items():
            is_active = (k == key)
            bg_col = "#382e18" if is_active else "#242429"

            widgets["box"].config(bg=bg_col)
            widgets["name_lbl"].config(bg=bg_col, fg="#f59e0b" if is_active else "#ffffff")
            widgets["desc_lbl"].config(bg=bg_col)
            widgets["check_lbl"].config(bg=bg_col, text="✓" if is_active else "")
            if widgets.get("int_row"):
                widgets["int_row"].config(bg=bg_col)
            if widgets.get("int_title_lbl"):
                widgets["int_title_lbl"].config(bg=bg_col, fg="#d97706" if is_active else "#71717a")
            if widgets.get("int_val_lbl"):
                cur_val = self.effect_intensities.get(k, 100)
                val_fg = ("#ef4444" if cur_val > 100 else "#f59e0b") if is_active else "#71717a"
                widgets["int_val_lbl"].config(bg=bg_col, fg=val_fg, text=f"{cur_val}%")
            if widgets.get("slider"):
                widgets["slider"].set_active(is_active, bg_col)

        name = self.get_effect_name(key)
        self.log(f"🔄 切换当前音效: 【{name}】")
        self.apply_current_effect_to_dsp()

    def on_effect_intensity_change(self, key, val_int):
        self.effect_intensities[key] = int(val_int)
        self.user_cfg["intensities"] = self.effect_intensities
        self.save_user_config()
        if self.current_effect_key == key:
            self.dsp_client.set_intensity(val_int)
        else:
            self.switch_effect(key)

    def get_effect_name(self, key):
        for e in EFFECT_DEFS:
            if e["key"] == key:
                return e["name"]
        return key

    def toggle_play_pause(self):
        if self.audio_data is None:
            self.play_synth_tone()
            return
        if self.is_playing:
            self.pause_audio()
        else:
            self.play_audio()

    def play_audio(self):
        if self.audio_data is None:
            return
        self.is_playing = True
        self.is_paused = False
        self.btn_play.config(text="⏸ 暂停", bg="#fbbf24")

        if self.local_stream is None:
            def local_callback(in_data, frame_count, time_info, status):
                if not self.is_playing or self.is_paused:
                    return (b'\x00' * (frame_count * 2 * 4), pyaudio.paContinue)

                start = self.current_frame
                end = start + frame_count

                if start >= self.total_frames:
                    self.current_frame = 0
                    start = 0
                    end = frame_count

                if end > self.total_frames:
                    chunk = np.zeros((frame_count, 2), dtype=np.float32)
                    valid_len = self.total_frames - start
                    chunk[:valid_len] = self.audio_data[start:self.total_frames]
                    self.current_frame = 0
                else:
                    chunk = self.audio_data[start:end]
                    self.current_frame = end

                fft_data = np.abs(np.fft.rfft(chunk[:, 0]))
                if len(fft_data) >= 32:
                    step = len(fft_data) // 32
                    if step > 0:
                        self.fft_magnitudes = fft_data[:32*step:step][:32]

                processed = self.dsp_client.process_chunk(chunk)

                effective_vol = self.volume
                out = processed * effective_vol
                if effective_vol > 1.0:
                    apply_studio_soft_limiter(out)

                return (out.tobytes(), pyaudio.paContinue)

            self.local_stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=self.sample_rate,
                output=True,
                stream_callback=local_callback,
                frames_per_buffer=1024
            )
            self.local_stream.start_stream()

    def pause_audio(self):
        self.is_playing = False
        self.is_paused = True
        self.btn_play.config(text="▶ 播放", bg="#f59e0b")

    def stop_audio(self):
        self.is_playing = False
        self.is_paused = False
        self.current_frame = 0
        self.btn_play.config(text="▶ 播放", bg="#f59e0b")
        if self.local_stream:
            try:
                self.local_stream.stop_stream()
                self.local_stream.close()
            except: pass
            self.local_stream = None
        self.seek_scale.set(0)
        self.time_cur_lbl.config(text="00:00")
        self.fft_magnitudes.fill(0)

    def on_seek(self, val):
        if self.audio_data is not None:
            target_frame = int(float(val))
            self.current_frame = min(target_frame, self.total_frames - 1)
            cur_sec = self.current_frame / self.sample_rate
            self.time_cur_lbl.config(text=self.format_time(cur_sec))

    def bind_shortcuts(self):
        self.root.bind("<space>", lambda e: self.toggle_play_pause())
        self.root.bind("<Left>", lambda e: self.seek_relative(-5))
        self.root.bind("<Right>", lambda e: self.seek_relative(5))
        self.root.bind("<Up>", lambda e: self.adjust_volume(10))
        self.root.bind("<Down>", lambda e: self.adjust_volume(-10))
        self.root.bind("<m>", lambda e: self.toggle_mute())
        self.root.bind("<M>", lambda e: self.toggle_mute())
        self.root.bind("<Map>", self._on_window_restored)
        self.root.bind("<FocusIn>", lambda e: self._on_window_restored() if e.widget == self.root else None)

    def _on_window_restored(self, event=None):
        if event is None or event.widget == self.root:
            self._force_full_refresh()
            self.root.after(20, self._force_full_refresh)
            self.root.after(80, self._force_full_refresh)

    def _force_full_refresh(self):
        try:
            if self.root.state() == 'iconic':
                return

            cur_w = self.main_canvas.winfo_width()
            if cur_w > 50:
                self.main_canvas.itemconfig(self.canvas_window, width=cur_w)
                self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

            if hasattr(self, 'vol_scale') and self.vol_scale:
                self.vol_scale.draw()

            if hasattr(self, 'effect_buttons') and self.effect_buttons:
                for item in self.effect_buttons.values():
                    slider = item.get("slider")
                    if slider:
                        slider.draw()

            if hasattr(self, 'toggle_sw') and self.toggle_sw:
                self.toggle_sw._update_image()

            try:
                hwnd = self.root.winfo_id()
                parent_hwnd = ctypes.windll.user32.GetParent(hwnd)
                target_hwnd = parent_hwnd if parent_hwnd else hwnd
                flags = 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400
                ctypes.windll.user32.RedrawWindow(target_hwnd, None, None, flags)
                ctypes.windll.user32.RedrawWindow(hwnd, None, None, flags)
            except Exception:
                pass

            self.root.update_idletasks()
        except Exception:
            pass

    def seek_relative(self, delta_sec):
        if self.audio_data is not None:
            delta_frames = int(delta_sec * self.sample_rate)
            new_frame = max(0, min(self.total_frames - 1, self.current_frame + delta_frames))
            self.current_frame = new_frame
            self.seek_scale.set(new_frame)

    def update_visualizer_loop(self):
        try:
            if self.root.state() == 'iconic':
                self.root.after(100, self.update_visualizer_loop)
                return
        except Exception:
            pass

        canvas = self.visualizer_canvas
        w = canvas.winfo_width()
        h = canvas.winfo_height()

        if w > 20 and hasattr(self, 'visualizer_bars') and len(self.visualizer_bars) == 32:
            num_bars = 32
            gap = 3
            bar_w = max(2, (w - 24) / num_bars - gap)
            max_val = np.max(self.fft_magnitudes) if np.max(self.fft_magnitudes) > 0 else 1.0

            for i in range(num_bars):
                raw_val = float(self.fft_magnitudes[i] / max_val)
                self.smooth_bars[i] = self.smooth_bars[i] * 0.72 + raw_val * 0.28
                bar_h = min(h - 8, self.smooth_bars[i] * (h - 8) * 1.4)

                if bar_h > self.peak_heights[i]:
                    self.peak_heights[i] = bar_h
                else:
                    self.peak_heights[i] = max(0.0, self.peak_heights[i] - 1.2)

                x0 = 12 + i * (bar_w + gap)
                x1 = x0 + bar_w
                y0 = h - 4 - bar_h
                y1 = h - 4
                canvas.coords(self.visualizer_bars[i], x0, y0, x1, y1)

                peak_y = h - 4 - self.peak_heights[i] - 2
                if self.peak_heights[i] > 2:
                    canvas.coords(self.visualizer_peaks[i], x0, peak_y, x1, peak_y + 2)
                else:
                    canvas.coords(self.visualizer_peaks[i], 0, 0, 0, 0)

        self.root.after(35, self.update_visualizer_loop)

    def format_time(self, sec):
        if sec is None or np.isnan(sec):
            return "00:00"
        m = int(sec // 60)
        s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    def on_close(self):
        logging.info("Closing application...")
        self._sys_vol_tracking_active = False
        self.stop_audio()
        if self.is_live_capturing:
            self.toggle_live_capture()
        try:
            self.pa.terminate()
        except: pass
        if self.dsp_process:
            try:
                self.dsp_process.terminate()
            except: pass
        self.root.destroy()
        sys.exit(0)

def main():
    logging.info("=" * 60)
    logging.info("音效管理系统启动 / Application Started")
    root = tk.Tk()
    app = SodaMusicPlayerApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
