# -*- coding: utf-8 -*-
"""
音效管理 & 全局系统音频增强器 (Qt6 旗舰硬件加速版 · 浅色/深色全主题自适应)
Native Windows Desktop Audio Player & Plan B System-wide Audio DSP Enhancer (PySide6 / PyQt6)
"""

import os
import sys
import json
import time
import socket
import struct
import logging
import threading
import queue
import subprocess
import ctypes
import math
import numpy as np
import pyaudiowpatch as pyaudio

# 无论如何启动，0 延迟彻底隐藏并脱离任何黑框控制台
try:
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd != 0:
        ctypes.windll.user32.ShowWindow(hwnd, 0)
        ctypes.windll.kernel32.FreeConsole()
    ctypes.windll.winmm.timeBeginPeriod(1)

    # 注册独立 Windows App ID，确保任务栏呈现专属高清图标
    myappid = 'soda.audio.effect.manager.v2.qt'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# 优先导入 PySide6，回退支持 PyQt6
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, Slot, QPropertyAnimation, Property
    from PySide6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QBrush, QPen, QFont, QIcon, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QComboBox, QScrollArea, QFrame, QMessageBox, QSizePolicy
    )
except ImportError:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal as Signal, pyqtSlot as Slot, QPropertyAnimation, pyqtProperty as Property
    from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QBrush, QPen, QFont, QIcon, QPixmap
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QComboBox, QScrollArea, QFrame, QMessageBox, QSizePolicy
    )

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

# 配置本地日志
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
    {"key": "1_intelligent", "name": "智能音效", "desc": "跟随曲风智能适配"},
    {"key": "2_surround_360", "name": "360环绕", "desc": "多角度超大声场体验"},
    {"key": "3_deep_bass", "name": "超重低音", "desc": "澎湃低音带来更多震撼"},
    {"key": "4_clear_vocal", "name": "清澈人声", "desc": "更具穿透力的人声体验"},
    {"key": "5_sound_3d", "name": "3D音效", "desc": "足不出户享受现场声场"},
    {"key": "6_hifi_live", "name": "HIFI现场", "desc": "亲临最 high 音乐现场"},
    {"key": "7_dynamic_electro", "name": "动感电音", "desc": "独具一格电子音乐风格"},
    {"key": "8_rock_music", "name": "摇滚音效", "desc": "再现饱含激情音乐节奏"},
    {"key": "9_vintage_record", "name": "复古唱片", "desc": "复古怀旧年代感黑胶模拟"}
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
        for _ in range(retries):
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
    """录音室级模拟软饱和防爆音限幅器"""
    threshold = 0.85
    abs_audio = np.abs(audio_chunk)
    mask = abs_audio > threshold
    if np.any(mask):
        excess = abs_audio[mask] - threshold
        compressed = threshold + (1.0 - threshold) * np.tanh(excess / (1.0 - threshold))
        audio_chunk[mask] = np.sign(audio_chunk[mask]) * compressed
    return audio_chunk

def apply_windows_dark_title_bar(hwnd, enable_dark=True):
    """设置 Windows 10/11 原生标题栏深色/浅色主题 (完美消除白顶或黑顶割裂感)"""
    try:
        val = ctypes.c_int(1 if enable_dark else 0)
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            int(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val)
        )
        if res != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(hwnd), 19, ctypes.byref(val), ctypes.sizeof(val)
            )
    except Exception:
        pass


class SystemVolumeWatcher:
    """Windows 系统全局主音量实时监听器（毫秒级同步任务栏与键盘音量键变化）"""
    def __init__(self):
        self.sys_vol = 1.0
        self.sys_muted = False
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=0.3)
            except Exception:
                pass
            self.thread = None

    def _worker(self):
        try:
            from comtypes import CoInitialize, CoUninitialize
            import pycaw.pycaw as pc
            CoInitialize()
            try:
                while self.running:
                    try:
                        speakers = pc.AudioUtilities.GetSpeakers()
                        if speakers and hasattr(speakers, 'EndpointVolume'):
                            ep = speakers.EndpointVolume
                            self.sys_vol = float(ep.GetMasterVolumeLevelScalar())
                            self.sys_muted = bool(ep.GetMute())
                    except Exception:
                        pass
                    time.sleep(0.04)
            finally:
                CoUninitialize()
        except Exception as e:
            logging.warning(f"SystemVolumeWatcher error: {e}")


def get_device_endpoint_volume(device_name):
    """获取指定物理声卡设备的系统音量标量 (0.0 ~ 1.0)"""
    try:
        from comtypes import CoInitialize, CoUninitialize
        import pycaw.pycaw as pc
        CoInitialize()
        try:
            for dev in pc.AudioUtilities.GetAllDevices():
                if device_name and (device_name.lower() in dev.FriendlyName.lower() or dev.FriendlyName.lower() in device_name.lower()):
                    if hasattr(dev, 'EndpointVolume'):
                        return float(dev.EndpointVolume.GetMasterVolumeLevelScalar())
        finally:
            CoUninitialize()
    except Exception:
        pass
    return None


def set_device_endpoint_volume(device_name, volume_scalar):
    """设置指定物理声卡设备的系统音量标量 (0.0 ~ 1.0)"""
    try:
        from comtypes import CoInitialize, CoUninitialize
        import pycaw.pycaw as pc
        CoInitialize()
        try:
            for dev in pc.AudioUtilities.GetAllDevices():
                if device_name and (device_name.lower() in dev.FriendlyName.lower() or dev.FriendlyName.lower() in device_name.lower()):
                    if hasattr(dev, 'EndpointVolume'):
                        dev.EndpointVolume.SetMasterVolumeLevelScalar(float(volume_scalar), None)
        finally:
            CoUninitialize()
    except Exception:
        pass


# ==============================================================================
# 自定义现代 Qt6 硬件加速美化控件 (支持浅色/深色主题动态适配)
# ==============================================================================

