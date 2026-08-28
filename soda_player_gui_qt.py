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
        QLabel, QPushButton, QComboBox, QScrollArea, QFrame, QMessageBox, QSizePolicy,
        QStackedLayout
    )
except ImportError:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal as Signal, pyqtSlot as Slot, QPropertyAnimation, pyqtProperty as Property
    from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QBrush, QPen, QFont, QIcon, QPixmap
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QComboBox, QScrollArea, QFrame, QMessageBox, QSizePolicy,
        QStackedLayout
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

# 配置本地日志 (限制最大 1MB 循环覆盖，杜绝超大日志产生)
from logging.handlers import RotatingFileHandler
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)
fh = RotatingFileHandler(LOG_FILE, maxBytes=1024 * 1024, backupCount=1, encoding='utf-8')
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


from ctypes import wintypes
from comtypes import COMObject, CoInitialize, CoUninitialize
import pycaw.pycaw as pc


class WindowsAudioEndpointNotificationClient(COMObject):
    """Core Audio IMMNotificationClient 回调实现类"""
    _com_interfaces_ = [pc.IMMNotificationClient]

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def OnDeviceStateChanged(self, pwstrDeviceId, dwNewState):
        if self.callback:
            try: self.callback('state_changed', pwstrDeviceId, dwNewState)
            except Exception: pass

    def OnDeviceAdded(self, pwstrDeviceId):
        if self.callback:
            try: self.callback('added', pwstrDeviceId)
            except Exception: pass

    def OnDeviceRemoved(self, pwstrDeviceId):
        if self.callback:
            try: self.callback('removed', pwstrDeviceId)
            except Exception: pass

    def OnDefaultDeviceChanged(self, flow, role, pwstrDefaultDeviceId):
        if self.callback:
            try: self.callback('default_changed', pwstrDefaultDeviceId)
            except Exception: pass

    def OnPropertyValueChanged(self, pwstrDeviceId, key):
        pass


class WindowsAudioDeviceWatcher:
    """Windows 音频设备即插即用/断开连接异步监听器 (基于 Core Audio IMMNotificationClient)"""
    def __init__(self, on_change_callback):
        self.on_change_callback = on_change_callback
        self.running = False
        self.thread = None
        self._client = None
        self._enumerator = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            CoInitialize()
            try:
                self._enumerator = pc.AudioUtilities.GetDeviceEnumerator()
                self._client = WindowsAudioEndpointNotificationClient(self.on_change_callback)
                self._enumerator.RegisterEndpointNotificationCallback(self._client)
                logging.info("WindowsAudioDeviceWatcher: Core Audio IMMNotificationClient registered.")
                while self.running:
                    time.sleep(0.5)
            finally:
                if self._enumerator and self._client:
                    try:
                        self._enumerator.UnregisterEndpointNotificationCallback(self._client)
                    except Exception:
                        pass
                CoUninitialize()
        except Exception as e:
            logging.warning(f"WindowsAudioDeviceWatcher exception: {e}")

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=0.4)
            except Exception:
                pass
            self.thread = None


def get_active_render_device_signature():
    """获取当前所有活动音频输出设备的轻量签名（用于心跳比对，耗时 < 5ms）"""
    try:
        CoInitialize()
        try:
            enum = pc.AudioUtilities.GetDeviceEnumerator()
            collection = enum.EnumAudioEndpoints(pc.EDataFlow.eRender.value, pc.DEVICE_STATE.ACTIVE.value)
            count = collection.GetCount()
            ids = []
            for i in range(count):
                dev = collection.Item(i)
                ids.append(dev.GetId())
            return tuple(sorted(ids))
        finally:
            CoUninitialize()
    except Exception:
        return ()


def get_device_endpoint_volume(device_name):
    """获取指定物理声卡设备的系统音量标量 (0.0 ~ 1.0)"""
    try:
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
        delta = 1 if event.angleDelta().y() > 0 else -1
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



