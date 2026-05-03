/**
 * 随心系统 / Suixin System
 * Copyright (c) 2026 huangkeqi
 * 保留所有权利。
 * 
 * 本软件目前为个人工作流工具，开源供学习参考。
 * 项目主页：https://github.com/huangkeqi-cmd/suixi-system
 */

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
随系 · 影像管理器 - PC 端
PanoramaManager PC Application

技术栈: Python 3.10+ + PyQt6
功能: 项目导入、影像关联、网页生成、本地服务器
"""

import sys
import os
import json
import zipfile
import shutil
import socket
import webbrowser
import tempfile
import urllib.parse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple
from http.server import HTTPServer, SimpleHTTPRequestHandler, BaseHTTPRequestHandler
import ssl
import threading
import socketserver

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QSplitter, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QDialog, QTextEdit, QProgressDialog,
    QMenuBar, QMenu, QToolBar, QStatusBar, QFrame, QScrollArea,
    QGridLayout, QGroupBox, QComboBox, QSpinBox, QCheckBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont, QIcon, QAction

from PIL import Image, ImageDraw, ImageFont
from PIL.ExifTags import TAGS
import qrcode


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class Marker:
    """标记点数据模型"""
    id: str
    status: str  # pending, captured, linked, missing
    cameraFileName: str = ""
    customName: str = ""
    x: float = 0.0  # 归一化坐标 0-1
    y: float = 0.0
    timestamp: str = ""  # 旧版本字段
    captureTime: str = ""  # 新版本字段 (schema 4.0)
    startTime: str = ""  # 采集开始时间
    endTime: str = ""    # 采集结束时间
    panoramaPath: str = ""
    originalPhotoPath: str = ""  # 原始照片绝对路径（不复制照片时使用）
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Marker':
        """从字典创建标记点，处理字段兼容性"""
        # 字段映射：新版本 captureTime 映射到 timestamp
        if 'captureTime' in data and not data.get('timestamp'):
            data['timestamp'] = data['captureTime']
        
        # 过滤掉不认识的字段
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered_data)
    
    def get_time_range(self) -> Optional[tuple]:
        """获取采集时间范围 (start, end)，如果只有 captureTime 则返回单个时间点"""
        from datetime import datetime
        
        marker_name = self.customName or self.id
        
        # 优先使用 startTime 和 endTime
        if self.startTime and self.endTime:
            try:
                start = datetime.fromisoformat(self.startTime.replace('Z', '+00:00'))
                end = datetime.fromisoformat(self.endTime.replace('Z', '+00:00'))
                print(f"[调试] {marker_name}: 解析时间范围成功 [{start}] - [{end}]")
                return (start, end)
            except Exception as e:
                print(f"[调试] {marker_name}: 解析 startTime/endTime 失败: {e}")
                pass
        
        # 回退到 captureTime
        if self.captureTime:
            try:
                t = datetime.fromisoformat(self.captureTime.replace('Z', '+00:00'))
                print(f"[调试] {marker_name}: 使用 captureTime [{t}]")
                return (t, t)  # 单点时间，范围相同
            except Exception as e:
                print(f"[调试] {marker_name}: 解析 captureTime 失败: {e}")
                pass
        
        # 最后尝试 timestamp
        if self.timestamp:
            try:
                t = datetime.fromisoformat(self.timestamp.replace('Z', '+00:00'))
                print(f"[调试] {marker_name}: 使用 timestamp [{t}]")
                return (t, t)
            except:
                pass
        
        print(f"[调试] {marker_name}: 无可用时间信息")
        return None


@dataclass
class Floor:
    """楼层数据模型"""
    id: str
    name: str
    order: int
    hasPlan: bool
    markers: List[dict]
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Floor':
        return cls(**data)


@dataclass
class Project:
    """项目数据模型 - 支持多楼层 (schema 4.0)"""
    schemaVersion: str
    projectName: str
    createdAt: str
    updatedAt: str
    floors: List[dict]  # 多楼层数组
    timeOffset: int = 0
    calibrated: bool = False
    photoBaseDir: str = ""  # 照片根目录（不复制照片时使用）
    # 旧版本兼容字段
    floorplan: str = ""
    floorplanOriginalName: str = ""
    markers: List[dict] = None
    
    def __post_init__(self):
        if self.markers is None:
            self.markers = []
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Project':
        """从字典创建项目，处理版本兼容性"""
        # 确保新字段有默认值
        data.setdefault('timeOffset', 0)
        data.setdefault('calibrated', False)
        data.setdefault('floors', [])
        
        # 旧版本兼容：如果有 markers 但没有 floors，创建默认楼层
        if not data.get('floors') and data.get('markers'):
            data['floors'] = [{
                'id': 'legacy_floor',
                'name': '默认楼层',
                'order': 0,
                'hasPlan': bool(data.get('floorplan')),
                'markers': data['markers']
            }]
        
        return cls(**data)
    
    def to_dict(self) -> dict:
        return asdict(self)


# =============================================================================
# HTTP 服务器线程
# =============================================================================

class HttpServerThread(QThread):
    """HTTP 服务器后台线程（支持HTTPS）"""
    server_started = pyqtSignal(str, int)  # ip, port
    server_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, viewer_dir: str, port: int = 0, use_https: bool = False):
        super().__init__()
        self.viewer_dir = viewer_dir
        self.port = port
        self.use_https = use_https
        self.server = None
        self.redirect_server = None
        self.is_running = False
        
    def run(self):
        try:
            # 创建自定义 Handler，指定根目录
            viewer_dir = self.viewer_dir
            
            class CustomHandler(SimpleHTTPRequestHandler):
                def translate_path(self, path):
                    # 保存原始路径用于调试
                    original_path = path
                    
                    # 将路径映射到 viewer_dir
                    path = path.split('?', 1)[0]
                    path = path.split('#', 1)[0]
                    path = path.split(';', 1)[0]
                    
                    # URL decode
                    try:
                        path = urllib.parse.unquote(path)
                    except:
                        pass
                    
                    # 去除开头的 /
                    if path.startswith('/'):
                        path = path[1:]
                    
                    # 使用 posixpath 处理 URL 路径
                    words = path.split('/')
                    words = filter(None, words)
                    
                    # 从 viewer_dir 开始构建路径
                    result_path = viewer_dir
                    for word in words:
                        if os.path.dirname(word) or word in (os.curdir, os.pardir):
                            continue
                        result_path = os.path.join(result_path, word)
                    
                    # 如果是目录，尝试返回 index.html
                    if os.path.isdir(result_path):
                        index_file = os.path.join(result_path, 'index.html')
                        if os.path.exists(index_file):
                            result_path = index_file
                    
                    print(f"[HTTP] {original_path} -> {result_path}")
                    return result_path
                
                def do_GET(self):
                    print(f"[HTTP] GET {self.path}")
                    return super().do_GET()
                
                def log_message(self, format, *args):
                    print(f"[HTTP] {format % args}")
            
            # HTTP到HTTPS重定向Handler
            class RedirectHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    # 获取原始路径
                    path = self.path
                    # 构建HTTPS URL
                    https_path = f"https://{self.headers.get('Host', '')}{path}"
                    # 发送重定向响应
                    self.send_response(301)
                    self.send_header('Location', https_path)
                    self.end_headers()
                    
                def log_message(self, format, *args):
                    print(f"[重定向] {format % args}")
            
            # 使用多线程服务器，支持更多并发连接
            class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
                allow_reuse_address = True
                daemon_threads = True
            
            if self.use_https:
                # HTTPS服务器
                self.server = ThreadedHTTPServer(("", self.port), CustomHandler)
                
                # 尝试加载SSL证书
                ssl_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ssl')
                cert_file = os.path.join(ssl_dir, '192.168.3.215+127.0.0.1+localhost.pem')
                key_file = os.path.join(ssl_dir, '192.168.3.215+127.0.0.1+localhost-key.pem')
                
                if os.path.exists(cert_file) and os.path.exists(key_file):
                    # 配置SSL
                    self.server.socket = ssl.wrap_socket(
                        self.server.socket,
                        keyfile=key_file,
                        certfile=cert_file,
                        server_side=True
                    )
                    print(f"[SSL] 证书已加载: {cert_file}")
                else:
                    print(f"[SSL] 证书文件未找到，将使用HTTP模式")
                    self.use_https = False
                    
            if not self.use_https or not self.server:
                self.server = ThreadedHTTPServer(("", self.port), CustomHandler)
            
            actual_port = self.server.socket.getsockname()[1]
            self.is_running = True
            
            # 获取本机 IP
            ip = self.get_local_ip()
            protocol = "https" if self.use_https else "http"
            print(f"[调试] 服务器启动: {protocol}://{ip}:{actual_port}")
            print(f"[调试] 根目录: {viewer_dir}")
            self.server_started.emit(ip, actual_port)
            
            self.server.serve_forever()
            
        except Exception as e:
            print(f"[调试] 服务器错误: {e}")
            import traceback
            traceback.print_exc()
            self.error_occurred.emit(str(e))
    
    def stop(self):
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
        except Exception as e:
            print(f"[调试] 关闭服务器异常: {e}")
        try:
            if self.redirect_server:
                self.redirect_server.shutdown()
                self.redirect_server.server_close()
        except Exception as e:
            print(f"[调试] 关闭重定向服务器异常: {e}")
        self.is_running = False
        # 给线程一些时间自行退出
        import time
        time.sleep(0.1)
        self.server_stopped.emit()
    
    @staticmethod
    def get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"


# =============================================================================
# 照片导入线程
# =============================================================================

def extract_exif_datetime(image_path: str) -> Optional[datetime]:
    """从照片 EXIF 数据提取拍摄时间"""
    try:
        img = Image.open(image_path)
        exif = img._getexif()
        img.close()
        
        if not exif:
            return None
        
        # 查找 DateTimeOriginal 标签 (36867)
        for tag_id, value in exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == 'DateTimeOriginal':
                try:
                    # 格式: "2026:04:22 13:30:45"
                    dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    print(f"[调试] EXIF: {os.path.basename(image_path)} -> {dt.strftime('%Y-%m-%d %H:%M:%S')} (本地时间)")
                    return dt
                except Exception as e:
                    print(f"[调试] 解析EXIF时间失败 {value}: {e}")
                    pass
    except Exception as e:
        print(f"[调试] 读取EXIF失败 {os.path.basename(image_path)}: {e}")
        pass
    return None


class TimeCalibrationDialog(QDialog):
    """时间校准对话框"""
    def __init__(self, current_offset: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("时间校准")
        self.setMinimumWidth(400)
        self.calibrated_offset = current_offset
        
        layout = QVBoxLayout(self)
        
        # 说明文字
        info = QLabel("如果照片时间与记录时间有偏差，可以调整校准值。\n"
                     "校准值 = 手机时间 - 相机时间（秒）")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # 当前值显示
        self.offset_label = QLabel(f"当前校准值: {current_offset} 秒")
        layout.addWidget(self.offset_label)
        
        # 调整滑块 - 扩大到±12小时以应对时区差异
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("-12h"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-43200, 43200)  # ±12小时
        self.slider.setValue(max(-43200, min(43200, current_offset)))  # 限制在范围内
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(3600)  # 1小时间隔
        self.slider.valueChanged.connect(self._on_slider_changed)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(QLabel("+12h"))
        layout.addLayout(slider_layout)
        
        # 精确输入
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("精确值:"))
        self.spin_box = QSpinBox()
        self.spin_box.setRange(-86400, 86400)  # ±24小时
        self.spin_box.setValue(current_offset)
        self.spin_box.setSuffix(" 秒")
        self.spin_box.setSingleStep(60)  # 步长60秒
        self.spin_box.valueChanged.connect(self._on_spin_changed)
        input_layout.addWidget(self.spin_box)
        layout.addLayout(input_layout)
        
        # 快捷按钮 - 增加小时级调整
        quick_layout = QHBoxLayout()
        quick_layout.addWidget(QLabel("快捷调整:"))
        
        for label, offset in [("-1h", -3600), ("-10m", -600), ("0", 0), ("+10m", 600), ("+1h", 3600)]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, o=offset: self._set_offset(o))
            quick_layout.addWidget(btn)
        
        layout.addLayout(quick_layout)
        
        # 说明示例
        example = QLabel("示例：如果相机时间比手机慢8小时（时区差异），\n"
                        "校准值应设为 +28800\n"
                        "校准值 = 手机时间 - 相机时间")
        example.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(example)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def _on_slider_changed(self, value):
        self.spin_box.setValue(value)
        self.calibrated_offset = value
        hours = abs(value) // 3600
        mins = (abs(value) % 3600) // 60
        secs = abs(value) % 60
        if hours > 0:
            time_str = f"{hours}小时{mins}分{secs}秒"
        elif mins > 0:
            time_str = f"{mins}分{secs}秒"
        else:
            time_str = f"{secs}秒"
        sign = "+" if value > 0 else "" if value < 0 else ""
        self.offset_label.setText(f"当前校准值: {sign}{value} 秒 ({sign}{time_str})")
    
    def _on_spin_changed(self, value):
        # 限制 slider 范围，避免超出
        slider_value = max(-43200, min(43200, value))
        self.slider.setValue(slider_value)
        self.calibrated_offset = value
        hours = abs(value) // 3600
        mins = (abs(value) % 3600) // 60
        secs = abs(value) % 60
        if hours > 0:
            time_str = f"{hours}小时{mins}分{secs}秒"
        elif mins > 0:
            time_str = f"{mins}分{secs}秒"
        else:
            time_str = f"{secs}秒"
        sign = "+" if value > 0 else "" if value < 0 else ""
        self.offset_label.setText(f"当前校准值: {sign}{value} 秒 ({sign}{time_str})")
    
    def _set_offset(self, offset):
        self.slider.setValue(offset)
        self.spin_box.setValue(offset)


class AutoCalibrationThread(QThread):
    """自动校准线程 - 通过分析匹配情况计算最佳 timeOffset"""
    calibration_complete = pyqtSignal(int, int, int)  # suggested_offset, matched_count, total_count
    
    def __init__(self, markers: List[dict], photo_files: List[str]):
        super().__init__()
        self.markers = [m for m in markers if m.get('status') == 'captured']
        self.photo_files = photo_files
    
    def run(self):
        """尝试不同的 offset 值，找到匹配最多的那个"""
        try:
            if not self.markers:
                self.calibration_complete.emit(0, 0, 0)
                return
            
            # 提取有时间的标记点（支持 startTime/endTime 和 captureTime）
            marker_times = []
            for marker_data in self.markers:
                # 使用 Marker 类的 get_time_range 方法来获取时间
                marker = Marker.from_dict(marker_data)
                time_range = marker.get_time_range()
                if time_range:
                    start_time, end_time = time_range
                    # 使用开始时间进行校准计算
                    marker_times.append((marker.id, start_time))
                    print(f"[自动校准] 标记点 {marker.customName or marker.id}: 时间 {start_time}")
            
            print(f"[自动校准] 共 {len(marker_times)} 个标记点有时间信息")
            
            if not marker_times:
                print("[自动校准] 警告: 没有找到带有时间信息的标记点")
                self.calibration_complete.emit(0, 0, 0)
                return
            
            # 提取照片的 EXIF 时间（限制只处理前50张照片，避免太慢）
            photo_times = []
            max_photos = min(50, len(self.photo_files))
            print(f"[自动校准] 扫描 {max_photos} 张照片的 EXIF 时间...")
            for i in range(max_photos):
                try:
                    dt = extract_exif_datetime(self.photo_files[i])
                    if dt:
                        photo_times.append((self.photo_files[i], dt))
                        print(f"[自动校准] 照片 {os.path.basename(self.photo_files[i])}: {dt}")
                except Exception:
                    pass
            
            print(f"[自动校准] 共 {len(photo_times)} 张照片有 EXIF 时间")
            
            if not photo_times:
                print("[自动校准] 警告: 没有照片包含 EXIF 时间信息")
                self.calibration_complete.emit(0, 0, 0)
                return
            
            # 尝试不同的 offset 范围
            # 首先尝试小时级别的偏移（应对时区差异），然后尝试分钟级别，最后精确到秒
            best_offset = 0
            best_matches = 0
            
            # 阶段1: 尝试小时级偏移（±12小时，步长1小时）- 应对时区差异
            print("[自动校准] 阶段1: 尝试小时级偏移...")
            for hour_offset in range(-12, 13):
                offset = hour_offset * 3600
                matches = self._count_matches(marker_times, photo_times, offset)
                if matches > best_matches:
                    best_matches = matches
                    best_offset = offset
                    print(f"[自动校准] 小时级: offset={offset}秒 ({hour_offset}小时), 匹配={matches}")
            
            print(f"[自动校准] 阶段1最佳: offset={best_offset}秒, 匹配={best_matches}")
            
            # 阶段2: 在最佳小时偏移附近尝试分钟级调整（±30分钟，步长5分钟）
            if best_matches > 0:
                print("[自动校准] 阶段2: 尝试分钟级调整...")
                base_offset = best_offset
                for minute_offset in range(-30, 31, 5):
                    offset = base_offset + minute_offset * 60
                    matches = self._count_matches(marker_times, photo_times, offset)
                    if matches > best_matches:
                        best_matches = matches
                        best_offset = offset
                        print(f"[自动校准] 分钟级: offset={offset}秒, 匹配={matches}")
            
            # 阶段3: 在最佳偏移附近精确调整（±60秒，步长10秒）
            if best_matches > 0:
                print("[自动校准] 阶段3: 精确调整...")
                base_offset = best_offset
                for second_offset in range(-60, 61, 10):
                    offset = base_offset + second_offset
                    matches = self._count_matches(marker_times, photo_times, offset)
                    if matches > best_matches:
                        best_matches = matches
                        best_offset = offset
            
            print(f"[自动校准] 最终结果: offset={best_offset}秒, 匹配={best_matches}/{len(marker_times)}")
            self.calibration_complete.emit(best_offset, best_matches, len(marker_times))
        except Exception as e:
            print(f"自动校准出错: {e}")
            import traceback
            traceback.print_exc()
            self.calibration_complete.emit(0, 0, 0)
    
    def _count_matches(self, marker_times, photo_times, offset):
        """计算给定偏移量下的匹配数量"""
        from datetime import timedelta
        matches = 0
        for _, marker_time in marker_times:
            adjusted_time = marker_time + timedelta(seconds=offset)
            # 去除时区信息，转换为本地时间
            if adjusted_time.tzinfo:
                adjusted_time = adjusted_time.replace(tzinfo=None)
            # 找最接近的照片
            min_diff = float('inf')
            for _, photo_time in photo_times:
                # 确保照片时间也没有时区信息
                if photo_time.tzinfo:
                    photo_time = photo_time.replace(tzinfo=None)
                diff = abs((adjusted_time - photo_time).total_seconds())
                if diff < min_diff:
                    min_diff = diff
            # 300秒内（5分钟）视为匹配，给自动校准更宽松的阈值
            if min_diff <= 300:
                matches += 1
        return matches


class PhotoImportThread(QThread):
    """照片导入和匹配后台线程"""
    progress_update = pyqtSignal(int, str)  # progress, message
    match_found = pyqtSignal(str, str, str)  # marker_id, filename, match_type
    import_complete = pyqtSignal(dict)  # results
    
    def __init__(self, project_dir: str, photo_dir: str, floors: List[dict], 
                 time_offset: int = 0, use_exif: bool = True, threshold: int = 30,
                 photo_base_dir: str = ""):
        super().__init__()
        self.project_dir = project_dir
        self.photo_dir = photo_dir
        self.floors = floors
        self.time_offset = time_offset
        self.use_exif = use_exif  # 是否使用 EXIF 时间
        self.threshold = threshold  # 匹配阈值（秒）
        self.photo_base_dir = photo_base_dir  # 照片根目录
        self._suggested_offset = None  # 建议的校准值
        # 收集所有楼层的标记点
        self.markers = []
        for floor in floors:
            floor_markers = floor.get('markers', [])
            print(f"[调试] 楼层 {floor.get('name', '未知')}: {len(floor_markers)} 个标记点")
            for m in floor_markers[:2]:  # 只显示前2个
                print(f"[调试]   标记点: id={m.get('id')}, status={m.get('status')}, startTime={m.get('startTime', '无')}, endTime={m.get('endTime', '无')}, captureTime={m.get('captureTime', '无')}")
            self.markers.extend(floor_markers)
        
    def run(self):
        results = {
            'exact': 0,      # EXIF 时间精确匹配
            'similar': 0,    # 文件名相似匹配
            'manual': 0,
            'missing': 0,
            'details': []
        }
        
        # 收集所有照片文件
        photo_files = []
        for root, dirs, files in os.walk(self.photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg')):
                    photo_files.append(os.path.join(root, f))
        
        print(f"[调试] 找到 {len(photo_files)} 张照片")
        print(f"[调试] 找到 {len(self.markers)} 个标记点")
        print(f"[调试] 时间偏移: {self.time_offset} 秒")
        
        # 预提取所有照片的 EXIF 时间（加速匹配）
        self.progress_update.emit(0, "正在读取照片 EXIF 信息...")
        self.photo_exif_times = {}
        for pf in photo_files:
            dt = extract_exif_datetime(pf)
            if dt:
                self.photo_exif_times[pf] = dt
                print(f"[调试] 照片 EXIF: {os.path.basename(pf)} -> {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        print(f"[调试] 成功提取 EXIF 时间的照片: {len(self.photo_exif_times)} 张")
        if len(self.photo_exif_times) == 0:
            print("[调试] 警告: 没有照片包含EXIF时间信息!")
            # 显示一些照片文件名帮助诊断
            for pf in photo_files[:3]:
                print(f"[调试] 示例照片: {os.path.basename(pf)}")
        
        # 统计各状态标记点数量
        captured_markers = [m for m in self.markers if m.get('status') == 'captured']
        print(f"[调试] 已拍摄标记点 (captured): {len(captured_markers)} 个")
        
        # 显示标记点时间信息
        for m in captured_markers[:3]:
            marker = Marker.from_dict(m)
            tr = marker.get_time_range()
            if tr:
                start, end = tr
                print(f"[调试] 标记点 {marker.customName or marker.id}: 范围 [{start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')}]")
        
        total_markers = len(self.markers)
        
        for idx, marker_data in enumerate(self.markers):
            marker = Marker.from_dict(marker_data)
            progress = int((idx / total_markers) * 100)
            self.progress_update.emit(progress, f"正在处理: {marker.customName or marker.id}")
            
            if marker.status != 'captured':
                print(f"[调试] 标记点 {marker.customName or marker.id}: 状态={marker.status}, 跳过")
                results['missing'] += 1
                marker_data['status'] = 'missing'
                continue
            
            print(f"[调试] 处理标记点 {marker.customName or marker.id}...")
            
            # 1. EXIF 时间匹配（最准确）
            if self.use_exif and self.photo_exif_times:
                matched_file = self._exif_time_match(marker)
                if matched_file:
                    self._link_photo(matched_file, marker)
                    marker_data['status'] = 'linked'
                    marker_data['panoramaPath'] = marker.panoramaPath
                    marker_data['originalPhotoPath'] = marker.originalPhotoPath
                    marker_data['cameraFileName'] = os.path.basename(matched_file)
                    results['exact'] += 1
                    self.match_found.emit(marker.id, os.path.basename(matched_file), 'exact')
                    continue
            
            # 2. 文件名时间戳匹配（备选）
            matched_file = self._filename_time_match(marker, photo_files)
            if matched_file:
                self._link_photo(matched_file, marker)
                marker_data['status'] = 'linked'
                marker_data['panoramaPath'] = marker.panoramaPath
                marker_data['originalPhotoPath'] = marker.originalPhotoPath
                marker_data['cameraFileName'] = os.path.basename(matched_file)
                results['similar'] += 1
                self.match_found.emit(marker.id, os.path.basename(matched_file), 'similar')
                continue
            
            # 3. 未找到
            results['missing'] += 1
            marker.status = 'missing'
            marker_data['status'] = 'missing'
        
        self.progress_update.emit(100, "导入完成")
        self.import_complete.emit(results)
    
    def _exif_time_match(self, marker: Marker) -> Optional[str]:
        """使用 EXIF 时间进行匹配 - 支持时间范围匹配"""
        marker_name = marker.customName or marker.id
        
        # 获取时间范围 (start, end)
        time_range = marker.get_time_range()
        if not time_range:
            print(f"[调试] 标记点 {marker_name}: 无时间信息")
            return None
        
        start_time, end_time = time_range
        
        try:
            # 应用 timeOffset 校正
            from datetime import timedelta
            adjusted_start = start_time + timedelta(seconds=self.time_offset)
            adjusted_end = end_time + timedelta(seconds=self.time_offset)
            
            # 转换为本地时间（去除时区信息）以便与 EXIF 时间比较
            # EXIF 时间是本地时间，没有时区信息
            if adjusted_start.tzinfo:
                adjusted_start = adjusted_start.replace(tzinfo=None)
            if adjusted_end.tzinfo:
                adjusted_end = adjusted_end.replace(tzinfo=None)
            
            # 计算时间范围长度
            range_seconds = (adjusted_end - adjusted_start).total_seconds()
            
            if range_seconds > 0:
                print(f"[调试] 标记点 {marker_name}: 时间范围 [{adjusted_start.strftime('%H:%M:%S')} - {adjusted_end.strftime('%H:%M:%S')}], 持续{range_seconds:.0f}秒")
            else:
                print(f"[调试] 标记点 {marker_name}: 单点时间 {adjusted_start.strftime('%H:%M:%S')}")
            
            # 打印所有照片时间帮助诊断
            print(f"[调试] 标记点 {marker_name}: 可用照片时间:")
            for photo_path, photo_time in list(self.photo_exif_times.items())[:5]:
                pt = photo_time.replace(tzinfo=None) if photo_time.tzinfo else photo_time
                print(f"[调试]   {os.path.basename(photo_path)}: {pt.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 收集候选照片，按拍摄时间排序，返回第一张在阈值内的
            candidates = []
            for photo_path, photo_time in self.photo_exif_times.items():
                # 确保照片时间也没有时区信息
                if photo_time.tzinfo:
                    photo_time = photo_time.replace(tzinfo=None)
                
                # 计算时间差（秒）
                if range_seconds > 0:
                    range_center = adjusted_start + timedelta(seconds=range_seconds / 2)
                    diff = abs((photo_time - range_center).total_seconds())
                else:
                    diff = abs((photo_time - adjusted_start).total_seconds())
                
                candidates.append((photo_path, diff, photo_time))
            
            # 按与采集点中心时间差值排序，取差值最小的第一张照片
            candidates.sort(key=lambda x: x[1])
            print(f"[调试] 标记点 {marker_name}: 候选照片(按时间排序, 取第一张):")
            for i, (path, diff, ptime) in enumerate(candidates[:5]):
                print(f"[调试]   {i+1}. {os.path.basename(path)}: {ptime.strftime('%H:%M:%S')} 差{diff:.1f}秒")
            
            # 返回第一个在阈值内的照片（同一时间段内多张照片时只识别第一张）
            for photo_path, diff, photo_time in candidates:
                if diff <= self.threshold:
                    print(f"[调试] 标记点 {marker_name}: 匹配成功 {os.path.basename(photo_path)}, 时间差={diff:.1f}秒")
                    return photo_path
            
            if candidates:
                best_diff = candidates[0][1]
                print(f"[调试] 标记点 {marker_name}: 最佳匹配时间差={best_diff:.1f}秒, 超过阈值{self.threshold}秒")
                # 如果差距很大（超过1小时）且未设置建议值，记录建议的校准值
                if best_diff > 3600 and self._suggested_offset is None:
                    # 需要判断是相机快还是慢
                    best_match = candidates[0][0]
                    pf_time = None
                    for p, t in self.photo_exif_times.items():
                        if p == best_match:
                            pf_time = t
                            break
                    if pf_time:
                        time_range = marker.get_time_range()
                        if time_range:
                            start_time, _ = time_range
                            # 计算差值
                            diff_seconds = (pf_time - start_time.replace(tzinfo=None) if start_time.tzinfo else pf_time - start_time).total_seconds()
                            hours = round(diff_seconds / 3600)
                            self._suggested_offset = int(hours * 3600)
                            print(f"[调试] 建议校准值: {self._suggested_offset} 秒 ({hours}小时)")
            else:
                print(f"[调试] 标记点 {marker_name}: 无匹配照片")
            
        except Exception as e:
            print(f"[调试] 标记点 {marker_name}: EXIF 匹配出错: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def _extract_time_from_filename(self, filename: str) -> Optional[datetime]:
        """从文件名中提取时间，支持多种格式"""
        import re
        
        # 移除扩展名
        name = os.path.splitext(filename)[0]
        
        # 模式1: 连续格式 20260422183045
        match = re.search(r'(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', name)
        if match:
            try:
                year, month, day, hour, minute, second = map(int, match.groups())
                # 验证时间合理性
                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, hour, minute, second)
            except:
                pass
        
        # 模式2: 带分隔符格式 2026_04_22_18_30_45 或 2026-04-22-18-30-45
        match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})', name)
        if match:
            try:
                year, month, day, hour, minute, second = map(int, match.groups())
                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, hour, minute, second)
            except:
                pass
        
        # 模式3: 带T分隔符 20260422T183045
        match = re.search(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})', name)
        if match:
            try:
                year, month, day, hour, minute, second = map(int, match.groups())
                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    return datetime(year, month, day, hour, minute, second)
            except:
                pass
        
        return None
    
    def _filename_time_match(self, marker: Marker, photo_files: List[str]) -> Optional[str]:
        """使用文件名时间戳进行匹配（备选方案）- 支持时间范围"""
        marker_name = marker.customName or marker.id
        
        # 获取时间范围
        time_range = marker.get_time_range()
        if not time_range:
            return None
        
        start_time, end_time = time_range
        
        try:
            # 应用 timeOffset
            from datetime import timedelta
            adjusted_start = start_time + timedelta(seconds=self.time_offset)
            adjusted_end = end_time + timedelta(seconds=self.time_offset)
            
            # 去除时区信息，转换为本地时间
            if adjusted_start.tzinfo:
                adjusted_start = adjusted_start.replace(tzinfo=None)
            if adjusted_end.tzinfo:
                adjusted_end = adjusted_end.replace(tzinfo=None)
            
            range_seconds = (adjusted_end - adjusted_start).total_seconds()
            
            print(f"[调试] {marker_name}: 文件名匹配 - 时间范围 [{adjusted_start}] - [{adjusted_end}]")
            
            # 收集候选并按文件名时间排序，返回第一张匹配的
            candidates = []
            for pf in photo_files:
                pf_time = self._extract_time_from_filename(os.path.basename(pf))
                if pf_time:
                    diff = abs((pf_time - adjusted_start).total_seconds())
                    if range_seconds > 0:
                        range_center = adjusted_start + timedelta(seconds=range_seconds / 2)
                        diff = abs((pf_time - range_center).total_seconds())
                    candidates.append((pf, diff, pf_time))
            
            # 按与采集点中心时间差值排序，取差值最小的第一张匹配的
            candidates.sort(key=lambda x: x[1])
            print(f"[调试] {marker_name}: 文件名候选(按时间排序, 取第一张):")
            for i, (pf, diff, ptime) in enumerate(candidates[:5]):
                print(f"[调试]   {i+1}. {os.path.basename(pf)}: {ptime.strftime('%H:%M:%S')} 差{diff:.0f}秒")
            
            for pf, diff, pf_time in candidates:
                if diff <= 600:
                    print(f"[调试] {marker_name}: 文件名匹配成功 {os.path.basename(pf)}, 差{diff:.0f}秒")
                    return pf
            
            if candidates:
                best_diff = candidates[0][1]
                print(f"[调试] {marker_name}: 文件名最佳匹配差{best_diff:.0f}秒 ({best_diff/3600:.1f}小时), 超阈值")
                if best_diff > 3600:
                    print(f"[调试] {marker_name}: 建议设置校准值约 {int(best_diff)} 秒 ({int(best_diff/3600)}小时)")
            
        except Exception as e:
            print(f"[调试] 文件名匹配出错: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def _link_photo(self, source_path: str, marker: Marker):
        """关联照片（不复制，只记录路径）"""
        marker.originalPhotoPath = source_path
        
        if self.photo_base_dir and os.path.commonpath([os.path.abspath(source_path), os.path.abspath(self.photo_base_dir)]) == os.path.abspath(self.photo_base_dir):
            # 如果在照片基目录下，记录相对路径
            rel_path = os.path.relpath(source_path, self.photo_base_dir)
            marker.panoramaPath = rel_path.replace('\\', '/')
        else:
            # 否则记录绝对路径
            marker.panoramaPath = os.path.abspath(source_path).replace('\\', '/')
        
        marker.status = 'linked'


# =============================================================================
# 平面图画布
# =============================================================================

class FloorplanCanvas(QGraphicsView):
    """交互式平面图画布"""
    marker_selected = pyqtSignal(str)  # marker_id
    marker_moved = pyqtSignal(str, float, float)  # marker_id, x, y
    marker_add_requested = pyqtSignal(float, float)  # x, y (归一化坐标)
    marker_context_menu = pyqtSignal(str, QPointF)  # marker_id, global_pos
    canvas_context_menu = pyqtSignal(QPointF)  # global_pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = None
        self.marker_items = {}
        self.text_items = []  # 跟踪文本标签
        self.selected_marker_id = None
        self._dragging_marker = None
        self._drag_start_pos = None
        self._drag_item_start_pos = None
        self._panning = False

        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.setMinimumSize(600, 400)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def load_floorplan(self, image_path: str):
        """加载平面图"""
        self.scene.clear()
        self.marker_items = {}
        self.text_items = []
        self.selected_marker_id = None
        self._dragging_marker = None

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return False

        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())

        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        return True

    def add_marker(self, marker_id: str, x: float, y: float, status: str, label: str = ""):
        """添加标记点"""
        if not self.pixmap_item:
            return

        rect = self.pixmap_item.boundingRect()
        pixel_x = x * rect.width()
        pixel_y = y * rect.height()

        # 根据状态设置颜色
        colors = {
            'pending': QColor(128, 128, 128),    # 灰色
            'captured': QColor(0, 122, 255),     # 蓝色
            'linked': QColor(52, 199, 89),       # 绿色
            'missing': QColor(255, 59, 48)       # 红色
        }
        color = colors.get(status, QColor(128, 128, 128))

        # 绘制圆形标记
        radius = 8
        ellipse = QGraphicsEllipseItem(
            pixel_x - radius, pixel_y - radius,
            radius * 2, radius * 2
        )
        ellipse.setBrush(QBrush(color))
        ellipse.setPen(QPen(QColor(255, 255, 255), 2))
        ellipse.setData(0, marker_id)
        ellipse.setData(1, status)
        ellipse.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable)
        ellipse.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, False)
        ellipse.setCursor(Qt.CursorShape.OpenHandCursor)

        self.scene.addItem(ellipse)
        self.marker_items[marker_id] = ellipse

        # 添加标签
        if label:
            text = QGraphicsTextItem(str(label))
            text.setPos(pixel_x + radius + 2, pixel_y - radius)
            text.setDefaultTextColor(QColor(255, 255, 255))
            self.scene.addItem(text)
            self.text_items.append(text)

    def update_marker_pos(self, marker_id: str, x: float, y: float):
        """更新标记点位置（数据变更后刷新显示）"""
        item = self.marker_items.get(marker_id)
        if not item or not self.pixmap_item:
            return
        rect = self.pixmap_item.boundingRect()
        pixel_x = x * rect.width()
        pixel_y = y * rect.height()
        radius = 8
        item.setRect(pixel_x - radius, pixel_y - radius, radius * 2, radius * 2)

    def clear_markers(self):
        """清除所有标记和标签"""
        for item in self.marker_items.values():
            if item.scene():
                self.scene.removeItem(item)
        self.marker_items = {}

        for item in self.text_items:
            if item.scene():
                self.scene.removeItem(item)
        self.text_items = []

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            item = self.itemAt(event.pos())
            if item and isinstance(item, QGraphicsEllipseItem) and item.data(0):
                self._dragging_marker = item
                self.selected_marker_id = item.data(0)
                self._drag_start_pos = scene_pos
                self._drag_item_start_pos = item.pos()
                item.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.marker_selected.emit(str(self.selected_marker_id))
                return
            else:
                # 点击在平面图上（空白或图片），开始平移
                self._panning = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._last_pan_pos = event.pos()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_marker and self.pixmap_item:
            scene_pos = self.mapToScene(event.pos())
            # 计算相对于图片的新位置
            rect = self.pixmap_item.boundingRect()
            new_x = max(0.0, min(1.0, scene_pos.x() / rect.width()))
            new_y = max(0.0, min(1.0, scene_pos.y() / rect.height()))
            pixel_x = new_x * rect.width()
            pixel_y = new_y * rect.height()
            radius = 8
            self._dragging_marker.setRect(pixel_x - radius, pixel_y - radius, radius * 2, radius * 2)
            return
        elif self._panning:
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging_marker and self.pixmap_item:
                rect = self.pixmap_item.boundingRect()
                item = self._dragging_marker
                item_rect = item.rect()
                center_x = item_rect.x() + item_rect.width() / 2
                center_y = item_rect.y() + item_rect.height() / 2
                norm_x = max(0.0, min(1.0, center_x / rect.width()))
                norm_y = max(0.0, min(1.0, center_y / rect.height()))
                marker_id = item.data(0)
                item.setCursor(Qt.CursorShape.OpenHandCursor)
                self._dragging_marker = None
                if marker_id:
                    self.marker_moved.emit(str(marker_id), norm_x, norm_y)
                return
            elif self._panning:
                self._panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        item = self.itemAt(event.pos())
        if item and isinstance(item, QGraphicsEllipseItem) and item.data(0):
            self.marker_context_menu.emit(str(item.data(0)), event.globalPos())
        elif self.pixmap_item and self.pixmap_item.contains(scene_pos):
            rect = self.pixmap_item.boundingRect()
            norm_x = max(0.0, min(1.0, scene_pos.x() / rect.width()))
            norm_y = max(0.0, min(1.0, scene_pos.y() / rect.height()))
            self.marker_add_requested.emit(norm_x, norm_y)
        else:
            self.canvas_context_menu.emit(event.globalPos())

    def wheelEvent(self, event):
        """鼠标滚轮缩放"""
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor
        self.scale(factor, factor)


# =============================================================================
# 主窗口
# =============================================================================

class PanoramaManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("随系 · 影像管理器")
        self.setGeometry(100, 100, 1400, 900)
        
        self.project_dir: Optional[str] = None
        self.project_data: Optional[Project] = None
        self.server_thread: Optional[HttpServerThread] = None
        self.current_floor_id: Optional[str] = None
        
        self._init_ui()
        self._init_menu()
    
    def _init_ui(self):
        """初始化界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # 分割器
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # 左侧面板 - 平面图
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 楼层切换标签
        self.floor_tabs_widget = QWidget()
        floor_tabs_layout = QHBoxLayout(self.floor_tabs_widget)
        floor_tabs_layout.setContentsMargins(10, 5, 10, 5)
        floor_tabs_layout.setSpacing(8)
        left_layout.addWidget(self.floor_tabs_widget)
        
        # 平面图标题
        floorplan_header = QLabel("📍 平面图")
        floorplan_header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        left_layout.addWidget(floorplan_header)
        
        # 楼层标签区域（动态创建，支持滚动）
        self.floor_tabs_scroll = QScrollArea()
        self.floor_tabs_scroll.setWidgetResizable(True)
        self.floor_tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.floor_tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.floor_tabs_scroll.setMaximumHeight(60)
        self.floor_tabs_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.floor_tabs_container = QWidget()
        self.floor_tabs_layout = QHBoxLayout(self.floor_tabs_container)
        self.floor_tabs_layout.setContentsMargins(10, 5, 10, 5)
        self.floor_tabs_layout.setSpacing(8)
        self.floor_tabs_scroll.setWidget(self.floor_tabs_container)
        left_layout.addWidget(self.floor_tabs_scroll)
        
        # 画布
        self.canvas = FloorplanCanvas()
        self.canvas.marker_selected.connect(self._on_marker_selected)
        self.canvas.marker_moved.connect(self._on_marker_moved)
        self.canvas.marker_add_requested.connect(self._on_marker_add_requested)
        self.canvas.marker_context_menu.connect(self._on_marker_context_menu)
        left_layout.addWidget(self.canvas)
        
        # 画布操作提示
        self.canvas_hint = QLabel("💡 左键拖动点位移动 | 右键点击点位弹出菜单 | 滚轮缩放 | 左键拖拽空白处平移")
        self.canvas_hint.setStyleSheet("font-size: 11px; color: #8e8e93; padding: 4px 10px;")
        left_layout.addWidget(self.canvas_hint)
        
        splitter.addWidget(left_panel)
        
        # 右侧面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # 项目信息
        self.project_info_group = QGroupBox("项目信息")
        project_info_layout = QGridLayout(self.project_info_group)
        
        project_info_layout.addWidget(QLabel("项目名称:"), 0, 0)
        self.project_name_label = QLabel("未加载项目")
        self.project_name_label.setStyleSheet("font-weight: bold; color: #666;")
        project_info_layout.addWidget(self.project_name_label, 0, 1)
        
        project_info_layout.addWidget(QLabel("创建时间:"), 1, 0)
        self.created_time_label = QLabel("-")
        project_info_layout.addWidget(self.created_time_label, 1, 1)
        
        project_info_layout.addWidget(QLabel("点位数量:"), 2, 0)
        self.marker_count_label = QLabel("-")
        project_info_layout.addWidget(self.marker_count_label, 2, 1)
        
        project_info_layout.addWidget(QLabel("时间校准:"), 3, 0)
        self.calibration_label = QLabel("-")
        self.calibration_label.setStyleSheet("color: #666;")
        project_info_layout.addWidget(self.calibration_label, 3, 1)
        
        right_layout.addWidget(self.project_info_group)
        
        # 操作按钮
        actions_group = QGroupBox("操作")
        actions_layout = QVBoxLayout(actions_group)
        
        self.import_photos_btn = QPushButton("📷 导入影像")
        self.import_photos_btn.setEnabled(False)
        self.import_photos_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #0056CC; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.import_photos_btn.clicked.connect(self.import_photos)
        actions_layout.addWidget(self.import_photos_btn)
        
        self.generate_viewer_btn = QPushButton("🌐 生成本地网页")
        self.generate_viewer_btn.setEnabled(False)
        self.generate_viewer_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #248A3D; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.generate_viewer_btn.clicked.connect(self.generate_web_viewer)
        actions_layout.addWidget(self.generate_viewer_btn)
        
        self.open_web_btn = QPushButton("🚀 打开本地网页")
        self.open_web_btn.setEnabled(False)
        self.open_web_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.open_web_btn.clicked.connect(self.start_http_server)
        actions_layout.addWidget(self.open_web_btn)
        
        self.stop_server_btn = QPushButton("⏹️ 停止服务")
        self.stop_server_btn.setEnabled(False)
        self.stop_server_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #B32418; }
        """)
        self.stop_server_btn.clicked.connect(self.stop_http_server)
        actions_layout.addWidget(self.stop_server_btn)
        
        # 保存修改按钮
        self.save_changes_btn = QPushButton("💾 保存修改到项目")
        self.save_changes_btn.setEnabled(False)
        self.save_changes_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #5856D6;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #3f3ea8; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.save_changes_btn.clicked.connect(self._save_project_changes)
        actions_layout.addWidget(self.save_changes_btn)
        
        # 导出项目按钮（导出为采集端可导入的数据包）
        self.export_project_btn = QPushButton("📦 导出采集端数据包")
        self.export_project_btn.setEnabled(False)
        self.export_project_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #AF52DE;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #8a3eb0; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.export_project_btn.clicked.connect(self._export_for_capture)
        actions_layout.addWidget(self.export_project_btn)
        
        right_layout.addWidget(actions_group)
        
        # 服务器信息
        self.server_info_group = QGroupBox("服务器信息")
        server_info_layout = QVBoxLayout(self.server_info_group)
        
        # 本地地址（可点击、可复制）
        local_layout = QHBoxLayout()
        local_layout.addWidget(QLabel("本地地址:"))
        self.local_url_edit = QLineEdit("未启动")
        self.local_url_edit.setReadOnly(True)
        self.local_url_edit.setStyleSheet("""
            QLineEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                color: #0a84ff;
            }
        """)
        local_layout.addWidget(self.local_url_edit)
        
        self.local_copy_btn = QPushButton("📋 复制")
        self.local_copy_btn.setFixedWidth(80)
        self.local_copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #30D158;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #248a3d; }
        """)
        self.local_copy_btn.clicked.connect(self._copy_local_url)
        local_layout.addWidget(self.local_copy_btn)
        
        self.local_open_btn = QPushButton("🔗 打开")
        self.local_open_btn.setFixedWidth(80)
        self.local_open_btn.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #0866c6; }
        """)
        self.local_open_btn.clicked.connect(self._open_local_url)
        local_layout.addWidget(self.local_open_btn)
        server_info_layout.addLayout(local_layout)
        
        # 局域网地址（可点击、可复制）
        lan_layout = QHBoxLayout()
        lan_layout.addWidget(QLabel("局域网地址:"))
        self.lan_url_edit = QLineEdit("未启动")
        self.lan_url_edit.setReadOnly(True)
        self.lan_url_edit.setStyleSheet("""
            QLineEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
                color: #ff9500;
            }
        """)
        lan_layout.addWidget(self.lan_url_edit)
        
        self.lan_copy_btn = QPushButton("📋 复制")
        self.lan_copy_btn.setFixedWidth(80)
        self.lan_copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #30D158;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #248a3d; }
        """)
        self.lan_copy_btn.clicked.connect(self._copy_lan_url)
        lan_layout.addWidget(self.lan_copy_btn)
        
        self.lan_open_btn = QPushButton("🔗 打开")
        self.lan_open_btn.setFixedWidth(80)
        self.lan_open_btn.setStyleSheet("""
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #0866c6; }
        """)
        self.lan_open_btn.clicked.connect(self._open_lan_url)
        lan_layout.addWidget(self.lan_open_btn)
        server_info_layout.addLayout(lan_layout)
        
        # 二维码显示
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(200)
        server_info_layout.addWidget(self.qr_label)
        
        self.server_info_group.setVisible(False)
        right_layout.addWidget(self.server_info_group)
        
        # 点位信息
        self.marker_info_group = QGroupBox("点位信息")
        marker_info_layout = QGridLayout(self.marker_info_group)
        
        marker_info_layout.addWidget(QLabel("点位ID:"), 0, 0)
        self.marker_id_label = QLabel("-")
        marker_info_layout.addWidget(self.marker_id_label, 0, 1)
        
        marker_info_layout.addWidget(QLabel("状态:"), 1, 0)
        self.marker_status_label = QLabel("-")
        marker_info_layout.addWidget(self.marker_status_label, 1, 1)
        
        marker_info_layout.addWidget(QLabel("相机文件名:"), 2, 0)
        self.marker_filename_label = QLabel("-")
        marker_info_layout.addWidget(self.marker_filename_label, 2, 1)
        
        marker_info_layout.addWidget(QLabel("自定义名称:"), 3, 0)
        self.marker_custom_name = QLineEdit()
        self.marker_custom_name.editingFinished.connect(self._update_marker_name)
        marker_info_layout.addWidget(self.marker_custom_name, 3, 1)
        
        marker_info_layout.addWidget(QLabel("坐标:"), 4, 0)
        self.marker_coord_label = QLabel("-")
        marker_info_layout.addWidget(self.marker_coord_label, 4, 1)
        
        self.marker_info_group.setEnabled(False)
        right_layout.addWidget(self.marker_info_group)
        
        # 已关联照片列表
        self.linked_photos_group = QGroupBox("已关联照片")
        linked_photos_layout = QVBoxLayout(self.linked_photos_group)
        
        self.linked_photos_list = QListWidget()
        self.linked_photos_list.setMaximumHeight(200)
        self.linked_photos_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #f9f9f9;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #007AFF;
                color: white;
            }
        """)
        self.linked_photos_list.itemClicked.connect(self._on_linked_photo_clicked)
        linked_photos_layout.addWidget(self.linked_photos_list)
        
        right_layout.addWidget(self.linked_photos_group)
        
        # 最近项目列表
        self.history_group = QGroupBox("最近项目")
        history_layout = QVBoxLayout(self.history_group)
        
        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(150)
        self.history_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background-color: #f9f9f9;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #eee;
            }
            QListWidget::item:selected {
                background-color: #007AFF;
                color: white;
            }
        """)
        self.history_list.itemClicked.connect(self._on_history_item_clicked)
        history_layout.addWidget(self.history_list)
        
        # 清除历史按钮
        clear_history_btn = QPushButton("清除历史")
        clear_history_btn.setStyleSheet("""
            QPushButton {
                padding: 6px;
                font-size: 12px;
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #B32418; }
        """)
        clear_history_btn.clicked.connect(self._clear_history)
        history_layout.addWidget(clear_history_btn)
        
        right_layout.addWidget(self.history_group)
        
        # 加载历史记录
        self._refresh_history_list()
        
        right_layout.addStretch()
        
        splitter.addWidget(right_panel)
        splitter.setSizes([900, 500])
    
    def _get_history_file(self) -> str:
        """获取历史记录文件路径"""
        history_dir = os.path.join(os.path.expanduser('~'), '.panorama_manager')
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, 'history.json')
    
    def _load_history(self) -> List[dict]:
        """加载历史记录"""
        history_file = self._get_history_file()
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[警告] 加载历史记录失败: {e}")
        return []
    
    def _save_history(self, history: List[dict]):
        """保存历史记录"""
        history_file = self._get_history_file()
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[警告] 保存历史记录失败: {e}")
    
    def _add_to_history(self, project_dir: str, project_name: str):
        """添加项目到历史记录"""
        history = self._load_history()
        
        # 移除已存在的相同项目
        history = [h for h in history if h.get('project_dir') != project_dir]
        
        # 添加到开头
        history.insert(0, {
            'project_dir': project_dir,
            'project_name': project_name,
            'last_opened': datetime.now().isoformat()
        })
        
        # 最多保留 20 条
        history = history[:20]
        
        self._save_history(history)
        self._refresh_history_list()
    
    def _refresh_history_list(self):
        """刷新历史列表显示"""
        self.history_list.clear()
        history = self._load_history()
        
        for item_data in history:
            project_dir = item_data.get('project_dir', '')
            project_name = item_data.get('project_name', '未命名项目')
            display_text = f"{project_name}\n  {project_dir}"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, project_dir)
            # 如果项目文件夹不存在，显示为灰色
            if not os.path.exists(project_dir):
                item.setForeground(QColor('#999999'))
            self.history_list.addItem(item)
    
    def _on_history_item_clicked(self, item: QListWidgetItem):
        """点击历史项目"""
        project_dir = item.data(Qt.ItemDataRole.UserRole)
        if not project_dir or not os.path.exists(project_dir):
            QMessageBox.warning(self, "提示", "该项目文件夹已不存在")
            return
        
        project_json_path = os.path.join(project_dir, 'project.json')
        if not os.path.exists(project_json_path):
            QMessageBox.critical(self, "错误", "该项目中没有 project.json 文件")
            return
        
        self.project_dir = project_dir
        self._load_project(project_json_path)
        self._add_to_history(self.project_dir, self.project_data.projectName)
    
    def _clear_history(self):
        """清除历史记录"""
        reply = QMessageBox.question(
            self, "确认", "确定要清除所有历史记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._save_history([])
            self._refresh_history_list()
    
    def _init_menu(self):
        """初始化菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        
        import_folder_action = QAction("从文件夹导入(&F)...", self)
        import_folder_action.setShortcut("Ctrl+I")
        import_folder_action.triggered.connect(self.import_from_folder)
        file_menu.addAction(import_folder_action)
        
        import_action = QAction("导入项目ZIP(&I)...", self)
        import_action.setShortcut("Ctrl+O")
        import_action.triggered.connect(self.import_project)
        file_menu.addAction(import_action)
        
        open_action = QAction("打开项目文件夹(&O)...", self)
        open_action.setShortcut("Ctrl+Shift+O")
        open_action.triggered.connect(self.open_project)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")
        
        calibrate_action = QAction("时间校准(&C)...", self)
        calibrate_action.setShortcut("Ctrl+T")
        calibrate_action.triggered.connect(lambda: self._show_calibration_dialog(None))
        tools_menu.addAction(calibrate_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")
        
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def import_project(self):
        """导入 ZIP 项目 - 自动创建同名文件夹"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择项目 ZIP 文件", "", "ZIP 文件 (*.zip)"
        )
        if not file_path:
            return
        
        try:
            # 获取 ZIP 文件所在目录和文件名（不含扩展名）
            zip_dir = os.path.dirname(file_path)
            zip_name = os.path.splitext(os.path.basename(file_path))[0]
            
            # 自动创建同名文件夹
            extract_dir = os.path.join(zip_dir, zip_name)
            
            # 如果文件夹已存在，添加数字后缀
            counter = 1
            original_extract_dir = extract_dir
            while os.path.exists(extract_dir):
                extract_dir = f"{original_extract_dir}_{counter}"
                counter += 1
            
            # 创建文件夹
            os.makedirs(extract_dir, exist_ok=True)
            
            # 解压
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # 查找 project.json
            project_json_path = None
            for root, dirs, files in os.walk(extract_dir):
                if 'project.json' in files:
                    project_json_path = os.path.join(root, 'project.json')
                    self.project_dir = root
                    break
            
            if not project_json_path:
                QMessageBox.critical(self, "错误", "未找到 project.json 文件")
                return
            
            # 加载项目
            self._load_project(project_json_path)
            
            # 添加到历史记录
            if self.project_data:
                self._add_to_history(self.project_dir, self.project_data.projectName)
            
            # 显示成功提示
            QMessageBox.information(
                self, 
                "导入成功", 
                f"项目已导入并自动选择:\n{extract_dir}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {str(e)}")
    
    def import_from_folder(self):
        """从文件夹导入项目 - 自动识别ZIP和照片文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择包含项目数据包和照片的文件夹"
        )
        if not dir_path:
            return
        
        try:
            # 扫描文件夹内容
            zip_files = []
            photo_dirs = []
            
            for item in os.listdir(dir_path):
                item_path = os.path.join(dir_path, item)
                if os.path.isfile(item_path) and item.lower().endswith('.zip'):
                    zip_files.append(item_path)
                elif os.path.isdir(item_path):
                    # 检测是否为照片文件夹（包含大量JPG）
                    jpg_count = 0
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            if f.lower().endswith(('.jpg', '.jpeg')):
                                jpg_count += 1
                        if jpg_count > 5:
                            break
                    if jpg_count > 5:
                        photo_dirs.append((item_path, jpg_count))
            
            if not zip_files:
                QMessageBox.warning(self, "提示", "所选文件夹中没有找到 ZIP 项目数据包")
                return
            
            # 自动选择照片文件夹（按照片数量最多的）
            photo_dir = None
            if len(photo_dirs) == 1:
                photo_dir = photo_dirs[0][0]
            elif len(photo_dirs) > 1:
                photo_dirs.sort(key=lambda x: x[1], reverse=True)
                photo_dir = photo_dirs[0][0]
            
            if not photo_dir:
                reply = QMessageBox.question(
                    self, "照片文件夹",
                    "未自动识别到照片文件夹，是否手动选择？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    photo_dir = QFileDialog.getExistingDirectory(
                        self, "选择照片文件夹", dir_path
                    )
            
            # 处理 ZIP 文件（目前只处理第一个）
            for zip_path in zip_files:
                zip_name = os.path.splitext(os.path.basename(zip_path))[0]
                extract_dir = os.path.join(dir_path, zip_name)
                
                # 如果文件夹已存在，直接使用；否则解压
                if not os.path.exists(extract_dir):
                    os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                
                # 查找 project.json
                project_json_path = None
                for root, dirs, files in os.walk(extract_dir):
                    if 'project.json' in files:
                        project_json_path = os.path.join(root, 'project.json')
                        self.project_dir = root
                        break
                
                if not project_json_path:
                    QMessageBox.warning(self, "提示", f"ZIP {os.path.basename(zip_path)} 中未找到 project.json")
                    continue
                
                # 加载项目
                self._load_project(project_json_path)
                
                # 设置照片基目录并保存
                if photo_dir:
                    self.project_data.photoBaseDir = photo_dir
                    self._save_project()
                    # 自动导入照片（关联，不复制）
                    self._auto_import_photos(photo_dir)
                else:
                    self.project_data.photoBaseDir = ""
                    self._save_project()
                    self._add_to_history(self.project_dir, self.project_data.projectName)
                
                break  # 只处理第一个 ZIP
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"从文件夹导入失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _auto_import_photos(self, photo_dir: str):
        """自动导入照片（不弹对话框，直接关联）"""
        if not self.project_dir or not self.project_data:
            return
        
        # 收集照片文件
        photo_files = []
        for root, dirs, files in os.walk(photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg')):
                    photo_files.append(os.path.join(root, f))
        
        if not photo_files:
            QMessageBox.warning(self, "提示", "照片文件夹中没有找到照片")
            self._add_to_history(self.project_dir, self.project_data.projectName)
            return
        
        self._pending_photo_dir = photo_dir
        self._pending_photo_files = photo_files
        
        # 显示提示
        QMessageBox.information(
            self, "自动导入",
            f"找到 {len(photo_files)} 张照片，将自动进行时间校准和关联。"
        )
        
        # 启动自动校准和导入
        self._auto_calibrate_and_import(photo_files)
    
    def open_project(self):
        """打开项目文件夹"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择项目文件夹"
        )
        if not dir_path:
            return
        
        project_json_path = os.path.join(dir_path, 'project.json')
        if not os.path.exists(project_json_path):
            QMessageBox.critical(self, "错误", "所选文件夹中没有 project.json 文件")
            return
        
        self.project_dir = dir_path
        self._load_project(project_json_path)
        self._add_to_history(self.project_dir, self.project_data.projectName)
    
    def _load_project(self, project_json_path: str):
        """加载项目数据"""
        try:
            with open(project_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查版本
            schema_version = data.get('schemaVersion', '1.0')
            if schema_version.startswith('4.'):
                # 4.0 版本完全支持
                pass
            elif schema_version != '1.0':
                QMessageBox.warning(self, "警告", 
                    f"项目文件版本 {schema_version} 可能不兼容当前软件")
            
            self.project_data = Project.from_dict(data)
            
            # 计算总点位数量（所有楼层）
            total_markers = 0
            for floor_data in self.project_data.floors:
                total_markers += len(floor_data.get('markers', []))
            
            # 更新界面
            self.project_name_label.setText(self.project_data.projectName)
            self.created_time_label.setText(self.project_data.createdAt)
            self.marker_count_label.setText(f"{len(self.project_data.floors)} 层 / {total_markers} 个点位")
            
            # 更新校准值显示
            offset = self.project_data.timeOffset
            if offset == 0:
                calib_text = "未校准"
            elif offset > 0:
                calib_text = f"+{offset}秒 (相机快)"
            else:
                calib_text = f"{offset}秒 (相机慢)"
            self.calibration_label.setText(calib_text)
            
            # 创建楼层切换标签
            self._create_floor_tabs()
            
            # 刷新已关联照片列表
            self._refresh_linked_photos_list()
            
            # 加载第一个有平面图的楼层
            current_floor = None
            for floor_data in self.project_data.floors:
                if floor_data.get('hasPlan'):
                    current_floor = floor_data
                    break
            
            # 如果没有楼层有平面图，尝试加载第一个楼层
            if not current_floor and self.project_data.floors:
                current_floor = self.project_data.floors[0]
            
            if current_floor:
                self._load_floor(current_floor['id'])
                
                # 设置对应楼层标签为选中状态
                for i in range(self.floor_tabs_layout.count()):
                    widget = self.floor_tabs_layout.itemAt(i).widget()
                    if isinstance(widget, QPushButton):
                        if widget.property('floor_id') == current_floor['id']:
                            widget.setChecked(True)
                            break
            
            # 启用按钮
            self.import_photos_btn.setEnabled(True)
            self.generate_viewer_btn.setEnabled(True)
            self.open_web_btn.setEnabled(True)
            self.save_changes_btn.setEnabled(True)
            self.export_project_btn.setEnabled(True)
            
            QMessageBox.information(self, "成功", 
                f"项目 '{self.project_data.projectName}' 加载成功\n"
                f"楼层数: {len(self.project_data.floors)}\n"
                f"总点位: {total_markers}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载项目失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def import_photos(self):
        """导入影像 - 全自动时间校准"""
        if not self.project_dir or not self.project_data:
            return
        
        photo_dir = QFileDialog.getExistingDirectory(
            self, "选择照片文件夹（SD 卡目录）"
        )
        if not photo_dir:
            return
        
        # 收集照片文件
        photo_files = []
        for root, dirs, files in os.walk(photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg')):
                    photo_files.append(os.path.join(root, f))
        
        if not photo_files:
            QMessageBox.warning(self, "提示", "所选文件夹中没有找到照片")
            return
        
        # 保存照片目录用于后续导入
        self._pending_photo_dir = photo_dir
        self._pending_photo_files = photo_files
        
        # 显示自动校准提示
        QMessageBox.information(
            self, "自动时间校准",
            f"找到 {len(photo_files)} 张照片。\n\n"
            "系统将自动分析照片和标记点的时间关系，\n"
            "计算最佳校准值并直接开始导入。"
        )
        
        # 启动自动校准线程
        print(f"[调试] 启动自动校准线程...")
        self._auto_calibrate_and_import(photo_files)
    
    def _auto_calibrate_and_import(self, photo_files: List[str]):
        """自动计算校准值并导入 - 全自动流程"""
        # 收集所有标记点
        all_markers = []
        for floor in self.project_data.floors:
            all_markers.extend(floor.get('markers', []))
        
        # 创建并启动自动校准线程
        self.calibration_thread = AutoCalibrationThread(all_markers, photo_files)
        self.calibration_thread.calibration_complete.connect(
            lambda offset, matched, total: self._on_auto_calibration_complete(offset, matched, total)
        )
        self.calibration_thread.start()
    
    def _on_auto_calibration_complete(self, suggested_offset: int, matched_count: int, total_count: int):
        """自动校准完成回调 - 自动应用并导入"""
        print(f"[调试] 自动校准完成: 建议偏移={suggested_offset}秒, 匹配={matched_count}/{total_count}")
        
        photo_dir = getattr(self, '_pending_photo_dir', None)
        
        # 如果有建议的校准值且与当前不同，自动应用
        if suggested_offset != 0 and suggested_offset != self.project_data.timeOffset:
            hours = abs(suggested_offset) // 3600
            minutes = (abs(suggested_offset) % 3600) // 60
            
            time_diff_str = ""
            if hours > 0:
                time_diff_str += f"{hours}小时"
            if minutes > 0:
                time_diff_str += f"{minutes}分钟"
            
            # 自动应用校准值
            self.project_data.timeOffset = suggested_offset
            self._save_project()
            
            # 更新显示
            if suggested_offset > 0:
                calib_text = f"+{suggested_offset}秒 (相机快)"
            else:
                calib_text = f"{suggested_offset}秒 (相机慢)"
            self.calibration_label.setText(calib_text)
            
            # 告知用户（信息弹窗，无需确认）
            QMessageBox.information(
                self, "时间校准已自动完成",
                f"系统自动分析完成！\n\n"
                f"检测到相机时间与手机时间相差约 {time_diff_str}。\n"
                f"已自动设置校准值为: {suggested_offset} 秒\n\n"
                f"【建议】\n"
                f"为避免时区问题，建议调整相机时间设置，\n"
                f"使相机时间与手机时间保持一致。\n\n"
                f"即将开始导入照片..."
            )
        else:
            # 无需校准或校准值为0
            if suggested_offset == 0 and matched_count == 0:
                QMessageBox.information(
                    self, "自动校准结果",
                    "无法从照片中提取有效时间信息进行校准。\n"
                    "将使用当前校准值继续导入。\n\n"
                    "【提示】\n"
                    "请确保照片包含EXIF时间信息。"
                )
            else:
                QMessageBox.information(
                    self, "自动校准结果",
                    f"时间校准分析完成！\n\n"
                    f"当前校准值合适，无需调整。\n"
                    f"匹配情况: {matched_count}/{total_count}\n\n"
                    f"即将开始导入照片..."
                )
        
        # 自动开始导入
        if photo_dir:
            self._start_import(photo_dir, self.project_data.timeOffset)
    
    def _show_calibration_dialog(self, photo_dir: Optional[str] = None, suggested_offset: int = None):
        """显示手动校准对话框"""
        try:
            # 如果有建议的校准值，直接应用并提示用户
            if suggested_offset is not None:
                hours = abs(suggested_offset) // 3600
                minutes = (abs(suggested_offset) % 3600) // 60
                time_diff_str = f"{hours}小时" if hours > 0 else f"{minutes}分钟"
                if hours > 0 and minutes > 0:
                    time_diff_str = f"{hours}小时{minutes}分钟"
                
                # 自动应用建议的校准值
                self.project_data.timeOffset = suggested_offset
                self._save_project()
                self.calibration_label.setText(f"{suggested_offset}秒 (相机慢)")
                
                # 显示已应用的提示
                QMessageBox.information(
                    self, "时间校准已自动应用",
                    f"检测到相机时间与手机时间相差约 {time_diff_str}。\n\n"
                    f"系统已自动设置校准值为: {suggested_offset} 秒\n\n"
                    "【建议】\n"
                    "为避免时区问题，建议调整相机时间设置，\n"
                    "使相机时间与手机时间保持一致。"
                )
                
                if photo_dir:
                    self._start_import(photo_dir, suggested_offset)
                return
            
            dialog = TimeCalibrationDialog(self.project_data.timeOffset, self)
            result = dialog.exec()
            print(f"[调试] 校准对话框返回: {result}")
            
            # PyQt6 中 QDialog.exec() 返回整数 (1=Accepted, 0=Rejected)
            if result == 1:  # QDialog.DialogCode.Accepted
                new_offset = dialog.calibrated_offset
                print(f"[调试] 用户设置校准值: {new_offset} 秒")
                if new_offset != self.project_data.timeOffset:
                    self.project_data.timeOffset = new_offset
                    self._save_project()
                    # 更新校准标签显示
                    if new_offset == 0:
                        calib_text = "未校准"
                    elif new_offset > 0:
                        calib_text = f"+{new_offset}秒 (相机快)"
                    else:
                        calib_text = f"{new_offset}秒 (相机慢)"
                    self.calibration_label.setText(calib_text)
                    QMessageBox.information(self, "校准已保存", f"时间校准值已更新为 {new_offset} 秒")
            else:
                print(f"[调试] 用户取消校准")
            
            # 如果有照片目录，继续导入
            if photo_dir:
                print(f"[调试] 校准后导入，偏移值: {self.project_data.timeOffset}")
                self._start_import(photo_dir, self.project_data.timeOffset)
        except Exception as e:
            print(f"[调试] 校准对话框出错: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"校准对话框出错: {e}")
    
    def _start_import(self, photo_dir: str, time_offset: int):
        """开始导入照片"""
        # 创建进度对话框
        self.progress_dialog = QProgressDialog("正在扫描照片...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("导入照片")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()
        
        # 启动导入线程 - 使用更宽松的阈值(300秒=5分钟)
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '') or photo_dir
        self.import_thread = PhotoImportThread(
            self.project_dir, photo_dir, self.project_data.floors, 
            time_offset, use_exif=True, threshold=300,
            photo_base_dir=photo_base_dir
        )
        self.import_thread.progress_update.connect(self._on_import_progress)
        self.import_thread.import_complete.connect(self._on_import_complete)
        self.import_thread.start()
    
    def _on_import_progress(self, progress: int, message: str):
        """导入进度更新"""
        self.progress_dialog.setValue(progress)
        self.progress_dialog.setLabelText(message)
    
    def _on_import_complete(self, results: dict):
        """导入完成"""
        self.progress_dialog.close()
        
        # 保存更新后的项目数据（包含新关联的照片路径）
        self._save_project()
        
        # 添加到历史记录
        if self.project_data:
            self._add_to_history(self.project_dir, self.project_data.projectName)
        
        total = results['exact'] + results['similar'] + results['missing']
        match_rate = (results['exact'] + results['similar']) / total * 100 if total > 0 else 0
        
        msg = f"""导入完成！

✅ EXIF精确匹配: {results['exact']} 个
⚠️ 文件名相似匹配: {results['similar']} 个
❌ 未找到: {results['missing']} 个
📊 匹配率: {match_rate:.1f}%

当前校准值: {self.project_data.timeOffset} 秒
"""
        
        # 如果匹配率低，自动应用校准并提示
        if match_rate < 50 and results['missing'] > 0:
            msg += "\n\n匹配率较低，正在自动调整时间校准..."
            
            # 检查是否检测到大时间差
            suggested_offset = None
            if hasattr(self.import_thread, '_suggested_offset'):
                suggested_offset = self.import_thread._suggested_offset
                hours = abs(suggested_offset) // 3600
                minutes = (abs(suggested_offset) % 3600) // 60
                time_diff_str = f"{hours}小时" if hours > 0 else f"{minutes}分钟"
                if hours > 0 and minutes > 0:
                    time_diff_str = f"{hours}小时{minutes}分钟"
                
                # 自动应用校准值
                self.project_data.timeOffset = suggested_offset
                self._save_project()
                self.calibration_label.setText(f"{suggested_offset}秒 (相机慢)")
                
                msg += f"\n\n检测到相机时间与手机时间相差约 {time_diff_str}。"
                msg += f"\n系统已自动设置校准值为: {suggested_offset} 秒"
                msg += "\n\n【建议】调整相机时间设置，使相机与手机时间保持一致。"
            
            QMessageBox.information(self, "导入结果", msg)
        else:
            QMessageBox.information(self, "导入结果", msg)
        
        # 刷新显示
        self._refresh_markers()
        
        # 自动生成本地网页并打开
        self._auto_generate_and_open_viewer()
    
    def _refresh_markers(self):
        """刷新标记点显示"""
        # 重新加载 project.json
        project_json_path = os.path.join(self.project_dir, 'project.json')
        with open(project_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.project_data = Project.from_dict(data)
        
        # 重新加载当前楼层
        if self.current_floor_id:
            self._load_floor(self.current_floor_id)
        
        # 刷新已关联照片列表
        self._refresh_linked_photos_list()
    
    def _refresh_linked_photos_list(self):
        """刷新已关联照片列表 - 按楼层顺序显示"""
        self.linked_photos_list.clear()
        
        if not self.project_data or not self.project_data.floors:
            return
        
        # 按 order 排序楼层（从高到低）
        sorted_floors = sorted(self.project_data.floors, key=lambda f: f.get('order', 0), reverse=True)
        
        for floor_data in sorted_floors:
            floor_name = floor_data.get('name', '未命名楼层')
            floor_id = floor_data.get('id', '')
            
            for marker in floor_data.get('markers', []):
                if marker.get('status') == 'linked' and marker.get('panoramaPath'):
                    photo_name = marker.get('cameraFileName', os.path.basename(marker.get('panoramaPath', '')))
                    custom_name = marker.get('customName', '')
                    display_text = f"[{floor_name}] {photo_name}"
                    if custom_name:
                        display_text += f" - {custom_name}"
                    
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, {
                        'marker_id': marker.get('id'),
                        'floor_id': floor_id,
                        'photo_path': marker.get('panoramaPath')
                    })
                    self.linked_photos_list.addItem(item)
    
    def _on_linked_photo_clicked(self, item):
        """点击已关联照片列表项"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            marker_id = data.get('marker_id')
            floor_id = data.get('floor_id')
            
            # 切换到对应楼层
            if floor_id and floor_id != self.current_floor_id:
                self._load_floor(floor_id)
                self._update_floor_tab_selection(floor_id)
            
            # 选中对应标记点
            if marker_id:
                self._on_marker_selected(marker_id)
    
    def _auto_generate_and_open_viewer(self):
        """自动生成本地网页并打开 - 不复制照片"""
        if not self.project_dir or not self.project_data:
            return
        
        # 固定生成到项目目录下的 viewer 文件夹
        viewer_dir = os.path.join(self.project_dir, 'viewer')
        
        try:
            # 创建目录结构
            os.makedirs(viewer_dir, exist_ok=True)
            
            # 处理外部照片目录（不复制照片）
            photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
            external_photos_link = os.path.join(viewer_dir, 'external_photos')
            
            if photo_base_dir and os.path.exists(photo_base_dir):
                # 移除旧的链接
                if os.path.exists(external_photos_link):
                    if os.path.islink(external_photos_link) or os.path.isdir(external_photos_link):
                        os.remove(external_photos_link) if os.path.islink(external_photos_link) else shutil.rmtree(external_photos_link)
                # 创建 junction (Windows) 或符号链接
                try:
                    if sys.platform == 'win32':
                        import subprocess
                        subprocess.run(['cmd', '/c', 'mklink', '/J', external_photos_link, photo_base_dir], check=True, capture_output=True)
                    else:
                        os.symlink(photo_base_dir, external_photos_link)
                except Exception as e:
                    print(f"[警告] 创建照片链接失败: {e}，将尝试复制")
                    shutil.copytree(photo_base_dir, external_photos_link, dirs_exist_ok=True)
            
            # 复制项目数据，调整 panoramaPath
            project_copy = self.project_data.to_dict()
            if photo_base_dir and os.path.exists(photo_base_dir):
                for floor_data in project_copy.get('floors', []):
                    for marker_data in floor_data.get('markers', []):
                        if marker_data.get('panoramaPath') and not os.path.isabs(marker_data['panoramaPath']):
                            marker_data['panoramaPath'] = 'external_photos/' + marker_data['panoramaPath']
                        elif marker_data.get('originalPhotoPath'):
                            orig = marker_data['originalPhotoPath']
                            if os.path.commonpath([os.path.abspath(orig), os.path.abspath(photo_base_dir)]) == os.path.abspath(photo_base_dir):
                                rel = os.path.relpath(orig, photo_base_dir).replace('\\', '/')
                                marker_data['panoramaPath'] = 'external_photos/' + rel
            
            with open(os.path.join(viewer_dir, 'project.json'), 'w', encoding='utf-8') as f:
                json.dump(project_copy, f, ensure_ascii=False, indent=2)
            
            # 复制各楼层平面图
            for floor_data in self.project_data.floors:
                floor_id = floor_data['id']
                floorplan_src = os.path.join(self.project_dir, f'floorplan_{floor_id}.jpg')
                
                # 尝试旧版本兼容
                if not os.path.exists(floorplan_src) and self.project_data.floorplan:
                    floorplan_src = os.path.join(self.project_dir, self.project_data.floorplan)
                
                if os.path.exists(floorplan_src):
                    floorplan_dst = os.path.join(viewer_dir, f'floorplan_{floor_id}.jpg')
                    shutil.copy2(floorplan_src, floorplan_dst)
            
            # 生成 HTML
            self._generate_viewer_html(viewer_dir)
            
            # 启动 HTTP 服务器
            self._auto_start_server(viewer_dir)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"自动生成网页失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _auto_start_server(self, viewer_dir: str):
        """自动启动 HTTP 服务器并打开浏览器"""
        # 先停止已有服务器
        if self.server_thread and self.server_thread.is_running:
            self.stop_http_server()
        
        # 尝试不同端口（跳过 8080，因为经常被占用）
        for port in [8888, 9000, 9999, 0]:
            try:
                self.server_thread = HttpServerThread(viewer_dir, port)
                self.server_thread.server_started.connect(self._on_auto_server_started)
                self.server_thread.error_occurred.connect(self._on_server_error)
                self.server_thread.start()
                # 等待一下看是否启动成功
                import time
                time.sleep(0.5)
                if self.server_thread.is_running:
                    break
            except Exception as e:
                print(f"[调试] 端口 {port} 启动失败: {e}")
                continue
        else:
            QMessageBox.critical(self, "错误", "无法启动服务器，所有端口都被占用")
    
    def _on_auto_server_started(self, ip: str, port: int):
        """自动启动服务器成功回调"""
        self.current_local_url = f"http://localhost:{port}"
        self.current_lan_url = f"http://{ip}:{port}"
        
        self.local_url_edit.setText(self.current_local_url)
        self.lan_url_edit.setText(self.current_lan_url)
        
        # 生成二维码
        try:
            import io
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(self.current_lan_url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            qr_pixmap = QPixmap()
            qr_pixmap.loadFromData(buffer.getvalue())
            self.qr_label.setPixmap(qr_pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio))
        except Exception as e:
            print(f"生成二维码失败: {e}")
        
        self.server_info_group.setVisible(True)
        self.stop_server_btn.setEnabled(True)
        self.open_web_btn.setEnabled(False)
        
        # 自动打开浏览器
        webbrowser.open(self.current_local_url)
        
        # 显示成功提示
        linked_count = sum(
            1 for floor in self.project_data.floors
            for marker in floor.get('markers', [])
            if marker.get('status') == 'linked' and marker.get('panoramaPath')
        )
        QMessageBox.information(
            self, "导入完成",
            f"照片导入成功！\n\n"
            f"已关联影像: {linked_count} 个\n\n"
            f"本地网页已生成并自动打开。\n"
            f"访问地址: {self.current_local_url}"
        )
    
    def _on_marker_selected(self, marker_id: str):
        """标记点选中"""
        if not self.project_data:
            return
        
        # 在所有楼层中查找标记点
        found_marker = None
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    found_marker = marker_data
                    self.current_floor_id = floor_data['id']
                    break
            if found_marker:
                break
        
        if found_marker:
            self.current_marker = Marker.from_dict(found_marker)
            
            self.marker_info_group.setEnabled(True)
            self.marker_id_label.setText(self.current_marker.id)
            self.marker_status_label.setText(self.current_marker.status)
            self.marker_filename_label.setText(self.current_marker.cameraFileName or '-')
            self.marker_custom_name.setText(self.current_marker.customName)
            self.marker_coord_label.setText(f"({self.current_marker.x:.4f}, {self.current_marker.y:.4f})")
    
    def _create_floor_tabs(self):
        """创建楼层切换标签"""
        # 清除旧标签
        while self.floor_tabs_layout.count():
            item = self.floor_tabs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not self.project_data or not self.project_data.floors:
            return
        
        # 按 order 排序（从高到低，使高楼层显示在左侧）
        sorted_floors = sorted(self.project_data.floors, key=lambda f: f.get('order', 0), reverse=True)
        
        for idx, floor_data in enumerate(sorted_floors):
            btn = QPushButton(floor_data['name'])
            btn.setCheckable(True)
            btn.setProperty('floor_id', floor_data['id'])
            btn.clicked.connect(lambda checked, fid=floor_data['id']: self._on_floor_tab_clicked(fid))
            
            # 设置样式
            btn.setStyleSheet("""
                QPushButton {
                    padding: 8px 16px;
                    background-color: #3A3A3C;
                    color: #999;
                    border: none;
                    border-radius: 16px;
                    font-size: 13px;
                }
                QPushButton:checked {
                    background-color: #0A84FF;
                    color: white;
                }
                QPushButton:hover {
                    background-color: #48484A;
                }
            """)
            
            self.floor_tabs_layout.addWidget(btn)
        
        self.floor_tabs_layout.addStretch()
    
    def _on_floor_tab_clicked(self, floor_id: str):
        """楼层标签点击事件"""
        self._update_floor_tab_selection(floor_id)
        self._load_floor(floor_id)
    
    def _update_floor_tab_selection(self, floor_id: str):
        """更新楼层标签选中状态"""
        for i in range(self.floor_tabs_layout.count()):
            widget = self.floor_tabs_layout.itemAt(i).widget()
            if isinstance(widget, QPushButton):
                is_current = widget.property('floor_id') == floor_id
                widget.setChecked(is_current)
    
    def _load_floor(self, floor_id: str):
        """加载指定楼层"""
        if not self.project_data:
            return
        
        # 查找楼层数据
        floor_data = None
        for f in self.project_data.floors:
            if f['id'] == floor_id:
                floor_data = f
                break
        
        if not floor_data:
            return
        
        self.current_floor_id = floor_id
        
        # 查找楼层平面图文件
        floorplan_filename = f"floorplan_{floor_id}.jpg"
        floorplan_path = os.path.join(self.project_dir, floorplan_filename)
        
        # 旧版本兼容
        if not os.path.exists(floorplan_path) and self.project_data.floorplan:
            floorplan_path = os.path.join(self.project_dir, self.project_data.floorplan)
        
        # 清除旧标记
        self.canvas.clear_markers()
        
        if os.path.exists(floorplan_path):
            self.canvas.load_floorplan(floorplan_path)
            
            # 绘制该楼层的标记点
            for marker_data in floor_data.get('markers', []):
                marker = Marker.from_dict(marker_data)
                label = marker.customName or marker.id
                self.canvas.add_marker(
                    marker.id, marker.x, marker.y, marker.status, label
                )
        else:
            QMessageBox.warning(self, "提示", f"楼层 '{floor_data['name']}' 的平面图文件不存在")
    
    def _update_marker_name(self):
        """更新点位名称"""
        if hasattr(self, 'current_marker'):
            new_name = self.marker_custom_name.text()
            # 更新数据（在所有楼层中查找）
            for floor_data in self.project_data.floors:
                for marker_data in floor_data.get('markers', []):
                    if marker_data['id'] == self.current_marker.id:
                        marker_data['customName'] = new_name
                        break
            
            # 保存
            self._save_project()
            
            # 刷新
            self._refresh_markers()
    
    def _save_project(self):
        """保存项目"""
        if self.project_data and self.project_dir:
            self.project_data.updatedAt = datetime.now().isoformat()
            
            project_json_path = os.path.join(self.project_dir, 'project.json')
            with open(project_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.project_data.to_dict(), f, ensure_ascii=False, indent=2)
    
    def generate_web_viewer(self):
        """生成网页查看器 - 不复制照片，使用junction/符号链接"""
        if not self.project_dir or not self.project_data:
            return
        
        # 固定生成到项目目录下的 viewer 文件夹
        viewer_dir = os.path.join(self.project_dir, 'viewer')
        
        try:
            # 创建目录结构
            os.makedirs(viewer_dir, exist_ok=True)
            
            # 处理外部照片目录（不复制照片）
            photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
            external_photos_link = os.path.join(viewer_dir, 'external_photos')
            
            if photo_base_dir and os.path.exists(photo_base_dir):
                # 移除旧的链接
                if os.path.exists(external_photos_link):
                    if os.path.islink(external_photos_link) or os.path.isdir(external_photos_link):
                        os.remove(external_photos_link) if os.path.islink(external_photos_link) else shutil.rmtree(external_photos_link)
                # 创建 junction (Windows) 或符号链接
                try:
                    if sys.platform == 'win32':
                        import subprocess
                        subprocess.run(['cmd', '/c', 'mklink', '/J', external_photos_link, photo_base_dir], check=True, capture_output=True)
                    else:
                        os.symlink(photo_base_dir, external_photos_link)
                except Exception as e:
                    print(f"[警告] 创建照片链接失败: {e}，将尝试复制")
                    # 回退：复制照片
                    shutil.copytree(photo_base_dir, external_photos_link, dirs_exist_ok=True)
            
            # 复制项目数据，调整 panoramaPath
            project_copy = self.project_data.to_dict()
            if photo_base_dir and os.path.exists(photo_base_dir):
                for floor_data in project_copy.get('floors', []):
                    for marker_data in floor_data.get('markers', []):
                        if marker_data.get('panoramaPath') and not os.path.isabs(marker_data['panoramaPath']):
                            # 相对路径，加上 external_photos 前缀
                            marker_data['panoramaPath'] = 'external_photos/' + marker_data['panoramaPath']
                        elif marker_data.get('originalPhotoPath'):
                            # 有原始路径，尝试转为相对路径
                            orig = marker_data['originalPhotoPath']
                            if os.path.commonpath([os.path.abspath(orig), os.path.abspath(photo_base_dir)]) == os.path.abspath(photo_base_dir):
                                rel = os.path.relpath(orig, photo_base_dir).replace('\\', '/')
                                marker_data['panoramaPath'] = 'external_photos/' + rel
            
            with open(os.path.join(viewer_dir, 'project.json'), 'w', encoding='utf-8') as f:
                json.dump(project_copy, f, ensure_ascii=False, indent=2)
            
            # 复制各楼层平面图
            for floor_data in self.project_data.floors:
                floor_id = floor_data['id']
                floorplan_src = os.path.join(self.project_dir, f'floorplan_{floor_id}.jpg')
                
                # 尝试旧版本兼容
                if not os.path.exists(floorplan_src) and self.project_data.floorplan:
                    floorplan_src = os.path.join(self.project_dir, self.project_data.floorplan)
                
                if os.path.exists(floorplan_src):
                    floorplan_dst = os.path.join(viewer_dir, f'floorplan_{floor_id}.jpg')
                    shutil.copy2(floorplan_src, floorplan_dst)
            
            # 生成 HTML
            self._generate_viewer_html(viewer_dir)
            
            QMessageBox.information(self, "成功", 
                f"网页查看器已生成到项目目录:\n{viewer_dir}\n\n"
                f"包含 {len(self.project_data.floors)} 个楼层的数据")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成失败: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def _generate_viewer_html(self, viewer_dir: str):
        """生成查看器 HTML 文件 - 支持多楼层"""
        # 构建多楼层数据
        floors_js = []
        # 按 order 排序楼层（从高到低，与PC端保持一致）
        sorted_floors = sorted(self.project_data.floors, key=lambda f: f.get('order', 0), reverse=True)
        for floor_data in sorted_floors:
            floor_id = floor_data['id']
            floor_name = floor_data['name']
            
            # 查找平面图文件
            floorplan_path = f"floorplan_{floor_id}.jpg"
            
            # 收集该楼层已关联的标记点
            photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
            linked_markers = []
            for m in floor_data.get('markers', []):
                if m.get('status') == 'linked' and m.get('panoramaPath'):
                    marker_copy = dict(m)
                    path = marker_copy.get('panoramaPath', '')
                    orig = marker_copy.get('originalPhotoPath', '')
                    if photo_base_dir and os.path.exists(photo_base_dir):
                        if path and not os.path.isabs(path):
                            marker_copy['panoramaPath'] = 'external_photos/' + path
                        elif orig and os.path.commonpath([os.path.abspath(orig), os.path.abspath(photo_base_dir)]) == os.path.abspath(photo_base_dir):
                            rel = os.path.relpath(orig, photo_base_dir).replace('\\', '/')
                            marker_copy['panoramaPath'] = 'external_photos/' + rel
                    linked_markers.append(marker_copy)
            
            if linked_markers:
                floors_js.append({
                    'id': floor_id,
                    'name': floor_name,
                    'floorplan': floorplan_path,
                    'markers': linked_markers
                })
        
        floors_json = json.dumps(floors_js, ensure_ascii=False)
        project_name = self.project_data.projectName
        
        print(f"[调试] 生成网页 - 楼层数: {len(floors_js)}, 数据预览: {floors_json[:200]}...")
        
        html_content = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__PROJECT_NAME__ - 影像查看器</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css"/>
    <script src="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; }
        
        .container { display: flex; height: 100vh; }
        
        /* 左侧面板 - 平面图 */
        .floorplan-panel { 
            width: 35%; 
            background: #1C1C1E;
            display: flex;
            flex-direction: column;
            border-right: 1px solid #333;
        }
        
        .floor-tabs {
            display: flex;
            overflow-x: auto;
            background: #2C2C2E;
            padding: 8px;
            gap: 8px;
        }
        .floor-tabs::-webkit-scrollbar { display: none; }
        
        .floor-tab {
            padding: 8px 16px;
            background: #3A3A3C;
            color: #999;
            border: none;
            border-radius: 16px;
            cursor: pointer;
            white-space: nowrap;
            font-size: 13px;
        }
        .floor-tab.active {
            background: #0A84FF;
            color: white;
        }
        
        .floorplan-container {
            flex: 1;
            position: relative;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .floorplan-wrapper {
            position: relative;
            width: 95%;
            height: 95%;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            touch-action: none;
            cursor: grab;
        }
        
        .floorplan-wrapper:active {
            cursor: grabbing;
        }
        
        .floorplan-wrapper img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            transform-origin: 0 0;
            transition: transform 0.1s ease-out;
            user-select: none;
            -webkit-user-drag: none;
        }
        
        .floorplan-wrapper.zooming img {
            transition: none;
        }
        
        .zoom-controls {
            position: absolute;
            bottom: 20px;
            right: 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            z-index: 100;
        }
        
        .zoom-btn {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            border: none;
            background: rgba(0,0,0,0.7);
            color: white;
            font-size: 24px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            backdrop-filter: blur(10px);
            transition: background 0.2s;
        }
        
        .zoom-btn:hover {
            background: rgba(0,0,0,0.9);
        }
        
        .zoom-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .zoom-reset {
            font-size: 14px;
            width: auto;
            padding: 0 16px;
            border-radius: 22px;
        }
        
        .marker-dot {
            position: absolute;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            cursor: pointer;
            border: 3px solid white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.5);
            background: #30D158;
            transition: transform 0.2s;
        }
        .marker-dot:hover { transform: translate(-50%, -50%) scale(1.2); }
        .marker-dot.active {
            background: #FFCC00;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 204, 0, 0.7); }
            70% { box-shadow: 0 0 0 12px rgba(255, 204, 0, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 204, 0, 0); }
        }
        
        /* 右侧面板 - 影像 */
        .panorama-panel { 
            width: 65%; 
            position: relative;
            background: #000;
        }
        
        #panorama { width: 100%; height: 100%; }
        
        .info-bar {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            padding: 15px 20px;
            background: linear-gradient(to bottom, rgba(0,0,0,0.8), transparent);
            color: white;
            z-index: 50;
        }
        .info-bar h1 { font-size: 16px; font-weight: 500; margin-bottom: 4px; }
        .info-bar .floor-name { font-size: 13px; color: #0A84FF; }
        
        .nav-buttons {
            position: absolute;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 10px;
            z-index: 50;
        }
        .nav-btn {
            padding: 12px 24px;
            background: rgba(0,0,0,0.7);
            color: white;
            border: none;
            border-radius: 24px;
            cursor: pointer;
            backdrop-filter: blur(10px);
            font-size: 14px;
        }
        .nav-btn:hover { background: rgba(0,0,0,0.9); }
        
        /* 控制按钮组 */
        .control-buttons {
            position: absolute;
            top: 15px;
            right: 20px;
            display: flex;
            gap: 10px;
            z-index: 60;
        }
        
        .control-btn {
            padding: 8px 16px;
            background: rgba(0,0,0,0.7);
            color: white;
            border: none;
            border-radius: 20px;
            cursor: pointer;
            backdrop-filter: blur(10px);
            font-size: 13px;
            display: flex;
            align-items: center;
            gap: 5px;
            transition: all 0.2s;
        }
        
        .control-btn:hover { background: rgba(0,0,0,0.9); }
        .control-btn.active { background: #0A84FF; }
        .control-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        /* VR 模式样式 */
        .vr-mode .panorama-panel { width: 100% !important; height: 100% !important; }
        .vr-mode .floorplan-panel { display: none !important; }
        .vr-mode .nav-buttons { display: none; }
        .vr-mode .info-bar { display: none; }
        
        /* VR 分屏容器 */
        #vr-container {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: #000;
            z-index: 1000;
        }
        
        #vr-container.active {
            display: flex;
        }
        
        .vr-eye {
            flex: 1;
            height: 100%;
            position: relative;
            overflow: hidden;
        }
        
        .vr-eye-left { border-right: 1px solid #333; }
        
        .vr-close-btn {
            position: absolute;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 24px;
            background: rgba(255,0,0,0.8);
            color: white;
            border: none;
            border-radius: 24px;
            cursor: pointer;
            font-size: 14px;
            z-index: 1001;
        }
        
        /* 陀螺仪模式提示 */
        .gyro-hint {
            position: absolute;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s;
        }
        
        .gyro-hint.show { opacity: 1; }
        
        /* 移动端适配 */
        @media (max-width: 768px) {
            .container { flex-direction: column; }
            .floorplan-panel { 
                width: 100%;
                height: 35%;
                border-right: none;
                border-bottom: 1px solid #333;
            }
            .panorama-panel { 
                width: 100%; 
                height: 65%;
            }
            .control-buttons {
                top: auto;
                bottom: 80px;
                right: 10px;
                flex-direction: column;
            }
            .control-btn {
                padding: 10px;
                font-size: 12px;
            }
            .control-btn span { display: none; }
        }
        
        /* 品牌页脚 */
        .brand-footer {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 6px 16px;
            background: rgba(0,0,0,0.55);
            color: rgba(255,255,255,0.55);
            font-size: 11px;
            text-align: center;
            z-index: 200;
            backdrop-filter: blur(4px);
            pointer-events: auto;
        }
        .brand-footer a {
            color: #0A84FF;
            text-decoration: none;
            margin-left: 6px;
        }
        .brand-footer a:hover {
            text-decoration: underline;
        }
        @media (max-width: 768px) {
            .brand-footer { font-size: 10px; padding: 4px 12px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="floorplan-panel">
            <div class="floor-tabs" id="floorTabs"></div>
            <div class="floorplan-container" id="floorplanContainer">
                <p style="color: #666;">加载中...</p>
            </div>
        </div>
        <div class="panorama-panel">
            <div class="info-bar">
                <h1 id="current-title">请选择点位</h1>
                <div class="floor-name" id="current-floor">-</div>
            </div>
            <div id="panorama"></div>
            <div class="gyro-hint" id="gyroHint">陀螺仪模式已开启，移动手机查看</div>
            <div class="control-buttons">
                <button class="control-btn" id="gyroBtn" onclick="toggleGyro()" title="陀螺仪模式">
                    📱 <span>陀螺仪</span>
                </button>
                <button class="control-btn" id="vrBtn" onclick="toggleVR()" title="VR 模式">
                    🥽 <span>VR模式</span>
                </button>
            </div>
            <div class="nav-buttons">
                <button class="nav-btn" onclick="prevPanorama()">◀ 上一张</button>
                <button class="nav-btn" onclick="nextPanorama()">下一张 ▶</button>
            </div>
        </div>
    </div>
    
    <!-- VR 分屏容器 -->
    <div id="vr-container">
        <button class="vr-close-btn" onclick="exitVR()">退出 VR 模式</button>
        <div class="vr-eye vr-eye-left" id="vrLeft"></div>
        <div class="vr-eye vr-eye-right" id="vrRight"></div>
    </div>

    <script>
        const floors = __FLOORS_JSON__;
        let currentFloorIndex = 0;
        let currentMarkerIndex = 0;
        let viewer = null;
        
        function init() {
            console.log('init() called, floors:', floors);
            
            if (!floors || floors.length === 0) {
                document.getElementById('floorplanContainer').innerHTML = 
                    '<p style="color: #666;">暂无数据（没有已关联的影像）</p>';
                return;
            }
            
            // 创建楼层标签
            const tabsContainer = document.getElementById('floorTabs');
            floors.forEach((floor, idx) => {
                const tab = document.createElement('button');
                tab.className = 'floor-tab' + (idx === 0 ? ' active' : '');
                tab.textContent = floor.name;
                tab.onclick = () => switchFloor(idx);
                tabsContainer.appendChild(tab);
            });
            
            // 加载第一个楼层
            loadFloor(0);
        }
        
        function switchFloor(index) {
            currentFloorIndex = index;
            currentMarkerIndex = 0;
            
            // 更新标签样式
            document.querySelectorAll('.floor-tab').forEach((tab, idx) => {
                tab.classList.toggle('active', idx === index);
            });
            
            loadFloor(index);
        }
        
        // 全局缩放状态
        let currentScale = 1;
        let currentOffsetX = 0;
        let currentOffsetY = 0;
        let isDragging = false;
        let dragStartX = 0;
        let dragStartY = 0;
        let lastTouchDistance = 0;
        let lastTouchCenter = null;
        
        function loadFloor(index) {
            const floor = floors[index];
            const container = document.getElementById('floorplanContainer');
            
            container.innerHTML = '';
            
            // 重置缩放状态
            currentScale = 1;
            currentOffsetX = 0;
            currentOffsetY = 0;
            
            // 创建包装器
            const wrapper = document.createElement('div');
            wrapper.className = 'floorplan-wrapper';
            wrapper.id = 'floorplanWrapper';
            container.appendChild(wrapper);
            
            const img = document.createElement('img');
            img.src = floor.floorplan;
            img.alt = floor.name;
            img.id = 'floorplanImg';
            
            img.onload = () => {
                wrapper.appendChild(img);
                
                // 计算图片实际显示尺寸（保持宽高比的缩放）
                const imgNaturalWidth = img.naturalWidth;
                const imgNaturalHeight = img.naturalHeight;
                const wrapperWidth = wrapper.clientWidth;
                const wrapperHeight = wrapper.clientHeight;
                
                const baseScale = Math.min(
                    wrapperWidth / imgNaturalWidth,
                    wrapperHeight / imgNaturalHeight
                );
                
                const displayedWidth = imgNaturalWidth * baseScale;
                const displayedHeight = imgNaturalHeight * baseScale;
                
                const offsetX = (wrapperWidth - displayedWidth) / 2;
                const offsetY = (wrapperHeight - displayedHeight) / 2;
                
                // 保存基础信息用于后续计算
                wrapper.dataset.baseScale = baseScale;
                wrapper.dataset.displayedWidth = displayedWidth;
                wrapper.dataset.displayedHeight = displayedHeight;
                wrapper.dataset.offsetX = offsetX;
                wrapper.dataset.offsetY = offsetY;
                wrapper.dataset.imgNaturalWidth = imgNaturalWidth;
                wrapper.dataset.imgNaturalHeight = imgNaturalHeight;
                
                // 添加标记点
                renderMarkers(wrapper, floor.markers, offsetX, offsetY, displayedWidth, displayedHeight);
                
                // 添加缩放控件
                addZoomControls(container);
                
                // 添加事件监听
                addZoomEvents(wrapper, img, floor.markers);
                
                // 加载影像
                loadPanorama(0);
            };
            
            img.onerror = () => {
                container.innerHTML = '<p style="color: #666;">平面图加载失败</p>';
            };
        }
        
        function renderMarkers(wrapper, markers, offsetX, offsetY, displayedWidth, displayedHeight) {
            // 清除旧标记点
            wrapper.querySelectorAll('.marker-dot').forEach(dot => dot.remove());
            
            markers.forEach((marker, idx) => {
                const dot = document.createElement('div');
                dot.className = 'marker-dot' + (idx === 0 ? ' active' : '');
                dot.dataset.markerX = marker.x;
                dot.dataset.markerY = marker.y;
                dot.dataset.markerIndex = idx;
                
                updateMarkerPosition(dot, offsetX, offsetY, displayedWidth, displayedHeight);
                
                dot.onclick = function(e) {
                    e.stopPropagation();
                    loadPanorama(idx);
                };
                wrapper.appendChild(dot);
            });
        }
        
        function updateMarkerPosition(dot, offsetX, offsetY, displayedWidth, displayedHeight) {
            const markerX = parseFloat(dot.dataset.markerX);
            const markerY = parseFloat(dot.dataset.markerY);
            const leftPos = offsetX + (markerX * displayedWidth);
            const topPos = offsetY + (markerY * displayedHeight);
            dot.style.left = leftPos + 'px';
            dot.style.top = topPos + 'px';
        }
        
        function addZoomControls(container) {
            const controls = document.createElement('div');
            controls.className = 'zoom-controls';
            controls.innerHTML = `
                <button class="zoom-btn" onclick="zoomIn()" title="放大">+</button>
                <button class="zoom-btn" onclick="zoomOut()" title="缩小">−</button>
                <button class="zoom-btn zoom-reset" onclick="zoomReset()" title="重置">重置</button>
            `;
            container.appendChild(controls);
        }
        
        function addZoomEvents(wrapper, img, markers) {
            // 鼠标滚轮缩放
            wrapper.addEventListener('wheel', function(e) {
                e.preventDefault();
                
                const rect = wrapper.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;
                
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                const newScale = Math.max(0.5, Math.min(5, currentScale * delta));
                
                if (newScale !== currentScale) {
                    // 以鼠标为中心缩放
                    const scaleRatio = newScale / currentScale;
                    currentOffsetX = mouseX - (mouseX - currentOffsetX) * scaleRatio;
                    currentOffsetY = mouseY - (mouseY - currentOffsetY) * scaleRatio;
                    currentScale = newScale;
                    
                    applyTransform(wrapper, img, markers);
                }
            }, { passive: false });
            
            // 拖拽平移
            wrapper.addEventListener('mousedown', function(e) {
                if (e.target.classList.contains('marker-dot')) return;
                isDragging = true;
                dragStartX = e.clientX - currentOffsetX;
                dragStartY = e.clientY - currentOffsetY;
                wrapper.style.cursor = 'grabbing';
            });
            
            document.addEventListener('mousemove', function(e) {
                if (!isDragging) return;
                e.preventDefault();
                currentOffsetX = e.clientX - dragStartX;
                currentOffsetY = e.clientY - dragStartY;
                applyTransform(wrapper, img, markers);
            });
            
            document.addEventListener('mouseup', function() {
                isDragging = false;
                wrapper.style.cursor = 'grab';
            });
            
            // 触摸缩放（双指）
            let initialTouchDistance = 0;
            let initialTouchCenter = null;
            let initialScale = 1;
            let initialOffsetX = 0;
            let initialOffsetY = 0;
            
            wrapper.addEventListener('touchstart', function(e) {
                if (e.touches.length === 2) {
                    e.preventDefault();
                    const touch1 = e.touches[0];
                    const touch2 = e.touches[1];
                    
                    // 记录初始状态
                    initialTouchDistance = Math.hypot(
                        touch2.clientX - touch1.clientX,
                        touch2.clientY - touch1.clientY
                    );
                    initialTouchCenter = {
                        x: (touch1.clientX + touch2.clientX) / 2,
                        y: (touch1.clientY + touch2.clientY) / 2
                    };
                    initialScale = currentScale;
                    initialOffsetX = currentOffsetX;
                    initialOffsetY = currentOffsetY;
                    
                    lastTouchDistance = initialTouchDistance;
                    lastTouchCenter = initialTouchCenter;
                } else if (e.touches.length === 1 && currentScale > 1) {
                    isDragging = true;
                    dragStartX = e.touches[0].clientX - currentOffsetX;
                    dragStartY = e.touches[0].clientY - currentOffsetY;
                }
            }, { passive: false });
            
            wrapper.addEventListener('touchmove', function(e) {
                if (e.touches.length === 2) {
                    e.preventDefault();
                    const touch1 = e.touches[0];
                    const touch2 = e.touches[1];
                    
                    // 当前两指距离
                    const distance = Math.hypot(
                        touch2.clientX - touch1.clientX,
                        touch2.clientY - touch1.clientY
                    );
                    
                    // 当前两指中心
                    const currentCenter = {
                        x: (touch1.clientX + touch2.clientX) / 2,
                        y: (touch1.clientY + touch2.clientY) / 2
                    };
                    
                    if (initialTouchDistance > 0) {
                        // 基于初始状态计算新缩放
                        const scaleDelta = distance / initialTouchDistance;
                        const newScale = Math.max(0.5, Math.min(5, initialScale * scaleDelta));
                        
                        // 以两指中心为基点缩放
                        const rect = wrapper.getBoundingClientRect();
                        const centerX = initialTouchCenter.x - rect.left;
                        const centerY = initialTouchCenter.y - rect.top;
                        
                        const scaleRatio = newScale / initialScale;
                        currentOffsetX = centerX - (centerX - initialOffsetX) * scaleRatio;
                        currentOffsetY = centerY - (centerY - initialOffsetY) * scaleRatio;
                        currentScale = newScale;
                        
                        applyTransform(wrapper, img, markers);
                    }
                    
                    lastTouchDistance = distance;
                    lastTouchCenter = currentCenter;
                } else if (e.touches.length === 1 && isDragging) {
                    e.preventDefault();
                    currentOffsetX = e.touches[0].clientX - dragStartX;
                    currentOffsetY = e.touches[0].clientY - dragStartY;
                    applyTransform(wrapper, img, markers);
                }
            }, { passive: false });
            
            wrapper.addEventListener('touchend', function() {
                lastTouchDistance = 0;
                lastTouchCenter = null;
                isDragging = false;
            });
            
            // 双击重置
            wrapper.addEventListener('dblclick', function() {
                zoomReset();
            });
        }
        
        function applyTransform(wrapper, img, markers) {
            // 应用变换到图片
            img.style.transform = 'translate(' + currentOffsetX + 'px, ' + currentOffsetY + 'px) scale(' + currentScale + ')';
            
            // 计算标记点的基础偏移（图片初始居中时的偏移）
            const baseOffsetX = parseFloat(wrapper.dataset.offsetX);
            const baseOffsetY = parseFloat(wrapper.dataset.offsetY);
            const displayedWidth = parseFloat(wrapper.dataset.displayedWidth);
            const displayedHeight = parseFloat(wrapper.dataset.displayedHeight);
            
            // 标记点位置 = 基础偏移 + 平移偏移 + (标记点相对位置 * 缩放后尺寸)
            wrapper.querySelectorAll('.marker-dot').forEach(dot => {
                const markerX = parseFloat(dot.dataset.markerX);
                const markerY = parseFloat(dot.dataset.markerY);
                
                // 计算标记点在缩放后的位置
                const leftPos = baseOffsetX + currentOffsetX + (markerX * displayedWidth * currentScale);
                const topPos = baseOffsetY + currentOffsetY + (markerY * displayedHeight * currentScale);
                
                dot.style.left = leftPos + 'px';
                dot.style.top = topPos + 'px';
                // 标记点大小不随缩放变化，保持可读性
                dot.style.transform = 'translate(-50%, -50%)';
            });
        }
        
        function zoomIn() {
            const wrapper = document.getElementById('floorplanWrapper');
            if (!wrapper) return;
            const img = document.getElementById('floorplanImg');
            const floor = floors[currentFloorIndex];
            
            currentScale = Math.min(5, currentScale * 1.25);
            applyTransform(wrapper, img, floor.markers);
        }
        
        function zoomOut() {
            const wrapper = document.getElementById('floorplanWrapper');
            if (!wrapper) return;
            const img = document.getElementById('floorplanImg');
            const floor = floors[currentFloorIndex];
            
            currentScale = Math.max(0.5, currentScale / 1.25);
            if (currentScale < 1.01 && currentScale > 0.99) {
                currentScale = 1;
                currentOffsetX = 0;
                currentOffsetY = 0;
            }
            applyTransform(wrapper, img, floor.markers);
        }
        
        function zoomReset() {
            const wrapper = document.getElementById('floorplanWrapper');
            if (!wrapper) return;
            const img = document.getElementById('floorplanImg');
            const floor = floors[currentFloorIndex];
            
            currentScale = 1;
            currentOffsetX = 0;
            currentOffsetY = 0;
            applyTransform(wrapper, img, floor.markers);
        }
        
        // 全局状态
        let isGyroEnabled = false;
        let isVREnabled = false;
        let vrViewerLeft = null;
        let vrViewerRight = null;
        
        function loadPanorama(index) {
            const floor = floors[currentFloorIndex];
            if (floor.markers.length === 0) return;
            
            currentMarkerIndex = index;
            const marker = floor.markers[index];
            
            document.getElementById('current-title').textContent = 
                marker.customName || marker.cameraFileName || '点位' + (index + 1);
            document.getElementById('current-floor').textContent = floor.name;
            
            // 更新激活的标记点
            document.querySelectorAll('.marker-dot').forEach((dot, idx) => {
                dot.classList.toggle('active', idx === index);
            });
            
            // 如果 VR 模式已启用，重新加载 VR 视图
            if (isVREnabled) {
                loadVRView(marker);
                return;
            }
            
            if (viewer) viewer.destroy();
            
            viewer = pannellum.viewer('panorama', {
                type: 'equirectangular',
                panorama: marker.panoramaPath,
                autoLoad: true,
                compass: true,
                showFullscreenCtrl: true,
                showZoomCtrl: true,
                title: marker.customName || '',
                orientationOnByDefault: isGyroEnabled,
                friction: 0.1,
                mouseZoom: true,
                draggable: true
            });
            
            // 如果启用了陀螺仪，强制启用设备方向控制
            if (isGyroEnabled && viewer) {
                // 延迟启用陀螺仪，确保查看器已初始化
                setTimeout(() => {
                    try {
                        // 尝试启用设备方向控制
                        if (viewer.enableOrientation) {
                            viewer.enableOrientation();
                        }
                    } catch(e) {
                        console.log('启用陀螺仪控制:', e);
                    }
                }, 100);
            }
        }
        
        // 切换陀螺仪模式
        function toggleGyro() {
            if (isGyroEnabled) {
                // 关闭陀螺仪
                isGyroEnabled = false;
                document.getElementById('gyroBtn').classList.remove('active');
                if (!isVREnabled) {
                    loadPanorama(currentMarkerIndex);
                }
            } else {
                // 开启陀螺仪 - iOS 13+ 需要显式请求权限, 必须在同步上下文调用
                if (typeof DeviceOrientationEvent !== 'undefined' && 
                    typeof DeviceOrientationEvent.requestPermission === 'function') {
                    // iOS 13+ 需要 HTTPS 环境
                    if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
                        alert('iOS 设备需要使用 HTTPS 连接才能启用陀螺仪功能。当前连接: ' + window.location.protocol + '//' + window.location.hostname);
                        return;
                    }
                    DeviceOrientationEvent.requestPermission()
                        .then(response => {
                            console.log('陀螺仪权限请求结果:', response);
                            if (response === 'granted') {
                                enableGyroMode();
                            } else if (response === 'denied') {
                                alert('权限被拒绝。请在 iPhone 设置 > Safari > 动作与方向访问 中允许访问。');
                            } else {
                                alert('需要设备方向权限才能使用陀螺仪功能。请重试并点击"允许"。');
                            }
                        })
                        .catch(e => {
                            console.error('请求权限失败:', e);
                            alert('无法获取陀螺仪权限: ' + e.message + ' 请确保使用HTTPS连接并在iPhone设置中允许动作与方向访问');
                        });
                } else {
                    // Android 或其他浏览器直接启用
                    enableGyroMode();
                }
            }
        }
        
        // 启用陀螺仪模式
        function enableGyroMode() {
            isGyroEnabled = true;
            const btn = document.getElementById('gyroBtn');
            const hint = document.getElementById('gyroHint');
            
            btn.classList.add('active');
            hint.classList.add('show');
            setTimeout(() => hint.classList.remove('show'), 3000);
            
            // 重新加载当前影像以应用设置
            if (!isVREnabled) {
                loadPanorama(currentMarkerIndex);
            }
        }
        
        // 切换 VR 模式
        function toggleVR() {
            if (isVREnabled) {
                exitVR();
            } else {
                // 进入 VR - iOS 13+ 需要显式请求权限，必须在同步上下文调用
                if (typeof DeviceOrientationEvent !== 'undefined' && 
                    typeof DeviceOrientationEvent.requestPermission === 'function') {
                    // iOS 13+ 需要 HTTPS 环境
                    if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost') {
                        alert('iOS 设备需要使用 HTTPS 连接才能启用 VR 功能。当前连接: ' + window.location.protocol + '//' + window.location.hostname);
                        return;
                    }
                    DeviceOrientationEvent.requestPermission()
                        .then(response => {
                            console.log('VR 权限请求结果:', response);
                            if (response === 'granted') {
                                startVRMode();
                            } else if (response === 'denied') {
                                alert('权限被拒绝。请在 iPhone 设置 > Safari > 动作与方向访问 中允许访问。');
                            } else {
                                alert('需要设备方向权限才能使用 VR 功能。请重试并点击"允许"。');
                            }
                        })
                        .catch(e => {
                            console.error('请求权限失败:', e);
                            alert('无法获取陀螺仪权限: ' + e.message + ' 请确保使用HTTPS连接并在iPhone设置中允许动作与方向访问');
                        });
                } else {
                    // Android 或其他浏览器直接启用
                    startVRMode();
                }
            }
        }
        
        // 启动 VR 模式
        function startVRMode() {
            isVREnabled = true;
            document.getElementById('vrBtn').classList.add('active');
            document.getElementById('vr-container').classList.add('active');
            
            // 强制横屏
            if (screen.orientation && screen.orientation.lock) {
                screen.orientation.lock('landscape').catch(err => {
                    console.log('无法锁定屏幕方向:', err);
                });
            } else if (screen.lockOrientation) {
                screen.lockOrientation('landscape');
            } else if (screen.mozLockOrientation) {
                screen.mozLockOrientation('landscape');
            } else if (screen.msLockOrientation) {
                screen.msLockOrientation('landscape');
            }
            
            // 进入全屏
            const elem = document.documentElement;
            if (elem.requestFullscreen) {
                elem.requestFullscreen();
            } else if (elem.webkitRequestFullscreen) {
                elem.webkitRequestFullscreen();
            } else if (elem.msRequestFullscreen) {
                elem.msRequestFullscreen();
            }
            
            // 加载 VR 分屏视图
            const floor = floors[currentFloorIndex];
            const marker = floor.markers[currentMarkerIndex];
            loadVRView(marker);
        }
        
        // 加载 VR 分屏视图
        function loadVRView(marker) {
            // 销毁旧的 VR 查看器
            if (vrViewerLeft) vrViewerLeft.destroy();
            if (vrViewerRight) vrViewerRight.destroy();
            
            const baseConfig = {
                type: 'equirectangular',
                panorama: marker.panoramaPath,
                autoLoad: true,
                compass: false,
                showFullscreenCtrl: false,
                showZoomCtrl: false,
                title: '',
                orientationOnByDefault: true,
                friction: 0.1,
                mouseZoom: false,
                doubleClickZoom: false,
                sceneFadeDuration: 0
            };
            
            // 左眼视图（稍微向左偏移）
            vrViewerLeft = pannellum.viewer('vrLeft', {
                ...baseConfig,
                haov: 360,
                vaov: 180,
                hfov: 100,
                yaw: -5  // 左眼稍微向左看
            });
            
            // 右眼视图（稍微向右偏移，模拟瞳距）
            vrViewerRight = pannellum.viewer('vrRight', {
                ...baseConfig,
                haov: 360,
                vaov: 180,
                hfov: 100,
                yaw: 5  // 右眼稍微向右看
            });
            
            // 同步左右眼视角
            syncVREyes();
        }
        
        // 同步 VR 左右眼视角
        function syncVREyes() {
            if (!vrViewerLeft || !vrViewerRight) return;
            
            // 监听设备方向变化来同步视角
            let lastYaw = 0;
            let lastPitch = 0;
            
            const syncView = () => {
                if (!vrViewerLeft || !vrViewerRight) return;
                
                try {
                    const leftYaw = vrViewerLeft.getYaw();
                    const leftPitch = vrViewerLeft.getPitch();
                    
                    // 只有变化超过阈值时才更新，减少渲染负担
                    if (Math.abs(leftYaw - lastYaw) > 0.1 || Math.abs(leftPitch - lastPitch) > 0.1) {
                        vrViewerRight.setYaw(leftYaw + 10, false);  // 保持瞳距偏移
                        vrViewerRight.setPitch(leftPitch, false);
                        lastYaw = leftYaw;
                        lastPitch = leftPitch;
                    }
                } catch(e) {}
                
                if (isVREnabled) {
                    requestAnimationFrame(syncView);
                }
            };
            
            syncView();
        }
        
        // 退出 VR 模式
        function exitVR() {
            isVREnabled = false;
            document.getElementById('vrBtn').classList.remove('active');
            document.getElementById('vr-container').classList.remove('active');
            
            // 解锁屏幕方向
            if (screen.orientation && screen.orientation.unlock) {
                screen.orientation.unlock();
            } else if (screen.unlockOrientation) {
                screen.unlockOrientation();
            } else if (screen.mozUnlockOrientation) {
                screen.mozUnlockOrientation();
            } else if (screen.msUnlockOrientation) {
                screen.msUnlockOrientation();
            }
            
            // 销毁 VR 查看器
            if (vrViewerLeft) {
                vrViewerLeft.destroy();
                vrViewerLeft = null;
            }
            if (vrViewerRight) {
                vrViewerRight.destroy();
                vrViewerRight = null;
            }
            
            // 退出全屏
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) {
                document.msExitFullscreen();
            }
            
            // 恢复普通视图
            loadPanorama(currentMarkerIndex);
        }
        
        // 监听 ESC 键退出 VR
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isVREnabled) {
                exitVR();
            }
        });
        
        function prevPanorama() {
            const floor = floors[currentFloorIndex];
            if (floor.markers.length === 0) return;
            
            let newIndex = currentMarkerIndex - 1;
            if (newIndex < 0) newIndex = floor.markers.length - 1;
            loadPanorama(newIndex);
        }
        
        function nextPanorama() {
            const floor = floors[currentFloorIndex];
            if (floor.markers.length === 0) return;
            
            let newIndex = currentMarkerIndex + 1;
            if (newIndex >= floor.markers.length) newIndex = 0;
            loadPanorama(newIndex);
        }
        
        // 窗口大小改变时重新加载当前楼层（重新计算点位位置）
        let resizeTimer = null;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() {
                // 重新加载当前楼层以重新计算标记点位置
                loadFloor(currentFloorIndex);
                // 恢复当前选中的标记点状态
                setTimeout(function() {
                    document.querySelectorAll('.marker-dot').forEach(function(dot, idx) {
                        dot.classList.toggle('active', idx === currentMarkerIndex);
                    });
                }, 100);
            }, 250);
        });
        
        // 启动
        init();
    </script>
    <!-- 生成的查看器底部 -->
    <div class="brand-footer">
        <span>由 随心系统 生成</span>
        <a href="https://github.com/huangkeqi-cmd/suixi-system">了解更多</a>
    </div>
</body>
</html>'''
        
        # 使用 replace 方法替换占位符，避免与 JS 代码中的花括号冲突
        html_content = html_content.replace('__FLOORS_JSON__', floors_json if floors_json else '[]')
        html_content = html_content.replace('__PROJECT_NAME__', project_name if project_name else '未命名项目')
        
        # 调试：检查替换结果
        if '__FLOORS_JSON__' in html_content or '__PROJECT_NAME__' in html_content:
            print("[警告] 占位符未被正确替换!")
        
        with open(os.path.join(viewer_dir, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"[调试] 网页已生成: {os.path.join(viewer_dir, 'index.html')}")
    
    def start_http_server(self):
        """启动 HTTP 服务器"""
        if not self.project_dir:
            return
        
        viewer_dir = os.path.join(self.project_dir, 'viewer')
        # 统一使用正斜杠
        viewer_dir = viewer_dir.replace('\\', '/')
        
        if not os.path.exists(viewer_dir):
            QMessageBox.warning(self, "提示", "网页查看器尚未生成，请先点击'生成本地网页'")
            return
        
        # 先停止已有服务器
        if self.server_thread and self.server_thread.is_running:
            self.stop_http_server()
        
        # 尝试不同端口（跳过 8080，因为经常被占用）
        for port in [8888, 9000, 9999, 0]:
            try:
                self.server_thread = HttpServerThread(viewer_dir, port)
                self.server_thread.server_started.connect(self._on_server_started)
                self.server_thread.error_occurred.connect(self._on_server_error)
                self.server_thread.start()
                # 等待一下看是否启动成功
                import time
                time.sleep(0.5)
                if self.server_thread.is_running:
                    break
            except Exception as e:
                print(f"[调试] 端口 {port} 启动失败: {e}")
                continue
        else:
            QMessageBox.critical(self, "错误", "无法启动服务器，所有端口都被占用")
            return
    
    def _on_server_started(self, ip: str, port: int):
        """服务器启动成功"""
        self.current_local_url = f"http://localhost:{port}"
        self.current_lan_url = f"http://{ip}:{port}"
        
        self.local_url_edit.setText(self.current_local_url)
        self.lan_url_edit.setText(self.current_lan_url)
        
        # 检查网页文件是否存在
        if self.project_dir:
            viewer_dir = os.path.join(self.project_dir, 'viewer')
            index_path = os.path.join(viewer_dir, 'index.html')
            if not os.path.exists(index_path):
                QMessageBox.warning(self, "警告", "viewer/index.html 不存在，请先生成本地网页后再启动服务器")
                self.stop_http_server()
                return
        
        # 生成二维码
        try:
            import io
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(self.current_lan_url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            
            # 保存到内存缓冲区
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            # 转换为 QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue())
            self.qr_label.setPixmap(pixmap.scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio))
            print(f"[调试] 二维码生成成功: {self.current_lan_url}")
        except Exception as e:
            print(f"[调试] 二维码生成失败: {e}")
            import traceback
            traceback.print_exc()
            self.qr_label.setText(f"二维码生成失败，请手动输入地址\n{self.current_lan_url}")
        
        self.server_info_group.setVisible(True)
        self.stop_server_btn.setEnabled(True)
        self.open_web_btn.setEnabled(False)
        
        # 延迟打开浏览器，确保服务器完全就绪
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(800, lambda: webbrowser.open(self.current_local_url))
    
    def _copy_local_url(self):
        """复制本地地址到剪贴板"""
        if hasattr(self, 'current_local_url'):
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_local_url)
            QMessageBox.information(self, "复制成功", f"本地地址已复制到剪贴板:\n{self.current_local_url}")
    
    def _open_local_url(self):
        """在浏览器中打开本地地址"""
        if hasattr(self, 'current_local_url'):
            webbrowser.open(self.current_local_url)
    
    def _copy_lan_url(self):
        """复制局域网地址到剪贴板"""
        if hasattr(self, 'current_lan_url'):
            from PyQt6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_lan_url)
            QMessageBox.information(self, "复制成功", f"局域网地址已复制到剪贴板:\n{self.current_lan_url}")
    
    def _open_lan_url(self):
        """在浏览器中打开局域网地址"""
        if hasattr(self, 'current_lan_url'):
            webbrowser.open(self.current_lan_url)
    
    def _on_server_error(self, error: str):
        """服务器错误"""
        QMessageBox.critical(self, "错误", f"启动服务器失败: {error}")
    
    def stop_http_server(self):
        """停止 HTTP 服务器（非阻塞）"""
        if self.server_thread:
            # 在后台线程中停止服务器，避免阻塞 GUI 导致窗口卡死
            import threading
            old_thread = self.server_thread
            self.server_thread = None
            def do_stop():
                try:
                    old_thread.stop()
                except Exception as e:
                    print(f"[调试] 停止服务器异常: {e}")
            t = threading.Thread(target=do_stop, daemon=True)
            t.start()
            # 最多等待1秒
            t.join(timeout=1.0)
        
        self.server_info_group.setVisible(False)
        self.stop_server_btn.setEnabled(False)
        self.open_web_btn.setEnabled(True)
        self.qr_label.clear()
    
    def _on_marker_moved(self, marker_id: str, norm_x: float, norm_y: float):
        """采集点被拖动后更新坐标数据"""
        if not self.project_data:
            return
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    marker_data['x'] = norm_x
                    marker_data['y'] = norm_y
                    self.current_marker = Marker.from_dict(marker_data)
                    self.marker_coord_label.setText(f"({norm_x:.4f}, {norm_y:.4f})")
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 12px; font-size: 14px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    return

    def _on_marker_add_requested(self, norm_x: float, norm_y: float):
        """在平面图上空白处添加新采集点"""
        if not self.project_data or not self.current_floor_id:
            QMessageBox.warning(self, "提示", "请先加载项目并选择楼层")
            return
        # 生成新ID
        new_id = 'm' + str(int(datetime.now().timestamp() * 1000))
        for floor_data in self.project_data.floors:
            if floor_data['id'] == self.current_floor_id:
                new_marker = {
                    'id': new_id,
                    'status': 'pending',
                    'cameraFileName': '',
                    'customName': '',
                    'x': norm_x,
                    'y': norm_y,
                    'timestamp': '',
                    'captureTime': '',
                    'startTime': '',
                    'endTime': '',
                    'panoramaPath': '',
                    'originalPhotoPath': '',
                    'direction': None
                }
                floor_data.setdefault('markers', []).append(new_marker)
                self.canvas.add_marker(new_id, norm_x, norm_y, 'pending', new_id)
                self.save_changes_btn.setStyleSheet("""
                    QPushButton {
                        padding: 12px; font-size: 14px;
                        background-color: #FF9500; color: white;
                        border: none; border-radius: 6px;
                    }
                    QPushButton:hover { background-color: #B36800; }
                """)
                self.save_changes_btn.setText("💾 保存修改（已变更）")
                self._update_marker_count()
                return

    def _update_marker_count(self):
        """更新点位数量显示"""
        if not self.project_data:
            return
        total = sum(len(f.get('markers', [])) for f in self.project_data.floors)
        self.marker_count_label.setText(f"{len(self.project_data.floors)} 层 / {total} 个点位")

    def _on_marker_context_menu(self, marker_id: str, global_pos):
        """采集点右键菜单"""
        menu = QMenu(self)
        move_action = menu.addAction("🔄 移动位置（已支持左键拖动）")
        delete_action = menu.addAction("🗑️ 删除点位")
        relink_action = menu.addAction("📷 重新关联照片...")
        action = menu.exec(global_pos)
        if action == delete_action:
            self._delete_marker(marker_id)
        elif action == relink_action:
            self._relink_marker_photo(marker_id)

    def _delete_marker(self, marker_id: str):
        """删除采集点"""
        if not self.project_data:
            return
        reply = QMessageBox.question(self, "确认删除", f"确定删除点位 {marker_id} 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        for floor_data in self.project_data.floors:
            markers = floor_data.get('markers', [])
            for i, m in enumerate(markers):
                if m['id'] == marker_id:
                    markers.pop(i)
                    self.canvas.clear_markers()
                    self._load_floor(self.current_floor_id)
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 12px; font-size: 14px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    self._update_marker_count()
                    return

    def _relink_marker_photo(self, marker_id: str):
        """重新关联照片到采集点"""
        if not self.project_dir:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择照片文件", self.project_dir,
            "图片文件 (*.jpg *.jpeg *.png *.heic *.heif);;所有文件 (*.*)"
        )
        if not file_path:
            return
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    fname = os.path.basename(file_path)
                    marker_data['cameraFileName'] = fname
                    marker_data['originalPhotoPath'] = file_path
                    marker_data['status'] = 'linked'
                    # 尝试复制到项目目录
                    try:
                        target = os.path.join(self.project_dir, 'photos', fname)
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.copy2(file_path, target)
                        marker_data['panoramaPath'] = os.path.join('photos', fname).replace('\\', '/')
                    except Exception as e:
                        print(f"[警告] 复制照片失败: {e}")
                    self._on_marker_selected(marker_id)
                    self.canvas.clear_markers()
                    self._load_floor(self.current_floor_id)
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 12px; font-size: 14px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    QMessageBox.information(self, "成功", f"已关联照片: {fname}")
                    return

    def _save_project_changes(self):
        """保存项目修改到 project.json"""
        if not self.project_dir or not self.project_data:
            return
        try:
            self._save_project()
            self.save_changes_btn.setStyleSheet("""
                QPushButton {
                    padding: 12px; font-size: 14px;
                    background-color: #5856D6; color: white;
                    border: none; border-radius: 6px;
                }
                QPushButton:hover { background-color: #3f3ea8; }
                QPushButton:disabled { background-color: #CCC; }
            """)
            self.save_changes_btn.setText("💾 保存修改到项目")
            QMessageBox.information(self, "成功", "项目修改已保存")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _export_for_capture(self):
        """导出为采集端可导入的数据包"""
        if not self.project_dir or not self.project_data:
            return
        try:
            export_path, _ = QFileDialog.getSaveFileName(
                self, "导出采集端数据包", f"{self.project_data.projectName}_采集端.zip",
                "ZIP 文件 (*.zip)"
            )
            if not export_path:
                return

            # 构建采集端格式数据
            export_data = {
                'schemaVersion': '4.0',
                'projectName': self.project_data.projectName,
                'createdAt': self.project_data.createdAt,
                'updatedAt': datetime.now().isoformat(),
                'timeOffset': self.project_data.timeOffset,
                'calibrated': self.project_data.calibrated,
                'floors': []
            }
            for floor_data in self.project_data.floors:
                floor_export = {
                    'id': floor_data['id'],
                    'name': floor_data['name'],
                    'order': floor_data.get('order', 0),
                    'hasPlan': floor_data.get('hasPlan', False),
                    'markers': []
                }
                for m in floor_data.get('markers', []):
                    floor_export['markers'].append({
                        'id': m['id'],
                        'status': m.get('status', 'pending'),
                        'cameraFileName': m.get('cameraFileName', ''),
                        'customName': m.get('customName', ''),
                        'x': m.get('x', 0),
                        'y': m.get('y', 0),
                        'timestamp': m.get('timestamp', ''),
                        'captureTime': m.get('captureTime', ''),
                        'startTime': m.get('startTime', ''),
                        'endTime': m.get('endTime', ''),
                        'direction': m.get('direction', None)
                    })
                export_data['floors'].append(floor_export)

            import zipfile
            with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 写入 project.json
                zf.writestr('project.json', json.dumps(export_data, ensure_ascii=False, indent=2))
                # 写入平面图
                for floor_data in self.project_data.floors:
                    if floor_data.get('hasPlan'):
                        plan_path = os.path.join(self.project_dir, f"floorplan_{floor_data['id']}.jpg")
                        if not os.path.exists(plan_path):
                            plan_path = os.path.join(self.project_dir, f"floorplan_{floor_data['id']}.png")
                        if os.path.exists(plan_path):
                            zf.write(plan_path, f"floorplan_{floor_data['id']}{os.path.splitext(plan_path)[1]}")
                # 写入照片
                photos_dir = os.path.join(self.project_dir, 'photos')
                if os.path.exists(photos_dir):
                    for root, dirs, files in os.walk(photos_dir):
                        for f in files:
                            full = os.path.join(root, f)
                            arc = os.path.relpath(full, self.project_dir)
                            zf.write(full, arc)

            QMessageBox.information(self, "导出成功",
                f"采集端数据包已导出到:\n{export_path}\n\n可直接导入采集端继续使用。")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"错误: {e}")
            import traceback
            traceback.print_exc()

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于",
            """<h2>随系 · 影像管理器 v1.0</h2>
            <p>用于商业改造现场的影像与平面图关联管理工具</p>
            <p>特点: 100% 离线、数据本地、现场容错优先</p>
            <p>© 2025 PanoramaManager</p>""")
    
    def closeEvent(self, event):
        """关闭窗口时停止服务器"""
        # 异步停止服务器，避免阻塞关闭流程
        if self.server_thread:
            import threading
            old_thread = self.server_thread
            self.server_thread = None
            threading.Thread(target=lambda: old_thread.stop() if old_thread else None, daemon=True).start()
        event.accept()


# =============================================================================
# 程序入口
# =============================================================================

def main():
    import datetime
    
    # =============================================================================
    # 随系 · 影像管理器
    # 系统追求：让工具追上现场的速度
    # =============================================================================
    
    print("\n" + "="*60)
    print("  随系 · 影像管理器")
    print("  系统追求：让工具追上现场的速度")
    print("="*60 + "\n")
    
    # 检查是否在打包后的 exe 中运行（无控制台）
    is_frozen = getattr(sys, 'frozen', False)
    has_console = sys.stdout is not None
    
    if has_console:
        # 设置日志文件 - 同时输出到控制台和文件
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug.log')
        
        class Logger:
            def __init__(self, filepath):
                self.terminal = sys.stdout
                self.log = open(filepath, 'a', encoding='utf-8')
                self.log.write(f"\n\n{'='*50}\n")
                self.log.write(f"程序启动: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                self.log.write(f"{'='*50}\n")
            
            def write(self, message):
                self.terminal.write(message)
                self.log.write(message)
                self.log.flush()
            
            def flush(self):
                self.terminal.flush()
                self.log.flush()
        
        sys.stdout = Logger(log_file)
        sys.stderr = sys.stdout  # 错误信息也写入日志
        
        print(f"[系统] 日志文件位置: {log_file}")
    else:
        # 打包后的 exe 没有控制台，禁用日志重定向
        class NullLogger:
            def write(self, message):
                pass
            def flush(self):
                pass
        
        sys.stdout = NullLogger()
        sys.stderr = NullLogger()
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置应用样式
    app.setStyleSheet("""
        QMainWindow {
            background-color: #F5F5F7;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #D1D1D6;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QLabel {
            color: #1C1C1E;
        }
    """)
    
    window = PanoramaManager()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