class SmoothToggleSwitch(QWidget):
    """现代 Fluent 风格平滑滑动开关（支持动画过渡与加载中 Spinner 状态）"""
    toggled = Signal(bool)

    def __init__(self, parent=None, width=54, height=28):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = False
        self._loading = False
        self._thumb_pos = 0.0
        self._spinner_angle = 0
        self.theme = "dark"

        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(160)

        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._rotate_spinner)

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def get_thumb_pos(self):
        return self._thumb_pos

    def set_thumb_pos(self, pos):
        self._thumb_pos = pos
        self.update()

    thumb_pos = Property(float, get_thumb_pos, set_thumb_pos)

    def _rotate_spinner(self):
        self._spinner_angle = (self._spinner_angle + 24) % 360
        self.update()

    def set_state(self, state):
        """state: 'on', 'off', 'loading'"""
        if state == "loading":
            self._loading = True
            if not self._spinner_timer.isActive():
                self._spinner_timer.start(30)
            self.update()
        else:
            self._loading = False
            self._spinner_timer.stop()
            self._checked = (state == "on")
            self._anim.stop()
            self._anim.setStartValue(self._thumb_pos)
            self._anim.setEndValue(1.0 if self._checked else 0.0)
            self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._loading:
            self.toggled.emit(not self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        r = h / 2.0

        if self._loading:
            bg_col = QColor("#d97706")
            border_col = QColor("#b45309")
        elif self._thumb_pos > 0.01:
            bg_col = QColor(16, 185, 129)
            border_col = QColor(5, 150, 105)
        else:
            if self.theme == "light":
                bg_col = QColor("#d1d5db")
                border_col = QColor("#9ca3af")
            else:
                bg_col = QColor("#3f3f46")
                border_col = QColor("#52525b")

        # 绘制胶囊外壳
        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 1.2))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), r - 1, r - 1)

        # 绘制 Thumb 或 Spinner
        if self._loading:
            cx, cy = w / 2.0, h / 2.0
            spin_r = 7.0
            painter.setPen(Qt.PenStyle.NoPen)
            for i in range(8):
                rad = math.radians(self._spinner_angle + i * 45)
                px = cx + spin_r * math.cos(rad)
                py = cy + spin_r * math.sin(rad)
                alpha = int(60 + (i / 7.0) * 195)
                painter.setBrush(QBrush(QColor(255, 255, 255, alpha)))
                dot_r = 2.2 if i >= 4 else 1.5
                painter.drawEllipse(QPointF(px, py), dot_r, dot_r)
        else:
            thumb_r = r - 3.5
            min_cx = r
            max_cx = w - r
            cx = min_cx + (max_cx - min_cx) * self._thumb_pos
            cy = h / 2.0

            # 阴影
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 40 if self.theme == "light" else 60)))
            painter.drawEllipse(QPointF(cx, cy + 1.2), thumb_r, thumb_r)

            # 白色滑块
            painter.setBrush(QBrush(QColor("#ffffff")))
            painter.drawEllipse(QPointF(cx, cy), thumb_r, thumb_r)


class FluentVolumeSlider(QWidget):
    """极速矢量音量滑块（支持金色高亮、红区增益、中间刻度与平滑拖拽）"""
    valueChanged = Signal(int)

    def __init__(self, parent=None, min_val=0, max_val=200, initial=100):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.min_val = min_val
        self.max_val = max_val
        self._val = initial
        self._dragging = False
        self.theme = "dark"

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def value(self):
        return self._val

    def setValue(self, val):
        val = max(self.min_val, min(self.max_val, int(val)))
        if val != self._val:
            self._val = val
            self.update()
            self.valueChanged.emit(self._val)

    def _pos_to_val(self, x):
        padding = 12
        w = self.width() - 2 * padding
        if w <= 0:
            return self._val
        ratio = max(0.0, min(1.0, (x - padding) / w))
        return int(round(self.min_val + ratio * (self.max_val - self.min_val)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setValue(self._pos_to_val(event.position().x()))

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.setValue(self._pos_to_val(event.position().x()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def wheelEvent(self, event):
        delta = 5 if event.angleDelta().y() > 0 else -5
        self.setValue(self._val + delta)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h / 2.0
        padding = 12.0
        track_w = w - 2 * padding

        ratio = (self._val - self.min_val) / float(self.max_val - self.min_val)
        cx = padding + track_w * ratio

        # 1. 轨道底槽
        track_col = QColor("#e5e7eb") if self.theme == "light" else QColor("#2a2a35")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track_col))
        painter.drawRoundedRect(QRectF(padding, cy - 3, track_w, 6), 3, 3)

        # 2. 100% 刻度标记
        notch_col = QColor("#9ca3af") if self.theme == "light" else QColor("#4b4b5c")
        painter.setPen(QPen(notch_col, 2))
        painter.drawLine(QPointF(padding + track_w * 0.5, cy - 5), QPointF(padding + track_w * 0.5, cy + 5))

        # 3. 激活进度填充
        if cx > padding + 1:
            prog_col = QColor("#ef4444") if self._val > 100 else QColor("#f59e0b")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(prog_col))
            painter.drawRoundedRect(QRectF(padding, cy - 3, cx - padding, 6), 3, 3)

        # 4. 触点 (金色/红色外圈 + 纯白实心内圈)
        prog_col = QColor("#ef4444") if self._val > 100 else QColor("#f59e0b")
        painter.setBrush(QBrush(prog_col))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 8, 8)

        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(QPointF(cx, cy), 4.5, 4.5)


class MiniCardSlider(QWidget):
    """卡片内部精致微型滑块（0% ~ 200%，100% 磁吸对齐）"""
    valueChanged = Signal(int)

    def __init__(self, parent=None, initial=100, is_active=False):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._val = initial
        self._is_active = is_active
        self._dragging = False
        self.theme = "dark"

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def value(self):
        return self._val

    def setValue(self, val):
        val = max(0, min(200, int(val)))
        if val != self._val:
            self._val = val
            self.update()
            self.valueChanged.emit(self._val)

    def setActive(self, is_active):
        self._is_active = is_active
        self.update()

    def _pos_to_val(self, x):
        padding = 6
        w = self.width() - 2 * padding
        if w <= 0:
            return self._val
        ratio = max(0.0, min(1.0, (x - padding) / w))
        raw = int(round(ratio * 200))
        if 96 <= raw <= 104:
            return 100
        return raw

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setValue(self._pos_to_val(event.position().x()))

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.setValue(self._pos_to_val(event.position().x()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        cy = h / 2.0
        padding = 6.0
        track_w = w - 2 * padding

        ratio = self._val / 200.0
        cx = padding + track_w * ratio
        mid_x = padding + track_w * 0.5

        if self._is_active:
            track_base = QColor("#fde68a") if self.theme == "light" else QColor("#261e12")
            fill_col = QColor("#ef4444") if self._val > 100 else QColor("#f59e0b")
            thumb_outer = fill_col
            thumb_inner = QColor("#ffffff")
            notch_col = QColor("#d97706") if self.theme == "light" else (QColor("#ffffff") if self._val >= 100 else QColor("#855810"))
        else:
            track_base = QColor("#e5e7eb") if self.theme == "light" else QColor("#22222b")
            fill_col = QColor("#9ca3af") if self.theme == "light" else QColor("#3f3f4c")
            thumb_outer = QColor("#6b7280") if self.theme == "light" else QColor("#525262")
            thumb_inner = QColor("#ffffff") if self.theme == "light" else QColor("#3f3f4c")
            notch_col = QColor("#cbd5e1") if self.theme == "light" else QColor("#2a2a35")

        # 1. 轨道
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(track_base))
        painter.drawRoundedRect(QRectF(padding, cy - 2, track_w, 4), 2, 2)

        # 2. 进度填充
        if cx > padding + 1:
            painter.setBrush(QBrush(fill_col))
            painter.drawRoundedRect(QRectF(padding, cy - 2, cx - padding, 4), 2, 2)

        # 3. 100% 刻度标记
        painter.setPen(QPen(notch_col, 1.5))
        painter.drawLine(QPointF(mid_x, cy - 3), QPointF(mid_x, cy + 3))

        # 4. 触点
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(thumb_outer))
        painter.drawEllipse(QPointF(cx, cy), 5, 5)

        painter.setBrush(QBrush(thumb_inner))
        painter.drawEllipse(QPointF(cx, cy), 2.2, 2.2)