class Galaxy3DBackgroundEngine(QtCore.QObject):
    """
    60FPS 3D 沉浸式粒子互动前台背景引擎
    完全集成 openmusic 官方原版的 5 频段声学分析与自适应节奏锁相环实时节拍引擎:
      - Sub-Bass (38-74Hz): 极低频大鼓与次低音冲击
      - Kick Core (52-165Hz): 核心底鼓与重低音爆发
      - Kick Body (165-420Hz): 贝斯琴腔共鸣
      - Vocal (420-2600Hz): 人声与主旋律 (配合人声屏蔽防误触发)
      - Snap (1800-9200Hz): 清脆打击乐与踩镲瞬态
      - High (6200-16000Hz): 高频泛音与空气感
      - 双速指数差分瞬态提取 (Dual-Speed Envelope Fast vs Slow)
      - 自适应 BPM 节奏锁相环 (Tempo Gap & Phase Lock)
      - 非对称 Attack/Release 包络跟随器
      - 动态多重音爆冲击波 (Sonic Shockwaves)
    支持 4 种 3D 视觉模式 (星河、星球、滚筒、微粒)，支持 360° 鼠标拖拽与滚轮变焦
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = "dark"
        self.mode = "galaxy"  # galaxy, planet, tunnel, dust, off (默认开启星河)
        self.blur_enabled = False  # 3D 沉浸背景动效模糊/虚化光晕开关 (默认关：高清针芒星尘)
        self.num_particles = 1000

        # 相机与 3D 旋转参数 (调整相机视角与变焦，星系与星球更加宏伟舒展)
        self.cam_dist = 10.5
        self.target_dist = 10.5
        self.rot_x = 0.28
        self.rot_y = 0.0
        self.vx = 0.0
        self.vy = 0.003
        self.is_dragging = False
        self.last_pos = None

        # 视觉平滑包络输出
        self.bass = 0.0
        self.mid = 0.0
        self.treble = 0.0
        self.energy = 0.0
        self.beat_pulse = 0.0
        self.time_t = 0.0
        self.shockwaves = []

        # 预计算粒子几何基础数据
        self._init_particle_geometries()

    def _init_particle_geometries(self):
        N = self.num_particles
        rng = np.random.RandomState(42)

        # 1. 星河涡旋基础坐标 (Galaxy - 更加开阔壮观的星系旋臂)
        u = rng.rand(N).astype(np.float32)
        arm = rng.randint(0, 3, N).astype(np.float32)
        self.g_arm = arm
        self.g_u = u
        self.g_angle = u * (3.8 * np.pi) + arm * (2.0 * np.pi / 3.0)
        self.g_radius = 0.45 + np.sqrt(u) * 7.5
        self.g_z = rng.randn(N).astype(np.float32) * 0.48 * np.exp(-self.g_radius / 4.5)
        self.g_size = 0.9 + u * 1.4 + rng.rand(N).astype(np.float32) * 0.7

        # 2. 星球基础坐标 (Planet - 宏伟星体与舒展土星环)
        is_sphere = np.arange(N) < int(N * 0.38)
        p_theta = rng.rand(N).astype(np.float32) * 2.0 * np.pi
        p_phi = (rng.rand(N).astype(np.float32) - 0.5) * np.pi

        sx = 3.2 * np.cos(p_phi) * np.cos(p_theta)
        sy = 3.2 * np.cos(p_phi) * np.sin(p_theta)
        sz = 3.2 * np.sin(p_phi)

        ring_r = 4.6 + rng.rand(N).astype(np.float32) * 5.2
        rx = ring_r * np.cos(p_theta)
        ry = ring_r * np.sin(p_theta)
        rz = rng.randn(N).astype(np.float32) * 0.10

        self.p_base = np.where(is_sphere[:, None], np.column_stack([sx, sy, sz]), np.column_stack([rx, ry, rz])).astype(np.float32)
        self.p_is_sphere = is_sphere

        # 3. 滚筒隧道基础坐标 (Tunnel - 温和纵深分布)
        self.t_angle = rng.rand(N).astype(np.float32) * 2.0 * np.pi
        self.t_z = (rng.rand(N).astype(np.float32) - 0.5) * 22.0
        self.t_radius = 2.8 + rng.rand(N).astype(np.float32) * 0.9

        # 4. 氛围微粒 (Dust - 三维平滑连续呼吸漂浮)
        self.d_pos = (rng.rand(N, 3).astype(np.float32) - 0.5) * 14.0
        self.d_phase = rng.rand(N, 3).astype(np.float32) * 2.0 * np.pi
        self.d_freq = 0.18 + rng.rand(N, 3).astype(np.float32) * 0.22
        self.d_cat = rng.randint(0, 3, N)

    def set_theme(self, theme):
        self.theme = theme

    def set_mode(self, mode):
        self.mode = mode

    def set_blur(self, enabled):
        self.blur_enabled = bool(enabled)

    def process_audio_frame(self, fft_data=None, time_rms=None, sample_rate=48000, dt=0.016):
        """纯净独立 3D 宇宙背景推进 (解耦声音联动，纯享丝滑宁静天体漫游)"""
        safe_dt = max(0.001, min(0.08, float(dt)))
        self.time_t += safe_dt

        # 惯性旋转阻尼
        if not self.is_dragging:
            self.rot_y += self.vy
            self.rot_x += self.vx
            self.rot_x = max(-0.95, min(0.95, self.rot_x))
            self.vx *= 0.94
            self.vy = self.vy * 0.94 if abs(self.vy) > 0.003 else 0.003

        self.cam_dist += (self.target_dist - self.cam_dist) * 0.08
        self.shockwaves = []
        self.bass = 0.0
        self.mid = 0.0
        self.treble = 0.0
        self.energy = 0.0
        self.beat_pulse = 0.0

    def eventFilter(self, watched, event):
        """全局鼠标拦截器：在窗口空白区域按住鼠标拖拽即可 3D 旋转"""
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.is_dragging = True
                self.last_pos = event.position()
                self.vx = 0.0
                self.vy = 0.0
        elif event.type() == QtCore.QEvent.Type.MouseMove:
            if self.is_dragging and self.last_pos:
                delta = event.position() - self.last_pos
                dx = delta.x()
                dy = delta.y()
                self.rot_y += dx * 0.004
                self.rot_x += dy * 0.004
                self.rot_x = max(-0.95, min(0.95, self.rot_x))
                self.vy = dx * 0.003
                self.vx = dy * 0.003
                self.last_pos = event.position()
        elif event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.is_dragging = False
                self.last_pos = None
        elif event.type() == QtCore.QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            self.target_dist = max(6.0, min(28.0, self.target_dist - delta * 0.008))
        return False

    def paint_background(self, painter, width, height):
        w = float(width)
        h = float(height)
        cx = w / 2.0
        cy = h / 2.0

        if self.mode == "off":
            bg_col = QColor("#f3f4f6") if self.theme == "light" else QColor("#121216")
            painter.fillRect(0, 0, int(w), int(h), bg_col)
            return

        # 1. 宇宙深空与星云渐变底色
        if self.theme == "light":
            grad = QRadialGradient(cx, cy, max(w, h) * 0.75)
            if self.blur_enabled:
                grad.setColorAt(0.0, QColor(224, 231, 255, 240))
                grad.setColorAt(0.40, QColor(241, 245, 249, 220))
                grad.setColorAt(0.80, QColor(226, 232, 240, 200))
                grad.setColorAt(1.0, QColor(218, 226, 236, 255))
            else:
                grad.setColorAt(0.0, QColor("#e0e7ff"))
                grad.setColorAt(0.5, QColor("#f1f5f9"))
                grad.setColorAt(1.0, QColor("#e2e8f0"))
        else:
            grad = QRadialGradient(cx, cy, max(w, h) * 0.75)
            if self.blur_enabled:
                grad.setColorAt(0.0, QColor(32, 20, 48, 255))
                grad.setColorAt(0.35, QColor(20, 22, 32, 255))
                grad.setColorAt(0.70, QColor(13, 14, 20, 255))
                grad.setColorAt(1.0, QColor(7, 8, 11, 255))
            else:
                grad.setColorAt(0.0, QColor(24, 18, 36))
                grad.setColorAt(0.45, QColor(14, 15, 22))
                grad.setColorAt(1.0, QColor(7, 8, 11))

        painter.fillRect(0, 0, int(w), int(h), QBrush(grad))

        # 2. 3D 旋转矩阵计算
        cos_x = math.cos(self.rot_x)
        sin_x = math.sin(self.rot_x)
        cos_y = math.cos(self.rot_y)
        sin_y = math.sin(self.rot_y)

        t = self.time_t
        N = self.num_particles
        fov = min(w, h) * 0.95

        # 根据当前模式计算 3D 粒子坐标 (纯净天体动力学轨迹，无声频畸变与剧烈抖动)
        if self.mode == "galaxy":
            flow = t * 0.16
            ang = self.g_angle + flow
            r_pulse = self.g_radius
            px = np.cos(ang) * r_pulse
            py = np.sin(ang) * r_pulse * 0.48 + np.sin(t * 0.3 + self.g_u * 6.0) * 0.18
            pz = self.g_z
            sizes = self.g_size
            colors_cat = self.g_arm

        elif self.mode == "planet":
            spin = t * 0.20
            pts = self.p_base.copy()
            c_sp = np.cos(spin)
            s_sp = np.sin(spin)
            pts[:, 0] = self.p_base[:, 0] * c_sp - self.p_base[:, 1] * s_sp
            pts[:, 1] = self.p_base[:, 0] * s_sp + self.p_base[:, 1] * c_sp
            px = pts[:, 0]
            py = pts[:, 1] * 0.5
            pz = pts[:, 2]
            sizes = np.where(self.p_is_sphere, 1.6, 1.1).astype(np.float32)
            colors_cat = np.where(self.p_is_sphere, 0, 1)

        elif self.mode == "tunnel":
            # 滚筒隧道：温和平稳向前推进，舒缓优雅
            tz = (self.t_z - t * 0.75) % 22.0 - 11.0
            tang = self.t_angle + t * 0.06
            tr = self.t_radius * (1.0 + np.sin(tz * 0.35 + t * 0.8) * 0.05)
            px = np.cos(tang) * tr
            py = np.sin(tang) * tr * 0.65
            pz = tz
            sizes = np.full(N, 1.1, dtype=np.float32)
            colors_cat = np.where(tz > 2.5, 0, np.where(tz > -3.5, 1, 2))

        else: # dust 氛围微粒：平滑三维连续浮动与轻柔呼吸，温和静谧
            drift_x = np.sin(t * self.d_freq[:, 0] + self.d_phase[:, 0]) * 1.2
            drift_y = np.cos(t * self.d_freq[:, 1] + self.d_phase[:, 1]) * 1.0
            drift_z = np.sin(t * self.d_freq[:, 2] + self.d_phase[:, 2]) * 0.8
            px = self.d_pos[:, 0] + drift_x
            py = self.d_pos[:, 1] + drift_y
            pz = self.d_pos[:, 2] + drift_z
            sizes = (0.85 + np.sin(t * 0.6 + self.d_phase[:, 0]) * 0.2).astype(np.float32)
            colors_cat = self.d_cat

        # 3D 旋转变换
        x1 = px * cos_y + pz * sin_y
        y1 = py
        z1 = -px * sin_y + pz * cos_y

        x2 = x1
        y2 = y1 * cos_x - z1 * sin_x
        z2 = y1 * sin_x + z1 * cos_x

        # 透视投影
        z_view = z2 + self.cam_dist
        valid = z_view > 0.6

        x_2d = cx + (x2[valid] * fov) / z_view[valid]
        y_2d = cy - (y2[valid] * fov) / z_view[valid]
        # 修正投影半径：针芒星尘高清微粒 (半径 0.75px ~ 2.2px，即直径 1.5px ~ 4.4px)
        s_2d = np.clip((sizes[valid] * fov) / (z_view[valid] * 38.0), 0.75, 2.2)
        depth_alpha = np.clip(1.0 - z_view[valid] / 24.0, 0.20, 1.0)
        cats = colors_cat[valid]

        # 3. 批量绘制发光粒子 (支持模糊虚化光晕 / 清晰微粒双模式)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(len(x_2d)):
            px_i = float(x_2d[i])
            py_i = float(y_2d[i])
            sz_i = float(s_2d[i])
            alp_i = float(depth_alpha[i])
            c_type = int(cats[i])

            if self.theme == "light":
                if c_type == 0:
                    base_rgb = (217, 119, 6)
                elif c_type == 1:
                    base_rgb = (14, 165, 233)
                else:
                    base_rgb = (168, 85, 247)
                final_alpha = int(alp_i * 220)
            else:
                if c_type == 0:
                    base_rgb = (255, 195, 75)
                elif c_type == 1:
                    base_rgb = (56, 210, 255)
                else:
                    base_rgb = (244, 114, 182)
                final_alpha = int(min(255, alp_i * 255 * 0.90))

            if self.blur_enabled:
                # 开启模糊虚化时：叠加柔光外圈 (Bloom Halo)
                halo_sz = sz_i * 2.2
                halo_alpha = max(4, int(final_alpha * 0.30))
                painter.setBrush(QBrush(QColor(base_rgb[0], base_rgb[1], base_rgb[2], halo_alpha)))
                painter.drawEllipse(QPointF(px_i, py_i), halo_sz, halo_sz)

            # 核心高清针芒星尘 (Crisp Star Core)
            painter.setBrush(QBrush(QColor(base_rgb[0], base_rgb[1], base_rgb[2], final_alpha)))
            painter.drawEllipse(QPointF(px_i, py_i), sz_i, sz_i)


class MainCentralWidget(QWidget):
    """主中央容器：底层 3D 沉浸星河渲染 + 上层 UI 子控件自动合成"""
    def __init__(self, bg_engine, parent=None):
        super().__init__(parent)
        self.setObjectName("CentralWidget")
        self.bg_engine = bg_engine

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.bg_engine.paint_background(painter, self.width(), self.height())


class SpectrumVisualizerWidget(QWidget):
    """
    60FPS 赛博科技声学动态律动频谱仪 (Pro Cyber-Acoustic Spectrum Visualizer)
    - 72 频段高精度声学对数分布 (30Hz ~ 18000Hz)，柱体纤细精致
    - 赛博霓虹连续多阶全光谱流动渐变 (Cyber Cyan -> Neon Mint -> Solar Gold -> Coral -> Hyper Violet)
    - 悬浮重力落差光标 (Gravity Physics Peak Hold with Hang-Time)
    - 动态荧光余晖残影衰减 (Phosphor Ghost Trail Decay)
    - 科技刻度网格与参考 dB 分贝标线 (-6dB / -18dB / -36dB)
    - 底部声学频标微型刻度与区域标签 (SUB / BASS / MID / HIGH / AIR)
    - 底部全息镜面微倒影光晕 (Holographic Bottom Mirror Glow)
    - 自适应全局声学动态范围追踪与人耳听觉频响加权补偿 (Adaptive Headroom AGC)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.num_bars = 72
        self.smooth_bars = np.zeros(self.num_bars, dtype=np.float32)
        self.ghost_bars = np.zeros(self.num_bars, dtype=np.float32)
        self.peak_heights = np.zeros(self.num_bars, dtype=np.float32)
        self.peak_velocities = np.zeros(self.num_bars, dtype=np.float32)
        self.peak_holds = np.zeros(self.num_bars, dtype=np.int32)
        self.global_peak = 0.5
        self.raw_magnitudes = np.zeros(self.num_bars, dtype=np.float32)
        self.idle_phase = 0.0
        self.theme = "dark"
        self.translucent = True

        # 生成 72 频段赛博高科技连续光谱色板
        self.bar_colors = self._generate_cyber_palette(self.num_bars)

    def _generate_cyber_palette(self, num_bars):
        """生成极具前沿科技感的光谱色谱 (Electric Cyan -> Neon Mint -> Solar Gold -> Cyber Coral -> Hyper Violet)"""
        stops = [
            (0.00, QColor("#00f0ff")),  # 极光电青 (Sub-Bass)
            (0.18, QColor("#06b6d4")),  # 赛博海蓝 (Deep Bass)
            (0.35, QColor("#00f59b")),  # 霓虹薄荷绿 (Punch & Low Mid)
            (0.52, QColor("#10b981")),  # 纯净翡翠 (Vocal Core)
            (0.68, QColor("#fbbf24")),  # 太阳金琥珀 (Mid Presence)
            (0.82, QColor("#f43f5e")),  # 赛博珊瑚红 (Crisp Treble)
            (1.00, QColor("#c084fc")),  # 极光幻紫 (Air & Harmonics)
        ]
        palette = []
        for i in range(num_bars):
            t = i / float(num_bars - 1)
            for s_idx in range(len(stops) - 1):
                t0, c0 = stops[s_idx]
                t1, c1 = stops[s_idx + 1]
                if t0 <= t <= t1 or s_idx == len(stops) - 2:
                    factor = (t - t0) / max(0.0001, (t1 - t0))
                    factor = max(0.0, min(1.0, factor))
                    r = int(c0.red() + (c1.red() - c0.red()) * factor)
                    g = int(c0.green() + (c1.green() - c0.green()) * factor)
                    b = int(c0.blue() + (c1.blue() - c0.blue()) * factor)
                    palette.append(QColor(r, g, b))
                    break
        return palette

    def set_theme(self, theme):
        self.theme = theme
        self.update()

    def set_translucent(self, translucent):
        self.translucent = translucent
        self.update()

    def update_magnitudes(self, fft_magnitudes):
        if fft_magnitudes is not None and len(fft_magnitudes) > 0:
            if len(fft_magnitudes) == self.num_bars:
                self.raw_magnitudes = fft_magnitudes
            else:
                # 动态自适应重采样到目标频段数
                old_x = np.linspace(0, 1, len(fft_magnitudes))
                new_x = np.linspace(0, 1, self.num_bars)
                self.raw_magnitudes = np.interp(new_x, old_x, fft_magnitudes).astype(np.float32)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        is_dark = (self.theme == "dark")

        # 1. 现代化深空暗黑磨砂外框底板
        bg_col = QColor(10, 11, 16, 215) if is_dark else QColor(248, 250, 252, 230)
        border_col = QColor(30, 41, 59, 200) if is_dark else QColor(226, 232, 240, 220)
        painter.setBrush(QBrush(bg_col))
        painter.setPen(QPen(border_col, 1))
        painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

        # 布局坐标计算
        padding_x = 18.0
        padding_top = 8.0
        baseline_y = h - 15.0  # 基线位置，下方预留 15px 给频标与倒影
        max_bar_h = baseline_y - padding_top - 4.0

        # 2. 科技网格分贝刻度参考线 (Reference dB Grid Lines)
        db_levels = [
            (0.75, "-6 dB"),
            (0.50, "-18 dB"),
            (0.25, "-36 dB")
        ]
        grid_pen = QPen(QColor(255, 255, 255, 12 if is_dark else 18), 1, Qt.PenStyle.DashLine)
        grid_pen.setDashPattern([3, 5])
        painter.setPen(grid_pen)
        font_db = QFont("Microsoft YaHei")
        font_db.setPixelSize(9)
        painter.setFont(font_db)

        for ratio, label in db_levels:
            line_y = baseline_y - max_bar_h * ratio
            painter.drawLine(QPointF(padding_x, line_y), QPointF(w - padding_x, line_y))
            # 右侧标注微型文字
            painter.setPen(QColor(255, 255, 255, 45 if is_dark else 70))
            painter.drawText(QRectF(w - padding_x - 42, line_y - 7, 40, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            painter.setPen(grid_pen)

        # 3. 声学频率基准线 (Baseline)
        base_pen = QPen(QColor(56, 189, 248, 55 if is_dark else 40), 1)
        painter.setPen(base_pen)
        painter.drawLine(QPointF(padding_x, baseline_y), QPointF(w - padding_x, baseline_y))

        # 4. 底部声学频段刻度标记 (SUB / BASS / MID / HIGH / AIR)
        freq_landmarks = [
            (0.05, "SUB"),
            (0.20, "BASS"),
            (0.42, "MID"),
            (0.70, "HIGH"),
            (0.92, "AIR"),
        ]
        font_tag = QFont("Microsoft YaHei", 8, QFont.Weight.Bold)
        font_tag.setPixelSize(9)
        painter.setFont(font_tag)
        usable_w = w - 2 * padding_x
        for norm_x, tag_txt in freq_landmarks:
            tx = padding_x + usable_w * norm_x
            painter.setPen(QColor(148, 163, 184, 110 if is_dark else 140))
            painter.drawText(QRectF(tx - 25, baseline_y + 1, 50, 13), Qt.AlignmentFlag.AlignCenter, tag_txt)

        # 5. 柱状与间距几何计算
        total_gaps = (self.num_bars - 1)
        gap = max(1.8, min(3.2, usable_w / float(self.num_bars * 3.5)))
        bar_w = (usable_w - total_gaps * gap) / float(self.num_bars)
        bar_w = max(2.5, bar_w)

        # 居中偏移修正
        actual_total_w = self.num_bars * bar_w + total_gaps * gap
        start_x = padding_x + max(0.0, (usable_w - actual_total_w) / 2.0)

        # 检查是否静音或待机，并执行自适应全局峰值追踪 (AGC)
        current_max = float(np.max(self.raw_magnitudes)) if len(self.raw_magnitudes) > 0 else 0.0
        if current_max > 0.0001:
            self.global_peak = max(self.global_peak * 0.985, current_max, 0.05)
            is_idle = False
        else:
            is_idle = True
            self.idle_phase += 0.035

        # 6. 渲染 72 根精细高科技律动柱
        for i in range(self.num_bars):
            val = float(self.raw_magnitudes[i]) if not is_idle else 0.0
            if is_idle:
                # 待机待命呼吸波 (Standby Ambient Cyber Wave)
                norm_val = 0.04 + 0.03 * math.sin(self.idle_phase + i * 0.14)
            else:
                # 高频人耳听觉感知增益补偿 (Fletcher-Munson Perceptual Curve)
                comp = 0.75 + 1.25 * math.pow(i / float(self.num_bars - 1), 0.48)
                val_comp = val * comp
                norm_val = min(1.0, math.pow(val_comp / max(0.01, self.global_peak), 0.7))

            # 瞬态响应：极速 Attack，丝滑指数衰减 Release
            if norm_val > self.smooth_bars[i]:
                self.smooth_bars[i] = self.smooth_bars[i] * 0.45 + norm_val * 0.55
            else:
                self.smooth_bars[i] = self.smooth_bars[i] * 0.82 + norm_val * 0.18

            bar_h = min(max_bar_h, self.smooth_bars[i] * max_bar_h)

            # 荧光余晖残影衰减物理模拟 (Phosphor Ghost Trail)
            if bar_h > self.ghost_bars[i]:
                self.ghost_bars[i] = bar_h
            else:
                self.ghost_bars[i] = max(0.0, self.ghost_bars[i] * 0.92)

            # 悬浮重力落差光标物理模拟 (Gravity Peak Hold)
            if bar_h > self.peak_heights[i]:
                self.peak_heights[i] = bar_h
                self.peak_velocities[i] = 0.0
                self.peak_holds[i] = 12  # 悬停约 180ms
            else:
                if self.peak_holds[i] > 0:
                    self.peak_holds[i] -= 1
                else:
                    self.peak_velocities[i] += 0.16  # 重力加速度
                    self.peak_heights[i] = max(0.0, self.peak_heights[i] - self.peak_velocities[i])

            x = start_x + i * (bar_w + gap)
            y = baseline_y - bar_h
            base_col = self.bar_colors[i]

            # A. 荧光余晖残影 (Ghost Trail)
            if self.ghost_bars[i] > bar_h + 2.0:
                ghost_y = baseline_y - self.ghost_bars[i]
                ghost_col = QColor(base_col.red(), base_col.green(), base_col.blue(), 30 if is_dark else 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(ghost_col))
                painter.drawRoundedRect(QRectF(x, ghost_y, bar_w, self.ghost_bars[i] - bar_h), 1.2, 1.2)

            # B. 底部全息镜面微倒影 (Hologram Mirror Reflection)
            if bar_h > 2.0:
                refl_h = min(9.0, bar_h * 0.24)
                refl_grad = QLinearGradient(x, baseline_y, x, baseline_y + refl_h)
                refl_grad.setColorAt(0.0, QColor(base_col.red(), base_col.green(), base_col.blue(), 50 if is_dark else 28))
                refl_grad.setColorAt(1.0, QColor(base_col.red(), base_col.green(), base_col.blue(), 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(refl_grad))
                painter.drawRoundedRect(QRectF(x, baseline_y + 1.0, bar_w, refl_h), 1.0, 1.0)

            # C. 律动光柱实体 (Sleek Cyber Neon Pillar)
            if bar_h > 1.0:
                bar_grad = QLinearGradient(x, baseline_y, x, y)
                bar_grad.setColorAt(0.0, QColor(base_col.red(), base_col.green(), base_col.blue(), 75 if is_dark else 110))
                bar_grad.setColorAt(0.65, QColor(base_col.red(), base_col.green(), base_col.blue(), 215 if is_dark else 230))
                bar_grad.setColorAt(1.0, QColor(min(255, base_col.red() + 60), min(255, base_col.green() + 60), min(255, base_col.blue() + 60), 255))
                
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(bar_grad))
                bar_r = min(1.8, bar_w / 2.0)
                painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), bar_r, bar_r)

                # 柱顶高能发光焦点 (Luminous Hot Tip)
                tip_h = min(2.5, bar_h)
                tip_col = QColor(255, 255, 255, 210)
                painter.setBrush(QBrush(tip_col))
                painter.drawRoundedRect(QRectF(x, y, bar_w, tip_h), bar_r, bar_r)

            # D. 悬浮重力落差光标 (Floating Luminous Peak Bead)
            if self.peak_heights[i] > 2.0:
                peak_y = baseline_y - self.peak_heights[i] - 2.5
                # 光晕
                halo_col = QColor(base_col.red(), base_col.green(), base_col.blue(), 65 if is_dark else 35)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(halo_col))
                painter.drawRoundedRect(QRectF(x - 0.5, peak_y - 0.5, bar_w + 1.0, 3.0), 1.2, 1.2)

                # 核心亮珠 (Pure White-Hot Core Bead)
                core_col = QColor(255, 255, 255, 240 if is_dark else 220)
                painter.setBrush(QBrush(core_col))
                painter.drawRoundedRect(QRectF(x, peak_y, bar_w, 2.0), 1.0, 1.0)


class EffectCardWidget(QFrame):
    """9款官方音效独立卡片（支持悬停发光、金色选中呼吸态及内嵌微调滑块）"""
    cardClicked = Signal(str)
    intensityChanged = Signal(str, int)

    def __init__(self, eff_def, parent=None, initial_intensity=100, is_active=False, theme="dark", translucent=True):
        super().__init__(parent)
        self.eff_def = eff_def
        self.key = eff_def["key"]
        self.is_active = is_active
        self.intensity = initial_intensity
        self.theme = theme
        self.translucent = translucent

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

    def set_translucent(self, translucent):
        self.translucent = translucent
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
                bg = "rgba(254, 243, 199, 0.92)" if self.translucent else "#fffbeb"
                self.setStyleSheet(f"""
                    QFrame#EffectCard {{
                        background-color: {bg};
                        border: 1.5px solid #f59e0b;
                        border-radius: 8px;
                    }}
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
                bg = "rgba(255, 255, 255, 0.85)" if self.translucent else "#ffffff"
                hover_bg = "rgba(249, 250, 251, 0.96)" if self.translucent else "#f9fafb"
                border = "1px solid rgba(0, 0, 0, 0.08)" if self.translucent else "1px solid #e5e7eb"
                self.setStyleSheet(f"""
                    QFrame#EffectCard {{
                        background-color: {bg};
                        border: {border};
                        border-radius: 8px;
                    }}
                    QFrame#EffectCard:hover {{
                        background-color: {hover_bg};
                        border: 1px solid rgba(245, 158, 11, 0.5);
                    }}
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
                bg = "rgba(245, 158, 11, 0.22)" if self.translucent else "#2e2515"
                self.setStyleSheet(f"""
                    QFrame#EffectCard {{
                        background-color: {bg};
                        border: 1.5px solid #f59e0b;
                        border-radius: 8px;
                    }}
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
                bg = "rgba(30, 30, 40, 0.72)" if self.translucent else "#1e1e26"
                hover_bg = "rgba(45, 45, 60, 0.88)" if self.translucent else "#282834"
                border = "1px solid rgba(255, 255, 255, 0.08)" if self.translucent else "1px solid #2f2f3c"
                self.setStyleSheet(f"""
                    QFrame#EffectCard {{
                        background-color: {bg};
                        border: {border};
                        border-radius: 8px;
                    }}
                    QFrame#EffectCard:hover {{
                        background-color: {hover_bg};
                        border: 1px solid rgba(255, 255, 255, 0.25);
                    }}
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
    sig_audio_devices_changed = Signal()

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
        self.bg_blur = self.user_cfg.get("bg_blur", True)
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
        self.current_live_phys_name = None
        self.has_cable_installed = False
        self.output_dev_list = []
        self.fft_magnitudes = np.zeros(72, dtype=np.float32)
        self.sys_vol_watcher = SystemVolumeWatcher()

        self._last_device_signature = get_active_render_device_signature()

        # 音频设备变更防抖定时器 (350ms 聚合多次蓝牙/系统事件)
        self.device_debounce_timer = QTimer(self)
        self.device_debounce_timer.setSingleShot(True)
        self.device_debounce_timer.timeout.connect(lambda: self.populate_audio_devices(trigger_source='auto'))

        # 轻量心跳轮询定时器 (1.5秒检测一次活动设备签名，兜底极端驱动情况)
        self.device_poll_timer = QTimer(self)
        self.device_poll_timer.timeout.connect(self._check_device_signature_poll)
        self.device_poll_timer.start(1500)

        # Core Audio IMMNotificationClient 后台监听器
        self.device_watcher = WindowsAudioDeviceWatcher(self._on_device_watcher_event)
        self.device_watcher.start()

        self.init_signals()
        self.init_ui()
        self.apply_theme(self.current_theme)
        self.start_dsp_backend()
        self.populate_audio_devices(trigger_source='manual')

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
        return {"volume": 100, "effect": "none", "theme": "dark", "bg_mode": "galaxy", "bg_blur": False}

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
        self.sig_audio_devices_changed.connect(self._on_audio_devices_changed_signal)

    def _on_audio_devices_changed_signal(self):
        """收到设备变更信号时启动 350ms 防抖更新"""
        if hasattr(self, 'device_debounce_timer'):
            self.device_debounce_timer.start(350)

    def _on_device_watcher_event(self, event_type, *args):
        """由 Windows Core Audio 回调线程触发"""
        self.sig_audio_devices_changed.emit()

    def _check_device_signature_poll(self):
        """轻量心跳巡检活动设备列表"""
        sig = get_active_render_device_signature()
        if sig and sig != self._last_device_signature:
            self._last_device_signature = sig
            self.sig_audio_devices_changed.emit()

    def nativeEvent(self, eventType, message):
        """拦截 Windows 原生 WM_DEVICECHANGE 硬件即插即用广播消息"""
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0219:  # WM_DEVICECHANGE
                self.sig_audio_devices_changed.emit()
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def showEvent(self, event):
        super().showEvent(event)
        apply_windows_dark_title_bar(self.winId(), enable_dark=(self.current_theme == "dark"))

    def toggle_theme(self):
        new_theme = "dark" if self.current_theme == "light" else "light"
        self.current_theme = new_theme
        self.user_cfg["theme"] = new_theme
        self.save_user_config()
        self.apply_theme(new_theme)

    def toggle_bg_blur(self):
        """切换 3D 沉浸动效背景的模糊虚化 / 清晰锐利动效"""
        self.bg_blur = not self.bg_blur
        self.user_cfg["bg_blur"] = self.bg_blur
        self.save_user_config()
        self.bg_3d_engine.set_blur(self.bg_blur)
        if hasattr(self, 'btn_bg_blur'):
            self.btn_bg_blur.setText("动效模糊: 开" if self.bg_blur else "动效模糊: 关")
        if self.centralWidget():
            self.centralWidget().update()

    def apply_theme(self, theme):
        self.current_theme = theme
        is_light = (theme == "light")
        apply_windows_dark_title_bar(self.winId(), enable_dark=not is_light)

        # 更新按钮文本与 3D 引擎配置 (纯净文字无多余图标)
        if hasattr(self, 'btn_theme'):
            self.btn_theme.setText("切换深色模式" if is_light else "切换浅色模式")
        if hasattr(self, 'btn_bg_blur'):
            self.btn_bg_blur.setText("动效模糊: 开" if self.bg_blur else "动效模糊: 关")
        if hasattr(self, 'bg_3d_engine'):
            self.bg_3d_engine.set_theme(theme)
            self.bg_3d_engine.set_blur(self.bg_blur)

        panel_card_bg_light = "rgba(255, 255, 255, 0.84)"
        panel_card_border_light = "1px solid rgba(0, 0, 0, 0.08)"
        box_bg_light = "rgba(249, 250, 251, 0.85)"
        btn_bg_light = "rgba(255, 255, 255, 0.9)"

        panel_card_bg_dark = "rgba(22, 22, 28, 0.78)"
        panel_card_border_dark = "1px solid rgba(255, 255, 255, 0.09)"
        box_bg_dark = "rgba(30, 30, 40, 0.72)"
        btn_bg_dark = "rgba(36, 36, 48, 0.8)"

        if is_light:
            self.setStyleSheet(f"""
                QMainWindow {{
                    background-color: transparent;
                }}
                QWidget#CentralWidget {{
                    background-color: transparent;
                }}
                QWidget#ContentWidget {{
                    background-color: transparent;
                }}
                QScrollArea {{
                    background-color: transparent;
                    border: none;
                }}
                QScrollBar:vertical {{
                    width: 0px;
                    height: 0px;
                }}
                QFrame#PanelCard {{
                    background-color: {panel_card_bg_light};
                    border: {panel_card_border_light};
                    border-radius: 12px;
                }}
                QPushButton {{
                    background-color: {btn_bg_light};
                    color: #1f2937;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: #f3f4f6;
                    border: 1px solid #9ca3af;
                }}
                QPushButton:pressed {{
                    background-color: #e5e7eb;
                }}
                QComboBox {{
                    background-color: {btn_bg_light};
                    color: #111827;
                    border: 1px solid #d1d5db;
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }}
                QComboBox:hover {{
                    border: 1px solid #f59e0b;
                }}
                QComboBox::drop-down {{
                    border: none;
                    width: 24px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: #ffffff;
                    color: #111827;
                    selection-background-color: #f59e0b;
                    selection-color: #000000;
                    border: 1px solid #d1d5db;
                    padding: 4px;
                }}
                QLabel {{
                    color: #111827;
                    font-family: 'Microsoft YaHei';
                }}
            """)
            if hasattr(self, 'switch_box'):
                self.switch_box.setStyleSheet(f"background-color: {box_bg_light}; border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 8px;")
            if hasattr(self, 'dev_box'):
                self.dev_box.setStyleSheet(f"background-color: {box_bg_light}; border: 1px solid rgba(0, 0, 0, 0.08); border-radius: 8px;")
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
            self.setStyleSheet(f"""
                QMainWindow {{
                    background-color: transparent;
                }}
                QWidget#CentralWidget {{
                    background-color: transparent;
                }}
                QWidget#ContentWidget {{
                    background-color: transparent;
                }}
                QScrollArea {{
                    background-color: transparent;
                    border: none;
                }}
                QScrollBar:vertical {{
                    width: 0px;
                    height: 0px;
                }}
                QFrame#PanelCard {{
                    background-color: {panel_card_bg_dark};
                    border: {panel_card_border_dark};
                    border-radius: 12px;
                }}
                QPushButton {{
                    background-color: {btn_bg_dark};
                    color: #f3f4f6;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }}
                QPushButton:hover {{
                    background-color: rgba(50, 50, 68, 0.95);
                    border: 1px solid rgba(255, 255, 255, 0.25);
                }}
                QPushButton:pressed {{
                    background-color: #1e1e26;
                }}
                QComboBox {{
                    background-color: {btn_bg_dark};
                    color: #ffffff;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 6px;
                    padding: 5px 10px;
                    font-family: 'Microsoft YaHei';
                    font-size: 12px;
                }}
                QComboBox:hover {{
                    border: 1px solid #f59e0b;
                }}
                QComboBox::drop-down {{
                    border: none;
                    width: 24px;
                }}
                QComboBox QAbstractItemView {{
                    background-color: #242430;
                    color: #ffffff;
                    selection-background-color: #f59e0b;
                    selection-color: #000000;
                    border: 1px solid #323242;
                    padding: 4px;
                }}
                QLabel {{
                    color: #f3f4f6;
                    font-family: 'Microsoft YaHei';
                }}
            """)
            if hasattr(self, 'switch_box'):
                self.switch_box.setStyleSheet(f"background-color: {box_bg_dark}; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;")
            if hasattr(self, 'dev_box'):
                self.dev_box.setStyleSheet(f"background-color: {box_bg_dark}; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;")
            if hasattr(self, 'btn_mute'):
                if not self.is_muted:
                    self.btn_mute.setStyleSheet("background-color: rgba(36, 36, 48, 0.85); border: 1px solid rgba(255, 255, 255, 0.12); color: #ffffff; padding: 5px 14px; font-weight: bold;")
            if hasattr(self, 'vol_badge'):
                vol_color = "#ef4444" if self.saved_vol > 100 else "#f59e0b"
                self.vol_badge.setStyleSheet(f"background-color: rgba(36, 36, 48, 0.85); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 6px; padding: 4px 6px; color: {vol_color}; font-family: Consolas; font-weight: bold;")
            if hasattr(self, 'vis_title'):
                self.vis_title.setStyleSheet("color: #f3f4f6; font-weight: bold; font-size: 12px;")
            if hasattr(self, 'dsp_tag'):
                self.dsp_tag.setStyleSheet("color: #34d399; font-family: Consolas; font-weight: bold; font-size: 11px;")

        # 子控件同步主题与透明度
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
        bg_mode = self.user_cfg.get("bg_mode", "galaxy")
        self.bg_3d_engine = Galaxy3DBackgroundEngine()
        self.bg_3d_engine.set_theme(self.current_theme)
        self.bg_3d_engine.set_mode(bg_mode)
        self.bg_3d_engine.set_blur(self.bg_blur)

        central_widget = MainCentralWidget(self.bg_3d_engine, self)
        self.setCentralWidget(central_widget)

        main_vbox = QVBoxLayout(central_widget)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(0)

        # 滚动区域 (滚动条隐藏，背景完全透明)
        scroll_area = QScrollArea(central_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("background: transparent; border: none;")
        scroll_area.viewport().setStyleSheet("background: transparent;")
        scroll_area.viewport().installEventFilter(self.bg_3d_engine)
        main_vbox.addWidget(scroll_area)

        content_widget = QWidget()
        content_widget.setObjectName("ContentWidget")
        content_widget.setStyleSheet("background: transparent;")
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
        dev_title = QLabel("监听输出设备 (耳机 / 音箱):", self.dev_box)
        dev_title.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 12px;")
        dev_top.addWidget(dev_title)
        dev_top.addStretch()

        self.combo_bg_mode = QComboBox(self.dev_box)
        self.combo_bg_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_bg_mode.setStyleSheet("font-size: 11px; padding: 2px 6px; min-width: 110px;")
        bg_modes = [
            ("沉浸背景: 关闭", "off"),
            ("沉浸背景: 星河", "galaxy"),
            ("沉浸背景: 星球", "planet"),
            ("沉浸背景: 滚筒", "tunnel"),
            ("沉浸背景: 微粒", "dust"),
        ]
        cur_idx = 0
        for i, (label, mode_val) in enumerate(bg_modes):
            self.combo_bg_mode.addItem(label, mode_val)
            if mode_val == bg_mode:
                cur_idx = i
        self.combo_bg_mode.setCurrentIndex(cur_idx)
        self.combo_bg_mode.currentIndexChanged.connect(self.on_bg_mode_changed)
        dev_top.addWidget(self.combo_bg_mode)

        self.btn_bg_blur = QPushButton("动效模糊: 开" if self.bg_blur else "动效模糊: 关", self.dev_box)
        self.btn_bg_blur.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bg_blur.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_bg_blur.clicked.connect(self.toggle_bg_blur)
        dev_top.addWidget(self.btn_bg_blur)

        self.btn_theme = QPushButton("切换浅色模式", self.dev_box)
        self.btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_theme.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.btn_theme.clicked.connect(self.toggle_theme)
        dev_top.addWidget(self.btn_theme)

        btn_refresh = QPushButton("刷新", self.dev_box)
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_refresh.clicked.connect(lambda: self.populate_audio_devices(trigger_source='manual'))
        dev_top.addWidget(btn_refresh)
        dev_box_layout.addLayout(dev_top)

        self.output_dev_combo = QComboBox(self.dev_box)
        self.output_dev_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.output_dev_combo.currentIndexChanged.connect(self.on_output_dev_combo_changed)
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
        self.vis_title = QLabel("实时动态声学频谱律动 (72-Band Pro DSP)", vis_card)
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
            if hasattr(self, 'bg_3d_engine'):
                raw_fft = getattr(self, 'fft_raw_spectrum', None)
                raw_rms = getattr(self, 'audio_rms_val', 0.0)
                sr = getattr(self, 'live_in_sr', 48000)
                self.bg_3d_engine.process_audio_frame(raw_fft, raw_rms, sample_rate=sr, dt=0.016)
            if self.centralWidget():
                self.centralWidget().update()

    def on_bg_mode_changed(self, index):
        mode = self.combo_bg_mode.itemData(index)
        if not mode:
            mode = "galaxy"
        self.bg_3d_engine.set_mode(mode)
        self.user_cfg["bg_mode"] = mode
        self.save_user_config()
        if self.centralWidget():
            self.centralWidget().update()

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

    def populate_audio_devices(self, trigger_source='auto'):
        try:
            prev_sel_name = None
            cur_idx = self.output_dev_combo.currentIndex()
            if cur_idx >= 0 and cur_idx < len(self.output_dev_list):
                prev_sel_name = self.output_dev_list[cur_idx][4]
            elif self.user_cfg.get("last_output_device"):
                prev_sel_name = self.user_cfg.get("last_output_device")

            old_device_names = set(item[4] for item in self.output_dev_list)

            # 在开启增强时使用独立探测实例，避免 terminate 影响正在进行的实时音频流
            probe_pa = None
            if not self.is_live_capturing:
                try: self.pa.terminate()
                except Exception: pass
                self.pa = pyaudio.PyAudio()
                active_pa = self.pa
            else:
                probe_pa = pyaudio.PyAudio()
                active_pa = probe_pa

            new_dev_list = []
            has_cable = False

            for i in range(active_pa.get_device_count()):
                try:
                    dev = active_pa.get_device_info_by_index(i)
                    host_info = active_pa.get_host_api_info_by_index(dev["hostApi"])
                    name = str(dev["name"])
                    sr = int(dev["defaultSampleRate"])
                    name_lower = name.lower()

                    if 'cable' in name_lower or 'vb-audio' in name_lower or 'virtual cable' in name_lower:
                        has_cable = True

                    if "wasapi" in host_info["name"].lower():
                        if dev["maxOutputChannels"] > 0 and not dev.get("isLoopbackDevice", False):
                            if 'cable' not in name_lower and 'vb-audio' not in name_lower:
                                is_headphone = any(k in name_lower for k in [
                                    '耳机', 'headphone', 'headset', 'earphone', 'buds', 'airpods',
                                    'wh-1000', 'freebuds', 'bose', 'sony', 'xiaomi', 'beats', 'oppo', 'vivo'
                                ])
                                is_display = any(k in name_lower for k in [
                                    'hd audio', 'display', 'benq', 'dell', 'samsung', 'lg', 'hdmi', 'dp', 'monitor'
                                ])
                                if is_headphone:
                                    icon = "🎧 "
                                elif is_display:
                                    icon = "🖥️ "
                                else:
                                    icon = "🔊 "
                                new_dev_list.append((i, f"{icon}{name}", sr, dev["maxOutputChannels"], name, is_headphone))
                except Exception as dev_err:
                    logging.warning(f"Error parsing device {i}: {dev_err}")

            if probe_pa:
                try: probe_pa.terminate()
                except Exception: pass

            self.has_cable_installed = has_cable
            if self.has_cable_installed:
                self.vbcable_bar.hide()
            else:
                self.vbcable_bar.show()

            new_device_names = set(item[4] for item in new_dev_list)
            added_names = new_device_names - old_device_names
            removed_names = old_device_names - new_device_names

            list_changed = (bool(added_names) or bool(removed_names) or len(new_dev_list) != len(self.output_dev_list))

            if not list_changed and trigger_source == 'auto':
                return

            self.output_dev_list = new_dev_list

            # 更新 UI 选项
            self.output_dev_combo.blockSignals(True)
            self.output_dev_combo.clear()
            self.output_dev_combo.addItems([item[1] for item in self.output_dev_list])

            # 智能设备匹配与选择逻辑
            # 1. 是否有新耳机设备刚连接？
            new_headphone_idx = None
            for idx, item in enumerate(self.output_dev_list):
                if item[4] in added_names and item[5]:
                    new_headphone_idx = idx
                    break

            matched_idx = -1
            if new_headphone_idx is not None:
                matched_idx = new_headphone_idx
                self.log(f"🎧 检测到耳机已连接: 【{self.output_dev_list[matched_idx][4]}】，已自动切换为当前输出设备！")
            elif prev_sel_name and any(item[4] == prev_sel_name for item in self.output_dev_list):
                # 原选择设备仍然在线且有效
                for idx, item in enumerate(self.output_dev_list):
                    if item[4] == prev_sel_name:
                        matched_idx = idx
                        break
            else:
                # 原设备已拔出/断开，优先回退到耳机类，其次扬声器，最后第一个设备
                for idx, item in enumerate(self.output_dev_list):
                    if item[5]:
                        matched_idx = idx
                        break
                if matched_idx == -1:
                    for idx, item in enumerate(self.output_dev_list):
                        if '扬声器' in item[4] or 'speaker' in item[4].lower() or 'realtek' in item[4].lower():
                            matched_idx = idx
                            break
                if matched_idx == -1 and self.output_dev_list:
                    matched_idx = 0

                if prev_sel_name and (prev_sel_name in removed_names or not any(item[4] == prev_sel_name for item in self.output_dev_list)):
                    if matched_idx >= 0 and matched_idx < len(self.output_dev_list):
                        fallback_name = self.output_dev_list[matched_idx][4]
                        self.log(f"⚠️ 当前设备 【{prev_sel_name}】 已断开，已自动平滑切换至可用设备: 【{fallback_name}】")
                    else:
                        self.log(f"⚠️ 当前设备 【{prev_sel_name}】 已断开，当前无其他可用输出设备。")

            if matched_idx >= 0 and matched_idx < len(self.output_dev_list):
                self.output_dev_combo.setCurrentIndex(matched_idx)
                sel_dev_name = self.output_dev_list[matched_idx][4]
                self.user_cfg["last_output_device"] = sel_dev_name
                self.save_user_config()

            self.output_dev_combo.blockSignals(False)

            if trigger_source == 'manual':
                self.log(f"🔄 声卡设备列表已刷新，发现 {len(self.output_dev_list)} 个可用输出设备")

            # 若增强引擎正在运行，自动比对并热切换输出流
            if self.is_live_capturing:
                self._check_live_stream_hot_swap()

        except Exception as e:
            logging.error(f"Device enumeration exception: {e}")

    def on_output_dev_combo_changed(self, index):
        if index < 0 or index >= len(self.output_dev_list):
            return
        dev_info = self.output_dev_list[index]
        dev_name = dev_info[4]
        self.user_cfg["last_output_device"] = dev_name
        self.save_user_config()
        if self.is_live_capturing:
            self._check_live_stream_hot_swap()

    def _check_live_stream_hot_swap(self):
        if not self.is_live_capturing:
            return
        cur_idx = self.output_dev_combo.currentIndex()
        if cur_idx < 0 or cur_idx >= len(self.output_dev_list):
            return
        dev_info = self.output_dev_list[cur_idx]
        phys_out_idx = dev_info[0]
        phys_out_name = dev_info[4]
        phys_out_sr = dev_info[2]
        phys_out_channels = min(2, dev_info[3])
        current_active = getattr(self, 'current_live_phys_name', None)
        if current_active != phys_out_name or self.live_out_stream is None:
            self._hot_swap_output_device(phys_out_idx, phys_out_name, phys_out_sr, phys_out_channels)

    def _hot_swap_output_device(self, new_phys_idx, new_phys_name, new_phys_sr, new_phys_channels):
        """在保持输入采集与 DSP 运算不中断的前提下，安全热插拔/热切换底层物理输出声卡流"""
        try:
            self.log(f"🔄 正在无缝热切换音频输出设备 -> 【{new_phys_name}】...")
            old_phys_name = getattr(self, 'current_live_phys_name', None)

            # 1. 还原旧设备物理端点音量
            if old_phys_name and hasattr(self, 'original_phys_vol') and self.original_phys_vol is not None:
                try:
                    set_device_endpoint_volume(old_phys_name, self.original_phys_vol)
                except Exception:
                    pass

            # 2. 准备新设备物理端点音量
            self.original_phys_vol = get_device_endpoint_volume(new_phys_name)
            set_device_endpoint_volume(new_phys_name, 1.0)
            self.current_live_phys_name = new_phys_name
            self.original_default_audio_name = new_phys_name

            # 3. 安全停止并关闭旧物理输出流
            old_out_stream = self.live_out_stream
            self.live_out_stream = None
            if old_out_stream:
                try:
                    old_out_stream.stop_stream()
                    old_out_stream.close()
                except Exception:
                    pass

            # 4. 创建并绑定新物理输出流
            self.live_out_stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=new_phys_channels,
                rate=self.live_rate,
                output=True,
                output_device_index=new_phys_idx,
                frames_per_buffer=self.live_chunk_size
            )
            self.log(f"✅ 音频输出设备已成功切换为: 【{new_phys_name}】")
        except Exception as e:
            logging.error(f"Failed to hot-swap output device: {e}")

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

                    self.current_live_phys_name = None
                    self.sig_set_toggle_state.emit("off")
                    self.sig_set_toggle_status_text.emit("● 未开启 (点击开启)", "#9ca3af")
                    self.sig_set_dsp_tag.emit("● 待机中 (等待开启)", "#71717a" if self.current_theme == "dark" else "#9ca3af")
                    self.log("⏹️ 系统全局声音实时增强已停止，默认播放设备及音量已还原。")
                except Exception as e:
                    logging.error(f"Async stop capture error: {e}")
                    self.current_live_phys_name = None
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
                    self.current_live_phys_name = phys_out_name
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
                    self.current_live_phys_name = None
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

                sample_data = floats[:, 0]
                fft_data = np.abs(np.fft.rfft(sample_data * np.hanning(len(sample_data))))
                self.fft_raw_spectrum = fft_data
                # 72 频段对数声学分布 (30Hz ~ 18000Hz)
                if len(fft_data) > 16:
                    sr = getattr(self, 'live_in_sr', 48000)
                    fft_size = len(sample_data)
                    bin_hz = sr / float(fft_size)
                    log_freqs = np.geomspace(30, min(18000, sr / 2.1), 73)
                    bands_72 = np.zeros(72, dtype=np.float32)
                    for bi in range(72):
                        f0 = log_freqs[bi]
                        f1 = log_freqs[bi + 1]
                        a = max(1, int(math.floor(f0 / bin_hz)))
                        b = min(len(fft_data) - 1, int(math.ceil(f1 / bin_hz)))
                        if b >= a:
                            chunk = fft_data[a:b+1]
                            bands_72[bi] = float(np.sqrt(np.mean(chunk ** 2)))
                        elif a < len(fft_data):
                            bands_72[bi] = float(fft_data[a])
                    self.fft_magnitudes = bands_72

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
        consecutive_errors = 0
        while self.is_live_capturing:
            try:
                stream = self.live_out_stream
                if not stream:
                    time.sleep(0.01)
                    continue
                try:
                    chunk_bytes = self.live_ring_buffer.get(timeout=0.05)
                except queue.Empty:
                    chunk_bytes = b'\x00' * (self.live_chunk_size * 2 * 4)

                stream.write(chunk_bytes)
                consecutive_errors = 0
            except Exception as e:
                if not self.is_live_capturing:
                    break
                consecutive_errors += 1
                logging.error(f"Live Out Playback Worker Exception ({consecutive_errors}): {e}")
                if consecutive_errors >= 3:
                    # 设备可能已拔出/断开，触发信号自动恢复切换
                    self.sig_audio_devices_changed.emit()
                    time.sleep(0.1)
                else:
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
            if hasattr(self, 'device_watcher') and self.device_watcher:
                self.device_watcher.stop()
        except Exception:
            pass
        try:
            if hasattr(self, 'device_poll_timer'):
                self.device_poll_timer.stop()
            if hasattr(self, 'device_debounce_timer'):
                self.device_debounce_timer.stop()
        except Exception:
            pass
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