class SpectrumVisualizerWidget(QWidget):
    """60FPS GPU 硬件加速 32 频段高保真彩虹渐变声学律动频谱仪"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.num_bars = 32
        self.smooth_bars = np.zeros(self.num_bars, dtype=np.float32)
        self.peak_heights = np.zeros(self.num_bars, dtype=np.float32)
        self.raw_magnitudes = np.zeros(self.num_bars, dtype=np.float32)
        self.theme = "dark"

        # 生成 32 频段高质感渐变色板 (黑金 -> 翡翠 -> 冰蓝 -> 梦幻紫)
        self.bar_colors = []
        for i in range(self.num_bars):
            t = i / float(self.num_bars - 1)
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
            self.bar_colors.append(QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))))

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def update_magnitudes(self, fft_magnitudes):
        if fft_magnitudes is not None and len(fft_magnitudes) >= self.num_bars:
            self.raw_magnitudes = fft_magnitudes[:self.num_bars]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        bg_col = QColor("#f9fafb") if self.theme == "light" else QColor("#121216")
        border_col = QColor("#e5e7eb") if self.theme == "light" else QColor("#272732")
        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 1))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 6, 6)

        padding = 12.0
        gap = 3.0
        total_gaps = (self.num_bars - 1) * gap
        usable_w = w - 2 * padding - total_gaps
        bar_w = max(2.0, usable_w / float(self.num_bars))

        max_val = float(np.max(self.raw_magnitudes)) if np.max(self.raw_magnitudes) > 0 else 1.0

        for i in range(self.num_bars):
            raw = float(self.raw_magnitudes[i] / max_val)
            self.smooth_bars[i] = self.smooth_bars[i] * 0.70 + raw * 0.30
            bar_h = min(h - 6.0, self.smooth_bars[i] * (h - 6.0) * 1.4)

            # 峰值下落物理模拟
            if bar_h > self.peak_heights[i]:
                self.peak_heights[i] = bar_h
            else:
                self.peak_heights[i] = max(0.0, self.peak_heights[i] - 1.1)

            x = padding + i * (bar_w + gap)
            y = h - 3.0 - bar_h

            # 绘制律动柱
            if bar_h > 1.0:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(self.bar_colors[i]))
                painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), 1.5, 1.5)

            # 绘制白线峰值 (Peak Hold Line)
            if self.peak_heights[i] > 2.0:
                peak_y = h - 3.0 - self.peak_heights[i] - 2.0
                line_col = QColor("#374151") if self.theme == "light" else QColor(255, 255, 255, 220)
                painter.setBrush(QBrush(line_col))
                painter.drawRoundedRect(QRectF(x, peak_y, bar_w, 2.0), 1.0, 1.0)


class EffectCardWidget(QFrame):
    """9款官方音效独立卡片（支持悬停发光、金色选中呼吸态及内嵌微调滑块）"""
    cardClicked = Signal(str)
    intensityChanged = Signal(str, int)

    def __init__(self, eff_def, parent=None, initial_intensity=100, is_active=False, theme="dark"):
        super().__init__(parent)
        self.eff_def = eff_def
        self.key = eff_def["key"]
        self.is_active = is_active
        self.intensity = initial_intensity
        self.theme = theme

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("EffectCard")

        self.init_ui()
        self.update_style()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(3)

        head_layout = QHBoxLayout()
        self.name_lbl = QLabel(self.eff_def["name"], self)
        self.name_lbl.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        head_layout.addWidget(self.name_lbl)

        self.check_lbl = QLabel("✓" if self.is_active else "", self)
        self.check_lbl.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        head_layout.addWidget(self.check_lbl, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addLayout(head_layout)

        self.desc_lbl = QLabel(self.eff_def["desc"], self)
        self.desc_lbl.setFont(QFont("Microsoft YaHei", 8))
        self.desc_lbl.setWordWrap(True)
        layout.addWidget(self.desc_lbl)

        self.slider_box = QWidget(self)
        slider_layout = QHBoxLayout(self.slider_box)
        slider_layout.setContentsMargins(0, 4, 0, 0)
        slider_layout.setSpacing(6)

        if self.key == "none":
            self.int_title_lbl = QLabel("原声直通纯净输出", self.slider_box)
            self.int_title_lbl.setFont(QFont("Microsoft YaHei", 8))
            slider_layout.addWidget(self.int_title_lbl)
            self.slider = None
            self.val_lbl = None
        else:
            self.int_title_lbl = QLabel("强度", self.slider_box)
            self.int_title_lbl.setFont(QFont("Microsoft YaHei", 8, QFont.Weight.Bold))
            slider_layout.addWidget(self.int_title_lbl)

            self.slider = MiniCardSlider(self.slider_box, initial=self.intensity, is_active=self.is_active)
            self.slider.set_theme(self.theme)
            self.slider.valueChanged.connect(self._on_slider_changed)
            slider_layout.addWidget(self.slider, stretch=1)

            self.val_lbl = QLabel(f"{self.intensity}%", self.slider_box)
            self.val_lbl.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            self.val_lbl.setFixedWidth(36)
            self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            slider_layout.addWidget(self.val_lbl)

        layout.addWidget(self.slider_box)

    def set_theme(self, theme):
        self.theme = theme
        if self.slider:
            self.slider.set_theme(theme)
        self.update_style()

    def _on_slider_changed(self, val):
        self.intensity = val
        if self.val_lbl:
            val_col = "#ef4444" if val > 100 else "#f59e0b"
            self.val_lbl.setText(f"{val}%")
            self.val_lbl.setStyleSheet(f"color: {val_col if self.is_active else ('#6b7280' if self.theme == 'light' else '#71717a')};")
        self.intensityChanged.emit(self.key, val)

    def set_active(self, is_active):
        self.is_active = is_active
        self.check_lbl.setText("✓" if is_active else "")
        if self.slider:
            self.slider.setActive(is_active)
        self.update_style()

    def update_style(self):
        if self.theme == "light":
            if self.is_active:
                self.setStyleSheet("""
                    QFrame#EffectCard {
                        background-color: #fffbeb;
                        border: 1.5px solid #f59e0b;
                        border-radius: 8px;
                    }
                """)
                self.name_lbl.setStyleSheet("color: #d97706;")
                self.check_lbl.setStyleSheet("color: #d97706;")
                self.desc_lbl.setStyleSheet("color: #4b5563;")
                if hasattr(self, 'int_title_lbl'):
                    self.int_title_lbl.setStyleSheet("color: #d97706;")
                if self.val_lbl:
                    val_col = "#ef4444" if self.intensity > 100 else "#f59e0b"
                    self.val_lbl.setStyleSheet(f"color: {val_col};")
            else:
                self.setStyleSheet("""
                    QFrame#EffectCard {
                        background-color: #ffffff;
                        border: 1px solid #e5e7eb;
                        border-radius: 8px;
                    }
                    QFrame#EffectCard:hover {
                        background-color: #f9fafb;
                        border: 1px solid #cbd5e1;
                    }
                """)
                self.name_lbl.setStyleSheet("color: #111827;")
                self.check_lbl.setText("")
                self.desc_lbl.setStyleSheet("color: #6b7280;")
                if hasattr(self, 'int_title_lbl'):
                    self.int_title_lbl.setStyleSheet("color: #9ca3af;")
                if self.val_lbl:
                    self.val_lbl.setStyleSheet("color: #9ca3af;")
        else:
            if self.is_active:
                self.setStyleSheet("""
                    QFrame#EffectCard {
                        background-color: #2f2615;
                        border: 1.5px solid #f59e0b;
                        border-radius: 8px;
                    }
                """)
                self.name_lbl.setStyleSheet("color: #f59e0b;")
                self.check_lbl.setStyleSheet("color: #f59e0b;")
                self.desc_lbl.setStyleSheet("color: #e5e7eb;")
                if hasattr(self, 'int_title_lbl'):
                    self.int_title_lbl.setStyleSheet("color: #d97706;")
                if self.val_lbl:
                    val_col = "#ef4444" if self.intensity > 100 else "#f59e0b"
                    self.val_lbl.setStyleSheet(f"color: {val_col};")
            else:
                self.setStyleSheet("""
                    QFrame#EffectCard {
                        background-color: #22222b;
                        border: 1px solid #2f2f3c;
                        border-radius: 8px;
                    }
                    QFrame#EffectCard:hover {
                        background-color: #292934;
                        border: 1px solid #404052;
                    }
                """)
                self.name_lbl.setStyleSheet("color: #ffffff;")
                self.check_lbl.setText("")
                self.desc_lbl.setStyleSheet("color: #9ca3af;")
                if hasattr(self, 'int_title_lbl'):
                    self.int_title_lbl.setStyleSheet("color: #71717a;")
                if self.val_lbl:
                    self.val_lbl.setStyleSheet("color: #71717a;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.cardClicked.emit(self.key)


# ==============================================================================
# Qt6 主程序窗口
# ==============================================================================

class SodaMusicPlayerQtApp(QMainWindow):
    # 线程安全信号定义
    sig_set_toggle_state = Signal(str)
    sig_set_toggle_status_text = Signal(str, str)
    sig_set_dsp_tag = Signal(str, str)
    sig_show_error = Signal(str, str)
    sig_show_info = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("音效管理")
        self.resize(980, 760)
        self.setMinimumSize(900, 560)

        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        elif os.path.exists(PNG_PATH):
            self.setWindowIcon(QIcon(PNG_PATH))

        self.user_cfg = self.load_user_config()
        self.current_theme = self.user_cfg.get("theme", "dark")
        self.saved_vol = int(self.user_cfg.get("volume", 100))
        self.volume = self.saved_vol / 100.0
        self.prev_volume = self.volume if self.volume > 0 else 1.0
        self.is_muted = False
        self.current_effect_key = self.user_cfg.get("effect", "none")
        self.effect_intensities = self.user_cfg.get("intensities", {})

        self.pa = pyaudio.PyAudio()
        self.dsp_process = None
        self.dsp_client = DspClient()
        self.sample_rate = 48000

        self.is_live_capturing = False
        self.live_thread = None
        self.in_thread = None
        self.live_in_stream = None
        self.live_out_stream = None
        self.original_default_audio_name = None
        self.has_cable_installed = False
        self.output_dev_list = []
        self.fft_magnitudes = np.zeros(32, dtype=np.float32)
        self.sys_vol_watcher = SystemVolumeWatcher()

        self.init_signals()
        self.init_ui()
        self.apply_theme(self.current_theme)
        self.start_dsp_backend()
        self.populate_audio_devices()

        # 启动 60FPS 硬件加速频谱律动定时器
        self.visualizer_timer = QTimer(self)
        self.visualizer_timer.timeout.connect(self._on_visualizer_tick)
        self.visualizer_timer.start(16)

    def load_user_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {"volume": 100, "effect": "none", "theme": "dark"}

    def save_user_config(self):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.user_cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def init_signals(self):
        self.sig_set_toggle_state.connect(lambda s: self.toggle_sw.set_state(s))
        self.sig_set_toggle_status_text.connect(lambda t, c: (self.sw_status_lbl.setText(t), self.sw_status_lbl.setStyleSheet(f"color: {c}; font-size: 12px;")))
        self.sig_set_dsp_tag.connect(lambda t, c: (self.dsp_tag.setText(t), self.dsp_tag.setStyleSheet(f"color: {c}; font-family: Consolas; font-weight: bold; font-size: 11px;")))
        self.sig_show_error.connect(lambda title, msg: QMessageBox.critical(self, title, msg))
        self.sig_show_info.connect(lambda title, msg: QMessageBox.information(self, title, msg))

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_dark_title_bar(self.winId(), enable_dark=(self.current_theme == "dark"))

    def toggle_theme(self):
        new_theme = "dark" if self.current_theme == "light" else "light"
        self.current_theme = new_theme
        self.user_cfg["theme"] = new_theme
        self.save_user_config()
        self.apply_theme(new_theme)

    def apply_theme(self, theme):
        self.current_theme = theme
        is_light = (theme == "light")
        apply_windows_dark_title_bar(self.winId(), enable_dark=not is_light)

        # 更新主题切换按钮文本
        if hasattr(self, 'btn_theme'):
            self.btn_theme.setText("🌙 切换深色模式" if is_light else "☀️ 切换浅色模式")

        if is_light:
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #f3f4f6;
                }
                QWidget#CentralWidget {
                    background-color: #f3f4f6;
                }
                QWidget#ContentWidget {
                    background-color: #f3f4f6;
                }
                QScrollArea {
                    background-color: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    width: 0px;
                    height: 0px;
                }
                QFrame#PanelCard {
                    background-color: #ffffff;
                    border: 1px solid #e5e7eb;
                    border-radius: 10px;
                }
                QPushButton {
                    background-color: #ffffff;
                    color: #1f2937;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #f3f4f6;
                    border: 1px solid #9ca3af;
                }
                QPushButton:pressed {
                    background-color: #e5e7eb;
                }
                QComboBox {
                    background-color: #ffffff;
                    color: #111827;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }
                QComboBox:hover {
                    border: 1px solid #f59e0b;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 24px;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: #111827;
                    selection-background-color: #f59e0b;
                    selection-color: #000000;
                    border: 1px solid #d1d5db;
                    padding: 4px;
                }
                QLabel {
                    color: #111827;
                    font-family: 'Microsoft YaHei';
                }
            """)
            if hasattr(self, 'switch_box'):
                self.switch_box.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;")
            if hasattr(self, 'dev_box'):
                self.dev_box.setStyleSheet("background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;")
            if hasattr(self, 'btn_mute'):
                if not self.is_muted:
                    self.btn_mute.setStyleSheet("background-color: #ffffff; border: 1px solid #d1d5db; color: #111827; padding: 5px 14px; font-weight: bold;")
            if hasattr(self, 'vol_badge'):
                vol_color = "#ef4444" if self.saved_vol > 100 else "#f59e0b"
                self.vol_badge.setStyleSheet(f"background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 4px 6px; color: {vol_color}; font-family: Consolas; font-weight: bold;")
            if hasattr(self, 'vis_title'):
                self.vis_title.setStyleSheet("color: #111827; font-weight: bold; font-size: 12px;")
            if hasattr(self, 'dsp_tag'):
                self.dsp_tag.setStyleSheet("color: #059669; font-family: Consolas; font-weight: bold; font-size: 11px;")
        else:
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #131316;
                }
                QWidget#CentralWidget {
                    background-color: #131316;
                }
                QWidget#ContentWidget {
                    background-color: #131316;
                }
                QScrollArea {
                    background-color: transparent;
                    border: none;
                }
                QScrollBar:vertical {
                    width: 0px;
                    height: 0px;
                }
                QFrame#PanelCard {
                    background-color: #1c1c24;
                    border: 1px solid #282834;
                    border-radius: 10px;
                }
                QPushButton {
                    background-color: #242430;
                    color: #f3f4f6;
                    border: 1px solid #323242;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #2f2f3e;
                    border: 1px solid #434358;
                }
                QPushButton:pressed {
                    background-color: #1e1e26;
                }
                QComboBox {
                    background-color: #242430;
                    color: #ffffff;
                    border: 1px solid #323242;
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }
                QComboBox:hover {
                    border: 1px solid #f59e0b;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 24px;
                }
                QComboBox QAbstractItemView {
                    background-color: #242430;
                    color: #ffffff;
                    selection-background-color: #f59e0b;
                    selection-color: #000000;
                    border: 1px solid #323242;
                    padding: 4px;
                }
                QLabel {
                    color: #f3f4f6;
                    font-family: 'Microsoft YaHei';
                }
            """)
            if hasattr(self, 'switch_box'):
                self.switch_box.setStyleSheet("background-color: #22222b; border: 1px solid #2f2f3c; border-radius: 8px;")
            if hasattr(self, 'dev_box'):
                self.dev_box.setStyleSheet("background-color: #22222b; border: 1px solid #2f2f3c; border-radius: 8px;")
            if hasattr(self, 'btn_mute'):
                if not self.is_muted:
                    self.btn_mute.setStyleSheet("background-color: #22222b; border: 1px solid #2f2f3c; color: #ffffff; padding: 5px 14px; font-weight: bold;")
            if hasattr(self, 'vol_badge'):
                vol_color = "#ef4444" if self.saved_vol > 100 else "#f59e0b"
                self.vol_badge.setStyleSheet(f"background-color: #22222b; border: 1px solid #2f2f3c; border-radius: 6px; padding: 4px 6px; color: {vol_color}; font-family: Consolas; font-weight: bold;")
            if hasattr(self, 'vis_title'):
                self.vis_title.setStyleSheet("color: #f3f4f6; font-weight: bold; font-size: 12px;")
            if hasattr(self, 'dsp_tag'):
                self.dsp_tag.setStyleSheet("color: #34d399; font-family: Consolas; font-weight: bold; font-size: 11px;")

        # 子控件同步主题
        if hasattr(self, 'toggle_sw'):
            self.toggle_sw.set_theme(theme)
        if hasattr(self, 'vol_slider'):
            self.vol_slider.set_theme(theme)
        if hasattr(self, 'visualizer_widget'):
            self.visualizer_widget.set_theme(theme)
        if hasattr(self, 'card_widgets'):
            for card in self.card_widgets.values():
                card.set_theme(theme)

    def init_ui(self):
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        main_vbox = QVBoxLayout(central_widget)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # 滚动区域 (关闭水平与垂直滚动条，保持界面极简纯粹)
        scroll_area = QScrollArea(central_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_vbox.addWidget(scroll_area)

        content_widget = QWidget()
        content_widget.setObjectName("ContentWidget")
        scroll_area.setWidget(content_widget)

        content_vbox = QVBoxLayout(content_widget)
        content_vbox.setContentsMargins(20, 16, 20, 20)
        content_vbox.setSpacing(10)

        # 1. 核心控制区 Card (全局实时增强开关 + 声卡监听下拉框 + 主题切换)
        live_card = QFrame(content_widget)
        live_card.setObjectName("PanelCard")
        live_card_layout = QVBoxLayout(live_card)
        live_card_layout.setContentsMargins(16, 12, 16, 12)
        live_card_layout.setSpacing(8)

        # 仅未安装驱动时显示的提示条
        self.vbcable_bar = QWidget(live_card)
        vbcable_bar_layout = QHBoxLayout(self.vbcable_bar)
        vbcable_bar_layout.setContentsMargins(12, 6, 12, 6)
        self.vbcable_bar.setStyleSheet("background-color: #3f2305; border-radius: 6px;")
        vbcable_lbl = QLabel("💡 首次使用提示：需要安装一次虚拟音频驱动 (仅需10秒)", self.vbcable_bar)
        vbcable_lbl.setStyleSheet("color: #fed7aa; font-size: 12px;")
        vbcable_bar_layout.addWidget(vbcable_lbl)
        vbcable_bar_layout.addStretch()

        btn_install_driver = QPushButton("⚡ 一键安装驱动", self.vbcable_bar)
        btn_install_driver.setStyleSheet("background-color: #f59e0b; color: #000000; font-weight: bold; border: none; padding: 4px 10px;")
        btn_install_driver.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_install_driver.clicked.connect(self.install_vbcable_driver)
        vbcable_bar_layout.addWidget(btn_install_driver)
        live_card_layout.addWidget(self.vbcable_bar)

        live_row = QHBoxLayout()
        live_row.setSpacing(14)

        # 左侧：滑动开关
        self.switch_box = QFrame(live_card)
        switch_box_layout = QHBoxLayout(self.switch_box)
        switch_box_layout.setContentsMargins(14, 8, 14, 8)
        switch_box_layout.setSpacing(12)

        self.toggle_sw = SmoothToggleSwitch(self.switch_box, width=54, height=28)
        self.toggle_sw.toggled.connect(self.toggle_live_capture)
        switch_box_layout.addWidget(self.toggle_sw)

        sw_text_box = QVBoxLayout()
        sw_text_box.setSpacing(1)
        sw_title = QLabel("全局声音实时增强", self.switch_box)
        sw_title.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        sw_text_box.addWidget(sw_title)

        self.sw_status_lbl = QLabel("● 未开启 (点击开启)", self.switch_box)
        self.sw_status_lbl.setStyleSheet("color: #9ca3af; font-size: 12px;")
        sw_text_box.addWidget(self.sw_status_lbl)
        switch_box_layout.addLayout(sw_text_box)
        live_row.addWidget(self.switch_box)

        # 右侧：监听输出设备下拉框
        self.dev_box = QFrame(live_card)
        dev_box_layout = QVBoxLayout(self.dev_box)
        dev_box_layout.setContentsMargins(14, 8, 14, 8)
        dev_box_layout.setSpacing(4)

        dev_top = QHBoxLayout()
        dev_title = QLabel("🎧 监听输出设备 (耳机 / 音箱):", self.dev_box)
        dev_title.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        dev_top.addWidget(dev_title)
        dev_top.addStretch()

        self.btn_theme = QPushButton("☀️ 切换浅色模式", self.dev_box)
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_theme.clicked.connect(self.toggle_theme)
        dev_top.addWidget(self.btn_theme)

        btn_refresh = QPushButton("🔄 刷新", self.dev_box)
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_refresh.clicked.connect(self.populate_audio_devices)
        dev_top.addWidget(btn_refresh)
        dev_box_layout.addLayout(dev_top)

        self.output_dev_combo = QComboBox(self.dev_box)
        self.output_dev_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        dev_box_layout.addWidget(self.output_dev_combo)

        live_row.addWidget(self.dev_box, stretch=1)
        live_card_layout.addLayout(live_row)
        content_vbox.addWidget(live_card)

        # 2. 全局音量控制 Card
        self.vol_card = QFrame(content_widget)
        self.vol_card.setObjectName("PanelCard")
        vol_card_layout = QHBoxLayout(self.vol_card)
        vol_card_layout.setContentsMargins(16, 8, 16, 8)
        vol_card_layout.setSpacing(10)

        self.btn_mute = QPushButton("🔊 静音", self.vol_card)
        self.btn_mute.clicked.connect(self.toggle_mute)
        vol_card_layout.addWidget(self.btn_mute)

        vol_icon_l = QLabel("🔈", self.vol_card)
        vol_icon_l.setStyleSheet("color: #71717a; font-size: 14px;")
        vol_card_layout.addWidget(vol_icon_l)

        self.vol_slider = FluentVolumeSlider(self.vol_card, min_val=0, max_val=200, initial=self.saved_vol)
        self.vol_slider.valueChanged.connect(self.on_volume_change)
        vol_card_layout.addWidget(self.vol_slider, stretch=1)

        vol_icon_r = QLabel("🔊", self.vol_card)
        vol_icon_r.setStyleSheet("color: #71717a; font-size: 14px;")
        vol_card_layout.addWidget(vol_icon_r)

        self.vol_badge = QLabel(f"音量 {self.saved_vol}%", self.vol_card)
        self.vol_badge.setFixedWidth(80)
        self.vol_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_color = "#ef4444" if self.saved_vol > 100 else "#f59e0b"
        self.vol_badge.setStyleSheet(f"border-radius: 6px; padding: 4px 6px; color: {vol_color}; font-family: Consolas; font-weight: bold;")
        vol_card_layout.addWidget(self.vol_badge)

        content_vbox.addWidget(self.vol_card)

        # 3. 实时动态声学频谱律动 Card
        vis_card = QFrame(content_widget)
        vis_card.setObjectName("PanelCard")
        vis_card_layout = QVBoxLayout(vis_card)
        vis_card_layout.setContentsMargins(14, 8, 14, 8)
        vis_card_layout.setSpacing(6)

        vis_header = QHBoxLayout()
        self.vis_title = QLabel("✨ 实时动态声学频谱律动", vis_card)
        self.vis_title.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        vis_header.addWidget(self.vis_title)
        vis_header.addStretch()

        self.dsp_tag = QLabel("● 待机中 (等待开启)", vis_card)
        self.dsp_tag.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        vis_header.addWidget(self.dsp_tag)
        vis_card_layout.addLayout(vis_header)

        self.visualizer_widget = SpectrumVisualizerWidget(vis_card)
        vis_card_layout.addWidget(self.visualizer_widget)
        content_vbox.addWidget(vis_card)

        # 4. 9 大音效卡片网格 Card
        effect_card = QFrame(content_widget)
        effect_card.setObjectName("PanelCard")
        effect_card_layout = QVBoxLayout(effect_card)
        effect_card_layout.setContentsMargins(16, 12, 16, 14)
        effect_card_layout.setSpacing(10)

        grid_title = QLabel("全部音效", effect_card)
        grid_title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        effect_card_layout.addWidget(grid_title)

        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)

        self.card_widgets = {}
        for idx, eff in enumerate(EFFECT_DEFS):
            r = idx // 3
            c = idx % 3
            k = eff["key"]
            is_active = (k == self.current_effect_key)
            init_int = self.effect_intensities.get(k, 100)

            card = EffectCardWidget(eff, parent=effect_card, initial_intensity=init_int, is_active=is_active, theme=self.current_theme)
            card.cardClicked.connect(self.switch_effect)
            card.intensityChanged.connect(self.on_effect_intensity_change)
            grid_layout.addWidget(card, r, c)
            self.card_widgets[k] = card

        effect_card_layout.addLayout(grid_layout)
        content_vbox.addWidget(effect_card)

    def _on_visualizer_tick(self):
        """60FPS 极速渲染刷新"""
        if not self.isMinimized():
            self.visualizer_widget.update_magnitudes(self.fft_magnitudes)

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
                logging.info(f"DSP Backend connected successfully! (PID={self.dsp_process.pid})")
                self.apply_current_effect_to_dsp()
            else:
                logging.error("Failed to connect to local DSP core!")
                self.sig_show_error.emit("错误", "无法连接本地 DSP 音频核心，请确保系统已安装 Node.js！")
        except Exception as e:
            logging.error(f"Failed to launch DSP backend: {e}")
            self.sig_show_error.emit("启动异常", f"启动 DSP 引擎失败: {e}")

    def install_vbcable_driver(self):
        if not os.path.exists(VBCABLE_SETUP_EXE):
            self.sig_show_error.emit("错误", f"未找到驱动安装包: {VBCABLE_SETUP_EXE}")
            return
        try:
            self.log("⚡ 正在启动虚拟音频驱动安装程序 (请在系统弹窗中点击【是】)...")
            ctypes.windll.shell32.ShellExecuteW(None, "runas", VBCABLE_SETUP_EXE, None, None, 1)
            self.sig_show_info.emit(
                "安装提示",
                "驱动安装器已启动！\n\n1. 请在弹出的窗口中点击【Install Driver】；\n2. 安装成功后点击确定；\n3. 返回本软件点击【🔄 刷新】即可！"
            )
        except Exception as e:
            logging.error(f"Failed to launch driver setup: {e}")
            self.sig_show_error.emit("启动异常", f"无法启动安装程序: {e}")

    def set_windows_default_playback_device(self, dev_name):
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
        try:
            prev_sel_name = None
            cur_idx = self.output_dev_combo.currentIndex()
            if cur_idx >= 0 and cur_idx < len(self.output_dev_list):
                prev_sel_name = self.output_dev_list[cur_idx][4]

            if not self.is_live_capturing:
                try: self.pa.terminate()
                except Exception: pass
                self.pa = pyaudio.PyAudio()

            self.output_dev_list = []
            self.has_cable_installed = False

            for i in range(self.pa.get_device_count()):
                try:
                    dev = self.pa.get_device_info_by_index(i)
                    host_info = self.pa.get_host_api_info_by_index(dev["hostApi"])
                    name = str(dev["name"])
                    sr = int(dev["defaultSampleRate"])
                    name_lower = name.lower()

                    if 'cable' in name_lower or 'vb-audio' in name_lower or 'virtual cable' in name_lower:
                        self.has_cable_installed = True

                    if "wasapi" in host_info["name"].lower():
                        if dev["maxOutputChannels"] > 0 and not dev.get("isLoopbackDevice", False):
                            if 'cable' not in name_lower and 'vb-audio' not in name_lower:
                                self.output_dev_list.append((i, f"🎧 {name}", sr, dev["maxOutputChannels"], name))
                except Exception as dev_err:
                    logging.warning(f"Error parsing device {i}: {dev_err}")

            self.output_dev_combo.clear()
            self.output_dev_combo.addItems([item[1] for item in self.output_dev_list])

            if self.has_cable_installed:
                self.vbcable_bar.hide()
                self.log("✅ 成功检测到系统虚拟音频通道 (已就绪)！")
            else:
                self.vbcable_bar.show()

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
                self.output_dev_combo.setCurrentIndex(matched_idx)

            self.log(f"🔄 声卡设备列表已刷新，发现 {len(self.output_dev_list)} 个可用输出设备")
        except Exception as e:
            logging.error(f"Device enumeration exception: {e}")

    def toggle_live_capture(self, checked):
        if self.is_live_capturing:
            self.sig_set_toggle_state.emit("loading")
            self.sig_set_toggle_status_text.emit("⏳ 正在还原系统声音...", "#f59e0b")
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

                    try:
                        self.sys_vol_watcher.stop()
                    except Exception: pass

                    if self.original_default_audio_name:
                        self.set_windows_default_playback_device(self.original_default_audio_name)
                        if self.original_phys_vol is not None:
                            set_device_endpoint_volume(self.original_default_audio_name, self.original_phys_vol)

                    self.sig_set_toggle_state.emit("off")
                    self.sig_set_toggle_status_text.emit("● 未开启 (点击开启)", "#9ca3af")
                    self.sig_set_dsp_tag.emit("● 待机中 (等待开启)", "#71717a" if self.current_theme == "dark" else "#9ca3af")
                    self.log("⏹️ 系统全局声音实时增强已停止，默认播放设备及音量已还原。")
                except Exception as e:
                    logging.error(f"Async stop capture error: {e}")
                    self.sig_set_toggle_state.emit("off")
                    self.sig_set_dsp_tag.emit("● 待机中", "#71717a" if self.current_theme == "dark" else "#9ca3af")

            threading.Thread(target=_async_stop, daemon=True).start()
        else:
            if not self.has_cable_installed:
                self.sig_show_info.emit("提示", "未检测到虚拟音频通道，请先点击【一键安装驱动】！")
                return

            if not self.output_dev_list:
                self.sig_show_error.emit("错误", "未找到可用的物理耳机/音箱输出设备！")
                return

            self.sig_set_toggle_state.emit("loading")
            self.sig_set_toggle_status_text.emit("⏳ 正在启动增强引擎...", "#f59e0b")
            self.sig_set_dsp_tag.emit("⏳ 正在初始化声卡...", "#f59e0b")
            self.log("⏳ 正在初始化声卡并接管 Windows 声音输出...")

            def _async_start():
                try:
                    cable_in_name = "CABLE Input"
                    cable_out_idx = None
                    cable_out_sr = 48000
                    cable_out_channels = 2

                    # 优先选择 CABLE Output 捕获原始完整信号 (避免被 Windows 提前二次衰减)
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

                    # 回退机制：若未获取到普通录音通道，则使用 Loopback 通道
                    if cable_out_idx is None:
                        for i in range(self.pa.get_device_count()):
                            dev = self.pa.get_device_info_by_index(i)
                            host_info = self.pa.get_host_api_info_by_index(dev["hostApi"])
                            name = dev["name"].lower()
                            if "wasapi" in host_info["name"].lower():
                                if ('cable' in name or 'vb-audio' in name) and dev["maxInputChannels"] > 0:
                                    cable_out_idx = i
                                    cable_out_sr = int(dev["defaultSampleRate"])
                                    cable_out_channels = min(2, dev["maxInputChannels"])
                                    break

                    if cable_out_idx is None:
                        self.sig_set_toggle_state.emit("off")
                        self.sig_set_dsp_tag.emit("● 待机中", "#71717a")
                        self.sig_show_error.emit("错误", "未找到 CABLE 录音设备，请检查驱动是否正常安装！")
                        return

                    sel_idx = self.output_dev_combo.currentIndex()
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

                    # 保存物理耳机/音箱原始音量，并将物理设备端点拉满至 100% 满幅，由软件内核与系统音量乘积完全控制
                    self.original_phys_vol = get_device_endpoint_volume(phys_out_name)
                    set_device_endpoint_volume(phys_out_name, 1.0)

                    self.apply_current_effect_to_dsp()
                    self.set_windows_default_playback_device(cable_in_name)

                    self.live_in_stream = self.pa.open(
                        format=pyaudio.paFloat32,
                        channels=cable_out_channels,
                        rate=self.live_rate,
                        input=True,
                        input_device_index=cable_out_idx,
                        frames_per_buffer=self.live_chunk_size
                    )

                    self.live_out_stream = self.pa.open(
                        format=pyaudio.paFloat32,
                        channels=phys_out_channels,
                        rate=self.live_rate,
                        output=True,
                        output_device_index=phys_out_idx,
                        frames_per_buffer=self.live_chunk_size
                    )

                    # 启动 Windows 系统主音量实时监听
                    self.sys_vol_watcher.start()

                    self.is_live_capturing = True
                    self.live_ring_buffer = queue.Queue(maxsize=16)

                    self.in_thread = threading.Thread(target=self._in_capture_and_dsp_worker, daemon=True)
                    self.in_thread.start()

                    self.live_thread = threading.Thread(target=self._out_playback_worker, daemon=True)
                    self.live_thread.start()

                    self.sig_set_toggle_state.emit("on")
                    self.sig_set_toggle_status_text.emit("● 实时增强运行中 (已接管)", "#34d399")
                    self.sig_set_dsp_tag.emit(f"● {self.live_rate // 1000}kHz 实时调音运行中", "#34d399" if self.current_theme == "dark" else "#059669")
                    self.log("🎙️ 系统全局声音实时增强已成功启动！")
                except Exception as e:
                    logging.error(f"Failed to start live capture: {e}")
                    self.is_live_capturing = False
                    self.sig_set_toggle_state.emit("off")
                    self.sig_set_toggle_status_text.emit("● 启动失败", "#ef4444")
                    self.sig_set_dsp_tag.emit("● 启动失败", "#ef4444")
                    if self.original_default_audio_name:
                        self.set_windows_default_playback_device(self.original_default_audio_name)
                    self.sig_show_error.emit("启动失败", f"无法启动系统声音接管: {e}")

            threading.Thread(target=_async_start, daemon=True).start()

    def _in_capture_and_dsp_worker(self):
        logging.info("Entering Ingest-DSP live_capture_worker...")
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

                fft_data = np.abs(np.fft.rfft(floats[:, 0]))
                if len(fft_data) >= 32:
                    step = len(fft_data) // 32
                    if step > 0:
                        self.fft_magnitudes = fft_data[:32*step:step][:32]

                processed = self.dsp_client.process_chunk(floats)

                # 完美结合 Windows 系统主音量与软件内增益滑块
                sys_factor = 0.0 if self.sys_vol_watcher.sys_muted else self.sys_vol_watcher.sys_vol
                effective_vol = self.volume * sys_factor
                out = processed * effective_vol
                if effective_vol > 1.0:
                    apply_studio_soft_limiter(out)

                out_bytes = out.astype(np.float32).tobytes()

                try:
                    self.live_ring_buffer.put(out_bytes, block=False)
                except queue.Full:
                    try:
                        self.live_ring_buffer.get_nowait()
                        self.live_ring_buffer.put_nowait(out_bytes)
                    except: pass

            except Exception as e:
                if not self.is_live_capturing:
                    break
                logging.error(f"Live Ingest Worker Exception: {e}")
                time.sleep(0.01)

    def _out_playback_worker(self):
        logging.info("Entering Out-Playback live_capture_worker...")
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
        self.volume = val / 100.0
        if not self.is_muted:
            self.prev_volume = self.volume if self.volume > 0 else 1.0

        vol_color = "#ef4444" if val > 100 else "#f59e0b"
        prefix = "增强" if val > 100 else "音量"
        self.vol_badge.setText(f"{prefix} {val}%")
        bg_col = "#ffffff" if self.current_theme == "light" else "#22222b"
        border_col = "#e5e7eb" if self.current_theme == "light" else "#2f2f3c"
        self.vol_badge.setStyleSheet(f"background-color: {bg_col}; border: 1px solid {border_col}; border-radius: 6px; padding: 4px 6px; color: {vol_color}; font-family: Consolas; font-weight: bold;")
        self.user_cfg["volume"] = val
        self.save_user_config()

    def toggle_mute(self):
        if self.is_muted:
            self.is_muted = False
            restore_val = int(self.prev_volume * 100) if self.prev_volume > 0 else 100
            self.vol_slider.setValue(restore_val)
            self.btn_mute.setText("🔊 静音")
            if self.current_theme == "light":
                self.btn_mute.setStyleSheet("background-color: #ffffff; border: 1px solid #d1d5db; color: #111827; padding: 5px 14px; font-weight: bold;")
            else:
                self.btn_mute.setStyleSheet("background-color: #22222b; border: 1px solid #2f2f3c; color: #ffffff; padding: 5px 14px; font-weight: bold;")
        else:
            self.prev_volume = self.volume if self.volume > 0 else 1.0
            self.is_muted = True
            self.vol_slider.setValue(0)
            self.btn_mute.setText("🔇 恢复声音")
            self.btn_mute.setStyleSheet("background-color: #ef4444; color: #ffffff; border: 1px solid #dc2626; padding: 5px 14px; font-weight: bold;")

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
                        self.log(f"🎛️ 100% 官方 DSP 核心已加载: 【{target_key}】(强度: {cur_int}%)")
            except Exception as e:
                logging.error(f"Async load effect error: {e}")

        threading.Thread(target=_async_loader, daemon=True).start()

    def switch_effect(self, key):
        self.current_effect_key = key
        self.user_cfg["effect"] = key
        self.save_user_config()

        for k, card in self.card_widgets.items():
            card.set_active(k == key)

        self.apply_current_effect_to_dsp()

    def on_effect_intensity_change(self, key, val_int):
        self.effect_intensities[key] = int(val_int)
        self.user_cfg["intensities"] = self.effect_intensities
        self.save_user_config()
        if self.current_effect_key == key:
            self.dsp_client.set_intensity(val_int)
        else:
            self.switch_effect(key)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Up:
            self.vol_slider.setValue(self.vol_slider.value() + 10)
        elif key == Qt.Key.Key_Down:
            self.vol_slider.setValue(self.vol_slider.value() - 10)
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        logging.info("Closing application...")
        try:
            self.sys_vol_watcher.stop()
        except Exception:
            pass
        if self.is_live_capturing:
            self.toggle_live_capture(False)
        try:
            self.pa.terminate()
        except Exception:
            pass
        if self.dsp_process:
            try:
                self.dsp_process.terminate()
            except Exception:
                pass
        event.accept()

def main():
    logging.info("=" * 60)
    logging.info("音效管理系统 (Qt6 旗舰版) 启动 / Qt6 Application Started")
    app = QApplication(sys.argv)
    window = SodaMusicPlayerQtApp()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
