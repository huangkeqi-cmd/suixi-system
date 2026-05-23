#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
随心系统 / Suixin System
Copyright (c) 2026 huangkeqi
保留所有权利。

本软件目前为个人工作流工具，开源供学习参考。
项目主页：https://github.com/huangkeqi-cmd/suixi-system
"""

# 影像管理器主入口
# -*- coding: utf-8 -*-
"""
随系 · 影像管理器 - PC 端
PanoramaManager PC Application

技术栈: Python 3.10+ + PyQt6
功能: 项目导入、影像关联、网页生成、本地服务器
"""

import sys
import os
import re
import json
import zipfile
import shutil
import socket
import webbrowser
import tempfile
import urllib.parse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
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
    QGraphicsTextItem, QGraphicsPathItem, QGraphicsLineItem,
    QDialog, QTextEdit, QProgressDialog,
    QMenuBar, QMenu, QToolBar, QStatusBar, QFrame, QScrollArea,
    QGridLayout, QGroupBox, QComboBox, QSpinBox, QCheckBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QSlider, QInputDialog
)
from PyQt6.QtCore import Qt, QRectF, QPointF, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPainter, QPen, QBrush, QColor, QFont, QIcon, QAction, QPainterPath, QPalette

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
    photos: List[str] = field(default_factory=list)  # 关联的多张照片路径列表
    direction: float = -90.0  # 扇形视线方向，-90度为上（12点钟方向）
    
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
        data = asdict(self)
        # 清理空的旧版兼容字段，减少数据冗余
        # 当 floors 存在且有内容时，移除旧的单楼层空字段
        if data.get('floors') and len(data['floors']) > 0:
            if not data.get('floorplan'):
                data.pop('floorplan', None)
            if not data.get('floorplanOriginalName'):
                data.pop('floorplanOriginalName', None)
            if not data.get('markers'):
                data.pop('markers', None)
        return data


# =============================================================================
# HTTP 服务器线程
# =============================================================================

class HttpServerThread(QThread):
    """HTTP 服务器后台线程（支持HTTPS）"""
    server_started = pyqtSignal(str, int)  # ip, port
    server_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)
    
    def __init__(self, viewer_dir: str, port: int = 0, use_https: bool = False, photo_base_dir: str = "", parent_app=None):
        super().__init__()
        self.viewer_dir = viewer_dir
        self.port = port
        self.use_https = use_https
        self.photo_base_dir = photo_base_dir
        self.parent_app = parent_app
        self.server = None
        self.redirect_server = None
        self.is_running = False
        
    def run(self):
        try:
            # 创建自定义 Handler，指定根目录
            viewer_dir = self.viewer_dir
            photo_base_dir = self.photo_base_dir
            
            class CustomHandler(SimpleHTTPRequestHandler):
                # 类属性，由外部设置
                external_parent_app = None
                
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
                    
                    # 处理 external_photos/ 前缀：直接映射到 photo_base_dir，绕过 junction
                    if photo_base_dir and path.startswith('external_photos/'):
                        sub_path = path[len('external_photos/'):]
                        words = sub_path.split('/')
                        words = filter(None, words)
                        result_path = photo_base_dir
                        for word in words:
                            if os.path.dirname(word) or word in (os.curdir, os.pardir):
                                continue
                            result_path = os.path.join(result_path, word)
                        print(f"[HTTP] {original_path} -> {result_path} (via photo_base_dir)")
                        return result_path
                    
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
                    # API: 接收全景图 yaw 角度更新
                    if self.path.startswith('/api/set_direction'):
                        try:
                            from urllib.parse import urlparse, parse_qs
                            parsed = urlparse(self.path)
                            params = parse_qs(parsed.query)
                            marker_id = params.get('marker_id', [None])[0]
                            direction_str = params.get('direction', [None])[0]  # 新版：直接发送方向
                            yaw_str = params.get('yaw', [None])[0]              # 兼容旧版
                            direction = None
                            if marker_id:
                                if direction_str is not None:
                                    direction = float(direction_str)
                                elif yaw_str is not None:
                                    direction = float(yaw_str) - 90
                                if direction is not None:
                                    direction = ((direction + 180) % 360) - 180
                                    if CustomHandler.external_parent_app:
                                        CustomHandler.external_parent_app.direction_update.emit(marker_id, direction)
                                    self.send_response(200)
                                    self.send_header('Content-Type', 'application/json')
                                    self.send_header('Access-Control-Allow-Origin', '*')
                                    self.end_headers()
                                    self.wfile.write(json.dumps({'status': 'ok', 'direction': direction}).encode())
                                    return
                        except Exception as e:
                            print(f"[API] 处理方向更新失败: {e}")
                        self.send_response(400)
                        self.end_headers()
                        return
                    return super().do_GET()
                
                def end_headers(self):
                    # 添加 CORS 头，解决浏览器安全策略问题
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', '*')
                    # 添加缓存控制头，防止浏览器缓存 viewer 文件
                    # 解决新旧版本切换时的缓存冲突问题
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    super().end_headers()
                
                def do_OPTIONS(self):
                    # 处理 CORS 预检请求
                    self.send_response(200)
                    self.end_headers()
                
                def guess_type(self, path):
                    # 确保 .JPG/.jpg 正确返回 image/jpeg
                    _type = super().guess_type(path)
                    if _type is None:
                        ext = os.path.splitext(path)[1].lower()
                        if ext in ('.jpg', '.jpeg'):
                            return 'image/jpeg'
                        if ext == '.png':
                            return 'image/png'
                        if ext == '.gif':
                            return 'image/gif'
                        if ext == '.webp':
                            return 'image/webp'
                    return _type
                
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
                CustomHandler.external_parent_app = self.parent_app
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
                CustomHandler.external_parent_app = self.parent_app
                self.server = ThreadedHTTPServer(("", self.port), CustomHandler)
            
            actual_port = self.server.socket.getsockname()[1]
            self.actual_port = actual_port  # 保存实际端口供外部读取
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
        finally:
            self.is_running = False
            print("[调试] 服务器线程已退出")
    
    def stop(self):
        self.is_running = False
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
    """从照片 EXIF 数据提取拍摄时间 - 支持多种 PIL 版本"""
    try:
        img = Image.open(image_path)
        exif = None
        
        # 尝试多种方式获取 EXIF 数据（兼容不同 PIL 版本）
        try:
            # PIL 9.0+ 推荐使用 getexif()
            exif = img.getexif()
        except AttributeError:
            try:
                # 旧版 PIL 使用 _getexif()
                exif = img._getexif()
            except AttributeError:
                pass
        
        img.close()
        
        if not exif:
            print(f"[调试] 无 EXIF 数据: {os.path.basename(image_path)}")
            return None
        
        # DateTimeOriginal 标签 ID = 36867 (0x9003)
        datetime_original_tag = 36867
        
        # 尝试获取 DateTimeOriginal
        value = None
        if isinstance(exif, dict):
            # 旧版 _getexif() 返回字典
            value = exif.get(datetime_original_tag)
        else:
            # 新版 getexif() 返回 Exif 对象
            value = exif.get(datetime_original_tag)
            # 如果获取不到，尝试遍历
            if value is None:
                for tag_id, tag_value in exif.items():
                    if tag_id == datetime_original_tag:
                        value = tag_value
                        break
        
        if value:
            try:
                # 格式: "2026:04:22 13:30:45"
                dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                print(f"[调试] EXIF: {os.path.basename(image_path)} -> {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                return dt
            except Exception as e:
                print(f"[调试] 解析EXIF时间失败 '{value}': {e}")
        else:
            # 尝试其他时间标签
            fallback_tags = [306, 36868]  # DateTime, DateTimeDigitized
            for tag_id in fallback_tags:
                try:
                    if isinstance(exif, dict):
                        fb_value = exif.get(tag_id)
                    else:
                        fb_value = exif.get(tag_id)
                    
                    if fb_value:
                        dt = datetime.strptime(str(fb_value), "%Y:%m:%d %H:%M:%S")
                        print(f"[调试] EXIF (fallback): {os.path.basename(image_path)} -> {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                        return dt
                except:
                    pass
            
            print(f"[调试] 未找到 DateTimeOriginal: {os.path.basename(image_path)}")
                    
    except Exception as e:
        print(f"[调试] 读取EXIF失败 {os.path.basename(image_path)}: {e}")
        import traceback
        traceback.print_exc()
    return None


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
                        print(f"[自动校准] 照片 {os.path.basename(self.photo_files[i])}: EXIF={dt}")
                except Exception:
                    pass
            
            # 如果 EXIF 时间不足，fallback 到文件名时间（适配手机本机拍摄）
            used_filename_fallback = False
            if len(photo_times) < max(3, len(marker_times) // 2):
                print(f"[自动校准] EXIF 时间不足({len(photo_times)}个)，尝试从文件名提取...")
                for i in range(max_photos):
                    # 跳过已有 EXIF 的照片
                    if any(self.photo_files[i] == pt[0] for pt in photo_times):
                        continue
                    try:
                        dt = extract_time_from_filename(os.path.basename(self.photo_files[i]))
                        if dt:
                            photo_times.append((self.photo_files[i], dt))
                            print(f"[自动校准] 照片 {os.path.basename(self.photo_files[i])}: 文件名={dt}")
                            used_filename_fallback = True
                    except Exception:
                        pass
                if used_filename_fallback:
                    print(f"[自动校准] 文件名提取完成，共 {len(photo_times)} 张照片有时间信息")
            
            print(f"[自动校准] 共 {len(photo_times)} 张照片有时间信息")
            
            if not photo_times:
                print("[自动校准] 警告: 没有照片包含时间信息（EXIF或文件名）")
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


def extract_time_from_filename(filename: str) -> Optional[datetime]:
    """从文件名中提取时间，支持多种手机拍摄格式
    
    支持格式:
    - 大疆: CAM_20260428131621_0272_D.JPG
    - iOS: IMG_1234.jpg, IMG_20260505_103045.jpg, IMG_2026-05-05_10-30-45.jpg
    - 安卓: 20260505_103045.jpg, DCIM_20260505_103045.jpg
    - 微信: wx_camera_1234567890123.jpg (毫秒时间戳)
    - 截图: Screenshot_20260505-103045.jpg, Screenshot_2026-05-05-10-30-45.png
    - 通用: 20260422183045, 2026-04-22-18-30-45, 2026_04_22_18_30_45
    - 本机拍摄: 楼层名_点位序号_YYYYMMDD_HHMMSS.jpg (随拍采集端导出)
    """
    import re
    
    # 移除扩展名
    name = os.path.splitext(filename)[0]
    
    # 模式1: 微信相机格式 wx_camera_1234567890123 (13位毫秒时间戳)
    match = re.search(r'wx_camera_(\d{13})', name)
    if match:
        try:
            timestamp_ms = int(match.group(1))
            return datetime.fromtimestamp(timestamp_ms / 1000)
        except:
            pass
    
    # 模式2: 截图格式 Screenshot_20260505-103045 或 Screenshot_2026-05-05-10-30-45
    match = re.search(r'Screenshot[_-]?(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})', name, re.IGNORECASE)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式3: IMG_前缀格式 IMG_20260505_103045 或 IMG_2026-05-05_10-30-45
    match = re.search(r'IMG[_-]?(\d{4})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_]?(\d{2})', name, re.IGNORECASE)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式4: 大疆格式 CAM_20260428131621_0272_D
    match = re.search(r'CAM[_-]?(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', name, re.IGNORECASE)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式5: 连续格式 20260422183045 (8位日期+6位时间)
    match = re.search(r'(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', name)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            # 验证时间合理性
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式6: 带分隔符格式 2026_04_22_18_30_45 或 2026-04-22-18-30-45
    match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})', name)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式7: 带T分隔符 20260422T183045
    match = re.search(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})', name)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass
    
    # 模式8: 纯日期格式 20260505 (仅日期，时间设为00:00:00)
    match = re.search(r'^(\d{4})(\d{2})(\d{2})$', name)
    if match:
        try:
            year, month, day = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, 0, 0, 0)
        except:
            pass

    # 模式9: YYYY-MM-DD HHMMSS 或 YYYY-MM-DD_HHMMSS（手机默认拍照格式）
    match = re.search(r'(\d{4})[-_](\d{2})[-_](\d{2})[ _](\d{2})(\d{2})(\d{2})', name)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, hour, minute, second)
        except:
            pass

    return None


class PhotoImportThread(QThread):
    """照片导入和匹配后台线程 - 支持本机拍摄照片全自动关联和外设照片自动偏移"""
    
    # 信号定义
    progress_update = pyqtSignal(int, str)  # progress, message
    match_found = pyqtSignal(str, str, str)  # marker_id, filename, match_type
    import_complete = pyqtSignal(dict)  # results
    status_update = pyqtSignal(str)  # 状态更新信号
    
    # 本机拍摄照片命名格式: 楼层名_点位序号_YYYYMMDD_HHMMSS.jpg
    LOCAL_PHOTO_RE = re.compile(r'^(.+?)_(\d+)_(\d{8})_(\d{6})\.(jpg|jpeg)$', re.IGNORECASE)
    
    def __init__(self, project_dir: str, photo_dir: str, floors: List[dict], 
                 time_offset: int = 0, use_exif: bool = True, threshold: int = 30,
                 photo_base_dir: str = ""):
        super().__init__()
        self.project_dir = project_dir
        self.photo_dir = photo_dir
        self.floors = floors
        self.time_offset = time_offset
        self.use_exif = use_exif
        self.threshold = threshold
        self.photo_base_dir = photo_base_dir
        
        # 收集所有楼层的标记点
        self.markers = []
        self.floor_name_map = {}  # 楼层名到楼层数据的映射
        
        for floor in floors:
            floor_name = floor.get('name', '未知')
            floor_markers = floor.get('markers', [])
            self.floor_name_map[floor_name] = floor
            
            print(f"[升级] 楼层 {floor_name}: {len(floor_markers)} 个标记点")
            for m in floor_markers[:2]:
                print(f"[升级]   标记点: id={m.get('id')}, status={m.get('status')}")
            self.markers.extend(floor_markers)
        
        # 匹配结果追踪（防止重复关联）
        self._used_photos = set()
        # 自动计算的偏移值
        self._auto_offset = None
        
    def _parse_local_photo_name(self, filename: str) -> Optional[dict]:
        """解析本机拍摄照片文件名
        
        格式: 楼层名_点位序号_YYYYMMDD_HHMMSS.jpg
        
        Returns:
            dict: {'floor_name': str, 'marker_index': int, 'datetime': datetime}
            None: 不是本机拍摄照片格式
        """
        match = self.LOCAL_PHOTO_RE.match(filename)
        if not match:
            return None
        
        floor_name = match.group(1)
        marker_index = int(match.group(2))
        date_str = match.group(3)  # YYYYMMDD
        time_str = match.group(4)  # HHMMSS
        
        try:
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
            return {
                'floor_name': floor_name,
                'marker_index': marker_index,
                'datetime': dt
            }
        except ValueError:
            return None
    
    def _classify_photos(self, photo_files: List[str]) -> Tuple[List[dict], List[dict]]:
        """自动区分本机拍摄照片和外设拍摄照片
        
        Returns:
            (local_photos, external_photos): 两个列表，每个元素是 {path, info} 字典
        """
        local_photos = []
        external_photos = []
        
        for pf in photo_files:
            filename = os.path.basename(pf)
            parsed = self._parse_local_photo_name(filename)
            
            if parsed:
                local_photos.append({
                    'path': pf,
                    'floor_name': parsed['floor_name'],
                    'marker_index': parsed['marker_index'],
                    'datetime': parsed['datetime']
                })
                print(f"[升级] 本机拍摄: {filename} (楼层:{parsed['floor_name']}, 点位:{parsed['marker_index']})")
            else:
                # 外设照片，记录EXIF时间（无EXIF时尝试文件名提取）
                exif_time = extract_exif_datetime(pf)
                if not exif_time:
                    exif_time = extract_time_from_filename(filename)
                external_photos.append({
                    'path': pf,
                    'exif_time': exif_time
                })
                if exif_time:
                    print(f"[升级] 外设照片: {filename} (时间:{exif_time.strftime('%Y-%m-%d %H:%M:%S')})")
                else:
                    print(f"[升级] 外设照片: {filename} (无时间)")
        
        return local_photos, external_photos
    
    def _match_local_photos(self, local_photos: List[dict]) -> Dict[str, List[str]]:
        """本机拍摄照片全自动关联 - 基于时间范围匹配，一个点位可关联多张照片
        
        匹配规则:
        1. 在对应楼层中查找 startTime <= photoTime <= endTime 的点位
        2. 收集所有落在时间范围内的照片到该点位
        3. 时间范围未命中时，用点位序号兜底匹配
        
        Returns:
            Dict[marker_id, List[photo_path]]: 匹配结果
        """
        from datetime import timedelta
        match_results: Dict[str, List[str]] = {}
        
        for photo in local_photos:
            floor_name = photo['floor_name']
            marker_index = photo['marker_index']
            photo_time = photo['datetime']
            photo_path = photo['path']
            
            # 跳过已使用的照片
            if photo_path in self._used_photos:
                print(f"[升级] 跳过重复: {os.path.basename(photo_path)}")
                continue
            
            # 查找对应的楼层
            floor = self.floor_name_map.get(floor_name)
            if not floor:
                print(f"[升级] 未找到楼层: {floor_name}")
                continue
            
            markers = floor.get('markers', [])
            captured = [m for m in markers if m.get('status') == 'captured'
                        and not (m.get('panoramaPath') or m.get('originalPhotoPath'))]
            
            # 阶段1: 基于时间范围匹配（核心逻辑）
            time_matches = []
            for m in captured:
                marker = Marker.from_dict(m)
                time_range = marker.get_time_range()
                if not time_range:
                    continue
                start_time, end_time = time_range
                # 去除时区以便比较
                if start_time.tzinfo:
                    start_time = start_time.replace(tzinfo=None)
                if end_time.tzinfo:
                    end_time = end_time.replace(tzinfo=None)
                
                if start_time <= photo_time <= end_time:
                    diff = abs((photo_time - start_time).total_seconds())
                    time_matches.append((m.get('id', ''), diff, photo_path))
            
            if len(time_matches) >= 1:
                # 选择 startTime 最接近的点位
                time_matches.sort(key=lambda x: x[1])
                marker_id = time_matches[0][0]
                if marker_id not in match_results:
                    match_results[marker_id] = []
                match_results[marker_id].append(photo_path)
                self._used_photos.add(photo_path)
                print(f"[升级] 本机照片时间匹配: {os.path.basename(photo_path)} -> 标记点 {marker_id}")
                continue
            
            # 阶段2: 时间范围未命中，用点位序号兜底
            for m in captured:
                marker_id = m.get('id', '')
                custom_name = m.get('customName', '')
                marker_seq = None
                
                # 从 customName 解析序号
                if custom_name:
                    parts = custom_name.replace('-', '_').split('_')
                    for part in reversed(parts):
                        if part.isdigit():
                            marker_seq = int(part)
                            break
                
                # 从 id 解析序号
                if marker_seq is None:
                    id_parts = marker_id.split('_')
                    for part in reversed(id_parts):
                        if part.isdigit():
                            marker_seq = int(part)
                            break
                
                if marker_seq == marker_index:
                    if marker_id not in match_results:
                        match_results[marker_id] = []
                    match_results[marker_id].append(photo_path)
                    self._used_photos.add(photo_path)
                    print(f"[升级] 本机照片序号兜底: {os.path.basename(photo_path)} -> 标记点 {marker_id}")
                    break
        
        return match_results
    
    def _calculate_auto_offset(self, external_photos: List[dict], captured_markers: List[dict]) -> int:
        """自动计算外设照片的时间偏移
        
        通过比对EXIF时间和采集点时间的中位数差来计算偏移
        
        Returns:
            int: 偏移秒数
        """
        if not external_photos or not captured_markers:
            return 0
        
        # 收集EXIF时间
        exif_times = []
        for photo in external_photos:
            if photo.get('exif_time'):
                exif_times.append(photo['exif_time'])
        
        if not exif_times:
            print("[升级] 外设照片无EXIF时间，无法自动计算偏移")
            return 0
        
        # 收集采集点时间
        marker_times = []
        for m in captured_markers:
            marker = Marker.from_dict(m)
            time_range = marker.get_time_range()
            if time_range:
                start, _ = time_range
                if start.tzinfo:
                    start = start.replace(tzinfo=None)
                marker_times.append(start)
        
        if not marker_times:
            return 0
        
        # 计算中位数时间
        exif_times_sorted = sorted(exif_times)
        marker_times_sorted = sorted(marker_times)
        
        # 中位数
        mid = len(exif_times_sorted) // 2
        median_exif = exif_times_sorted[mid]
        
        mid_marker = len(marker_times_sorted) // 2
        median_marker = marker_times_sorted[mid_marker]
        
        # 计算差值（秒）
        diff_seconds = (median_exif - median_marker).total_seconds()
        
        # 四舍五入到最近的小时
        hours = round(diff_seconds / 3600)
        offset = int(hours * 3600)
        
        print(f"[升级] 自动偏移计算: EXIF中位数={median_exif.strftime('%H:%M:%S')}, "
              f"采集点中位数={median_marker.strftime('%H:%M:%S')}, "
              f"差值={diff_seconds:.0f}秒, 偏移={offset}秒 ({hours}小时)")
        
        return offset
    
    def _match_external_photos(self, external_photos: List[dict], 
                               captured_markers: List[dict], 
                               time_offset: int) -> Dict[str, List[str]]:
        """外设照片匹配 - 使用自动计算的偏移进行时间范围匹配，一个点位可关联多张照片
        
        Returns:
            Dict[marker_id, List[photo_path]]: 匹配结果
        """
        from datetime import timedelta
        
        match_results: Dict[str, List[str]] = {}
        threshold = self.threshold  # 30秒阈值
        
        for m in captured_markers:
            marker = Marker.from_dict(m)
            
            # 跳过已关联的
            if m.get('panoramaPath') or m.get('originalPhotoPath'):
                continue
            
            marker_id = marker.id
            time_range = marker.get_time_range()
            if not time_range:
                continue
            
            start_time, end_time = time_range
            
            # 应用偏移
            adjusted_start = start_time + timedelta(seconds=time_offset)
            adjusted_end = end_time + timedelta(seconds=time_offset)
            
            if adjusted_start.tzinfo:
                adjusted_start = adjusted_start.replace(tzinfo=None)
            if adjusted_end.tzinfo:
                adjusted_end = adjusted_end.replace(tzinfo=None)
            
            range_seconds = (adjusted_end - adjusted_start).total_seconds()
            center = adjusted_start + timedelta(seconds=range_seconds / 2)
            
            # 阈值策略：
            # 使用固定阈值 300 秒（与自动校准一致）
            # 确保能够匹配到照片，避免动态阈值过小导致匹配失败
            threshold = 300
            
            best_match = None
            best_diff = float('inf')
            
            for photo in external_photos:
                photo_path = photo['path']
                
                # 跳过已使用的照片
                if photo_path in self._used_photos:
                    continue
                
                exif_time = photo.get('exif_time')
                if not exif_time:
                    continue
                
                if exif_time.tzinfo:
                    exif_time = exif_time.replace(tzinfo=None)
                
                # 计算与采集时间中心的时间差
                diff = abs((exif_time - center).total_seconds())
                
                # 在阈值内且比之前找到的更好
                if diff <= threshold and diff < best_diff:
                    best_diff = diff
                    best_match = photo_path
            
            # 只返回最佳匹配（单张）
            if best_match:
                match_results[marker_id] = [best_match]
                self._used_photos.add(best_match)
                print(f"[升级] 外设照片匹配: {os.path.basename(best_match)} -> "
                      f"标记点 {marker_id}, 中心差{best_diff:.0f}秒")
        
        return match_results
    
    def run(self):
        """执行照片导入和匹配"""
        results = {
            'local_matched': 0,   # 本机拍摄直接匹配
            'external_matched': 0, # 外设照片时间匹配
            'auto_offset': 0,      # 自动计算的偏移
            'missing': 0,
            'details': []
        }
        
        # 1. 收集所有照片文件
        self.status_update.emit("正在扫描照片...")
        photo_files = []
        for root, dirs, files in os.walk(self.photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    photo_files.append(os.path.join(root, f))
        
        print(f"[升级] 扫描完成: {len(photo_files)} 张照片, {len(self.markers)} 个标记点")
        self.progress_update.emit(5, f"找到 {len(photo_files)} 张照片，正在分析...")
        
        # 2. 自动区分照片来源
        local_photos, external_photos = self._classify_photos(photo_files)
        print(f"[升级] 分类结果: 本机拍摄={len(local_photos)}, 外设照片={len(external_photos)}")
        self.progress_update.emit(10, f"本机拍摄:{len(local_photos)} 外设:{len(external_photos)}")
        
        # 3. 本机拍摄照片全自动关联
        self.status_update.emit("正在关联本机拍摄照片...")
        local_matches = self._match_local_photos(local_photos)
        print(f"[升级] 本机拍摄匹配: {len(local_matches)} 个")
        self.progress_update.emit(30, f"本机拍摄关联完成: {len(local_matches)} 个")
        
        # 4. 外设照片自动偏移计算
        captured_markers = [m for m in self.markers if m.get('status') == 'captured']
        if external_photos and captured_markers:
            self.status_update.emit("正在计算时间偏移...")
            self._auto_offset = self._calculate_auto_offset(external_photos, captured_markers)
            results['auto_offset'] = self._auto_offset
            
            if self._auto_offset != 0:
                hours = self._auto_offset / 3600
                print(f"[升级] 使用自动偏移: {self._auto_offset}秒 ({hours:+.1f}小时)")
                self.progress_update.emit(40, f"自动偏移: {hours:+.1f}小时")
            else:
                self.progress_update.emit(40, "无时间偏移")
        
        # 5. 外设照片时间匹配
        self.status_update.emit("正在关联外设照片...")
        external_matches = self._match_external_photos(
            external_photos, captured_markers, self._auto_offset or 0
        )
        print(f"[升级] 外设照片匹配: {len(external_matches)} 个")
        self.progress_update.emit(70, f"外设照片关联完成: {len(external_matches)} 个")
        
        # 6. 应用匹配结果到标记点
        total_markers = len(self.markers)
        processed = 0
        
        for idx, marker_data in enumerate(self.markers):
            marker = Marker.from_dict(marker_data)
            progress = 70 + int((idx / total_markers) * 30)
            self.progress_update.emit(progress, f"正在处理: {marker.customName or marker.id}")
            
            try:
                if marker.status != 'captured':
                    results['missing'] += 1
                    marker_data['status'] = 'missing'
                    continue
                
                marker_id = marker.id
                
                # 检查本机拍摄匹配
                if marker_id in local_matches:
                    photo_paths = local_matches[marker_id]
                    self._link_photos(photo_paths, marker)
                    marker_data['status'] = 'linked'
                    marker_data['panoramaPath'] = marker.panoramaPath
                    marker_data['originalPhotoPath'] = marker.originalPhotoPath
                    marker_data['photos'] = marker.photos
                    marker_data['cameraFileName'] = os.path.basename(photo_paths[0]) if photo_paths else ''
                    results['local_matched'] += 1
                    self.match_found.emit(marker_id, os.path.basename(photo_paths[0]) if photo_paths else '', 'local')
                    continue
                
                # 检查外设照片匹配
                if marker_id in external_matches:
                    photo_paths = external_matches[marker_id]
                    self._link_photos(photo_paths, marker)
                    marker_data['status'] = 'linked'
                    marker_data['panoramaPath'] = marker.panoramaPath
                    marker_data['originalPhotoPath'] = marker.originalPhotoPath
                    marker_data['photos'] = marker.photos
                    marker_data['cameraFileName'] = os.path.basename(photo_paths[0]) if photo_paths else ''
                    results['external_matched'] += 1
                    self.match_found.emit(marker_id, os.path.basename(photo_paths[0]) if photo_paths else '', 'external')
                    continue
                
                # 未找到匹配
                results['missing'] += 1
                marker_data['status'] = 'missing'
                
            except Exception as e:
                print(f"[错误] 处理标记点 {marker_id} 时发生异常: {e}")
                import traceback
                traceback.print_exc()
                results['missing'] += 1
                marker_data['status'] = 'missing'
            
            processed += 1
        
        # 7. 完成
        self.progress_update.emit(100, "导入完成")
        total_linked = results['local_matched'] + results['external_matched']
        self.status_update.emit(f"完成: 关联{total_linked}个，缺失{results['missing']}个")
        self.import_complete.emit(results)
    
    def _link_photos(self, photo_paths: List[str], marker: Marker):
        """关联多张照片（纯路径关联，不复制文件）"""
        rel_paths = []
        
        for source_path in photo_paths:
            try:
                abs_source = os.path.abspath(source_path)
                if self.photo_base_dir:
                    abs_base = os.path.abspath(self.photo_base_dir)
                    try:
                        if os.path.commonpath([abs_source, abs_base]) == abs_base:
                            rel_path = os.path.relpath(abs_source, abs_base)
                            rel_paths.append('external_photos/' + rel_path.replace('\\', '/'))
                        else:
                            rel_paths.append('external_photos/' + abs_source.replace('\\', '/'))
                    except ValueError:
                        rel_paths.append('external_photos/' + abs_source.replace('\\', '/'))
                else:
                    rel_paths.append('external_photos/' + abs_source.replace('\\', '/'))
            except Exception as e:
                print(f"[错误] 路径处理异常: {e}")
                rel_paths.append('external_photos/' + source_path.replace('\\', '/'))
        
        marker.photos = rel_paths
        marker.panoramaPath = rel_paths[0] if rel_paths else ""
        marker.originalPhotoPath = photo_paths[0] if photo_paths else ""
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
    marker_double_clicked = pyqtSignal(str)  # marker_id
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
        self._hovered_marker_id = None

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
        # 扩大场景矩形，允许拖动查看平面图边缘
        rect = self.pixmap_item.boundingRect()
        expanded_rect = rect.adjusted(-500, -500, 500, 500)
        self.scene.setSceneRect(expanded_rect)

        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        return True

    def add_marker(self, marker_id: str, x: float, y: float, status: str, label: str = "", direction: float = None):
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
        ellipse.setData(2, direction)  # direction，后续从marker数据设置
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
            text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # 文本不拦截鼠标
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

    def render_direction_sectors(self):
        """渲染所有标记点的扇形视线范围"""
        import math
        
        for item in list(self.scene.items()):
            if isinstance(item, QGraphicsPathItem) and item.data(0) and str(item.data(0)).endswith('_sector'):
                self.scene.removeItem(item)
        
        if not self.pixmap_item:
            return
        
        sector_angle = 90
        radius = 40
        
        for marker_id, ellipse in self.marker_items.items():
            direction = ellipse.data(2)
            if direction is None:
                continue
            try:
                direction = float(direction)
            except (TypeError, ValueError):
                continue
            
            rect = ellipse.rect()
            cx = rect.x() + rect.width() / 2
            cy = rect.y() + rect.height() / 2
            
            ang = direction
            half = sector_angle / 2
            start_ang = -(ang + half)
            
            path = QPainterPath()
            path.moveTo(cx, cy)
            
            left_rad = math.radians(start_ang)
            lx = cx + radius * math.cos(left_rad)
            ly = cy - radius * math.sin(left_rad)
            path.lineTo(lx, ly)
            
            arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            path.arcTo(arc_rect, start_ang, sector_angle)
            
            path.lineTo(cx, cy)
            
            sector = QGraphicsPathItem(path)
            sector.setBrush(QColor(0, 122, 255, 80))
            sector.setPen(QPen(QColor(255, 255, 255), 1))
            sector.setData(0, f"{marker_id}_sector")
            sector.setZValue(1)
            self.scene.addItem(sector)

    def rotate_sector(self, marker_id: str, angle_delta: float):
        """旋转扇形方向
        
        Args:
            marker_id: 标记点ID
            angle_delta: 旋转角度增量（度）
        """
        item = self.marker_items.get(marker_id)
        if not item:
            return
        
        current_direction = item.data(2)
        if current_direction is None:
            current_direction = -90.0
        
        new_direction = (current_direction + angle_delta) % 360
        if new_direction > 180:
            new_direction -= 360
        
        # 更新存储的方向
        item.setData(2, new_direction)
        
        # 重新渲染扇形
        self.render_direction_sectors()
        
        return new_direction

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            # 调整模式：记录初始位置
            if getattr(self, '_adjust_mode', False):
                self._last_adjust_pos = event.pos()
                return
            # 穿透上层扇形/文本，确保命中采集点椭圆
            target_item = None
            for item in self.items(event.pos()):
                if isinstance(item, QGraphicsEllipseItem) and item.data(0):
                    target_item = item
                    break
            if target_item:
                self._dragging_marker = target_item
                self.selected_marker_id = target_item.data(0)
                self._drag_start_pos = scene_pos
                self._drag_item_start_pos = target_item.pos()
                target_item.setCursor(Qt.CursorShape.ClosedHandCursor)
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
            rect = self.pixmap_item.boundingRect()
            new_x = max(0.0, min(1.0, scene_pos.x() / rect.width()))
            new_y = max(0.0, min(1.0, scene_pos.y() / rect.height()))
            pixel_x = new_x * rect.width()
            pixel_y = new_y * rect.height()
            radius = 8
            self._dragging_marker.setRect(pixel_x - radius, pixel_y - radius, radius * 2, radius * 2)
            return
        elif getattr(self, '_adjust_mode', False) and self.pixmap_item:
            # 调整模式：鼠标绕采集点中心旋转扇形
            marker_id = getattr(self, '_adjust_marker_id', None)
            if marker_id:
                item = self.marker_items.get(marker_id)
                if item:
                    # 获取采集点中心在场景中的位置
                    item_rect = item.rect()
                    center_x = item_rect.x() + item_rect.width() / 2
                    center_y = item_rect.y() + item_rect.height() / 2
                    
                    # 获取鼠标在场景中的位置
                    scene_pos = self.mapToScene(event.pos())
                    mouse_x = scene_pos.x()
                    mouse_y = scene_pos.y()
                    
                    # 计算鼠标相对于采集点中心的角度
                    dx = mouse_x - center_x
                    dy = mouse_y - center_y
                    
                    # 计算角度（QPainterPath坐标系：0°=右，顺时针为正）
                    import math
                    angle_rad = math.atan2(dy, dx)
                    angle_deg = math.degrees(angle_rad)
                    
                    # 转换为扇形方向角度
                    # direction: -90°=上(12点), 0°=右, 90°=下, ±180°=左
                    # math.atan2: 0°=右, 90°=下, -90°=上, ±180°=左
                    # 所以 direction = angle_deg（方向一致）
                    new_dir = angle_deg
                    
                    # 标准化到 [-180, 180]
                    if new_dir > 180:
                        new_dir -= 360
                    
                    item.setData(2, new_dir)
                    self.render_direction_sectors()
                    
                    # 通过父窗口更新方向显示
                    parent = self.parent()
                    while parent and not hasattr(parent, 'direction_label'):
                        parent = parent.parent()
                    if parent and hasattr(parent, 'direction_label'):
                        parent.direction_label.setText(f"{new_dir:.0f}°")
            return
        elif self._panning:
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            return
        else:
            # 悬停检测：指针在采集点上时变黄
            target_item = None
            for item in self.items(event.pos()):
                if isinstance(item, QGraphicsEllipseItem) and item.data(0):
                    target_item = item
                    break
            
            if target_item:
                marker_id = str(target_item.data(0))
                if self._hovered_marker_id != marker_id:
                    # 恢复上一个悬停点的颜色
                    if self._hovered_marker_id and self._hovered_marker_id in self.marker_items:
                        old_item = self.marker_items[self._hovered_marker_id]
                        old_status = old_item.data(1)
                        old_item.setBrush(QBrush(self._get_status_color(old_status)))
                    
                    self._hovered_marker_id = marker_id
                    target_item.setBrush(QBrush(QColor(255, 204, 0)))  # 黄色高亮
                    target_item.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                if self._hovered_marker_id and self._hovered_marker_id in self.marker_items:
                    old_item = self.marker_items[self._hovered_marker_id]
                    old_status = old_item.data(1)
                    old_item.setBrush(QBrush(self._get_status_color(old_status)))
                    self._hovered_marker_id = None
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

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 如果在调整模式，双击确认角度并退出
            if getattr(self, '_adjust_mode', False):
                self.marker_double_clicked.emit('__ADJUST_MODE_CONFIRM__')
                return
            
            # 穿透上层扇形/文本，确保命中采集点椭圆
            target_item = None
            for item in self.items(event.pos()):
                if isinstance(item, QGraphicsEllipseItem) and item.data(0):
                    target_item = item
                    break
            if target_item:
                self.marker_double_clicked.emit(str(target_item.data(0)))
                return
        super().mouseDoubleClickEvent(event)

    def _get_status_color(self, status: str) -> QColor:
        """根据状态返回颜色"""
        colors = {
            'pending': QColor(128, 128, 128),
            'captured': QColor(0, 122, 255),
            'linked': QColor(52, 199, 89),
            'missing': QColor(255, 59, 48)
        }
        return colors.get(status, QColor(128, 128, 128))
    
    def clear_hover(self):
        """清除悬停高亮"""
        if self._hovered_marker_id and self._hovered_marker_id in self.marker_items:
            old_item = self.marker_items[self._hovered_marker_id]
            old_status = old_item.data(1)
            old_item.setBrush(QBrush(self._get_status_color(old_status)))
            self._hovered_marker_id = None

    def contextMenuEvent(self, event):
        try:
            scene_pos = self.mapToScene(event.pos())
            # 穿透上层扇形/文本，确保能命中采集点椭圆
            target_item = None
            for item in self.items(event.pos()):
                if isinstance(item, QGraphicsEllipseItem) and item.data(0):
                    target_item = item
                    break
            if target_item:
                marker_id = str(target_item.data(0))
                if marker_id:
                    self.marker_context_menu.emit(marker_id, QPointF(event.globalPos()))
                    return
            # 点击空白处添加新采集点
            if self.pixmap_item and self.pixmap_item.contains(scene_pos):
                rect = self.pixmap_item.boundingRect()
                norm_x = max(0.0, min(1.0, scene_pos.x() / rect.width()))
                norm_y = max(0.0, min(1.0, scene_pos.y() / rect.height()))
                self.marker_add_requested.emit(norm_x, norm_y)
            else:
                self.canvas_context_menu.emit(event.globalPos())
        except Exception as e:
            print(f"[错误] contextMenuEvent 异常: {e}")
            import traceback
            traceback.print_exc()


    def wheelEvent(self, event):
        """鼠标滚轮缩放——以鼠标位置为基准点"""
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor

        # 记录缩放前鼠标位置对应的场景坐标
        mouse_pos = event.position().toPoint()
        old_scene_pos = self.mapToScene(mouse_pos)

        # 执行缩放
        self.scale(factor, factor)

        # 计算缩放后该场景坐标在视图中的新位置
        new_view_pos = self.mapFromScene(old_scene_pos)

        # 计算偏移量，使鼠标位置对应的场景点保持在原位
        delta = new_view_pos - mouse_pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())


# =============================================================================
# 主窗口
# =============================================================================

class FloatingToolbar(QFrame):
    """可拖动的悬浮快捷操作按钮栏 - 支持横向/竖向排列和按钮可见性控制"""

    BUTTON_CONFIG = {
        'relink': {'text': '重新关联', 'tooltip': '重新关联单点照片'},
        'delete': {'text': '删除当前', 'tooltip': '删除当前点位'},
        'sector': {'text': '显/隐扇形', 'tooltip': '显示/隐藏全部扇形视线'},
        'adjust': {'text': '调点方向', 'tooltip': '调整单点扇形视线方向'},
        'set_all': {'text': '调全方向', 'tooltip': '调整所有点扇形视线方向'},
    }

    # 信号：按钮点击的转发，避免按钮被重建时丢失连接
    relink_clicked = pyqtSignal()
    delete_clicked = pyqtSignal()
    sector_clicked = pyqtSignal()
    adjust_clicked = pyqtSignal()
    set_all_clicked = pyqtSignal()

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._settings = settings or self._default_settings()
        self.buttons = {}
        self._dragging = False
        self._drag_start = None
        self._init_ui()
        self._apply_style()

    def _default_settings(self):
        return {
            'visible': True,
            'orientation': 'horizontal',
            'button_visibility': {
                'relink': True, 'delete': True, 'sector': True,
                'adjust': True, 'set_all': True,
            },
            'position': {'x': 10, 'y': 70},
        }

    def get_settings(self):
        return {
            'visible': self.isVisible(),
            'orientation': self._settings.get('orientation', 'vertical'),
            'button_visibility': {
                key: btn.isVisible() for key, btn in self.buttons.items()
            },
            'position': {'x': self.x(), 'y': self.y()},
        }

    def update_settings(self, settings):
        self._settings = settings
        self._rebuild_layout()
        self._apply_style()
        self.setVisible(settings.get('visible', True))
        # 切换方向后，确保位置合理
        parent = self.parent()
        if parent:
            if self._settings.get('orientation', 'vertical') == 'horizontal':
                # 横向：底部居中
                x = 10
                y = 130
                self.move(x, y)
            else:
                # 竖向：右侧
                x = max(10, parent.width() - 90 - 10)
                self.move(x, self.y())

    def _init_ui(self):
        self._rebuild_layout()

    def _rebuild_layout(self):
        old_layout = self.layout()
        if old_layout:
            # 安全清理：先收集所有widget，移除后再deleteLater
            widgets_to_delete = []
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    widgets_to_delete.append(w)
                    w.setParent(None)
            old_layout.deleteLater()
            # 延迟删除widget，避免半销毁状态导致setStyleSheet崩溃
            for w in widgets_to_delete:
                w.deleteLater()

        orientation = self._settings.get('orientation', 'vertical')
        is_vertical = orientation == 'vertical'

        parent = self.parent()

        if is_vertical:
            layout = QVBoxLayout(self)
            # 竖向：右侧，使用当前y坐标或默认值
            if parent:
                x = max(10, parent.width() - 90 - 10)
                y = self.y() if self.y() > 0 else 70
                self.setGeometry(x, y, 90, 230)
            else:
                self.setGeometry(self.x(), self.y(), 90, 230)
        else:
            layout = QHBoxLayout(self)
            # 横向：底部居中
            if parent:
                x = 10
                y = 130
                self.setGeometry(x, y, 380, 50)
            else:
                self.setGeometry(self.x(), self.y(), 380, 50)

        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        if is_vertical:
            title = QLabel(" 快捷操作")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

        visibility = self._settings.get('button_visibility', {})
        for key, config in self.BUTTON_CONFIG.items():
            if visibility.get(key, True):
                btn = QPushButton(config['text'])
                btn.setToolTip(config['tooltip'])
                # 统一连接到内部转发器，避免外部直接连接到具体按钮实例
                btn.clicked.connect(lambda checked=False, k=key: self._on_button_clicked(k))
                layout.addWidget(btn)
                self.buttons[key] = btn

        if is_vertical:
            layout.addStretch()

        # 恢复按钮的启用状态：如果父窗口实现了 _update_floating_toolbar，让父窗口来设置状态
        parent = self.parent()
        if parent and hasattr(parent, '_update_floating_toolbar'):
            try:
                parent._update_floating_toolbar()
            except Exception:
                pass
        else:
            # 默认启用（除非父窗口在后续更新中覆盖）
            for k, b in self.buttons.items():
                b.setEnabled(True)

    def _on_button_clicked(self, key: str):
        """内部转发，请勿在外部直接连接 button.clicked 信号"""
        if key == 'relink':
            self.relink_clicked.emit()
        elif key == 'delete':
            self.delete_clicked.emit()
        elif key == 'sector':
            self.sector_clicked.emit()
        elif key == 'adjust':
            self.adjust_clicked.emit()
        elif key == 'set_all':
            self.set_all_clicked.emit()

    def set_button_enabled(self, key: str, enabled: bool):
        """由父窗口调用以设置某个按钮的启用状态。"""
        btn = self.buttons.get(key)
        if btn:
            btn.setEnabled(bool(enabled))

    def _apply_style(self):
        parent = self.parent()
        if parent and hasattr(parent, '_style_manager'):
            parent._style_manager.apply_to_widget(self)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: transparent;
                    border: none;
                }
                QLabel {
                    color: #1C1C1E;
                    font-size: 12px;
                    background-color: transparent;
                }
                QPushButton {
                    padding: 5px 8px;
                    font-size: 11px;
                    background-color: #F5F5F7;
                    color: #1C1C1E;
                    border: 1px solid #D1D1D6;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #0A84FF;
                    color: white;
                }
                QPushButton:disabled {
                    background-color: #555;
                    color: #888;
                }
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event):
        if self._dragging and self.parent():
            new_pos = self.pos() + event.pos() - self._drag_start
            max_x = self.parent().width() - self.width()
            max_y = self.parent().height() - self.height()
            new_pos.setX(max(0, min(new_pos.x(), max_x)))
            new_pos.setY(max(0, min(new_pos.y(), max_y)))
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False


class FloatingToolbarSettingsDialog(QDialog):
    """悬浮工具栏设置对话框"""
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("悬浮工具栏设置")
        self.resize(350, 400)
        self._settings = dict(current_settings)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.visible_cb = QCheckBox("显示悬浮工具栏")
        self.visible_cb.setChecked(self._settings.get('visible', True))
        layout.addWidget(self.visible_cb)

        layout.addSpacing(10)

        orient_group = QGroupBox("排列方向")
        orient_layout = QHBoxLayout(orient_group)
        self.vert_radio = QRadioButton("竖向排列")
        self.horiz_radio = QRadioButton("横向排列")
        orient_layout.addWidget(self.vert_radio)
        orient_layout.addWidget(self.horiz_radio)
        orient_layout.addStretch()

        if self._settings.get('orientation', 'vertical') == 'vertical':
            self.vert_radio.setChecked(True)
        else:
            self.horiz_radio.setChecked(True)
        layout.addWidget(orient_group)

        layout.addSpacing(10)

        btn_group = QGroupBox("显示按钮（勾选要显示的按钮）")
        btn_layout = QVBoxLayout(btn_group)
        self.btn_checks = {}
        visibility = self._settings.get('button_visibility', {})
        for key, config in FloatingToolbar.BUTTON_CONFIG.items():
            cb = QCheckBox(config['text'] + " - " + config['tooltip'])
            cb.setChecked(visibility.get(key, True))
            btn_layout.addWidget(cb)
            self.btn_checks[key] = cb
        layout.addWidget(btn_group)

        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def get_settings(self):
        return {
            'visible': self.visible_cb.isChecked(),
            'orientation': 'vertical' if self.vert_radio.isChecked() else 'horizontal',
            'button_visibility': {
                key: cb.isChecked() for key, cb in self.btn_checks.items()
            },
            'position': self._settings.get('position', {'x': 10, 'y': 70}),
        }


class StyleSettingsDialog(QDialog):
    """风格设置对话框 - 支持深色/浅色/跟随系统主题"""
    def __init__(self, current_style, parent=None):
        super().__init__(parent)
        self.setWindowTitle("界面风格设置")
        self.resize(400, 350)
        self._style = dict(current_style)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        theme_group = QGroupBox("主题模式")
        theme_layout = QVBoxLayout(theme_group)
        self.dark_radio = QRadioButton("深色模式")
        self.light_radio = QRadioButton("浅色模式")
        self.system_radio = QRadioButton("跟随系统")
        theme_layout.addWidget(self.dark_radio)
        theme_layout.addWidget(self.light_radio)
        theme_layout.addWidget(self.system_radio)

        theme = self._style.get('theme', 'dark')
        if theme == 'light':
            self.light_radio.setChecked(True)
        elif theme == 'system':
            self.system_radio.setChecked(True)
        else:
            self.dark_radio.setChecked(True)
        layout.addWidget(theme_group)

        layout.addSpacing(10)

        accent_group = QGroupBox("强调色")
        accent_layout = QHBoxLayout(accent_group)
        self.accent_combo = QComboBox()
        accent_colors = [
            ('#0A84FF', '蓝色 (默认)'),
            ('#30D158', '绿色'),
            ('#FF9500', '橙色'),
            ('#FF3B30', '红色'),
            ('#AF52DE', '紫色'),
            ('#FF2D55', '粉红'),
        ]
        for val, name in accent_colors:
            self.accent_combo.addItem(name, val)
        current_accent = self._style.get('accent_color', '#0A84FF')
        idx = self.accent_combo.findData(current_accent)
        if idx >= 0:
            self.accent_combo.setCurrentIndex(idx)
        accent_layout.addWidget(QLabel("选择强调色:"))
        accent_layout.addWidget(self.accent_combo, 1)
        layout.addWidget(accent_group)

        layout.addSpacing(10)

        radius_group = QGroupBox("界面圆角")
        radius_layout = QHBoxLayout(radius_group)
        self.radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.radius_slider.setRange(0, 20)
        self.radius_slider.setValue(self._style.get('border_radius', 8))
        self.radius_label = QLabel(f"{self.radius_slider.value()}px")
        self.radius_slider.valueChanged.connect(lambda v: self.radius_label.setText(f"{v}px"))
        radius_layout.addWidget(self.radius_slider)
        radius_layout.addWidget(self.radius_label)
        layout.addWidget(radius_group)

        layout.addStretch()

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(ok_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

    def get_style(self):
        theme = 'dark'
        if self.light_radio.isChecked():
            theme = 'light'
        elif self.system_radio.isChecked():
            theme = 'system'
        return {
            'theme': theme,
            'accent_color': self.accent_combo.currentData(),
            'border_radius': self.radius_slider.value(),
        }


class StyleManager:
    """管理器风格管理器 - 支持深色/浅色/跟随系统主题"""

    THEMES = {
        'dark': {
            'window_bg': '#1C1C1E',
            'panel_bg': '#2C2C2E',
            'card_bg': '#3A3A3C',
            'text_primary': '#FFFFFF',
            'text_secondary': '#8E8E93',
            'border': '#48484A',
            'button_bg': '#3A3A3C',
            'button_hover': '#0A84FF',
            'input_bg': '#2C2C2E',
        },
        'light': {
            'window_bg': '#F5F5F7',
            'panel_bg': '#FFFFFF',
            'card_bg': '#FFFFFF',
            'text_primary': '#1C1C1E',
            'text_secondary': '#8E8E93',
            'border': '#D1D1D6',
            'button_bg': '#007AFF',
            'button_hover': '#0056CC',
            'input_bg': '#FFFFFF',
        },
    }

    def __init__(self, app=None, style_config=None):
        self.app = app
        self._config = style_config or {'theme': 'light', 'accent_color': '#007AFF', 'border_radius': 8}
        self._current_theme = self._config.get('theme', 'light')
        self._accent = self._config.get('accent_color', '#0A84FF')
        self._radius = self._config.get('border_radius', 8)

    def update_config(self, config):
        self._config = config
        self._current_theme = config.get('theme', 'dark')
        self._accent = config.get('accent_color', '#0A84FF')
        self._radius = config.get('border_radius', 8)
        if self.app:
            self.apply_to_application()

    def get_current_colors(self):
        theme = self._current_theme
        if theme == 'system':
            import platform
            if platform.system() == 'Windows':
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                        theme = 'light' if value == 1 else 'dark'
                except:
                    theme = 'dark'
            else:
                theme = 'dark'
        return self.THEMES.get(theme, self.THEMES['dark'])

    def apply_to_application(self):
        if not self.app:
            return

        # 关键修复：清理样式缓存，避免dangling widget指针崩溃 (QTBUG-11658)
        # 在setStyleSheet之前必须unpolish，否则已销毁widget的缓存会导致SIGSEGV
        if hasattr(self.app, 'style') and self.app.style():
            try:
                self.app.style().unpolish(self.app)
            except:
                pass

        colors = self.get_current_colors()
        is_dark = self._current_theme in ('dark', 'system')

        if is_dark:
            self.app.setStyleSheet(f"""
                QMainWindow {{
                    background-color: {colors['window_bg']};
                }}
                QGroupBox {{
                    font-weight: bold;
                    border: 1px solid {colors['border']};
                    border-radius: {self._radius}px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: {colors['text_primary']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                    color: {colors['text_primary']};
                }}
                QLabel {{
                    color: {colors['text_primary']};
                }}
                # QPushButton {{
                #     border-radius: {self._radius}px;
                # }}
                QLineEdit {{
                    background-color: {colors['input_bg']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    color: {colors['text_primary']};
                    padding: 5px;
                }}
                QListWidget {{
                    background-color: {colors['panel_bg']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    color: {colors['text_primary']};
                }}
                QTableWidget {{
                    background-color: {colors['panel_bg']};
                    color: {colors['text_primary']};
                }}
                QHeaderView::section {{
                    background-color: {colors['card_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                }}
                QComboBox {{
                    background-color: {colors['input_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    padding: 4px;
                }}
                QSlider::groove:horizontal {{
                    border: 1px solid {colors['border']};
                    height: 6px;
                    background: {colors['card_bg']};
                    border-radius: 3px;
                }}
                QSlider::handle:horizontal {{
                    background: {self._accent};
                    width: 14px;
                    border-radius: 7px;
                }}
                QCheckBox {{
                    color: {colors['text_primary']};
                }}
                QRadioButton {{
                    color: {colors['text_primary']};
                }}
                QScrollArea {{
                    border: none;
                    background: transparent;
                }}
                QTextEdit {{
                    background-color: {colors['input_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                }}
            """)
        else:
            self.app.setStyleSheet(f"""
                QMainWindow {{
                    background-color: {colors['window_bg']};
                }}
                QGroupBox {{
                    font-weight: bold;
                    border: 1px solid {colors['border']};
                    border-radius: {self._radius}px;
                    margin-top: 10px;
                    padding-top: 10px;
                    color: {colors['text_primary']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                    color: {colors['text_primary']};
                }}
                QLabel {{
                    color: {colors['text_primary']};
                }}
                # QPushButton {{
                #     border-radius: {self._radius}px;
                # }}
                QLineEdit {{
                    background-color: {colors['input_bg']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    color: {colors['text_primary']};
                    padding: 5px;
                }}
                QListWidget {{
                    background-color: {colors['panel_bg']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    color: {colors['text_primary']};
                }}
                QTableWidget {{
                    background-color: {colors['panel_bg']};
                    color: {colors['text_primary']};
                }}
                QHeaderView::section {{
                    background-color: {colors['card_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                }}
                QComboBox {{
                    background-color: {colors['input_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                    padding: 4px;
                }}
                QSlider::groove:horizontal {{
                    border: 1px solid {colors['border']};
                    height: 6px;
                    background: {colors['card_bg']};
                    border-radius: 3px;
                }}
                QSlider::handle:horizontal {{
                    background: {self._accent};
                    width: 14px;
                    border-radius: 7px;
                }}
                QCheckBox {{
                    color: {colors['text_primary']};
                }}
                QRadioButton {{
                    color: {colors['text_primary']};
                }}
                QScrollArea {{
                    border: none;
                    background: transparent;
                }}
                QTextEdit {{
                    background-color: {colors['input_bg']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border']};
                    border-radius: 4px;
                }}
            """)

        palette = self.app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(colors['window_bg']))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(colors['text_primary']))
        palette.setColor(QPalette.ColorRole.Base, QColor(colors['panel_bg']))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors['card_bg']))
        palette.setColor(QPalette.ColorRole.Text, QColor(colors['text_primary']))
        palette.setColor(QPalette.ColorRole.Button, QColor(colors['button_bg']))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors['text_primary']))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(self._accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor('#FFFFFF'))
        self.app.setPalette(palette)

        # 直接应用样式表和调色板（已在前面调用 setStyleSheet）
        # 注意：已在 setStyleSheet 之前尝试 unpolish 应用，避免未销毁 widget 导致的内部崩溃

        

    def apply_to_widget(self, widget):
        colors = self.get_current_colors()
        is_dark = self._current_theme in ('dark', 'system')

        if isinstance(widget, QFrame):
            if is_dark:
                widget.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba(28, 28, 30, 0.92);
                        border: 1px solid {colors['border']};
                        border-radius: {self._radius}px;
                    }}
                    QLabel {{
                        color: {colors['text_primary']};
                        font-size: 12px;
                    }}
                    QPushButton {{
                        padding: 5px 8px;
                        font-size: 11px;
                        background-color: {colors['card_bg']};
                        color: {colors['text_primary']};
                        border: none;
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {self._accent};
                    }}
                    QPushButton:disabled {{
                        background-color: #555;
                        color: #888;
                    }}
                """)
            else:
                widget.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba(255, 255, 255, 0.95);
                        border: 1px solid {colors['border']};
                        border-radius: {self._radius}px;
                    }}
                    QLabel {{
                        color: {colors['text_primary']};
                        font-size: 12px;
                    }}
                    QPushButton {{
                        padding: 5px 8px;
                        font-size: 11px;
                        background-color: {colors['card_bg']};
                        color: {colors['text_primary']};
                        border: 1px solid {colors['border']};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{
                        background-color: {self._accent};
                        color: white;
                    }}
                    QPushButton:disabled {{
                        background-color: #CCC;
                        color: #888;
                    }}
                """)


class PanoramaManager(QMainWindow):
    # 方向更新信号（从HTTP服务器线程传递到主线程）
    direction_update = pyqtSignal(str, float)
    
    def _cache_bust_url(self, base_url: str) -> str:
        """给URL加上时间戳参数，避免浏览器缓存"""
        import time
        return f"{base_url}?v={int(time.time())}"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("随系 · 影像管理器")
        self.setGeometry(100, 100, 1400, 900)
        
        self.project_dir: Optional[str] = None
        self.project_data: Optional[Project] = None
        self.server_thread: Optional[HttpServerThread] = None
        self.current_floor_id: Optional[str] = None
        
        # 快捷键配置
        self._shortcuts = self._load_shortcuts()
        # 风格管理器
        self._style_config = self._load_style_config()
        self._style_manager = StyleManager(None, self._style_config)
        # 悬浮工具栏设置
        self._toolbar_settings = self._load_toolbar_settings()

        # 撤销/重做栈
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        # 上一个命令记录（空格重复用）
        self._last_command = None
        
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
        self.canvas.marker_double_clicked.connect(self._on_marker_double_clicked)
        left_layout.addWidget(self.canvas)
        
        # 悬浮快捷按钮栏（使用信号转发，避免按钮重建时丢失连接）
        self.floating_toolbar = FloatingToolbar(left_panel, self._toolbar_settings)
        # 连接到 FloatingToolbar 的转发信号（稳定，不随按钮重建而变化）
        self.floating_toolbar.relink_clicked.connect(
            lambda: self._relink_marker_photo(self.current_marker.id) if hasattr(self, 'current_marker') and self.current_marker else None
        )
        self.floating_toolbar.delete_clicked.connect(self._delete_current_marker)
        self.floating_toolbar.sector_clicked.connect(self._toggle_sector)
        self.floating_toolbar.adjust_clicked.connect(
            lambda: self._toggle_adjust_mode(self.current_marker.id) if hasattr(self, 'current_marker') and self.current_marker else None
        )
        self.floating_toolbar.set_all_clicked.connect(self._set_all_sectors_direction)
        
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
                padding: 6px 12px;
                font-size: 13px;
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
        
        # 一键锚点按钮 - 手动指定锚点照片
        self.one_key_anchor_btn = QPushButton("⚓ 一键锚点")
        self.one_key_anchor_btn.setEnabled(False)
        self.one_key_anchor_btn.setToolTip("手动指定锚点照片，用于校准时间偏移\n适用于外设拍摄照片的自动关联")
        self.one_key_anchor_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                font-size: 13px;
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.one_key_anchor_btn.clicked.connect(self._one_key_anchor)
        actions_layout.addWidget(self.one_key_anchor_btn)
        
        self.generate_viewer_btn = QPushButton("🌐 生成本地网页")
        self.generate_viewer_btn.setEnabled(False)
        self.generate_viewer_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                font-size: 13px;
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
                padding: 6px 12px;
                font-size: 13px;
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
                padding: 6px 12px;
                font-size: 13px;
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
                padding: 6px 12px;
                font-size: 13px;
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
                padding: 6px 12px;
                font-size: 13px;
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

        # 服务器信息展开按钮（默认隐藏服务器信息）
        self.toggle_server_info_btn = QPushButton("📡 显示服务器信息")
        self.toggle_server_info_btn.setEnabled(False)  # 服务器启动后才可用
        self.toggle_server_info_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px;
                font-size: 13px;
                background-color: #5AC8FA;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #4CA0D0; }
            QPushButton:disabled { background-color: #CCC; }
        """)
        self.toggle_server_info_btn.clicked.connect(self._toggle_server_info)
        actions_layout.addWidget(self.toggle_server_info_btn)

        # 导入状态显示
        actions_layout.addSpacing(10)
        self.import_status_label = QLabel("就绪")
        self.import_status_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-size: 12px;
                padding: 5px;
                background-color: #f5f5f5;
                border-radius: 4px;
            }
        """)
        self.import_status_label.setWordWrap(True)
        actions_layout.addWidget(self.import_status_label)
        
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
        self.marker_filename_edit = QLineEdit("-")
        self.marker_filename_edit.setReadOnly(True)
        self.marker_filename_edit.setStyleSheet("""
            QLineEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        marker_info_layout.addWidget(self.marker_filename_edit, 2, 1)
        
        self.open_photo_folder_btn = QPushButton("📂 打开所在文件夹")
        self.open_photo_folder_btn.setStyleSheet("""
            QPushButton {
                padding: 6px;
                font-size: 12px;
                background-color: #0a84ff;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0866c6; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.open_photo_folder_btn.clicked.connect(self._open_photo_folder)
        self.open_photo_folder_btn.setEnabled(False)
        marker_info_layout.addWidget(self.open_photo_folder_btn, 3, 0, 1, 2)
        
        marker_info_layout.addWidget(QLabel("自定义名称:"), 4, 0)
        custom_name_layout = QHBoxLayout()
        self.marker_custom_name = QLineEdit()
        self.marker_custom_name.editingFinished.connect(self._update_marker_name)
        custom_name_layout.addWidget(self.marker_custom_name)
        
        self.pick_photo_btn = QPushButton("📷 选择照片")
        self.pick_photo_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px;
                font-size: 12px;
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #248A3D; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.pick_photo_btn.clicked.connect(self._show_photo_picker)
        self.pick_photo_btn.setEnabled(False)
        custom_name_layout.addWidget(self.pick_photo_btn)
        marker_info_layout.addLayout(custom_name_layout, 4, 1)
        
        marker_info_layout.addWidget(QLabel("坐标:"), 5, 0)
        self.marker_coord_label = QLabel("-")
        marker_info_layout.addWidget(self.marker_coord_label, 5, 1)
        
        # 照片预览框
        marker_info_layout.addWidget(QLabel("照片预览:"), 6, 0)
        self.photo_preview = QLabel("无照片")
        self.photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_preview.setMinimumSize(200, 150)
        self.photo_preview.setMaximumSize(200, 150)
        self.photo_preview.setStyleSheet("""
            QLabel {
                background-color: #1C1C1E;
                border: 2px solid #ddd;
                border-radius: 8px;
                color: #999;
                font-size: 12px;
            }
        """)
        marker_info_layout.addWidget(self.photo_preview, 6, 1)
        
        # 照片预览提示文字
        self.photo_preview_hint = QLabel("💡 对比扇形方向与全景内容是否对齐")
        self.photo_preview_hint.setStyleSheet("color: #999; font-size: 11px; padding: 2px;")
        marker_info_layout.addWidget(self.photo_preview_hint, 7, 1)
        
        # 视线方向控制
        marker_info_layout.addWidget(QLabel("视线方向:"), 8, 0)
        self.direction_label = QLabel("-90°")
        self.direction_label.setStyleSheet("font-weight: bold; color: #0A84FF; font-size: 14px;")
        marker_info_layout.addWidget(self.direction_label, 8, 1)
        
        # 旋转按钮组
        rotate_layout = QHBoxLayout()
        
        self.rotate_left_btn = QPushButton("↺ 左转")
        self.rotate_left_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px;
                font-size: 12px;
                background-color: #3A3A3C;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #48484A; }
        """)
        self.rotate_left_btn.clicked.connect(lambda: self._rotate_sector(-15))
        rotate_layout.addWidget(self.rotate_left_btn)
        
        self.rotate_right_btn = QPushButton("右转 ↻")
        self.rotate_right_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px;
                font-size: 12px;
                background-color: #3A3A3C;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #48484A; }
        """)
        self.rotate_right_btn.clicked.connect(lambda: self._rotate_sector(15))
        rotate_layout.addWidget(self.rotate_right_btn)
        
        marker_info_layout.addLayout(rotate_layout, 9, 1)
        
        # 对齐全景按钮
        self.align_panorama_btn = QPushButton("🎯 对齐全景")
        self.align_panorama_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px;
                font-size: 13px;
                background-color: #FF9500;
                color: white;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.align_panorama_btn.clicked.connect(self._align_to_panorama)
        marker_info_layout.addWidget(self.align_panorama_btn, 10, 0, 1, 2)
        
        self.delete_marker_btn = QPushButton("🗑️ 删除当前点位")
        self.delete_marker_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                font-size: 13px;
                background-color: #FF3B30;
                color: white;
                border: none;
                border-radius: 6px;
                margin-top: 8px;
            }
            QPushButton:hover { background-color: #B32418; }
        """)
        self.delete_marker_btn.clicked.connect(self._delete_current_marker)
        marker_info_layout.addWidget(self.delete_marker_btn, 11, 0, 1, 2)
        
        self.marker_info_group.setEnabled(False)
        self.marker_info_group.setCheckable(True)
        self.marker_info_group.setChecked(False)
        self.marker_info_group.toggled.connect(self._on_marker_info_group_toggled)
        right_layout.addWidget(self.marker_info_group)
        # 初始隐藏组内控件
        self._on_marker_info_group_toggled(False)

        # 已关联照片列表
        self.linked_photos_group = QGroupBox("已关联照片")
        self.linked_photos_group.setCheckable(True)
        self.linked_photos_group.setChecked(False)
        self.linked_photos_group.toggled.connect(self._on_linked_photos_group_toggled)
        # 后续继续原有布局...
        linked_photos_layout = QVBoxLayout(self.linked_photos_group)
        ...
        right_layout.addWidget(self.linked_photos_group)
        self._on_linked_photos_group_toggled(False)
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
        
        # 连接方向更新信号（从HTTP服务器线程传递到主线程）
        self.direction_update.connect(self._on_direction_update_from_web)
        
        right_layout.addStretch()
        
        splitter.addWidget(right_panel)
        right_panel.setMinimumWidth(420)
        splitter.setSizes([900, 500])
    
    def _get_history_file(self) -> str:
        """获取历史记录文件路径"""
        history_dir = os.path.join(os.path.expanduser('~'), '.panorama_manager')
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, 'history.json')
    
    # -------------------------------------------------------------------------
    # 快捷键配置
    # -------------------------------------------------------------------------
    
    def _default_shortcuts(self) -> dict:
        return {
            'delete': 'Delete',
            'undo': 'Ctrl+Z',
            'redo': 'Ctrl+Y',
            'repeat': 'Space',
            'relink': '',
            'toggle_sector': '',
            'adjust_mode': '',
            'set_all_direction': '',
            'align_panorama': '',
            'rotate_left': '',
            'rotate_right': '',
        }
    
    def _get_shortcuts_file(self) -> str:
        history_dir = os.path.join(os.path.expanduser('~'), '.panorama_manager')
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, 'shortcuts.json')
    
    def _load_shortcuts(self) -> dict:
        path = self._get_shortcuts_file()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                defaults = self._default_shortcuts()
                defaults.update(loaded)
                return defaults
            except Exception as e:
                print(f"[警告] 加载快捷键配置失败: {e}")
        return self._default_shortcuts()
    
    def _save_shortcuts(self):
        path = self._get_shortcuts_file()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._shortcuts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[警告] 保存快捷键配置失败: {e}")
    
    def _show_shortcut_settings(self):
        dialog = ShortcutDialog(self._shortcuts, self)
        if dialog.exec():
            self._shortcuts = dialog.get_shortcuts()
            self._save_shortcuts()
            QMessageBox.information(self, "保存成功", "快捷键设置已保存，下次启动自动生效")
    
    def _export_shortcuts(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出快捷键配置", "shortcuts.json", "JSON (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self._shortcuts, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "成功", f"已导出到:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {e}")
    
    def _import_shortcuts(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入快捷键配置", "", "JSON (*.json)")
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                for k in self._shortcuts:
                    if k in loaded:
                        self._shortcuts[k] = loaded[k]
                self._save_shortcuts()
                QMessageBox.information(self, "成功", "快捷键配置已导入并保存")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入失败: {e}")
    
    def _match_shortcut(self, event, shortcut_str: str) -> bool:
        if not shortcut_str:
            return False
        parts = [p.strip().lower() for p in shortcut_str.split('+')]
        mods = Qt.KeyboardModifier.NoModifier
        key_name = None
        for p in parts:
            if p == 'ctrl':
                mods |= Qt.KeyboardModifier.ControlModifier
            elif p == 'shift':
                mods |= Qt.KeyboardModifier.ShiftModifier
            elif p == 'alt':
                mods |= Qt.KeyboardModifier.AltModifier
            elif p == 'meta':
                mods |= Qt.KeyboardModifier.MetaModifier
            else:
                key_name = p
        if not key_name:
            return False
        key_map = {
            'space': Qt.Key.Key_Space,
            'delete': Qt.Key.Key_Delete,
            'return': Qt.Key.Key_Return,
            'enter': Qt.Key.Key_Enter,
            'esc': Qt.Key.Key_Escape,
            'tab': Qt.Key.Key_Tab,
            'backspace': Qt.Key.Key_Backspace,
            'up': Qt.Key.Key_Up,
            'down': Qt.Key.Key_Down,
            'left': Qt.Key.Key_Left,
            'right': Qt.Key.Key_Right,
            'home': Qt.Key.Key_Home,
            'end': Qt.Key.Key_End,
            'pageup': Qt.Key.Key_PageUp,
            'pagedown': Qt.Key.Key_PageDown,
            'insert': Qt.Key.Key_Insert,
        }
        if key_name in key_map:
            target_key = key_map[key_name]
        else:
            attr_name = f'Key_{key_name[0].upper()}{key_name[1:]}' if len(key_name) > 1 else f'Key_{key_name.upper()}'
            target_key = getattr(Qt.Key, attr_name, None)
            if target_key is None:
                return False
        return event.key() == target_key and event.modifiers() == mods
    
    # -------------------------------------------------------------------------
    # 撤销 / 重做 / 命令重复
    # -------------------------------------------------------------------------
    
    def _push_history(self):
        """保存当前项目状态到撤销栈"""
        if not self.project_data:
            return
        import copy
        state = copy.deepcopy(self.project_data.to_dict())
        self._undo_stack.append(state)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
    
    def _undo(self):
        """撤销上一次编辑"""
        if not self._undo_stack or not self.project_data:
            return
        import copy
        current_state = copy.deepcopy(self.project_data.to_dict())
        self._redo_stack.append(current_state)
        prev_state = self._undo_stack.pop()
        self.project_data = Project.from_dict(prev_state)
        self._save_project()
        self._refresh_markers()
        self.import_status_label.setText("↩️ 已撤销")
        self.canvas.clear_hover()
    
    def _redo(self):
        """重做上一次撤销"""
        if not self._redo_stack or not self.project_data:
            return
        import copy
        current_state = copy.deepcopy(self.project_data.to_dict())
        self._undo_stack.append(current_state)
        next_state = self._redo_stack.pop()
        self.project_data = Project.from_dict(next_state)
        self._save_project()
        self._refresh_markers()
        self.import_status_label.setText("↪️ 已重做")
        self.canvas.clear_hover()
    
    def _record_command(self, name: str, *args, **kwargs):
        """记录上一个可重复命令"""
        self._last_command = (name, args, kwargs)
    
    def _repeat_last_command(self):
        """空格重复上一个命令"""
        if not self._last_command:
            return
        name, args, kwargs = self._last_command
        if name == '_delete_current_marker':
            self._delete_current_marker()
        elif name == '_delete_marker' and args:
            self._delete_marker(args[0])
        elif name == '_relink_marker_photo':
            if hasattr(self, 'current_marker') and self.current_marker:
                self._relink_marker_photo(self.current_marker.id)
        elif name == '_toggle_sector':
            self._toggle_sector()
        elif name == '_toggle_adjust_mode':
            if hasattr(self, 'current_marker') and self.current_marker:
                self._toggle_adjust_mode(self.current_marker.id)
        elif name == '_set_all_sectors_direction':
            self._set_all_sectors_direction()
        elif name == '_rotate_sector' and args:
            self._rotate_sector(args[0])
        elif name == '_align_to_panorama':
            self._align_to_panorama()
        elif name == '_link_photo_to_marker' and len(args) >= 2:
            self._link_photo_to_marker(args[0], args[1])
        elif name == '_update_marker_name':
            self._update_marker_name()
        elif name == '_on_marker_add_requested' and len(args) >= 2:
            self._on_marker_add_requested(args[0], args[1])
    
    def _update_floating_toolbar(self):
        """更新悬浮按钮状态"""
        has_marker = hasattr(self, 'current_marker') and self.current_marker is not None
        if 'relink' in self.floating_toolbar.buttons:
            self.floating_toolbar.buttons['relink'].setEnabled(has_marker)
        if 'delete' in self.floating_toolbar.buttons:
            self.floating_toolbar.buttons['delete'].setEnabled(has_marker)
        if 'adjust' in self.floating_toolbar.buttons:
            self.floating_toolbar.buttons['adjust'].setEnabled(has_marker)

    # -------------------------------------------------------------------------
    # 悬浮工具栏设置
    # -------------------------------------------------------------------------

    def _get_toolbar_settings_file(self) -> str:
        history_dir = os.path.join(os.path.expanduser('~'), '.panorama_manager')
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, 'toolbar_settings.json')

    def _load_toolbar_settings(self) -> dict:
        path = self._get_toolbar_settings_file()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[警告] 加载工具栏设置失败: {e}")
        return FloatingToolbar._default_settings(FloatingToolbar)

    def _save_toolbar_settings(self):
        path = self._get_toolbar_settings_file()
        try:
            settings = self.floating_toolbar.get_settings()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[警告] 保存工具栏设置失败: {e}")

    def _show_toolbar_settings(self):
        dialog = FloatingToolbarSettingsDialog(self._toolbar_settings, self)
        if dialog.exec():
            self._toolbar_settings = dialog.get_settings()
            self.floating_toolbar.update_settings(self._toolbar_settings)
            self._save_toolbar_settings()
            QMessageBox.information(self, "保存成功", "悬浮工具栏设置已保存")

    # -------------------------------------------------------------------------
    # 风格设置
    # -------------------------------------------------------------------------

    def _get_style_config_file(self) -> str:
        history_dir = os.path.join(os.path.expanduser('~'), '.panorama_manager')
        os.makedirs(history_dir, exist_ok=True)
        return os.path.join(history_dir, 'style_config.json')

    def _load_style_config(self) -> dict:
        path = self._get_style_config_file()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[警告] 加载风格配置失败: {e}")
        return {'theme': 'light', 'accent_color': '#007AFF', 'border_radius': 8}

    def _save_style_config(self):
        path = self._get_style_config_file()
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self._style_config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[警告] 保存风格配置失败: {e}")

    def _show_style_settings(self):
        dialog = StyleSettingsDialog(self._style_config, self)
        if dialog.exec(): 
            self._style_config = dialog.get_style()
            self._style_manager.update_config(self._style_config)
            # 应用风格到应用
            app = QApplication.instance()
            if app:
                self._style_manager.app = app
                self._style_manager.apply_to_application()
            self._save_style_config()
            QMessageBox.information(self, "保存成功", "风格设置已保存，部分更改需要重启后完全生效")

    def _apply_current_style(self):
        """应用当前风格到应用"""
        app = QApplication.instance()
        if app and self._style_manager:
            self._style_manager.app = app
            self._style_manager.apply_to_application()
            # 重新应用悬浮工具栏风格
            self.floating_toolbar._apply_style()
    
    # -------------------------------------------------------------------------
    # 键盘事件
    # -------------------------------------------------------------------------
    
    def keyPressEvent(self, event):
        # 如果当前焦点在文本输入框，不拦截
        focused = QApplication.instance().focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit)):
            super().keyPressEvent(event)
            return
        
        shortcuts = self._shortcuts
        
        if self._match_shortcut(event, shortcuts.get('delete', 'Delete')):
            self._delete_current_marker()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('undo', 'Ctrl+Z')):
            self._undo()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('redo', 'Ctrl+Y')):
            self._redo()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('repeat', 'Space')):
            self._repeat_last_command()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('relink', '')):
            if hasattr(self, 'current_marker') and self.current_marker:
                self._relink_marker_photo(self.current_marker.id)
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('toggle_sector', '')):
            self._toggle_sector()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('adjust_mode', '')):
            if hasattr(self, 'current_marker') and self.current_marker:
                self._toggle_adjust_mode(self.current_marker.id)
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('set_all_direction', '')):
            self._set_all_sectors_direction()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('align_panorama', '')):
            self._align_to_panorama()
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('rotate_left', '')):
            self._rotate_sector(-15)
            event.accept()
            return
        elif self._match_shortcut(event, shortcuts.get('rotate_right', '')):
            self._rotate_sector(15)
            event.accept()
            return
        
        super().keyPressEvent(event)
    
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
        
        shortcut_action = QAction("快捷键设置(&K)...", self)
        shortcut_action.setShortcut("Ctrl+K")
        shortcut_action.triggered.connect(self._show_shortcut_settings)
        tools_menu.addAction(shortcut_action)
        
        export_shortcut_action = QAction("导出快捷键配置(&E)...", self)
        export_shortcut_action.triggered.connect(self._export_shortcuts)
        tools_menu.addAction(export_shortcut_action)
        
        import_shortcut_action = QAction("导入快捷键配置(&M)...", self)
        import_shortcut_action.triggered.connect(self._import_shortcuts)
        tools_menu.addAction(import_shortcut_action)
        
        
        tools_menu.addSeparator()

        toolbar_settings_action = QAction("悬浮工具栏设置(&B)...", self)
        toolbar_settings_action.triggered.connect(self._show_toolbar_settings)
        tools_menu.addAction(toolbar_settings_action)

        style_settings_action = QAction("界面风格设置(&S)...", self)
        style_settings_action.triggered.connect(self._show_style_settings)
        tools_menu.addAction(style_settings_action)
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
            
            # 设置项目目录为解压目录
            self.project_dir = extract_dir
            
            # 检查并设置照片基目录（查找同级目录下的常见照片文件夹）
            zip_parent_dir = os.path.dirname(file_path)
            photo_base_dir = self._find_photo_base_dir(zip_parent_dir)
            if photo_base_dir:
                self.project_data.photoBaseDir = photo_base_dir
                self._save_project()
                print(f"[调试] 自动设置照片基目录: {photo_base_dir}")
            
            # 添加到历史记录
            if self.project_data:
                self._add_to_history(self.project_dir, self.project_data.projectName)
            
            # 显示成功提示
            photo_hint = f"\n\n照片基目录: {photo_base_dir}" if photo_base_dir else "\n\n未找到照片文件夹，请手动设置"
            QMessageBox.information(
                self, 
                "导入成功", 
                f"项目已导入并自动选择:\n{extract_dir}{photo_hint}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {str(e)}")
    
    def import_from_folder(self):
        """从文件夹导入项目 - 自动识别ZIP和照片文件夹（适配手机本机拍摄）"""
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
            
            # 自动扫描常见照片目录（DCIM, Photos, Camera, 图片等）
            common_photo_dirs = ['DCIM', 'Photos', 'Camera', '图片', '照片', '相册', 'Pictures']
            for common_name in common_photo_dirs:
                common_path = os.path.join(dir_path, common_name)
                if os.path.isdir(common_path) and common_path not in [p[0] for p in photo_dirs]:
                    jpg_count = 0
                    for root, dirs, files in os.walk(common_path):
                        for f in files:
                            if f.lower().endswith(('.jpg', '.jpeg')):
                                jpg_count += 1
                        if jpg_count > 0:
                            break
                    if jpg_count > 0:
                        photo_dirs.append((common_path, jpg_count))
            
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
            
            # 为所有楼层中完全没有 direction 字段或 direction 为 null 的点位设置默认值
            # 已有 direction 值的保持不变，以项目数据为准
            for floor_data in self.project_data.floors:
                for marker_data in floor_data.get('markers', []):
                    if 'direction' not in marker_data or marker_data.get('direction') is None:
                        marker_data['direction'] = -90.0
                        print(f"[调试] 点位 {marker_data.get('customName') or marker_data.get('id')} 无 direction，设为默认 -90°")
                    else:
                        print(f"[调试] 点位 {marker_data.get('customName') or marker_data.get('id')} 已有 direction={marker_data.get('direction')}°，保持不变")
            
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
            self.one_key_anchor_btn.setEnabled(True)
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
        """自动校准完成回调 - 自动应用并导入，减少弹窗干扰"""
        print(f"[调试] 自动校准完成: 建议偏移={suggested_offset}秒, 匹配={matched_count}/{total_count}")
        
        photo_dir = getattr(self, '_pending_photo_dir', None)
        THRESHOLD_SECONDS = 172800  # 48小时异常阈值
        
        # 如果有建议的校准值且与当前不同，自动应用
        if suggested_offset != 0 and suggested_offset != self.project_data.timeOffset:
            hours = abs(suggested_offset) // 3600
            minutes = (abs(suggested_offset) % 3600) // 60
            
            # 自动应用校准值
            self.project_data.timeOffset = suggested_offset
            self._save_project()
            
            # 更新显示
            if suggested_offset > 0:
                calib_text = f"+{suggested_offset}秒 (相机快)"
            else:
                calib_text = f"{suggested_offset}秒 (相机慢)"
            self.calibration_label.setText(calib_text)
            
            # 仅当偏移超过48小时才弹出异常提示
            if abs(suggested_offset) > THRESHOLD_SECONDS:
                time_diff_str = f"{hours}小时" if hours > 0 else f"{minutes}分钟"
                if hours > 0 and minutes > 0:
                    time_diff_str = f"{hours}小时{minutes}分钟"
                confirm = QMessageBox.question(
                    self, "异常时间偏移",
                    f"检测到相机时间与手机时间相差约 {time_diff_str}（{suggested_offset} 秒），\n"
                    f"远超正常范围（48小时）。\n\n"
                    f"这可能是由于：\n"
                    f"1. 相机时区设置错误\n"
                    f"2. 相机日期/时间未调整\n"
                    f"3. 照片来源不正确\n\n"
                    f"是否仍要使用此偏移值继续导入？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    self.project_data.timeOffset = 0
                    self._save_project()
                    self.calibration_label.setText("未校准")
                    print("[调试] 用户拒绝异常偏移，重置为0")
                    return
        else:
            # 无需校准或校准值为0，静默继续
            if suggested_offset == 0 and matched_count == 0:
                print("[调试] 无法提取有效时间信息，将使用当前校准值继续导入")
            else:
                print(f"[调试] 时间校准分析完成，匹配 {matched_count}/{total_count}，无需调整")
        
        # 自动开始导入
        if photo_dir:
            self._start_import(photo_dir, self.project_data.timeOffset)
    
    def _start_import(self, photo_dir: str, time_offset: int):
        """开始导入照片 - 适配手机本机拍摄，使用更宽松的阈值"""
        # 创建进度对话框
        self.progress_dialog = QProgressDialog("正在扫描照片...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("导入照片")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()
        
        # 判断照片来源类型，设置合适的匹配阈值
        # 手机本机拍摄通常需要更多时间调整位置，使用更宽松的阈值
        threshold = self._detect_photo_source_threshold(photo_dir)
        
        # 启动导入线程
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '') or photo_dir
        self.import_thread = PhotoImportThread(
            self.project_dir, photo_dir, self.project_data.floors, 
            time_offset, use_exif=True, threshold=threshold,
            photo_base_dir=photo_base_dir
        )
        self.import_thread.progress_update.connect(self._on_import_progress)
        self.import_thread.status_update.connect(self._on_import_status_update)
        self.import_thread.import_complete.connect(self._on_import_complete)
        self.import_thread.start()
    
    def _detect_photo_source_threshold(self, photo_dir: str) -> int:
        """根据照片命名特征检测来源类型，返回合适的匹配阈值（秒）
        
        手机本机拍摄：600秒（10分钟）- 用户需要调整位置、角度
        专业全景相机：300秒（5分钟）- 操作更快速专业
        """
        sample_files = []
        for root, dirs, files in os.walk(photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg')):
                    sample_files.append(f)
            if len(sample_files) >= 10:
                break
        
        if not sample_files:
            return 300  # 默认阈值
        
        # 统计各种命名特征
        phone_patterns = 0
        camera_patterns = 0
        
        for f in sample_files[:20]:  # 检查前20个样本
            name_lower = f.lower()
            # 手机特征
            if any(p in name_lower for p in ['img_', 'screenshot', 'wx_camera', 'dcim', 'camera']):
                phone_patterns += 1
            # 专业相机特征
            elif any(p in name_lower for p in ['cam_', 'dji', 'gopro', 'panorama']):
                camera_patterns += 1
        
        # 如果超过50%是手机命名特征，使用更宽松的阈值
        total_checked = len(sample_files[:20])
        if phone_patterns / total_checked > 0.3:
            print(f"[调试] 检测到手机拍摄照片，使用宽松阈值 600 秒")
            return 600
        
        print(f"[调试] 使用标准阈值 300 秒")
        return 300
    
    def _on_import_progress(self, progress: int, message: str):
        """导入进度更新"""
        self.progress_dialog.setValue(progress)
        self.progress_dialog.setLabelText(message)
    
    def _on_import_status_update(self, status: str):
        """导入状态更新"""
        if hasattr(self, 'import_status_label'):
            self.import_status_label.setText(status)
    
    def _one_key_anchor(self):
        """一键锚点 - 手动指定锚点照片来校准时间偏移
        
        流程:
        1. 选择照片目录（如果没有已选目录）
        2. 选择一个锚点照片（外设拍摄）
        3. 选择对应的采集点位
        4. 自动计算偏移
        5. 重新运行导入
        """
        if not self.project_data:
            QMessageBox.warning(self, "提示", "请先打开项目")
            return
        
        # 1. 确定照片目录
        photo_dir = getattr(self, '_pending_photo_dir', None)
        if not photo_dir:
            photo_dir = getattr(self.project_data, 'photoDir', None)
        
        if not photo_dir:
            photo_dir = QFileDialog.getExistingDirectory(
                self, "选择照片文件夹"
            )
            if not photo_dir:
                return
            self._pending_photo_dir = photo_dir
        
        # 2. 选择锚点照片
        photo_path, _ = QFileDialog.getOpenFileName(
            self, "选择锚点照片（外设拍摄）",
            photo_dir,
            "图片文件 (*.jpg *.jpeg *.png)"
        )
        if not photo_path:
            return
        
        # 3. 获取锚点照片的EXIF时间
        from PIL import Image
        from PIL.ExifTags import TAGS
        anchor_exif_time = None
        try:
            img = Image.open(photo_path)
            exif_data = img._getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == 'DateTimeOriginal':
                        anchor_exif_time = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        break
        except Exception as e:
            print(f"[锚点] 获取EXIF时间失败: {e}")
        
        if not anchor_exif_time:
            QMessageBox.warning(self, "错误", "无法读取照片EXIF时间")
            return
        
        # 4. 选择对应的采集点位（从captured状态的点位中选择）
        captured_markers = []
        for floor in self.project_data.floors:
            for m in floor.get('markers', []):
                if m.get('status') == 'captured':
                    captured_markers.append(m)
        
        if not captured_markers:
            QMessageBox.warning(self, "错误", "没有已采集的点位可供选择")
            return
        
        # 创建选择对话框
        from PyQt6.QtWidgets import QInputDialog
        marker_names = []
        marker_map = {}
        for m in captured_markers:
            name = m.get('customName', m.get('id', '未知'))
            time_info = m.get('captureTime', m.get('startTime', ''))
            label = f"{name} ({time_info})" if time_info else name
            marker_names.append(label)
            marker_map[label] = m
        
        selected, ok = QInputDialog.getItem(
            self, "选择锚点点位",
            "请选择与该照片对应的采集点位:",
            marker_names, 0, False
        )
        if not ok or not selected:
            return
        
        selected_marker = marker_map[selected]
        
        # 5. 获取点位时间
        marker_time = None
        marker = Marker.from_dict(selected_marker)
        time_range = marker.get_time_range()
        if time_range:
            marker_time = time_range[0]
            if marker_time.tzinfo:
                marker_time = marker_time.replace(tzinfo=None)
        
        if not marker_time:
            QMessageBox.warning(self, "错误", "无法获取点位时间信息")
            return
        
        # 6. 计算偏移
        offset_seconds = (anchor_exif_time - marker_time).total_seconds()
        hours = round(offset_seconds / 3600)
        offset_hours = int(hours * 3600)
        
        print(f"[锚点] 计算偏移: 照片时间={anchor_exif_time}, 点位时间={marker_time}, 偏移={offset_seconds}秒 ({hours:.1f}小时)")
        
        # 7. 更新校准值
        self.project_data.timeOffset = offset_hours
        print(f"[锚点] 应用校准值: {offset_hours} 秒 ({hours:.1f}小时)")
        
        # 8. 显示确认对话框
        confirm = QMessageBox.question(
            self, "确认校准",
            f"计算得到的时间偏移: {offset_hours} 秒 ({hours:.1f} 小时)\n\n"
            f"是否使用此偏移重新导入照片？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            # 9. 重新运行导入
            if photo_dir and self.project_data:
                self._start_import(photo_dir, self.project_data.timeOffset)
            else:
                QMessageBox.information(self, "提示", "请先执行【📷 导入影像】选择照片目录")
    
    def _on_import_complete(self, results: dict):
        """导入完成"""
        self.progress_dialog.close()
        
        # 保存更新后的项目数据（包含新关联的照片路径）
        self._save_project()
        
        # 添加到历史记录
        if self.project_data:
            self._add_to_history(self.project_dir, self.project_data.projectName)
        
        # 处理新旧两种结果格式兼容
        if 'local_matched' in results:
            # 新格式（本机拍摄/外设照片分类）
            local_matched = results.get('local_matched', 0)
            external_matched = results.get('external_matched', 0)
            auto_offset = results.get('auto_offset', 0)
            total_linked = local_matched + external_matched
            missing = results.get('missing', 0)
            total = total_linked + missing
            
            # 计算关联率：使用总处理数（已关联 + 未找到）作为分母
            total_processed = total_linked + missing
            match_rate = total_linked / total_processed * 100 if total_processed > 0 else 0
            
            offset_info = ""
            if auto_offset != 0:
                hours = auto_offset / 3600
                offset_info = f"\n🔧 自动偏移: {auto_offset}秒 ({hours:+.1f}小时)"
            
            msg = f"""📷 影像导入完成！

🏠 本机拍摄自动关联: {local_matched} 个
📱 外设照片时间匹配: {external_matched} 个
✅ 总关联: {total_linked} 个
❌ 未找到: {missing} 个
📊 关联率: {match_rate:.1f}%{offset_info}

💾 照片关联方式: 仅记录文件路径，无文件复制
📁 当前校准值: {self.project_data.timeOffset} 秒
"""
            
            if match_rate < 50 and missing > 0:
                msg += "\n💡 提示: 可使用【⚓ 一键锚点】功能手动校准"
            
            QMessageBox.information(self, "导入结果", msg)
        else:
            # 旧格式兼容
            total = results.get('exact', 0) + results.get('similar', 0) + results.get('missing', 0)
            match_rate = (results.get('exact', 0) + results.get('similar', 0)) / total * 100 if total > 0 else 0
            
            msg = f"""导入完成！

✅ EXIF精确匹配: {results.get('exact', 0)} 个
⚠️ 文件名相似匹配: {results.get('similar', 0)} 个
❌ 未找到: {results.get('missing', 0)} 个
📊 匹配率: {match_rate:.1f}%

💾 照片关联方式: 仅记录文件路径，无文件复制
📁 当前校准值: {self.project_data.timeOffset} 秒
"""
            
            # 如果匹配率低，自动应用校准并提示
            if match_rate < 50 and results.get('missing', 0) > 0:
                msg += "\n\n💡 提示: 可使用【⚓ 一键锚点】功能手动校准"
            
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
        print("[调试] _auto_generate_and_open_viewer 开始执行...")
        
        if not self.project_dir:
            print("[调试] 错误: project_dir 为空")
            return
        
        if not self.project_data:
            print("[调试] 错误: project_data 为空")
            return
        
        # 固定生成到项目目录下的 viewer 文件夹
        viewer_dir = os.path.join(self.project_dir, 'viewer')
        print(f"[调试] viewer_dir: {viewer_dir}")
        
        try:
            # 创建目录结构
            os.makedirs(viewer_dir, exist_ok=True)
            print(f"[调试] 目录创建成功: {viewer_dir}")
            
            # 处理外部照片目录（不复制照片）
            photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
            external_photos_link = os.path.join(viewer_dir, 'external_photos')
            
            if photo_base_dir and os.path.exists(photo_base_dir):
                # 移除旧的链接
                if os.path.exists(external_photos_link):
                    if os.path.islink(external_photos_link):
                        os.remove(external_photos_link)
                    elif os.path.isdir(external_photos_link):
                        if sys.platform == 'win32':
                            import subprocess
                            subprocess.run(['cmd', '/c', 'rmdir', '/q', external_photos_link], capture_output=True)
                        else:
                            shutil.rmtree(external_photos_link)
                # 创建 junction (Windows) 或符号链接
                link_created = False
                try:
                    if sys.platform == 'win32':
                        import subprocess
                        link_arg = external_photos_link.replace('/', '\\')
                        target_arg = photo_base_dir.replace('/', '\\')
                        result = subprocess.run(['cmd', '/c', 'mklink', '/J', link_arg, target_arg], check=True, capture_output=True)
                        if result.returncode == 0:
                            link_created = True
                    else:
                        os.symlink(photo_base_dir, external_photos_link)
                        link_created = True
                except subprocess.CalledProcessError as e:
                    stderr = e.stderr.decode('gbk', errors='ignore') if e.stderr else str(e)
                    print(f"[警告] 创建目录联接失败: {stderr}")
                    # 检查是否权限不足
                    if sys.platform == 'win32' and ('权限' in stderr or 'access' in stderr.lower() or 'denied' in stderr.lower()):
                        QMessageBox.warning(
                            self, "权限提示",
                            "创建照片目录联接需要管理员权限。\n\n"
                            "系统将自动回退到【照片复制模式】，"
                            "这可能会占用较多磁盘空间。\n\n"
                            "如需使用联接模式节省空间，请右键选择「以管理员身份运行」本程序。"
                        )
                except Exception as e:
                    print(f"[警告] 创建照片链接失败: {e}")
                
                if not link_created:
                    try:
                        shutil.copytree(photo_base_dir, external_photos_link, dirs_exist_ok=True)
                        print("[信息] 已回退到照片复制模式")
                    except Exception as copy_err:
                        print(f"[错误] 照片复制也失败了: {copy_err}")
                        QMessageBox.critical(self, "错误", f"无法创建照片链接或复制照片:\n{copy_err}")
            
            # 复制项目数据，调整 panoramaPath
            project_copy = self.project_data.to_dict()
            print(f"[调试] 处理 panoramaPath，photo_base_dir: {photo_base_dir}")
            linked_count = 0
            if photo_base_dir and os.path.exists(photo_base_dir):
                for floor_data in project_copy.get('floors', []):
                    for marker_data in floor_data.get('markers', []):
                        old_path = marker_data.get('panoramaPath', '')
                        if marker_data.get('status') == 'linked' and old_path:
                            marker_data['panoramaPath'] = self._resolve_marker_panorama_path(marker_data, photo_base_dir)
                            new_path = marker_data['panoramaPath']
                            if new_path:
                                linked_count += 1
                                print(f"[调试]   {marker_data.get('customName') or marker_data.get('id')}: {old_path[:40]}... -> {new_path[:40]}...")
                            else:
                                print(f"[警告]   {marker_data.get('customName') or marker_data.get('id')}: 路径解析为空!")
            print(f"[调试] 共处理 {linked_count} 个已关联标记点")
            
            with open(os.path.join(viewer_dir, 'project.json'), 'w', encoding='utf-8') as f:
                json.dump(project_copy, f, ensure_ascii=False, indent=2)
                print(f"[调试] project.json 已保存")
            
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
        print(f"[调试] _auto_start_server 开始，viewer_dir: {viewer_dir}")
        
        # 先停止已有服务器
        if self.server_thread and self.server_thread.is_running:
            print("[调试] 停止已有服务器...")
            self.stop_http_server()
        
        # 获取照片根目录，传递给 HTTP 服务器用于 direct mapping
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '') if self.project_data else ''
        print(f"[调试] photo_base_dir: {photo_base_dir}")
        
        # 尝试不同端口（跳过 8080，因为经常被占用）
        for port in [8888, 9000, 9999, 0]:
            try:
                print(f"[调试] 尝试启动端口: {port}")
                self.server_thread = HttpServerThread(viewer_dir, port, photo_base_dir=photo_base_dir, parent_app=self)
                self.server_thread.server_started.connect(self._on_auto_server_started)
                self.server_thread.error_occurred.connect(self._on_server_error)
                self.server_thread.start()
                # 等待一下看是否启动成功
                import time
                time.sleep(0.5)
                if self.server_thread.is_running:
                    print(f"[调试] 端口 {port} 启动成功")
                    break
                else:
                    print(f"[调试] 端口 {port} 未进入运行状态")
            except Exception as e:
                print(f"[调试] 端口 {port} 启动失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        else:
            print("[错误] 所有端口启动失败")
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
        
        # 默认不自动显示服务器信息，由用户手动展开
        self.server_info_group.setVisible(False)
        self.toggle_server_info_btn.setEnabled(True)
        self.toggle_server_info_btn.setText("📡 显示服务器信息")
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
            self.marker_filename_edit.setText(self.current_marker.cameraFileName or '-')
            self.marker_custom_name.setText(self.current_marker.customName)
            self.marker_coord_label.setText(f"({self.current_marker.x:.4f}, {self.current_marker.y:.4f})")
            
            # 更新按钮状态
            has_photo = bool(self.current_marker.originalPhotoPath or self.current_marker.panoramaPath)
            self.open_photo_folder_btn.setEnabled(has_photo)
            self.pick_photo_btn.setEnabled(True)
            self.delete_marker_btn.setEnabled(True)
            
            # 新增：更新视线方向
            direction = getattr(self.current_marker, 'direction', -90.0)
            if direction is None:
                direction = -90.0
            self.direction_label.setText(f"{direction:.0f}°")
            
            # 新增：更新照片预览
            self._update_photo_preview()
            
            # 新增：更新对齐全景按钮状态
            self.align_panorama_btn.setEnabled(has_photo)
            self._update_floating_toolbar()
    
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
            for seq, marker_data in enumerate(floor_data.get('markers', []), start=1):
                marker = Marker.from_dict(marker_data)
                label = str(seq)
                self.canvas.add_marker(
                    marker.id, marker.x, marker.y, marker.status, label,
                    direction=getattr(marker, 'direction', None)
                )
            self.canvas.render_direction_sectors()
        else:
            QMessageBox.warning(self, "提示", f"楼层 '{floor_data['name']}' 的平面图文件不存在")
    
    def _update_marker_name(self):
        """更新点位名称"""
        if hasattr(self, 'current_marker'):
            self._push_history()
            self._record_command('_update_marker_name')
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
                    if os.path.islink(external_photos_link):
                        os.remove(external_photos_link)
                    elif os.path.isdir(external_photos_link):
                        if sys.platform == 'win32':
                            import subprocess
                            subprocess.run(['cmd', '/c', 'rmdir', '/q', external_photos_link], capture_output=True)
                        else:
                            shutil.rmtree(external_photos_link)
                # 创建 junction (Windows) 或符号链接
                try:
                    if sys.platform == 'win32':
                        import subprocess
                        link_arg = external_photos_link.replace('/', '\\')
                        target_arg = photo_base_dir.replace('/', '\\')
                        subprocess.run(['cmd', '/c', 'mklink', '/J', link_arg, target_arg], check=True, capture_output=True)
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
                        marker_data['panoramaPath'] = self._resolve_marker_panorama_path(marker_data, photo_base_dir)
            
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
        """生成查看器 HTML 文件 - 支持多楼层与完整漫游手动设置"""
        # ========== 漫游热点计算 ==========
        import math
        roam_hotspots = {}  # {floor_id: {marker_id: [hotspot, ...]}}

        for floor_data in sorted(self.project_data.floors, key=lambda f: f.get('order', 0), reverse=True):
            floor_id = floor_data['id']
            markers = floor_data.get('markers', [])
            roam_hotspots[floor_id] = {}

            # 只处理已关联且有照片的采集点
            linked_markers = [m for m in markers if m.get('status') == 'linked' and m.get('panoramaPath')]

            # 计算该楼层的最大距离（用于透视归一化）
            max_floor_distance = 0.0
            for i, m1 in enumerate(linked_markers):
                for m2 in linked_markers[i+1:]:
                    dx = m1.get('x', 0) - m2.get('x', 0)
                    dy = m1.get('y', 0) - m2.get('y', 0)
                    d = math.sqrt(dx*dx + dy*dy)
                    if d > max_floor_distance:
                        max_floor_distance = d
            # 兜底：避免除零
            if max_floor_distance < 0.001:
                max_floor_distance = 1.0

            for current in linked_markers:
                current_id = current['id']
                current_x = current.get('x', 0)
                current_y = current.get('y', 0)
                current_dir = current.get('direction', -90.0)
                if current_dir is None:
                    current_dir = -90.0

                hotspots = []

                for target in linked_markers:
                    if target['id'] == current_id:
                        continue  # 跳过自己

                    target_x = target.get('x', 0)
                    target_y = target.get('y', 0)

                    # 计算平面相对向量
                    dx = target_x - current_x
                    dy = target_y - current_y

                    # 平面距离（归一化坐标 0-1范围）
                    distance = math.sqrt(dx * dx + dy * dy)
                    if distance < 0.001:
                        continue  # 重合点跳过

                    # === 修正后的方位角计算（图像Y向下，翻转后Y轴为北） ===
                    # 地理方位角：从北顺时针，0=北，90=东，180=南，270=西
                    # atan2(dx, dy) 因为 Y 正方向为北
                    azimuth_rad = math.atan2(dx, -dy)  # 图像Y向下，翻转得到正确方位角
                    azimuth = math.degrees(azimuth_rad)
                    if azimuth < 0:
                        azimuth += 360

                    # 当前朝向：direction=-90(上/北) → heading=0(北)
                    # direction=0(右/东) → heading=90(东)
                    heading = (current_dir + 90) % 360

                    # 相对全景角度：目标方位角 - 当前朝向
                    relative_yaw = azimuth - heading

                    # 标准化到 [-180, 180]
                    while relative_yaw > 180:
                        relative_yaw -= 360
                    while relative_yaw < -180:
                        relative_yaw += 360

                    # 前方/身后判断：|yaw| > 120° 视为身后
                    is_behind = abs(relative_yaw) > 120

                    # === 透视比例：0=当前点（脚下），1=最远点（灭点） ===
                    perspective_ratio = min(1.0, distance / max_floor_distance)

                    # 身后点额外增加透视距离感
                    if is_behind:
                        perspective_ratio = min(1.0, perspective_ratio * 1.3)

                    target_name = target.get('customName') if target.get('customName') else target.get('id', '')

                    hotspots.append({
                        'targetId': target['id'],
                        'targetName': target_name,
                        'yaw': round(relative_yaw, 2),
                        # pitch 由前端根据 vanishingPointPitch 配置实时计算
                        # 公式: pitch = -85 + perspectiveRatio * (vanishingPointPitch + 85)
                        'distance': round(distance, 4),
                        # 透视比例：0=最近，1=最远
                        'perspectiveRatio': round(perspective_ratio, 4),
                        'isBehind': is_behind,
                        'maxDistance': round(max_floor_distance, 4)
                    })

                # 按透视比例排序（近的优先显示）
                hotspots.sort(key=lambda h: h['perspectiveRatio'])
                roam_hotspots[floor_id][current_id] = hotspots

        # 漫游热点数据已嵌入每个 marker 的 roamHotSpots 字段
        total_hs = sum(len(v) for d in roam_hotspots.values() for v in d.values())
        print(f"[调试] 漫游热点计算完成，共 {total_hs} 个热点关系")

        project_name = self.project_data.projectName

        # 构建多楼层数据
        floors_js = []
        # 按 order 排序楼层（从高到低，与PC端保持一致）
        sorted_floors = sorted(self.project_data.floors, key=lambda f: f.get('order', 0), reverse=True)
        for floor_data in sorted_floors:
            floor_id = floor_data['id']
            floor_name = floor_data['name']
            
            # 查找平面图文件
            floorplan_path = f"floorplan_{floor_id}.jpg"
            
            # 收集该楼层所有标记点（不限制状态，让查看器显示所有点位）
            photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
            all_markers = []
            # 为该楼层计算漫游热点（每个已关联点指向其他已关联点）
            floor_linked_markers = [m for m in floor_data.get('markers', []) 
                                     if m.get('status') == 'linked' and m.get('panoramaPath')]

            for m in floor_data.get('markers', []):
                marker_copy = dict(m)
                # 只有已关联的才需要处理 panoramaPath
                if m.get('status') == 'linked' and m.get('panoramaPath'):
                    if photo_base_dir and os.path.exists(photo_base_dir):
                        marker_copy['panoramaPath'] = self._resolve_marker_panorama_path(marker_copy, photo_base_dir)
                    # 附加漫游热点数据：同楼层其他已关联点
                    current_id = m['id']
                    hs_list = roam_hotspots.get(floor_id, {}).get(current_id, [])
                    # 简化数据，保留前端需要的字段 + 照片数量（用于时空环层数）
                    marker_copy['roamHotSpots'] = [
                        {
                            'targetId': h['targetId'],
                            'targetName': h['targetName'],
                            'yaw': h['yaw'],
                            'distance': h['distance'],
                            'isBehind': h['isBehind'],
                            'perspectiveRatio': h.get('perspectiveRatio', 0),
                            # 时空转换点：目标点位的照片数量决定环层数
                            'photoCount': len(target.get('photos', [])) or (1 if target.get('panoramaPath') else 0)
                        }
                        for h in hs_list
                    ]
                all_markers.append(marker_copy)
            
            # 只要有平面图或标记点就加入楼层
            if floorplan_path or all_markers:
                floors_js.append({
                    'id': floor_id,
                    'name': floor_name,
                    'floorplan': floorplan_path,
                    'markers': all_markers
                })
        
        floors_json = json.dumps(floors_js, ensure_ascii=False)
        print(f"[调试] 生成网页 - 楼层数: {len(floors_js)}")

        # ========== HTML 内容 - 完整漫游手动设置版本 ==========
        html_content = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__PROJECT_NAME__ - 影像查看器</title>
    <link rel="icon" href="data:,">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css"/>
    <script src="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; }
        .container { display: flex; height: 100vh; }
        .floorplan-panel { width: 35%; background: #1C1C1E; display: flex; flex-direction: column; border-right: 1px solid #333; }
        .floor-tabs { display: flex; overflow-x: auto; background: #2C2C2E; padding: 8px; gap: 8px; }
        .floor-tabs::-webkit-scrollbar { display: none; }
        .floor-tab { padding: 8px 16px; background: #3A3A3C; color: #999; border: none; border-radius: 16px; cursor: pointer; white-space: nowrap; font-size: 13px; }
        .floor-tab.active { background: #0A84FF; color: white; }
        .floorplan-container { flex: 1; position: relative; overflow: hidden; display: flex; align-items: center; justify-content: center; }
        .floorplan-wrapper { position: relative; width: 95%; height: 95%; display: flex; align-items: center; justify-content: center; overflow: hidden; touch-action: none; cursor: grab; }
        .floorplan-wrapper:active { cursor: grabbing; }
        .floorplan-wrapper img { max-width: 100%; max-height: 100%; object-fit: contain; transform-origin: 0 0; transition: transform 0.1s ease-out; user-select: none; -webkit-user-drag: none; }
        .floorplan-wrapper.zooming img { transition: none; }
        .zoom-controls { position: absolute; bottom: 20px; right: 20px; display: flex; flex-direction: column; gap: 8px; z-index: 100; }
        .zoom-btn { width: 44px; height: 44px; border-radius: 50%; border: none; background: rgba(0,0,0,0.7); color: white; font-size: 24px; cursor: pointer; display: flex; align-items: center; justify-content: center; backdrop-filter: blur(10px); transition: background 0.2s; }
        .zoom-btn:hover { background: rgba(0,0,0,0.9); }
        .zoom-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .zoom-reset { font-size: 13px; width: auto; padding: 0 16px; border-radius: 22px; }
        .marker-dot { position: absolute; width: 24px; height: 24px; border-radius: 50%; transform: translate(-50%, -50%); cursor: pointer; border: 3px solid white; box-shadow: 0 2px 8px rgba(0,0,0,0.5); background: #30D158; transition: transform 0.2s; }
        .marker-dot:hover { transform: translate(-50%, -50%) scale(1.2); }
        .marker-dot.active { background: #FFCC00; animation: pulse 1.5s infinite; }
        .marker-dot.pending { background: #FF3B30; }
        .marker-dot.missing { background: #8E8E93; }
        .marker-dot.captured { background: #0A84FF; }
        @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(255, 204, 0, 0.7); } 70% { box-shadow: 0 0 0 12px rgba(255, 204, 0, 0); } 100% { box-shadow: 0 0 0 0 rgba(255, 204, 0, 0); } }
        .panorama-panel { width: 65%; position: relative; background: #000; }
        #panorama { width: 100%; height: 100%; }
        .info-bar { position: absolute; top: 0; left: 0; right: 0; padding: 15px 20px; background: linear-gradient(to bottom, rgba(0,0,0,0.8), transparent); color: white; z-index: 50; }
        .info-bar h1 { font-size: 16px; font-weight: 500; margin-bottom: 4px; }
        .info-bar .floor-name { font-size: 13px; color: #0A84FF; }
        .nav-buttons { position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%); display: flex; gap: 10px; z-index: 50; }
        .nav-btn { padding: 12px 24px; background: rgba(0,0,0,0.7); color: white; border: none; border-radius: 24px; cursor: pointer; backdrop-filter: blur(10px); font-size: 13px; }
        .nav-btn:hover { background: rgba(0,0,0,0.9); }
        .control-buttons { position: absolute; top: 15px; right: 20px; display: flex; gap: 10px; z-index: 60; }
        .control-btn { padding: 8px 16px; background: rgba(0,0,0,0.7); color: white; border: none; border-radius: 20px; cursor: pointer; backdrop-filter: blur(10px); font-size: 13px; display: flex; align-items: center; gap: 5px; transition: all 0.2s; }
        .control-btn:hover { background: rgba(0,0,0,0.9); }
        .control-btn.active { background: #0A84FF; }
        .control-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .vr-mode .panorama-panel { width: 100% !important; height: 100% !important; }
        .vr-mode .floorplan-panel { display: none !important; }
        .vr-mode .nav-buttons { display: none; }
        .vr-mode .info-bar { display: none; }
        #vr-container { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: #000; z-index: 1000; }
        #vr-container.active { display: flex; }
        .vr-eye { flex: 1; height: 100%; position: relative; overflow: hidden; }
        .vr-eye-left { border-right: 1px solid #333; }
        .vr-close-btn { position: absolute; top: 20px; left: 50%; transform: translateX(-50%); padding: 12px 24px; background: rgba(255,0,0,0.8); color: white; border: none; border-radius: 24px; cursor: pointer; font-size: 13px; z-index: 1001; }
        .gyro-hint { position: absolute; bottom: 80px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.7); color: white; padding: 8px 16px; border-radius: 20px; font-size: 12px; pointer-events: none; opacity: 0; transition: opacity 0.3s; }
        .gyro-hint.show { opacity: 1; }
        #photoViewer { display: none; width: 100%; height: 100%; position: relative; overflow: hidden; background: #000; align-items: center; justify-content: center; }
        #photoViewer.active { display: flex; }
        #photoViewer img { max-width: 100%; max-height: 100%; object-fit: contain; transition: transform 0.1s ease-out; user-select: none; -webkit-user-drag: none; }
        .photo-nav { position: absolute; top: 50%; transform: translateY(-50%); width: 44px; height: 44px; border-radius: 50%; border: none; background: rgba(0,0,0,0.6); color: white; font-size: 20px; cursor: pointer; display: flex; align-items: center; justify-content: center; z-index: 55; backdrop-filter: blur(4px); }
        .photo-nav:hover { background: rgba(0,0,0,0.85); }
        .photo-nav.prev { left: 15px; }
        .photo-nav.next { right: 15px; }
        .photo-counter { position: absolute; bottom: 70px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.6); color: white; padding: 6px 14px; border-radius: 16px; font-size: 13px; z-index: 55; backdrop-filter: blur(4px); }
        @media (max-width: 768px) { .container { flex-direction: column; } .floorplan-panel { width: 100%; height: 35%; border-right: none; border-bottom: 1px solid #333; } .panorama-panel { width: 100%; height: 65%; } .control-buttons { top: auto; bottom: 80px; right: 10px; flex-direction: column; } .control-btn { padding: 10px; font-size: 12px; } .control-btn span { display: none; } }
        .brand-footer { position: fixed; bottom: 0; left: 0; right: 0; padding: 6px 16px; background: rgba(0,0,0,0.55); color: rgba(255,255,255,0.55); font-size: 11px; text-align: center; z-index: 200; backdrop-filter: blur(4px); pointer-events: auto; }
        .brand-footer a { color: #0A84FF; text-decoration: none; margin-left: 6px; }
        .brand-footer a:hover { text-decoration: underline; }
        @media (max-width: 768px) { .brand-footer { font-size: 10px; padding: 4px 12px; } }

        /* ========== 时空转换环（黑洞形态 + 透视变形） ========== */
        /* 覆盖 Pannellum 默认热点样式 */
        .pnlm-hotspot {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }

        /* 时空转换环主样式 */
        .pnlm-hotspot.roam-hotspot {
            border-radius: 50% !important;
            cursor: pointer !important;
            background: radial-gradient(circle at 35% 35%, 
                rgba(30,30,35,0.9) 0%, 
                rgba(5,5,8,0.98) 45%, 
                rgba(15,15,20,0.95) 100%) !important;
            box-shadow: 
                inset 0 3px 10px rgba(0,0,0,0.95),
                inset 0 -1px 3px rgba(255,255,255,0.08),
                0 0 0 1.5px rgba(255,255,255,0.12),
                0 2px 8px rgba(0,0,0,0.4) !important;
            transition: all 0.25s ease !important;
        }

        .pnlm-hotspot.roam-hotspot:hover {
            z-index: 10000 !important;
            filter: brightness(1.4) !important;
            box-shadow: 
                inset 0 3px 12px rgba(0,0,0,1),
                0 0 0 2px rgba(10,132,255,0.5),
                0 0 20px rgba(10,132,255,0.3) !important;
        }

        /* 脉冲动画 */
        .pnlm-hotspot.roam-hotspot.pulse {
            animation: wormholePulse 2.5s ease-in-out infinite;
        }
        @keyframes wormholePulse {
            0%, 100% { 
                box-shadow: inset 0 3px 10px rgba(0,0,0,0.95), 0 0 0 1.5px rgba(255,255,255,0.12); 
            }
            50% { 
                box-shadow: inset 0 3px 14px rgba(0,0,0,1), 0 0 0 2.5px rgba(10,132,255,0.5), 0 0 25px rgba(10,132,255,0.25); 
            }
        }

        /* 身后点：弱化 */
        .pnlm-hotspot.roam-hotspot.behind {
            filter: grayscale(0.6) brightness(0.6) !important;
            opacity: 0.45 !important;
        }

        /* 脉冲光环动画 */
        @keyframes hotspotPulse {
            0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.8; }
            100% { transform: translate(-50%, -50%) scale(2.2); opacity: 0; }
        }

        /* 箭头弹跳动画 */
        @keyframes arrowBounce {
            0%, 100% { transform: translate(-50%, -50%) translateY(0); }
            50% { transform: translate(-50%, -50%) translateY(-6px); }
        }

        /* 漩涡旋转动画 */
        @keyframes vortexSpin {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }

        /* 脉冲光环动画 */
        @keyframes hotspotPulse {
            0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.8; }
            100% { transform: translate(-50%, -50%) scale(2.2); opacity: 0; }
        }

        /* 箭头弹跳动画 */
        @keyframes arrowBounce {
            0%, 100% { transform: translate(-50%, -50%) translateY(0); }
            50% { transform: translate(-50%, -50%) translateY(-6px); }
        }

        /* 漩涡旋转动画 */
        @keyframes vortexSpin {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }

        /* 点位名称标签（默认隐藏，hover显示） */
        .pnlm-hotspot.roam-hotspot .marker-label {
            position: absolute;
            bottom: calc(100% + 8px);
            left: 50%;
            transform: translateX(-50%);
            white-space: nowrap;
            background: rgba(0,0,0,0.8);
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
            pointer-events: none;
            display: block;
            opacity: 0.9;
            backdrop-filter: blur(8px);
            border: 1px solid rgba(255,255,255,0.2);
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        /* 不设置 hover 规则：label 元素由 JS 根据 showName 控制是否创建，存在即显示 */

        /* 漫游设置面板 */
        #roamSettingsPanel { display: none; position: absolute; top: 60px; right: 20px; width: 360px; max-height: 85vh; overflow-y: auto; background: rgba(28,28,30,0.96); border: 1px solid #444; border-radius: 14px; padding: 20px; z-index: 200; backdrop-filter: blur(16px); font-size: 12px; color: #fff; box-shadow: 0 20px 60px rgba(0,0,0,0.6); }
        #roamSettingsPanel::-webkit-scrollbar { width: 6px; }
        #roamSettingsPanel::-webkit-scrollbar-track { background: transparent; }
        #roamSettingsPanel::-webkit-scrollbar-thumb { background: #555; border-radius: 3px; }
        #roamSettingsPanel::-webkit-scrollbar-thumb:hover { background: #777; }
        
        .roam-section { margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid #333; }
        .roam-section:last-child { border-bottom: none; margin-bottom: 0; }
        .roam-section-title { font-size: 13px; font-weight: 600; color: #0A84FF; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
        .roam-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; min-height: 32px; }
        .roam-row label { color: #ccc; font-size: 12px; flex: 1; }
        .roam-row .roam-value { color: #0A84FF; font-weight: 600; min-width: 50px; text-align: right; font-size: 12px; }
        .roam-row input[type="range"] { -webkit-appearance: none; height: 4px; background: #444; border-radius: 2px; outline: none; width: 120px; margin: 0 10px; }
        .roam-row input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; background: #0A84FF; border-radius: 50%; cursor: pointer; border: 2px solid #fff; box-shadow: 0 2px 8px rgba(10,132,255,0.4); }
        .roam-row input[type="color"] { width: 40px; height: 24px; border: none; border-radius: 4px; cursor: pointer; background: none; }
        .roam-row input[type="checkbox"] { width: 18px; height: 18px; accent-color: #0A84FF; cursor: pointer; }
        .roam-row .roam-input-num { width: 60px; padding: 4px 8px; background: #2C2C2E; border: 1px solid #444; border-radius: 6px; color: #fff; font-size: 12px; text-align: center; }
        .roam-row .roam-input-num:focus { outline: none; border-color: #0A84FF; }
        .roam-btns { display: flex; gap: 8px; margin-top: 12px; }
        .roam-btn { flex: 1; padding: 10px; border: none; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 500; transition: all 0.2s; }
        .roam-btn.primary { background: #0A84FF; color: white; }
        .roam-btn.primary:hover { background: #0866c6; }
        .roam-btn.danger { background: #FF3B30; color: white; }
        .roam-btn.danger:hover { background: #B32418; }
        .roam-btn.secondary { background: #3A3A3C; color: #fff; border: 1px solid #555; }
        .roam-btn.secondary:hover { background: #48484A; }
        .roam-hint { color: #888; font-size: 11px; margin-top: 6px; line-height: 1.5; }
        .roam-hint code { background: #2C2C2E; padding: 2px 6px; border-radius: 4px; color: #FFCC00; font-family: monospace; }
        .roam-preview-box { background: #2C2C2E; border-radius: 8px; padding: 12px; margin-top: 8px; }
        .roam-preview-title { font-size: 11px; color: #888; margin-bottom: 6px; }
        .roam-preview-dot { display: inline-block; border-radius: 50%; margin-right: 8px; vertical-align: middle; }
        
        /* 实时生效提示 */
        .live-indicator { position: absolute; top: 60px; right: 390px; background: rgba(52,199,89,0.9); color: white; padding: 6px 14px; border-radius: 16px; font-size: 12px; z-index: 199; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
        .live-indicator.show { opacity: 1; }
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
            <div class="roam-indicator" id="roamIndicator" style="display:none;position:absolute;top:60px;right:20px;background:rgba(52,199,89,0.9);color:white;padding:6px 14px;border-radius:16px;font-size:12px;z-index:60;">🌌 时空转换：点击黑洞环穿梭</div>
            <div id="panorama"></div>
            <div id="photoViewer">
                <button class="photo-nav prev" id="photoPrev" onclick="prevPhoto()" title="上一张">◀</button>
                <img id="photoImg" src="" alt="照片" draggable="false">
                <button class="photo-nav next" id="photoNext" onclick="nextPhoto()" title="下一张">▶</button>
                <div class="photo-counter" id="photoCounter">1 / 1</div>
            </div>
            <div class="gyro-hint" id="gyroHint">陀螺仪模式已开启，移动手机查看</div>
            <div class="control-buttons">
                <button class="control-btn" id="viewModeBtn" onclick="toggleViewMode()" title="切换查看模式">🖼️ <span>图片</span></button>
                <button class="control-btn" id="gyroBtn" onclick="toggleGyro()" title="陀螺仪模式">📱 <span>陀螺仪</span></button>
                <button class="control-btn" id="vrBtn" onclick="toggleVR()" title="VR 模式">🥽 <span>VR模式</span></button>
                <button class="control-btn" id="roamSettingsBtn" onclick="toggleRoamSettings()" title="时空转换设置">⚙️ <span>时空设置</span></button>
            </div>

            <!-- 实时生效提示 -->
            <div class="live-indicator" id="liveIndicator">⚡ 设置已实时生效</div>

            <!-- 漫游设置面板 -->
            <div id="roamSettingsPanel">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <h2 style="margin:0;font-size:16px;">🌌 时空转换设置</h2>
                    <button onclick="toggleRoamSettings()" style="background:none;border:none;color:#fff;font-size:20px;cursor:pointer;width:32px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:50%;transition:background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.1)'" onmouseout="this.style.background='none'">×</button>
                </div>

                <!-- 功能开关 -->
                <div class="roam-section">
                    <div class="roam-section-title">🔌 功能开关</div>
                    <div class="roam-row">
                        <label>智能朝向保持（切换场景保持视角）</label>
                        <input type="checkbox" id="cfg_smartOrientation" onchange="updateRoamConfig('smartOrientationEnabled', this.checked)">
                    </div>
                    <div class="roam-row">
                        <label>预加载相邻场景（后台缓存）</label>
                        <input type="checkbox" id="cfg_preload" onchange="updateRoamConfig('preloadEnabled', this.checked)">
                    </div>
                    <div class="roam-row">
                        <label>脉冲动画（最近热点呼吸效果）</label>
                        <input type="checkbox" id="cfg_pulse" onchange="updateRoamConfig('pulseEnabled', this.checked)">
                    </div>
                    <div class="roam-row">
                        <label>调试日志（控制台输出计算过程）</label>
                        <input type="checkbox" id="cfg_debug" onchange="updateRoamConfig('debugLog', this.checked)">
                    </div>
                    <div class="roam-row">
                        <label>显示点位名称标签（默认隐藏）</label>
                        <input type="checkbox" id="cfg_showName" onchange="updateRoamConfig('showName', this.checked); applyCurrentSettings()">
                    </div>
                    <div class="roam-hint">💡 关闭「智能朝向保持」可让每次跳转都正对下一个点位<br>💡 开启「显示点位名称」可在热点上方常驻显示目标名称</div>
                </div>

                <!-- 灭点高度 -->
                <div class="roam-section">
                    <div class="roam-section-title">📐 灭点高度（俯仰角）</div>
                    <div class="roam-row">
                        <label>灭点俯仰角（远处地平线高度）</label>
                        <input type="range" id="cfg_vanishingPitch" min="-45" max="45" oninput="updateRoamConfig('vanishingPointPitch', parseInt(this.value));updateDisplay('val_vanishingPitch',this.value+'°')">
                        <span class="roam-value" id="val_vanishingPitch">-15°</span>
                    </div>
                    <div class="roam-row">
                        <label>近处俯仰角（脚下地面，固定）</label>
                        <span class="roam-value" style="color:#888;">-85°</span>
                    </div>
                    <div class="roam-hint">灭点高度决定远处转换点在全景中的垂直位置<br>值越大（接近45°）灭点越高（地平线以上），值越小（-45°）灭点越低</div>
                </div>

                <!-- 转换点样式 -->
                <div class="roam-section">
                    <div class="roam-section-title">🎨 转换点样式</div>
                    <div class="roam-row">
                        <label>选择引导样式</label>
                        <select id="cfg_hotspotStyle" onchange="updateRoamConfig('hotspotStyle', this.value); updateStylePreview(this.value); applyCurrentSettings()" style="background:#2C2C2E;color:#fff;border:1px solid #444;border-radius:6px;padding:6px 10px;font-size:12px;cursor:pointer;">
                            <option value="blackhole">🕳️ 黑洞环（多层同心圆）</option>
                            <option value="pulse">💫 脉冲光环（游戏标记）</option>
                            <option value="arrow">⬇️ 箭头指引（3D指向）</option>
                        </select>
                    </div>
                    <div class="roam-preview-box">
                        <div class="roam-preview-title">样式预览</div>
                        <div id="stylePreview" style="display:flex;gap:12px;align-items:center;justify-content:center;height:60px;">
                            <div id="previewBlackhole" style="display:none;width:40px;height:40px;border-radius:50%;border:3px solid #34C759;box-shadow:0 0 10px rgba(52,199,89,0.4),inset 0 2px 6px rgba(0,0,0,0.7);position:relative;"><div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:10px;height:10px;border-radius:50%;background:rgba(0,0,0,0.9);"></div></div>
                            <div id="previewPulse" style="display:none;width:40px;height:40px;border-radius:50%;background:#34C759;position:relative;box-shadow:0 0 20px rgba(52,199,89,0.5);"><span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:white;font-size:16px;text-shadow:0 0 4px rgba(0,0,0,0.8);">▼</span></div>
                            <div id="previewArrow" style="display:none;width:0;height:0;border-left:18px solid transparent;border-right:18px solid transparent;border-bottom:28px solid #34C759;filter:drop-shadow(0 0 8px rgba(52,199,89,0.5));position:relative;top:-4px;"></div>
                        </div>
                    </div>
                    <div class="roam-hint">黑洞环：多层同心圆向中心收缩，适合科幻风格<br>脉冲光环：外发光脉冲+箭头，类似游戏任务标记<br>箭头指引：3D箭头+轨迹线，明确指向目标位置</div>
                </div>

                <!-- 显示数量限制 -->
                <div class="roam-section">
                    <div class="roam-section-title">🔢 显示数量限制</div>
                    <div class="roam-row">
                        <label>最大显示转换点数量（0=不限制）</label>
                        <input type="range" id="cfg_maxVisible" min="0" max="20" oninput="updateRoamConfig('maxVisibleHotspots', parseInt(this.value));updateDisplay('val_maxVisible',this.value==0?'不限':this.value+'个')">
                        <span class="roam-value" id="val_maxVisible">不限</span>
                    </div>
                    <div class="roam-hint">限制显示数量可减少视觉混乱，只保留最近的转换点<br>设置为0显示所有转换点</div>
                </div>

                <!-- 热点大小 -->
                <div class="roam-section">
                    <div class="roam-section-title">📐 热点大小（像素）</div>
                    <div class="roam-row">
                        <label>脚下（最近）大小</label>
                        <input type="range" id="cfg_sizeMax" min="20" max="120" oninput="updateRoamConfig('sizeMax', parseInt(this.value));updateDisplay('val_sizeMax',this.value+'px')">
                        <span class="roam-value" id="val_sizeMax">56px</span>
                    </div>
                    <div class="roam-row">
                        <label>灭点（最远）大小</label>
                        <input type="range" id="cfg_sizeMin" min="2" max="40" oninput="updateRoamConfig('sizeMin', parseInt(this.value));updateDisplay('val_sizeMin',this.value+'px')">
                        <span class="roam-value" id="val_sizeMin">10px</span>
                    </div>
                    <div class="roam-row">
                        <label>大小衰减曲线 <code>pow(ratio, curve)</code></label>
                        <input type="range" id="cfg_sizeCurve" min="1" max="30" oninput="updateRoamConfig('sizeCurve', parseInt(this.value)/10);updateDisplay('val_sizeCurve',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_sizeCurve">0.7</span>
                    </div>
                    <div class="roam-hint">曲线值 <code>&lt;1</code> 近距离衰减慢（热点保持大更久），<code>&gt;1</code> 快速缩小</div>
                </div>

                <!-- 间距密度 -->
                <div class="roam-section">
                    <div class="roam-section-title">📐 间距密度（远处点聚集）</div>
                    <div class="roam-row">
                        <label>远处点视觉压缩程度</label>
                        <input type="range" id="cfg_spacingDensity" min="0" max="10" oninput="updateRoamConfig('spacingDensity', parseInt(this.value)/10);updateDisplay('val_spacingDensity',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_spacingDensity">0.3</span>
                    </div>
                    <div class="roam-hint">值越大，远处转换点越向灭点方向聚集<br>0=平面等距，1=最大聚集（灭点处重合）</div>
                </div>

                <!-- 透明度 -->
                <div class="roam-section">
                    <div class="roam-section-title">👁️ 透明度</div>
                    <div class="roam-row">
                        <label>脚下（最近）不透明度</label>
                        <input type="range" id="cfg_opacityMax" min="20" max="100" oninput="updateRoamConfig('opacityMax', parseInt(this.value)/100);updateDisplay('val_opacityMax',this.value+'%')">
                        <span class="roam-value" id="val_opacityMax">100%</span>
                    </div>
                    <div class="roam-row">
                        <label>灭点（最远）不透明度</label>
                        <input type="range" id="cfg_opacityMin" min="0" max="60" oninput="updateRoamConfig('opacityMin', parseInt(this.value)/100);updateDisplay('val_opacityMin',this.value+'%')">
                        <span class="roam-value" id="val_opacityMin">15%</span>
                    </div>
                    <div class="roam-row">
                        <label>透明度衰减曲线</label>
                        <input type="range" id="cfg_opacityCurve" min="1" max="30" oninput="updateRoamConfig('opacityCurve', parseInt(this.value)/10);updateDisplay('val_opacityCurve',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_opacityCurve">0.5</span>
                    </div>
                </div>

                <!-- 颜色 -->
                <div class="roam-section">
                    <div class="roam-section-title">🎨 颜色（RGB）</div>
                    <div class="roam-row">
                        <label>脚下（最近）颜色</label>
                        <input type="color" id="cfg_colorNear" value="#34C759" onchange="updateRoamColor('colorNear', this.value)">
                    </div>
                    <div class="roam-row">
                        <label>灭点（最远）颜色</label>
                        <input type="color" id="cfg_colorFar" value="#8E8E93" onchange="updateRoamColor('colorFar', this.value)">
                    </div>
                    <div class="roam-preview-box">
                        <div class="roam-preview-title">颜色预览</div>
                        <div id="colorPreview" style="display:flex;gap:8px;align-items:center;">
                            <span class="roam-preview-dot" id="previewNear" style="width:24px;height:24px;background:#34C759;"></span>
                            <span style="color:#666;">→</span>
                            <span class="roam-preview-dot" id="previewFar" style="width:12px;height:12px;background:#8E8E93;opacity:0.5;"></span>
                        </div>
                    </div>
                </div>

                <!-- 身后点处理 -->
                <div class="roam-section">
                    <div class="roam-section-title">↩️ 身后点（视野外）处理</div>
                    <div class="roam-row">
                        <label>大小缩放比例</label>
                        <input type="range" id="cfg_behindSize" min="1" max="10" oninput="updateRoamConfig('behindSizeScale', parseInt(this.value)/10);updateDisplay('val_behindSize',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_behindSize">0.7</span>
                    </div>
                    <div class="roam-row">
                        <label>透明度缩放比例</label>
                        <input type="range" id="cfg_behindOpacity" min="1" max="10" oninput="updateRoamConfig('behindOpacityScale', parseInt(this.value)/10);updateDisplay('val_behindOpacity',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_behindOpacity">0.5</span>
                    </div>
                    <div class="roam-row">
                        <label>灰度化程度</label>
                        <input type="range" id="cfg_behindGray" min="0" max="10" oninput="updateRoamConfig('behindGrayScale', parseInt(this.value)/10);updateDisplay('val_behindGray',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_behindGray">0.3</span>
                    </div>
                    <div class="roam-hint">身后点指视野后方（|yaw|>120°）的热点，通常需要弱化显示</div>
                </div>

                <!-- 边框与阴影 -->
                <div class="roam-section">
                    <div class="roam-section-title">✨ 边框与阴影</div>
                    <div class="roam-row">
                        <label>近处边框透明度</label>
                        <input type="range" id="cfg_borderNear" min="20" max="100" oninput="updateRoamConfig('borderOpacityNear', parseInt(this.value)/100);updateDisplay('val_borderNear',this.value+'%')">
                        <span class="roam-value" id="val_borderNear">95%</span>
                    </div>
                    <div class="roam-row">
                        <label>远处边框透明度</label>
                        <input type="range" id="cfg_borderFar" min="0" max="80" oninput="updateRoamConfig('borderOpacityFar', parseInt(this.value)/100);updateDisplay('val_borderFar',this.value+'%')">
                        <span class="roam-value" id="val_borderFar">40%</span>
                    </div>
                    <div class="roam-row">
                        <label>阴影强度倍率</label>
                        <input type="range" id="cfg_shadow" min="0" max="20" oninput="updateRoamConfig('shadowIntensity', parseInt(this.value)/10);updateDisplay('val_shadow',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_shadow">1.0</span>
                    </div>
                </div>

                <!-- 智能朝向 -->
                <div class="roam-section">
                    <div class="roam-section-title">🧭 智能朝向保持参数</div>
                    <div class="roam-row">
                        <label>俯仰角限制（±度）</label>
                        <input type="range" id="cfg_pitchLimit" min="0" max="90" oninput="updateRoamConfig('pitchLimit', parseInt(this.value));updateDisplay('val_pitchLimit',this.value+'°')">
                        <span class="roam-value" id="val_pitchLimit">30°</span>
                    </div>
                    <div class="roam-row">
                        <label>俯仰角阻尼系数（0-1）</label>
                        <input type="range" id="cfg_pitchDamp" min="0" max="10" oninput="updateRoamConfig('pitchDamping', parseInt(this.value)/10);updateDisplay('val_pitchDamp',(parseInt(this.value)/10).toFixed(1))">
                        <span class="roam-value" id="val_pitchDamp">0.5</span>
                    </div>
                    <div class="roam-hint">阻尼 <code>0.5</code> 表示切换后俯仰角变为原来一半，防止视角过偏</div>
                </div>

                <!-- 预加载 -->
                <div class="roam-section">
                    <div class="roam-section-title">⏳ 预加载参数</div>
                    <div class="roam-row">
                        <label>预加载延迟（毫秒）</label>
                        <input type="range" id="cfg_preloadDelay" min="0" max="3000" step="100" oninput="updateRoamConfig('preloadDelay', parseInt(this.value));updateDisplay('val_preloadDelay',this.value+'ms')">
                        <span class="roam-value" id="val_preloadDelay">1000ms</span>
                    </div>
                    <div class="roam-row">
                        <label>最大并行加载数</label>
                        <input type="range" id="cfg_maxConcurrent" min="1" max="5" oninput="updateRoamConfig('maxConcurrent', parseInt(this.value));updateDisplay('val_maxConcurrent',this.value)">
                        <span class="roam-value" id="val_maxConcurrent">2</span>
                    </div>
                </div>

                <!-- 过渡动画 -->
                <div class="roam-section">
                    <div class="roam-section-title">🎬 过渡动画</div>
                    <div class="roam-row">
                        <label>淡出时长（毫秒）</label>
                        <input type="range" id="cfg_fadeOut" min="0" max="1000" step="50" oninput="updateRoamConfig('fadeOutDuration', parseInt(this.value));updateDisplay('val_fadeOut',this.value+'ms')">
                        <span class="roam-value" id="val_fadeOut">300ms</span>
                    </div>
                    <div class="roam-row">
                        <label>淡入时长（毫秒）</label>
                        <input type="range" id="cfg_fadeIn" min="0" max="2000" step="100" oninput="updateRoamConfig('fadeInDuration', parseInt(this.value));updateDisplay('val_fadeIn',this.value+'ms')">
                        <span class="roam-value" id="val_fadeIn">800ms</span>
                    </div>
                </div>

                <!-- 脉冲阈值 -->
                <div class="roam-section">
                    <div class="roam-section-title">💓 脉冲动画阈值</div>
                    <div class="roam-row">
                        <label>触发脉冲的最大透视比例</label>
                        <input type="range" id="cfg_pulseThreshold" min="0" max="50" oninput="updateRoamConfig('pulseThreshold', parseInt(this.value)/100);updateDisplay('val_pulseThreshold',(parseInt(this.value)/100).toFixed(2))">
                        <span class="roam-value" id="val_pulseThreshold">0.15</span>
                    </div>
                    <div class="roam-hint">只有 <code>perspectiveRatio &lt; 0.15</code> 的热点会播放呼吸动画</div>
                </div>

                <!-- 操作按钮 -->
                <div class="roam-btns">
                    <button class="roam-btn primary" onclick="RoamConfigStorage.save();showLiveIndicator('💾 设置已保存')">💾 保存到浏览器</button>
                    <button class="roam-btn secondary" onclick="applyCurrentSettings();showLiveIndicator('⚡ 已应用到当前场景')">🔄 立即应用</button>
                </div>
                <div class="roam-btns" style="margin-top:8px;">
                    <button class="roam-btn danger" onclick="RoamConfigStorage.reset()">🔄 恢复全部默认</button>
                </div>
                <div class="roam-hint" style="margin-top:10px;text-align:center;">
                    修改数值后点击「立即应用」可实时预览效果<br>
                    满意后点击「保存到浏览器」永久记住
                </div>
            </div>

            <div class="nav-buttons">
                <button class="nav-btn" onclick="prevPanorama()">◀ 上一张</button>
                <button class="nav-btn" onclick="nextPanorama()">下一张 ▶</button>
            </div>
        </div>
    </div>
    
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

        // ========== 工具函数 ==========
        function normalizeAngle(angle) {
            while (angle > 180) angle -= 360;
            while (angle < -180) angle += 360;
            return angle;
        }

        function getMoveAzimuth(fromMarker, toMarker) {
            var dx = toMarker.x - fromMarker.x;
            var dy = toMarker.y - fromMarker.y;
            var azimuth = Math.atan2(dx, dy) * 180 / Math.PI;
            return normalizeAngle(azimuth);
        }

        function hexToRgb(hex) {
            var r = parseInt(hex.slice(1, 3), 16);
            var g = parseInt(hex.slice(3, 5), 16);
            var b = parseInt(hex.slice(5, 7), 16);
            return [r, g, b];
        }

        function rgbToHex(r, g, b) {
            return '#' + [r, g, b].map(function(x) {
                var hex = Math.round(x).toString(16);
                return hex.length === 1 ? '0' + hex : hex;
            }).join('');
        }

        // ========== 预加载管理器 ==========
        var PreloadManager = {
            queue: [],
            active: 0,
            cache: new Set(),
            add: function(url) {
                if (this.cache.has(url) || this.queue.includes(url)) return;
                this.queue.push(url);
                this.process();
            },
            process: function() {
                while (this.active < RoamConfig.maxConcurrent && this.queue.length > 0) {
                    var url = this.queue.shift();
                    this.load(url);
                }
            },
            load: function(url) {
                this.active++;
                var self = this;
                var img = new Image();
                img.onload = img.onerror = function() {
                    self.active--;
                    self.cache.add(url);
                    self.process();
                };
                img.src = url;
            },
            clear: function() { this.queue = []; },
            preloadForMarker: function(marker) {
                if (!marker || !marker.roamHotSpots) return;
                var self = this;
                marker.roamHotSpots.forEach(function(hs) {
                    var target = null;
                    for (var fi = 0; fi < floors.length; fi++) {
                        for (var mi = 0; mi < floors[fi].markers.length; mi++) {
                            if (floors[fi].markers[mi].id === hs.targetId) { target = floors[fi].markers[mi]; break; }
                        }
                        if (target) break;
                    }
                    if (target && target.panoramaPath) self.add(target.panoramaPath);
                });
            }
        };

        // ========== 漫游全局配置（所有参数均可手动调整） ==========
        var RoamConfig = {
            // 热点大小
            sizeMin: 6,
            sizeMax: 56,
            sizeCurve: 1.2,
            // 间距密度：远处点在视觉上的压缩程度（0-1，0=无压缩，1=最大压缩）
            spacingDensity: 0.3,
            // 透明度
            opacityMin: 0.15,
            opacityMax: 1.0,
            opacityCurve: 0.5,
            // 颜色 (RGB数组)
            colorNear: [52, 199, 89],
            colorFar: [142, 142, 147],
            // 脉冲动画
            pulseEnabled: true,
            pulseThreshold: 0.15,
            // 身后点
            behindSizeScale: 0.65,
            behindOpacityScale: 0.5,
            behindGrayScale: 0.3,
            // 边框与阴影
            borderOpacityNear: 0.95,
            borderOpacityFar: 0.4,
            shadowIntensity: 1.0,
            // 智能朝向保持
            smartOrientationEnabled: true,
            pitchLimit: 30,
            pitchDamping: 0.5,
            // 预加载
            preloadEnabled: true,
            preloadDelay: 1000,
            maxConcurrent: 2,
            // 过渡动画
            fadeOutDuration: 300,
            fadeInDuration: 800,
            // 点位名称显示
            showName: false,
            // 灭点俯仰角（远处地平线高度，-45~45，正数=地平线以上）
            vanishingPointPitch: -15,
            // 热点样式
            hotspotStyle: 'blackhole',
            // 最大显示热点数（0=不限）
            maxVisibleHotspots: 0,
            // 调试
            debugLog: false
        };

        // ========== 配置持久化 ==========
        var RoamConfigStorage = {
            key: 'panorama_roam_config_v2',
            load: function() {
                try {
                    var saved = localStorage.getItem(this.key);
                    if (saved) {
                        var parsed = JSON.parse(saved);
                        for (var k in parsed) {
                            if (RoamConfig.hasOwnProperty(k)) RoamConfig[k] = parsed[k];
                        }
                        // 兼容旧配置：showLabel -> showName
                        if (parsed.hasOwnProperty('showLabel') && !parsed.hasOwnProperty('showName')) {
                            RoamConfig.showName = parsed.showLabel;
                        }
                        // 兼容旧配置：给新字段设置默认值
                        if (!parsed.hasOwnProperty('vanishingPointPitch')) RoamConfig.vanishingPointPitch = -15;
                        if (!parsed.hasOwnProperty('hotspotStyle')) RoamConfig.hotspotStyle = 'blackhole';
                        if (!parsed.hasOwnProperty('maxVisibleHotspots')) RoamConfig.maxVisibleHotspots = 0;
                        if (!parsed.hasOwnProperty('spacingDensity')) RoamConfig.spacingDensity = 0.3;
                        // 兼容旧配置：给新字段设置默认值
                        if (!parsed.hasOwnProperty('vanishingPointPitch')) RoamConfig.vanishingPointPitch = -15;
                        if (!parsed.hasOwnProperty('hotspotStyle')) RoamConfig.hotspotStyle = 'blackhole';
                        if (!parsed.hasOwnProperty('maxVisibleHotspots')) RoamConfig.maxVisibleHotspots = 0;
                        if (!parsed.hasOwnProperty('spacingDensity')) RoamConfig.spacingDensity = 0.3;
                        if (RoamConfig.debugLog) console.log('[配置] 已从 localStorage 加载保存的设置');
                    }
                } catch(e) { console.log('[配置] 加载失败:', e); }
            },
            save: function() {
                try {
                    localStorage.setItem(this.key, JSON.stringify(RoamConfig));
                    if (RoamConfig.debugLog) console.log('[配置] 已保存到 localStorage');
                } catch(e) { console.log('[配置] 保存失败:', e); }
            },
            reset: function() {
                localStorage.removeItem(this.key);
                location.reload();
            }
        };

        // 页面加载时读取配置
        RoamConfigStorage.load();

        // ========== UI 同步：将当前配置值反映到设置面板 ==========
        function syncUIFromConfig() {
            // 开关
            document.getElementById('cfg_smartOrientation').checked = RoamConfig.smartOrientationEnabled;
            document.getElementById('cfg_preload').checked = RoamConfig.preloadEnabled;
            document.getElementById('cfg_pulse').checked = RoamConfig.pulseEnabled;
            document.getElementById('cfg_debug').checked = RoamConfig.debugLog;
            document.getElementById('cfg_showName').checked = RoamConfig.showName;

            // 灭点高度
            document.getElementById('cfg_vanishingPitch').value = RoamConfig.vanishingPointPitch;
            document.getElementById('val_vanishingPitch').textContent = RoamConfig.vanishingPointPitch + '°';

            // 样式选择
            document.getElementById('cfg_hotspotStyle').value = RoamConfig.hotspotStyle;
            updateStylePreview(RoamConfig.hotspotStyle);

            // 显示数量
            document.getElementById('cfg_maxVisible').value = RoamConfig.maxVisibleHotspots;
            document.getElementById('val_maxVisible').textContent = RoamConfig.maxVisibleHotspots === 0 ? '不限' : RoamConfig.maxVisibleHotspots + '个';
            document.getElementById('cfg_showName').checked = RoamConfig.showName;
            
            // 大小
            document.getElementById('cfg_sizeMax').value = RoamConfig.sizeMax;
            document.getElementById('val_sizeMax').textContent = RoamConfig.sizeMax + 'px';
            document.getElementById('cfg_sizeMin').value = RoamConfig.sizeMin;
            document.getElementById('val_sizeMin').textContent = RoamConfig.sizeMin + 'px';
            document.getElementById('cfg_sizeCurve').value = Math.round(RoamConfig.sizeCurve * 10);
            document.getElementById('val_sizeCurve').textContent = RoamConfig.sizeCurve.toFixed(1);
            // 间距密度
            document.getElementById('cfg_spacingDensity').value = Math.round((RoamConfig.spacingDensity || 0.3) * 10);
            document.getElementById('val_spacingDensity').textContent = ((RoamConfig.spacingDensity || 0.3)).toFixed(1);
            
            // 透明度
            document.getElementById('cfg_opacityMax').value = Math.round(RoamConfig.opacityMax * 100);
            document.getElementById('val_opacityMax').textContent = Math.round(RoamConfig.opacityMax * 100) + '%';
            document.getElementById('cfg_opacityMin').value = Math.round(RoamConfig.opacityMin * 100);
            document.getElementById('val_opacityMin').textContent = Math.round(RoamConfig.opacityMin * 100) + '%';
            document.getElementById('cfg_opacityCurve').value = Math.round(RoamConfig.opacityCurve * 10);
            document.getElementById('val_opacityCurve').textContent = RoamConfig.opacityCurve.toFixed(1);
            
            // 颜色
            document.getElementById('cfg_colorNear').value = rgbToHex(RoamConfig.colorNear[0], RoamConfig.colorNear[1], RoamConfig.colorNear[2]);
            document.getElementById('cfg_colorFar').value = rgbToHex(RoamConfig.colorFar[0], RoamConfig.colorFar[1], RoamConfig.colorFar[2]);
            document.getElementById('previewNear').style.background = document.getElementById('cfg_colorNear').value;
            document.getElementById('previewFar').style.background = document.getElementById('cfg_colorFar').value;
            
            // 身后点
            document.getElementById('cfg_behindSize').value = Math.round(RoamConfig.behindSizeScale * 10);
            document.getElementById('val_behindSize').textContent = RoamConfig.behindSizeScale.toFixed(1);
            document.getElementById('cfg_behindOpacity').value = Math.round(RoamConfig.behindOpacityScale * 10);
            document.getElementById('val_behindOpacity').textContent = RoamConfig.behindOpacityScale.toFixed(1);
            document.getElementById('cfg_behindGray').value = Math.round(RoamConfig.behindGrayScale * 10);
            document.getElementById('val_behindGray').textContent = RoamConfig.behindGrayScale.toFixed(1);
            
            // 边框阴影
            document.getElementById('cfg_borderNear').value = Math.round(RoamConfig.borderOpacityNear * 100);
            document.getElementById('val_borderNear').textContent = Math.round(RoamConfig.borderOpacityNear * 100) + '%';
            document.getElementById('cfg_borderFar').value = Math.round(RoamConfig.borderOpacityFar * 100);
            document.getElementById('val_borderFar').textContent = Math.round(RoamConfig.borderOpacityFar * 100) + '%';
            document.getElementById('cfg_shadow').value = Math.round(RoamConfig.shadowIntensity * 10);
            document.getElementById('val_shadow').textContent = RoamConfig.shadowIntensity.toFixed(1);
            
            // 智能朝向
            document.getElementById('cfg_pitchLimit').value = RoamConfig.pitchLimit;
            document.getElementById('val_pitchLimit').textContent = RoamConfig.pitchLimit + '°';
            document.getElementById('cfg_pitchDamp').value = Math.round(RoamConfig.pitchDamping * 10);
            document.getElementById('val_pitchDamp').textContent = RoamConfig.pitchDamping.toFixed(1);
            
            // 预加载
            document.getElementById('cfg_preloadDelay').value = RoamConfig.preloadDelay;
            document.getElementById('val_preloadDelay').textContent = RoamConfig.preloadDelay + 'ms';
            document.getElementById('cfg_maxConcurrent').value = RoamConfig.maxConcurrent;
            document.getElementById('val_maxConcurrent').textContent = RoamConfig.maxConcurrent;
            
            // 过渡动画
            document.getElementById('cfg_fadeOut').value = RoamConfig.fadeOutDuration;
            document.getElementById('val_fadeOut').textContent = RoamConfig.fadeOutDuration + 'ms';
            document.getElementById('cfg_fadeIn').value = RoamConfig.fadeInDuration;
            document.getElementById('val_fadeIn').textContent = RoamConfig.fadeInDuration + 'ms';
            
            // 脉冲阈值
            document.getElementById('cfg_pulseThreshold').value = Math.round(RoamConfig.pulseThreshold * 100);
            document.getElementById('val_pulseThreshold').textContent = RoamConfig.pulseThreshold.toFixed(2);
        }

        // ========== 配置更新函数（实时热更新） ==========
        function updateStylePreview(style) {
            document.getElementById('previewBlackhole').style.display = style === 'blackhole' ? 'block' : 'none';
            document.getElementById('previewPulse').style.display = style === 'pulse' ? 'block' : 'none';
            document.getElementById('previewArrow').style.display = style === 'arrow' ? 'block' : 'none';
        }

        function updateStylePreview(style) {
            var pb = document.getElementById('previewBlackhole');
            var pp = document.getElementById('previewPulse');
            var pa = document.getElementById('previewArrow');
            if (pb) pb.style.display = style === 'blackhole' ? 'block' : 'none';
            if (pp) pp.style.display = style === 'pulse' ? 'block' : 'none';
            if (pa) pa.style.display = style === 'arrow' ? 'block' : 'none';
        }

        function updateRoamConfig(key, value) {
            RoamConfig[key] = value;
            if (RoamConfig.debugLog) console.log('[配置更新]', key, '=', value);
        }

        function updateRoamColor(key, hexValue) {
            RoamConfig[key] = hexToRgb(hexValue);
            document.getElementById('previewNear').style.background = document.getElementById('cfg_colorNear').value;
            document.getElementById('previewFar').style.background = document.getElementById('cfg_colorFar').value;
            if (RoamConfig.debugLog) console.log('[颜色更新]', key, '=', hexValue, '→ RGB', RoamConfig[key]);
        }

        function updateDisplay(elementId, text) {
            document.getElementById(elementId).textContent = text;
        }

        function showLiveIndicator(text) {
            var el = document.getElementById('liveIndicator');
            el.textContent = text;
            el.classList.add('show');
            setTimeout(function() { el.classList.remove('show'); }, 2000);
        }

        // ========== 核心：将当前配置应用到已加载的全景 ==========
        function applyCurrentSettings() {
            if (!viewer) {
                showLiveIndicator('❌ 请先选择一个有影像的点位');
                return;
            }
            // 重新加载当前场景以应用新设置
            var floor = floors[currentFloorIndex];
            var marker = floor.markers[currentMarkerIndex];
            if (marker && marker.panoramaPath) {
                // 记录当前视角
                var prevYaw = 0, prevPitch = 0;
                try {
                    prevYaw = viewer.getYaw();
                    prevPitch = viewer.getPitch();
                } catch(e) {}
                // 销毁并重建（最简单的方式确保所有热点样式更新）
                viewer.destroy();
                showPanoramaViewer(marker, marker.photos || [marker.panoramaPath]);
                // 恢复视角
                try {
                    if (viewer) {
                        viewer.setYaw(prevYaw, false);
                        viewer.setPitch(prevPitch, false);
                    }
                } catch(e) {}
                showLiveIndicator('⚡ 设置已实时生效');
            }
        }

        // ========== 初始化 ==========
        function init() {
            console.log('init() called, floors:', floors);
            if (!floors || floors.length === 0) {
                document.getElementById('floorplanContainer').innerHTML = '<p style="color: #666;">暂无楼层数据</p>';
                return;
            }
            const tabsContainer = document.getElementById('floorTabs');
            floors.forEach((floor, idx) => {
                const tab = document.createElement('button');
                tab.className = 'floor-tab' + (idx === 0 ? ' active' : '');
                tab.textContent = floor.name;
                tab.onclick = () => switchFloor(idx);
                tabsContainer.appendChild(tab);
            });
            // 同步UI显示
            syncUIFromConfig();
            loadFloor(0);
        }

        function switchFloor(index) {
            currentFloorIndex = index;
            currentMarkerIndex = 0;
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
            currentScale = 1;
            currentOffsetX = 0;
            currentOffsetY = 0;
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
                const imgNaturalWidth = img.naturalWidth;
                const imgNaturalHeight = img.naturalHeight;
                const wrapperWidth = wrapper.clientWidth;
                const wrapperHeight = wrapper.clientHeight;
                const baseScale = Math.min(wrapperWidth / imgNaturalWidth, wrapperHeight / imgNaturalHeight);
                const displayedWidth = imgNaturalWidth * baseScale;
                const displayedHeight = imgNaturalHeight * baseScale;
                const offsetX = (wrapperWidth - displayedWidth) / 2;
                const offsetY = (wrapperHeight - displayedHeight) / 2;
                wrapper.dataset.baseScale = baseScale;
                wrapper.dataset.displayedWidth = displayedWidth;
                wrapper.dataset.displayedHeight = displayedHeight;
                wrapper.dataset.offsetX = offsetX;
                wrapper.dataset.offsetY = offsetY;
                wrapper.dataset.imgNaturalWidth = imgNaturalWidth;
                wrapper.dataset.imgNaturalHeight = imgNaturalHeight;
                renderMarkers(wrapper, floor.markers, offsetX, offsetY, displayedWidth, displayedHeight);
                addZoomControls(container);
                addZoomEvents(wrapper, img, floor.markers);
                renderSectors(wrapper, floor.markers, offsetX, offsetY, displayedWidth, displayedHeight, 1);
                loadPanorama(0);
            };
            img.onerror = () => { container.innerHTML = '<p style="color: #666;">平面图加载失败</p>'; };
        }

        function renderMarkers(wrapper, markers, offsetX, offsetY, displayedWidth, displayedHeight) {
            wrapper.querySelectorAll('.marker-dot').forEach(dot => dot.remove());
            markers.forEach((marker, idx) => {
                const dot = document.createElement('div');
                const statusClass = marker.status || 'pending';
                dot.className = 'marker-dot ' + statusClass + (idx === 0 ? ' active' : '');
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

        function renderSectors(wrapper, markers, offsetX, offsetY, displayedWidth, displayedHeight, scale) {
            wrapper.querySelectorAll('.sector-svg').forEach(s => s.remove());
            const sectorAngle = 90;
            const radius = 30;
            markers.forEach((marker, idx) => {
                if (idx !== currentMarkerIndex) return;
                let direction;
                if (currentSectorDirection !== null) {
                    direction = currentSectorDirection;
                } else if (marker.direction !== null && marker.direction !== undefined && marker.direction !== '') {
                    direction = parseFloat(marker.direction);
                } else { return; }
                const cx = offsetX + (marker.x * displayedWidth);
                const cy = offsetY + (marker.y * displayedHeight);
                const ang = direction;
                const half = sectorAngle / 2;
                const startAngDeg = -(ang + half);
                const startAng = startAngDeg * Math.PI / 180;
                const endAng = (startAngDeg + sectorAngle) * Math.PI / 180;
                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.classList.add('sector-svg');
                svg.style.position = 'absolute';
                svg.style.left = '0';
                svg.style.top = '0';
                svg.style.width = '100%';
                svg.style.height = '100%';
                svg.style.pointerEvents = 'none';
                svg.style.zIndex = '5';
                svg.setAttribute('viewBox', '0 0 ' + wrapper.clientWidth + ' ' + wrapper.clientHeight);
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                const r = radius;
                const leftRad = startAng;
                const lx = cx + r * Math.cos(leftRad);
                const ly = cy - r * Math.sin(leftRad);
                const rightRad = endAng;
                const rx = cx + r * Math.cos(rightRad);
                const ry = cy - r * Math.sin(rightRad);
                const d = 'M ' + cx + ' ' + cy + ' L ' + lx + ' ' + ly + ' A ' + r + ' ' + r + ' 0 0 0 ' + rx + ' ' + ry + ' Z';
                path.setAttribute('d', d);
                path.setAttribute('fill', 'rgba(0, 122, 255, 0.25)');
                path.setAttribute('stroke', 'rgba(255, 255, 255, 0.7)');
                path.setAttribute('stroke-width', '1');
                svg.appendChild(path);
                wrapper.appendChild(svg);
            });
        }

        function addZoomControls(container) {
            const controls = document.createElement('div');
            controls.className = 'zoom-controls';
            controls.innerHTML = '<button class="zoom-btn" onclick="zoomIn()" title="放大">+</button><button class="zoom-btn" onclick="zoomOut()" title="缩小">−</button><button class="zoom-btn zoom-reset" onclick="zoomReset()" title="重置">重置</button>';
            container.appendChild(controls);
        }

        function addZoomEvents(wrapper, img, markers) {
            wrapper.addEventListener('wheel', function(e) {
                e.preventDefault();
                const rect = wrapper.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                const mouseY = e.clientY - rect.top;
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                const newScale = Math.max(0.5, Math.min(5, currentScale * delta));
                if (newScale !== currentScale) {
                    const scaleRatio = newScale / currentScale;
                    currentOffsetX = mouseX - (mouseX - currentOffsetX) * scaleRatio;
                    currentOffsetY = mouseY - (mouseY - currentOffsetY) * scaleRatio;
                    currentScale = newScale;
                    applyTransform(wrapper, img, markers);
                }
            }, { passive: false });
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
                    initialTouchDistance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
                    initialTouchCenter = { x: (touch1.clientX + touch2.clientX) / 2, y: (touch1.clientY + touch2.clientY) / 2 };
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
                    const distance = Math.hypot(touch2.clientX - touch1.clientX, touch2.clientY - touch1.clientY);
                    const currentCenter = { x: (touch1.clientX + touch2.clientX) / 2, y: (touch1.clientY + touch2.clientY) / 2 };
                    if (initialTouchDistance > 0) {
                        const scaleDelta = distance / initialTouchDistance;
                        const newScale = Math.max(0.5, Math.min(5, initialScale * scaleDelta));
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
            wrapper.addEventListener('dblclick', function() { zoomReset(); });
        }

        function applyTransform(wrapper, img, markers) {
            img.style.transform = 'translate(' + currentOffsetX + 'px, ' + currentOffsetY + 'px) scale(' + currentScale + ')';
            const baseOffsetX = parseFloat(wrapper.dataset.offsetX);
            const baseOffsetY = parseFloat(wrapper.dataset.offsetY);
            const displayedWidth = parseFloat(wrapper.dataset.displayedWidth);
            const displayedHeight = parseFloat(wrapper.dataset.displayedHeight);
            wrapper.querySelectorAll('.marker-dot').forEach(dot => {
                const markerX = parseFloat(dot.dataset.markerX);
                const markerY = parseFloat(dot.dataset.markerY);
                const leftPos = baseOffsetX + currentOffsetX + (markerX * displayedWidth * currentScale);
                const topPos = baseOffsetY + currentOffsetY + (markerY * displayedHeight * currentScale);
                dot.style.left = leftPos + 'px';
                dot.style.top = topPos + 'px';
                dot.style.transform = 'translate(-50%, -50%)';
            });
            renderSectors(wrapper, markers, baseOffsetX + currentOffsetX, baseOffsetY + currentOffsetY, displayedWidth * currentScale, displayedHeight * currentScale, currentScale);
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
        let viewMode = 'panorama';
        let currentPhotoIndex = 0;
        let photoScale = 1;
        let photoOffsetX = 0;
        let photoOffsetY = 0;
        let isPhotoDragging = false;
        let photoDragStartX = 0;
        let photoDragStartY = 0;
        let currentSectorDirection = null;

        function loadPanorama(index) {
            const floor = floors[currentFloorIndex];
            if (floor.markers.length === 0) return;
            currentMarkerIndex = index;
            const marker = floor.markers[index];
            document.getElementById('current-title').textContent = marker.customName || marker.cameraFileName || '点位' + (index + 1);
            document.getElementById('current-floor').textContent = floor.name;
            document.querySelectorAll('.marker-dot').forEach((dot, idx) => {
                dot.classList.toggle('active', idx === index);
            });
            var roamInd2 = document.getElementById('roamIndicator');
            if (roamInd2) roamInd2.style.display = 'none';
            currentSectorDirection = null;
            const wrapper = document.getElementById('floorplanWrapper');
            if (wrapper) {
                const baseOffsetX = parseFloat(wrapper.dataset.offsetX) || 0;
                const baseOffsetY = parseFloat(wrapper.dataset.offsetY) || 0;
                const displayedWidth = parseFloat(wrapper.dataset.displayedWidth) || 0;
                const displayedHeight = parseFloat(wrapper.dataset.displayedHeight) || 0;
                renderSectors(wrapper, floor.markers, baseOffsetX + currentOffsetX, baseOffsetY + currentOffsetY, displayedWidth * currentScale, displayedHeight * currentScale, currentScale);
            }
            if (!marker.panoramaPath) {
                if (viewer) viewer.destroy();
                viewer = null;
                document.getElementById('panorama').innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#666;font-size:18px;">该点位暂无影像</div>';
                document.getElementById('panorama').style.display = 'block';
                document.getElementById('photoViewer').classList.remove('active');
                return;
            }
            if (isVREnabled) { loadVRView(marker); return; }
            const photos = marker.photos || [marker.panoramaPath];
            let mode = viewMode;
            if (mode === 'auto') mode = 'panorama';
            updateViewModeUI(mode);
            if (mode === 'panorama') {
                showPanoramaViewer(marker, photos);
            } else {
                showPhotoViewer(marker, photos);
            }
        }

        function updateViewModeUI(mode) {
            const btn = document.getElementById('viewModeBtn');
            if (mode === 'panorama') {
                btn.innerHTML = '🌐 <span>全景</span>';
                btn.classList.add('active');
            } else {
                btn.innerHTML = '🖼️ <span>图片</span>';
                btn.classList.remove('active');
            }
        }

        function toggleViewMode() {
            const floor = floors[currentFloorIndex];
            const marker = floor.markers[currentMarkerIndex];
            if (!marker.panoramaPath) return;
            if (viewMode === 'panorama') {
                viewMode = 'photo';
            } else {
                viewMode = 'panorama';
            }
            loadPanorama(currentMarkerIndex);
        }

        function showPanoramaViewer(marker, photos) {
            document.getElementById('panorama').style.display = 'block';
            document.getElementById('photoViewer').classList.remove('active');
            
            let prevYaw = 0, prevPitch = 0, prevHfov = 100;
            if (viewer) {
                try {
                    prevYaw = viewer.getYaw();
                    prevPitch = viewer.getPitch();
                    prevHfov = viewer.getHfov();
                } catch(e) {}
            }
            
            const panoramaDiv = document.getElementById('panorama');
            panoramaDiv.style.transition = 'opacity ' + (RoamConfig.fadeOutDuration / 1000) + 's ease';
            panoramaDiv.style.opacity = '0.3';
            
            if (viewer) viewer.destroy();
            
            const config = {
                autoLoad: true,
                compass: true,
                showFullscreenCtrl: true,
                showZoomCtrl: true,
                title: marker.customName || '',
                orientationOnByDefault: isGyroEnabled,
                friction: 0.1,
                mouseZoom: true,
                draggable: true,
                sceneFadeDuration: RoamConfig.fadeInDuration
            };
            
            if (window._preservedView && window._preservedView.yaw !== null) {
                config.yaw = window._preservedView.yaw;
                config.pitch = window._preservedView.pitch;
                console.log('[智能朝向] 应用 preserved yaw:', config.yaw, 'pitch:', config.pitch);
                window._preservedView = null;
            }
            
            if (photos.length === 4) {
                config.type = 'cubemap';
                config.cubeMap = photos;
            } else {
                config.type = 'equirectangular';
                config.panorama = photos[0];
            }
            
            config.hotSpots = getRoamHotSpotsConfig(marker);
            
            viewer = pannellum.viewer('panorama', config);
            
            setTimeout(() => {
                panoramaDiv.style.opacity = '1';
            }, 50);
            
            var indicator = document.getElementById('roamIndicator');
            if (indicator) {
                if (config.hotSpots && config.hotSpots.length > 0) {
                    indicator.style.display = 'block';
                } else {
                    indicator.style.display = 'none';
                }
            }
            
            let baseDirection = (marker.direction !== null && marker.direction !== undefined && marker.direction !== '') 
                ? parseFloat(marker.direction) : -90;
            let initialYaw = null;
            currentSectorDirection = null;
            
            const wrapper = document.getElementById('floorplanWrapper');
            if (wrapper) {
                const floor = floors[currentFloorIndex];
                const baseOffsetX = parseFloat(wrapper.dataset.offsetX) || 0;
                const baseOffsetY = parseFloat(wrapper.dataset.offsetY) || 0;
                const displayedWidth = parseFloat(wrapper.dataset.displayedWidth) || 0;
                const displayedHeight = parseFloat(wrapper.dataset.displayedHeight) || 0;
                renderSectors(wrapper, floor.markers, baseOffsetX + currentOffsetX, baseOffsetY + currentOffsetY, displayedWidth * currentScale, displayedHeight * currentScale, currentScale);
            }
            
            const sendDirectionUpdate = (yaw) => {
                if (initialYaw === null) {
                    initialYaw = yaw;
                    console.log('[全景] 初始视角 yaw:', yaw, '基准方向:', baseDirection);
                    return;
                }
                let delta = yaw - initialYaw;
                if (Math.abs(delta) < 1) return;
                let newDirection = baseDirection + delta;
                newDirection = ((newDirection + 180) % 360 + 360) % 360 - 180;
                currentSectorDirection = newDirection;
                
                const wrapper = document.getElementById('floorplanWrapper');
                if (wrapper) {
                    const floor = floors[currentFloorIndex];
                    const baseOffsetX = parseFloat(wrapper.dataset.offsetX) || 0;
                    const baseOffsetY = parseFloat(wrapper.dataset.offsetY) || 0;
                    const displayedWidth = parseFloat(wrapper.dataset.displayedWidth) || 0;
                    const displayedHeight = parseFloat(wrapper.dataset.displayedHeight) || 0;
                    renderSectors(wrapper, floor.markers, baseOffsetX + currentOffsetX, baseOffsetY + currentOffsetY, displayedWidth * currentScale, displayedHeight * currentScale, currentScale);
                }
                
                const currentMarker = floors[currentFloorIndex].markers[currentMarkerIndex];
                if (currentMarker && currentMarker.id) {
                    let syncDir = ((newDirection + 180) % 360 + 360) % 360 - 180;
                    fetch(`/api/set_direction?marker_id=${encodeURIComponent(currentMarker.id)}&direction=${syncDir}`)
                        .then(r => r.json())
                        .then(data => console.log('[联动] 方向已同步:', data.direction))
                        .catch(err => console.log('[联动] 同步失败:', err));
                }
            };
            
            if (window._syncInterval) {
                clearInterval(window._syncInterval);
                window._syncInterval = null;
            }
            
            window._syncInterval = setInterval(() => {
                if (!viewer) { 
                    clearInterval(window._syncInterval); 
                    window._syncInterval = null;
                    return; 
                }
                try {
                    const yaw = viewer.getYaw();
                    sendDirectionUpdate(yaw);
                } catch(e) {}
            }, 100);
            
            if (isGyroEnabled && viewer) {
                setTimeout(() => {
                    try { if (viewer.enableOrientation) viewer.enableOrientation(); }
                    catch(e) { console.log('启用陀螺仪控制:', e); }
                }, 100);
            }
            
            if (RoamConfig.preloadEnabled) {
                setTimeout(function() {
                    PreloadManager.maxConcurrent = RoamConfig.maxConcurrent;
                    PreloadManager.clear();
                    PreloadManager.preloadForMarker(marker);
                    if (RoamConfig.debugLog) console.log('[预加载] 已触发相邻场景预加载');
                }, RoamConfig.preloadDelay);
            }
        }

        function showPhotoViewer(marker, photos) {
            document.getElementById('panorama').style.display = 'none';
            if (viewer) { viewer.destroy(); viewer = null; }
            if (window._syncInterval) { clearInterval(window._syncInterval); window._syncInterval = null; }
            var roamInd = document.getElementById('roamIndicator');
            if (roamInd) roamInd.style.display = 'none';
            
            const photoViewer = document.getElementById('photoViewer');
            photoViewer.classList.add('active');
            currentPhotoIndex = 0;
            photoScale = 1;
            photoOffsetX = 0;
            photoOffsetY = 0;
            renderPhoto(photos);
        }

        function renderPhoto(photos) {
            const img = document.getElementById('photoImg');
            const prevBtn = document.getElementById('photoPrev');
            const nextBtn = document.getElementById('photoNext');
            const counter = document.getElementById('photoCounter');
            
            img.src = photos[currentPhotoIndex];
            img.style.transform = 'translate(0px, 0px) scale(1)';
            photoScale = 1;
            photoOffsetX = 0;
            photoOffsetY = 0;
            
            const showNav = photos.length > 1;
            prevBtn.style.display = showNav ? 'flex' : 'none';
            nextBtn.style.display = showNav ? 'flex' : 'none';
            counter.style.display = showNav ? 'block' : 'none';
            counter.textContent = (currentPhotoIndex + 1) + ' / ' + photos.length;
        }

        function nextPhoto() {
            const floor = floors[currentFloorIndex];
            const marker = floor.markers[currentMarkerIndex];
            const photos = marker.photos || [marker.panoramaPath];
            if (photos.length <= 1) return;
            currentPhotoIndex = (currentPhotoIndex + 1) % photos.length;
            renderPhoto(photos);
        }

        function prevPhoto() {
            const floor = floors[currentFloorIndex];
            const marker = floor.markers[currentMarkerIndex];
            const photos = marker.photos || [marker.panoramaPath];
            if (photos.length <= 1) return;
            currentPhotoIndex = (currentPhotoIndex - 1 + photos.length) % photos.length;
            renderPhoto(photos);
        }

        (function setupPhotoViewerEvents() {
            const viewerEl = document.getElementById('photoViewer');
            const img = document.getElementById('photoImg');
            
            viewerEl.addEventListener('wheel', function(e) {
                if (!viewerEl.classList.contains('active')) return;
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                photoScale = Math.max(0.5, Math.min(5, photoScale * delta));
                img.style.transform = 'translate(' + photoOffsetX + 'px, ' + photoOffsetY + 'px) scale(' + photoScale + ')';
            }, { passive: false });
            
            img.addEventListener('mousedown', function(e) {
                if (!viewerEl.classList.contains('active')) return;
                isPhotoDragging = true;
                photoDragStartX = e.clientX - photoOffsetX;
                photoDragStartY = e.clientY - photoOffsetY;
                img.style.cursor = 'grabbing';
            });
            
            document.addEventListener('mousemove', function(e) {
                if (!isPhotoDragging) return;
                e.preventDefault();
                photoOffsetX = e.clientX - photoDragStartX;
                photoOffsetY = e.clientY - photoDragStartY;
                img.style.transform = 'translate(' + photoOffsetX + 'px, ' + photoOffsetY + 'px) scale(' + photoScale + ')';
            });
            
            document.addEventListener('mouseup', function() {
                isPhotoDragging = false;
                img.style.cursor = 'grab';
            });
            
            img.addEventListener('touchstart', function(e) {
                if (!viewerEl.classList.contains('active') || e.touches.length !== 1) return;
                isPhotoDragging = true;
                photoDragStartX = e.touches[0].clientX - photoOffsetX;
                photoDragStartY = e.touches[0].clientY - photoOffsetY;
            }, { passive: false });
            
            document.addEventListener('touchmove', function(e) {
                if (!isPhotoDragging || e.touches.length !== 1) return;
                e.preventDefault();
                photoOffsetX = e.touches[0].clientX - photoDragStartX;
                photoOffsetY = e.touches[0].clientY - photoDragStartY;
                img.style.transform = 'translate(' + photoOffsetX + 'px, ' + photoOffsetY + 'px) scale(' + photoScale + ')';
            }, { passive: false });
            
            document.addEventListener('touchend', function() {
                isPhotoDragging = false;
            });
            
            img.addEventListener('dblclick', function() {
                if (!viewerEl.classList.contains('active')) return;
                photoScale = 1;
                photoOffsetX = 0;
                photoOffsetY = 0;
                img.style.transform = 'translate(0px, 0px) scale(1)';
            });
        })();

        function toggleGyro() {
            if (isGyroEnabled) {
                isGyroEnabled = false;
                document.getElementById('gyroBtn').classList.remove('active');
                if (!isVREnabled) {
                    loadPanorama(currentMarkerIndex);
                }
            } else {
                if (typeof DeviceOrientationEvent !== 'undefined' && 
                    typeof DeviceOrientationEvent.requestPermission === 'function') {
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
                    enableGyroMode();
                }
            }
        }

        function enableGyroMode() {
            isGyroEnabled = true;
            const btn = document.getElementById('gyroBtn');
            const hint = document.getElementById('gyroHint');
            
            btn.classList.add('active');
            hint.classList.add('show');
            setTimeout(() => hint.classList.remove('show'), 3000);
            
            if (!isVREnabled) {
                loadPanorama(currentMarkerIndex);
            }
        }

        function toggleVR() {
            if (isVREnabled) {
                exitVR();
            } else {
                if (typeof DeviceOrientationEvent !== 'undefined' && 
                    typeof DeviceOrientationEvent.requestPermission === 'function') {
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
                    startVRMode();
                }
            }
        }

        function startVRMode() {
            isVREnabled = true;
            document.getElementById('vrBtn').classList.add('active');
            document.getElementById('vr-container').classList.add('active');
            
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
            
            const elem = document.documentElement;
            if (elem.requestFullscreen) {
                elem.requestFullscreen();
            } else if (elem.webkitRequestFullscreen) {
                elem.webkitRequestFullscreen();
            } else if (elem.msRequestFullscreen) {
                elem.msRequestFullscreen();
            }
            
            const floor = floors[currentFloorIndex];
            const marker = floor.markers[currentMarkerIndex];
            loadVRView(marker);
        }

        function loadVRView(marker) {
            if (vrViewerLeft) vrViewerLeft.destroy();
            if (vrViewerRight) vrViewerRight.destroy();
            
            const photos = marker.photos || [marker.panoramaPath];
            const baseConfig = {
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
            
            if (photos.length === 4) {
                baseConfig.type = 'cubemap';
                baseConfig.cubeMap = photos;
            } else {
                baseConfig.type = 'equirectangular';
                baseConfig.panorama = photos[0];
            }
            
            vrViewerLeft = pannellum.viewer('vrLeft', {
                ...baseConfig,
                haov: 360,
                vaov: 180,
                hfov: 100,
                yaw: -5
            });
            
            vrViewerRight = pannellum.viewer('vrRight', {
                ...baseConfig,
                haov: 360,
                vaov: 180,
                hfov: 100,
                yaw: 5
            });
            
            syncVREyes();
        }

        function syncVREyes() {
            if (!vrViewerLeft || !vrViewerRight) return;
            
            let lastYaw = 0;
            let lastPitch = 0;
            
            const syncView = () => {
                if (!vrViewerLeft || !vrViewerRight) return;
                
                try {
                    const leftYaw = vrViewerLeft.getYaw();
                    const leftPitch = vrViewerLeft.getPitch();
                    
                    if (Math.abs(leftYaw - lastYaw) > 0.1 || Math.abs(leftPitch - lastPitch) > 0.1) {
                        vrViewerRight.setYaw(leftYaw + 10, false);
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

        function exitVR() {
            isVREnabled = false;
            document.getElementById('vrBtn').classList.remove('active');
            document.getElementById('vr-container').classList.remove('active');
            
            if (screen.orientation && screen.orientation.unlock) {
                screen.orientation.unlock();
            } else if (screen.unlockOrientation) {
                screen.unlockOrientation();
            } else if (screen.mozUnlockOrientation) {
                screen.mozUnlockOrientation();
            } else if (screen.msUnlockOrientation) {
                screen.msUnlockOrientation();
            }
            
            if (vrViewerLeft) {
                vrViewerLeft.destroy();
                vrViewerLeft = null;
            }
            if (vrViewerRight) {
                vrViewerRight.destroy();
                vrViewerRight = null;
            }
            
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) {
                document.msExitFullscreen();
            }
            
            loadPanorama(currentMarkerIndex);
        }

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
            
            if (viewer && RoamConfig.smartOrientationEnabled) {
                try {
                    var currentMarker = floor.markers[currentMarkerIndex];
                    var targetMarker = floor.markers[newIndex];
                    var prevYaw = viewer.getYaw();
                    var prevPitch = viewer.getPitch();
                    var currentDir = (currentMarker.direction !== null && currentMarker.direction !== undefined)
                        ? parseFloat(currentMarker.direction) : -90;
                    var currentHeading = normalizeAngle(currentDir + 90);
                    var userOffset = normalizeAngle(prevYaw - currentHeading);
                    var moveAzimuth = getMoveAzimuth(currentMarker, targetMarker);
                    window._preservedView = {
                        yaw: normalizeAngle(moveAzimuth + 180 + userOffset),
                        pitch: Math.max(-RoamConfig.pitchLimit, Math.min(RoamConfig.pitchLimit, prevPitch * RoamConfig.pitchDamping))
                    };
                } catch(e) {}
            }
            
            loadPanorama(newIndex);
        }

        function nextPanorama() {
            const floor = floors[currentFloorIndex];
            if (floor.markers.length === 0) return;
            
            let newIndex = currentMarkerIndex + 1;
            if (newIndex >= floor.markers.length) newIndex = 0;
            
            if (viewer && RoamConfig.smartOrientationEnabled) {
                try {
                    var currentMarker = floor.markers[currentMarkerIndex];
                    var targetMarker = floor.markers[newIndex];
                    var prevYaw = viewer.getYaw();
                    var prevPitch = viewer.getPitch();
                    var currentDir = (currentMarker.direction !== null && currentMarker.direction !== undefined)
                        ? parseFloat(currentMarker.direction) : -90;
                    var currentHeading = normalizeAngle(currentDir + 90);
                    var userOffset = normalizeAngle(prevYaw - currentHeading);
                    var moveAzimuth = getMoveAzimuth(currentMarker, targetMarker);
                    window._preservedView = {
                        yaw: normalizeAngle(moveAzimuth + 180 + userOffset),
                        pitch: Math.max(-RoamConfig.pitchLimit, Math.min(RoamConfig.pitchLimit, prevPitch * RoamConfig.pitchDamping))
                    };
                } catch(e) {}
            }
            
            loadPanorama(newIndex);
        }

        let resizeTimer = null;
        window.addEventListener('resize', function() {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function() {
                loadFloor(currentFloorIndex);
                setTimeout(function() {
                    document.querySelectorAll('.marker-dot').forEach(function(dot, idx) {
                        dot.classList.toggle('active', idx === currentMarkerIndex);
                    });
                }, 100);
            }, 250);
        });

        // ========== 时空转换环系统（黑洞形态 + 透视变形） ==========
        function getRoamHotSpotsConfig(marker) {
            var C = RoamConfig;
            if (!marker || !marker.roamHotSpots || marker.roamHotSpots.length === 0) {
                return [];
            }
            var hotspots = marker.roamHotSpots || [];
            // 数量限制：只显示最靠近的 N 个
            if (C.maxVisibleHotspots > 0 && hotspots.length > C.maxVisibleHotspots) {
                hotspots = hotspots.slice(0, C.maxVisibleHotspots);
            }
            return hotspots.map(function(hs) {
                var pr = hs.perspectiveRatio || 0;

                // 大小：向灭点方向透视缩小
                var easedPr = Math.pow(pr, C.sizeCurve);
                var baseSize = Math.round(C.sizeMax * (1 - easedPr) + C.sizeMin * easedPr);

                // 透视变形：向灭点方向压缩（远处更扁，模拟地面透视）
                var perspectiveCompress = 1 - pr * 0.4;
                var ringHeight = Math.round(baseSize * perspectiveCompress);
                var ringWidth = baseSize;

                // 透明度
                var opacityEased = Math.pow(pr, C.opacityCurve);
                var opacity = C.opacityMax - opacityEased * (C.opacityMax - C.opacityMin);

                // 颜色
                var r = Math.round(C.colorNear[0] + pr * (C.colorFar[0] - C.colorNear[0]));
                var g = Math.round(C.colorNear[1] + pr * (C.colorFar[1] - C.colorNear[1]));
                var b = Math.round(C.colorNear[2] + pr * (C.colorFar[2] - C.colorNear[2]));
                var ringColor = 'rgba(' + r + ', ' + g + ', ' + b + ', ' + opacity + ')';
                var borderColor = 'rgba(255, 255, 255, ' + (C.borderOpacityNear - pr * (C.borderOpacityNear - C.borderOpacityFar)) + ')';

                // 身后点处理
                if (hs.isBehind) {
                    baseSize = Math.round(baseSize * C.behindSizeScale);
                    ringWidth = baseSize;
                    ringHeight = Math.round(baseSize * perspectiveCompress);
                    opacity *= C.behindOpacityScale;
                    r = Math.round(r + (160 - r) * C.behindGrayScale);
                    g = Math.round(g + (160 - g) * C.behindGrayScale);
                    b = Math.round(b + (160 - b) * C.behindGrayScale);
                    ringColor = 'rgba(' + r + ', ' + g + ', ' + b + ', ' + opacity + ')';
                }

                // CSS 类
                var cssClass = 'roam-hotspot';
                if (C.pulseEnabled && pr < C.pulseThreshold) {
                    cssClass += ' pulse';
                }
                if (hs.isBehind) {
                    cssClass += ' behind';
                }

                // 环厚度（随距离变细）
                var ringThickness = Math.max(2, Math.round(4 * (1 - pr * 0.6)));

                // 目标点位照片数量（决定环层数）
                var targetPhotos = hs.photoCount || 1;
                var maxRings = Math.min(targetPhotos, 3);

                if (C.debugLog) {
                    console.log('[时空环]', hs.targetName, 'pr=' + pr.toFixed(3), 'size=' + ringWidth + 'x' + ringHeight, 'rings=' + maxRings);
                }

                // 根据 vanishingPointPitch 配置实时计算 pitch
                    var vanishingPitch = (C.vanishingPointPitch !== undefined) ? C.vanishingPointPitch : -15;
                    var computedPitch = -85 + ((hs.perspectiveRatio || 0) * (vanishingPitch + 85));

                    // 间距密度压缩：远处点视觉间距更小（向灭点方向聚集）
                    var spacingDensity = (C.spacingDensity !== undefined) ? C.spacingDensity : 0.3;
                    var visualYaw = hs.yaw * (1 - spacingDensity * (hs.perspectiveRatio || 0));

                    return {
                    pitch: computedPitch,
                    yaw: visualYaw,
                    type: 'info',
                    clickHandlerFunc: function(e, args) {
                        jumpToMarker(args.targetId);
                    },
                    clickHandlerArgs: { targetId: hs.targetId },
                    cssClass: cssClass,
                    // createTooltipFunc 在热点创建时和 hover 时都会触发
                    // 这里设置热点本身的样式 + 添加 tooltip
                    createTooltipFunc: function(hotSpotDiv, args) {
                        // 设置热点容器大小和透视变形
                        hotSpotDiv.style.width = args.ringWidth + 'px';
                        hotSpotDiv.style.height = args.ringHeight + 'px';
                        hotSpotDiv.style.minWidth = args.ringWidth + 'px';
                        hotSpotDiv.style.minHeight = args.ringHeight + 'px';

                        // 清空并重建内容（避免重复添加）
                        hotSpotDiv.innerHTML = '';

                        var style = args.hotspotStyle || 'blackhole';

                        if (style === 'blackhole') {
                            // ===== 样式A：黑洞环（多层同心圆环） =====
                            for (var ri = 0; ri < args.maxRings; ri++) {
                                var ring = document.createElement('div');
                                ring.style.position = 'absolute';
                                ring.style.top = '50%';
                                ring.style.left = '50%';
                                ring.style.transform = 'translate(-50%, -50%)';
                                ring.style.borderRadius = '50%';
                                ring.style.boxSizing = 'border-box';
                                ring.style.pointerEvents = 'none';

                                var scale = 1 + ri * 0.35;
                                var rw = Math.round(args.ringWidth * scale);
                                var rh = Math.round(args.ringHeight * scale);

                                ring.style.width = rw + 'px';
                                ring.style.height = rh + 'px';

                                var th = Math.max(1, Math.round(args.ringThickness * (1 - ri * 0.15)));
                                ring.style.border = th + 'px solid ' + args.ringColor;

                                var ringOpacity = Math.max(0.2, 1 - ri * 0.25);
                                ring.style.opacity = ringOpacity;

                                // 外发光效果
                                var glowColor = args.ringColor.replace(')', ', 0.3)').replace('rgba', 'rgba');
                                ring.style.boxShadow = '0 0 ' + (8 + ri * 4) + 'px ' + glowColor + ', inset 0 2px 6px rgba(0,0,0,' + (0.7 - ri * 0.15) + ')';

                                hotSpotDiv.appendChild(ring);
                            }

                            // 中心点（黑洞核心）
                            var core = document.createElement('div');
                            core.style.position = 'absolute';
                            core.style.top = '50%';
                            core.style.left = '50%';
                            core.style.transform = 'translate(-50%, -50%)';
                            core.style.width = Math.round(args.ringWidth * 0.25) + 'px';
                            core.style.height = Math.round(args.ringHeight * 0.25) + 'px';
                            core.style.borderRadius = '50%';
                            core.style.background = 'radial-gradient(circle, rgba(0,0,0,0.9) 0%, rgba(20,20,25,0.6) 100%)';
                            core.style.boxShadow = 'inset 0 1px 4px rgba(255,255,255,0.1), 0 0 10px rgba(0,0,0,0.5)';
                            core.style.pointerEvents = 'none';
                            hotSpotDiv.appendChild(core);

                        } else if (style === 'pulse') {
                            // ===== 样式B：脉冲光环（游戏任务标记风格） =====
                            // 外环脉冲
                            var pulseRing = document.createElement('div');
                            pulseRing.className = 'pulse-ring';
                            pulseRing.style.position = 'absolute';
                            pulseRing.style.top = '50%';
                            pulseRing.style.left = '50%';
                            pulseRing.style.transform = 'translate(-50%, -50%)';
                            pulseRing.style.width = Math.round(args.ringWidth * 2.5) + 'px';
                            pulseRing.style.height = Math.round(args.ringHeight * 2.5) + 'px';
                            pulseRing.style.borderRadius = '50%';
                            pulseRing.style.border = '2px solid ' + args.ringColor;
                            pulseRing.style.opacity = '0.6';
                            pulseRing.style.pointerEvents = 'none';
                            pulseRing.style.animation = 'hotspotPulse 2s ease-out infinite';
                            hotSpotDiv.appendChild(pulseRing);

                            // 中环
                            var midRing = document.createElement('div');
                            midRing.style.position = 'absolute';
                            midRing.style.top = '50%';
                            midRing.style.left = '50%';
                            midRing.style.transform = 'translate(-50%, -50%)';
                            midRing.style.width = Math.round(args.ringWidth * 1.6) + 'px';
                            midRing.style.height = Math.round(args.ringHeight * 1.6) + 'px';
                            midRing.style.borderRadius = '50%';
                            midRing.style.border = '2px solid ' + args.ringColor;
                            midRing.style.opacity = '0.4';
                            midRing.style.pointerEvents = 'none';
                            midRing.style.animation = 'hotspotPulse 2s ease-out 0.5s infinite';
                            hotSpotDiv.appendChild(midRing);

                            // 核心实心圆
                            var core = document.createElement('div');
                            core.style.position = 'absolute';
                            core.style.top = '50%';
                            core.style.left = '50%';
                            core.style.transform = 'translate(-50%, -50%)';
                            core.style.width = args.ringWidth + 'px';
                            core.style.height = args.ringHeight + 'px';
                            core.style.borderRadius = '50%';
                            core.style.background = args.ringColor;
                            core.style.opacity = '0.85';
                            core.style.boxShadow = '0 0 20px ' + args.ringColor.replace(')', ', 0.5)').replace('rgba', 'rgba');
                            core.style.pointerEvents = 'none';
                            hotSpotDiv.appendChild(core);

                            // 中心箭头指示
                            var arrow = document.createElement('div');
                            arrow.innerHTML = '▼';
                            arrow.style.position = 'absolute';
                            arrow.style.top = '50%';
                            arrow.style.left = '50%';
                            arrow.style.transform = 'translate(-50%, -50%)';
                            arrow.style.color = 'white';
                            arrow.style.fontSize = Math.round(args.ringWidth * 0.5) + 'px';
                            arrow.style.textShadow = '0 0 4px rgba(0,0,0,0.8)';
                            arrow.style.pointerEvents = 'none';
                            arrow.style.lineHeight = '1';
                            hotSpotDiv.appendChild(arrow);

                        } else if (style === 'arrow') {
                            // ===== 样式C：箭头指引（3D指向效果） =====
                            // 轨迹线
                            var trail = document.createElement('div');
                            trail.style.position = 'absolute';
                            trail.style.top = '50%';
                            trail.style.left = '50%';
                            trail.style.width = '2px';
                            trail.style.height = Math.round(args.ringHeight * 1.5) + 'px';
                            trail.style.background = 'linear-gradient(to bottom, ' + args.ringColor + ', transparent)';
                            trail.style.transform = 'translate(-50%, -100%)';
                            trail.style.opacity = '0.6';
                            trail.style.pointerEvents = 'none';
                            hotSpotDiv.appendChild(trail);

                            // 箭头主体
                            var arrowBody = document.createElement('div');
                            arrowBody.style.position = 'absolute';
                            arrowBody.style.top = '50%';
                            arrowBody.style.left = '50%';
                            arrowBody.style.transform = 'translate(-50%, -50%)';
                            arrowBody.style.width = '0';
                            arrowBody.style.height = '0';
                            arrowBody.style.borderLeft = Math.round(args.ringWidth * 0.6) + 'px solid transparent';
                            arrowBody.style.borderRight = Math.round(args.ringWidth * 0.6) + 'px solid transparent';
                            arrowBody.style.borderBottom = Math.round(args.ringHeight * 0.8) + 'px solid ' + args.ringColor;
                            arrowBody.style.opacity = '0.85';
                            arrowBody.style.filter = 'drop-shadow(0 0 8px ' + args.ringColor.replace(')', ', 0.6)').replace('rgba', 'rgba') + ')';
                            arrowBody.style.pointerEvents = 'none';
                            arrowBody.style.animation = 'arrowBounce 1.5s ease-in-out infinite';
                            hotSpotDiv.appendChild(arrowBody);

                            // 底部圆点（落点标记）
                            var dot = document.createElement('div');
                            dot.style.position = 'absolute';
                            dot.style.top = '50%';
                            dot.style.left = '50%';
                            dot.style.transform = 'translate(-50%, -50%)';
                            dot.style.width = Math.round(args.ringWidth * 0.3) + 'px';
                            dot.style.height = Math.round(args.ringHeight * 0.3) + 'px';
                            dot.style.borderRadius = '50%';
                            dot.style.background = 'white';
                            dot.style.boxShadow = '0 0 10px ' + args.ringColor;
                            dot.style.pointerEvents = 'none';
                            hotSpotDiv.appendChild(dot);
                        }

                        // 点位名称显示控制
                        // showName=true: 常驻显示自定义 label
                        // showName=false: 不显示任何文字（纯转换点）
                        if (C.showName && args.text) {
                            var label = document.createElement('span');
                            label.className = 'marker-label';
                            label.textContent = args.text;
                            label.style.display = 'block';
                            label.style.opacity = '0.9';
                            hotSpotDiv.appendChild(label);
                        }
                        // 不创建 Pannellum 默认 tooltip，避免重复或不需要的文字显示
                    },
                    createTooltipArgs: {
                        ringWidth: ringWidth,
                        ringHeight: ringHeight,
                        ringThickness: ringThickness,
                        ringColor: ringColor,
                        text: hs.targetName,
                        maxRings: maxRings,
                        showName: C.showName,
                        hotspotStyle: C.hotspotStyle
                    },
                    scale: true,
                    text: hs.targetName
                };
            });
        }
function jumpToMarker(targetId) {
            var targetFloorIdx = -1, targetMarkerIdx = -1;
            var targetMarker = null;
            for (var fIdx = 0; fIdx < floors.length; fIdx++) {
                var floor = floors[fIdx];
                for (var mIdx = 0; mIdx < floor.markers.length; mIdx++) {
                    if (floor.markers[mIdx].id === targetId) {
                        targetFloorIdx = fIdx;
                        targetMarkerIdx = mIdx;
                        targetMarker = floor.markers[mIdx];
                        break;
                    }
                }
                if (targetMarker) break;
            }

            if (!targetMarker) return;

            var preservedYaw = null;
            var preservedPitch = null;

            if (RoamConfig.smartOrientationEnabled && viewer && currentMarkerIndex >= 0) {
                try {
                    var currentMarker = floors[currentFloorIndex].markers[currentMarkerIndex];
                    var prevYaw = viewer.getYaw();
                    var prevPitch = viewer.getPitch();
                    
                    var currentDir = (currentMarker.direction !== null && currentMarker.direction !== undefined)
                        ? parseFloat(currentMarker.direction) : -90;
                    var currentHeading = normalizeAngle(currentDir + 90);
                    var userOffset = normalizeAngle(prevYaw - currentHeading);
                    var moveAzimuth = getMoveAzimuth(currentMarker, targetMarker);
                    
                    preservedYaw = normalizeAngle(moveAzimuth + 180 + userOffset);
                    preservedPitch = Math.max(-RoamConfig.pitchLimit, Math.min(RoamConfig.pitchLimit, prevPitch * RoamConfig.pitchDamping));
                    
                    if (RoamConfig.debugLog) {
                        console.log('[智能朝向] 当前heading:', currentHeading.toFixed(1), 
                                    '用户偏移:', userOffset.toFixed(1),
                                    '移动方位:', moveAzimuth.toFixed(1),
                                    '新yaw:', preservedYaw.toFixed(1));
                    }
                } catch(e) {
                    if (RoamConfig.debugLog) console.log('[智能朝向] 计算失败:', e);
                }
            }

            window._preservedView = { yaw: preservedYaw, pitch: preservedPitch };

            if (targetFloorIdx !== currentFloorIndex) {
                switchFloor(targetFloorIdx);
            }

            setTimeout(function(idx) {
                return function() { loadPanorama(idx); };
            }(targetMarkerIdx), 150);
        }

        function toggleRoamSettings() {
            var panel = document.getElementById('roamSettingsPanel');
            var btn = document.getElementById('roamSettingsBtn');
            if (panel.style.display === 'none' || !panel.style.display) {
                panel.style.display = 'block';
                btn.classList.add('active');
                syncUIFromConfig();
            } else {
                panel.style.display = 'none';
                btn.classList.remove('active');
            }
        }

        // 启动
        init();
    </script>
    <div class="brand-footer">
        <span>由 随心系统 生成</span>
        <a href="https://github.com/huangkeqi-cmd/suixi-system">了解更多</a>
    </div>
</body>
</html>'''

        # 使用 replace 方法替换占位符
        html_content = html_content.replace('__FLOORS_JSON__', floors_json if floors_json else '[]')
        html_content = html_content.replace('__PROJECT_NAME__', project_name if project_name else '未命名项目')
        
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
        
        # 先停止已有服务器并等待完全关闭
        if self.server_thread and self.server_thread.is_running:
            self.stop_http_server()
            # 等待旧服务器端口释放，避免 Windows 上 SO_REUSEADDR 导致的竞争
            import time
            time.sleep(1.0)
        
        # 获取照片根目录，传递给 HTTP 服务器用于 direct mapping
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '') if self.project_data else ''
        
        # 尝试不同端口（跳过 8080，因为经常被占用）
        for port in [8888, 9000, 9999, 0]:
            try:
                self.server_thread = HttpServerThread(viewer_dir, port, photo_base_dir=photo_base_dir, parent_app=self)
                self.server_thread.server_started.connect(self._on_server_started)
                self.server_thread.error_occurred.connect(self._on_server_error)
                self.server_thread.start()
                # 等待线程启动并实际开始 serve_forever
                import time
                time.sleep(0.8)
                if not self.server_thread.is_running:
                    print(f"[调试] 端口 {port} 线程未进入运行状态，尝试下一个端口")
                    continue
                # 实际发送一个 HTTP 请求验证服务器是否真正在响应
                verified = False
                for _ in range(5):
                    try:
                        import urllib.request
                        # 使用实际分配的端口（port=0时会自动分配）
                        actual_port = getattr(self.server_thread, 'actual_port', port) or port
                        test_url = f"http://127.0.0.1:{actual_port}/"
                        req = urllib.request.Request(test_url, method='HEAD')
                        req.add_header('User-Agent', 'PanoramaManager/1.0')
                        with urllib.request.urlopen(req, timeout=1.0) as resp:
                            if resp.status in (200, 404):
                                verified = True
                                print(f"[调试] 端口 {port} 验证通过，HTTP {resp.status}")
                                break
                    except Exception as probe_err:
                        print(f"[调试] 端口 {port} 探测中: {probe_err}")
                        time.sleep(0.3)
                if verified:
                    break
                else:
                    print(f"[调试] 端口 {port} 未能验证通过，尝试下一个端口")
                    # 强制停止未验证通过的线程
                    try:
                        self.server_thread.stop()
                    except Exception:
                        pass
                    self.server_thread = None
                    time.sleep(0.5)
            except Exception as e:
                print(f"[调试] 端口 {port} 启动失败: {e}")
                continue
        else:
            QMessageBox.critical(self, "错误", "无法启动服务器，所有端口都被占用或无法响应")
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
        
        # 默认不自动显示服务器信息，由用户手动展开
        self.server_info_group.setVisible(False)
        self.toggle_server_info_btn.setEnabled(True)
        self.toggle_server_info_btn.setText("📡 显示服务器信息")
        self.stop_server_btn.setEnabled(True)
        self.open_web_btn.setEnabled(False)
        
        # 延迟打开浏览器，确保服务器完全就绪（添加缓存破坏参数）
        from PyQt6.QtCore import QTimer
        cached_url = self._cache_bust_url(self.current_local_url)
        QTimer.singleShot(800, lambda: webbrowser.open(cached_url))
    
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
            import time
            old_thread = self.server_thread
            self.server_thread = None
            def do_stop():
                try:
                    old_thread.stop()
                except Exception as e:
                    print(f"[调试] 停止服务器异常: {e}")
            t = threading.Thread(target=do_stop, daemon=True)
            t.start()
            # 最多等待3秒，确保服务器完全关闭
            t.join(timeout=3.0)
            if t.is_alive():
                print("[调试] 警告: 服务器停止超时，可能仍在后台运行")
            else:
                print("[调试] 服务器已完全停止")
            # 额外等待端口释放
            time.sleep(0.5)
        
        self.server_info_group.setVisible(False)
        self.stop_server_btn.setEnabled(False)
        self.open_web_btn.setEnabled(True)
        self.qr_label.clear()
        self.toggle_server_info_btn.setEnabled(False)
        self.toggle_server_info_btn.setText("📡 显示服务器信息")
    
    def _on_marker_moved(self, marker_id: str, norm_x: float, norm_y: float):
        """采集点被拖动后更新坐标数据"""
        if not self.project_data:
            return
        self._push_history()
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    marker_data['x'] = norm_x
                    marker_data['y'] = norm_y
                    self.current_marker = Marker.from_dict(marker_data)
                    self.marker_coord_label.setText(f"({norm_x:.4f}, {norm_y:.4f})")
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    self.canvas.render_direction_sectors()
                    return

    def _on_marker_add_requested(self, norm_x: float, norm_y: float):
        """在平面图上空白处添加新采集点"""
        if not self.project_data or not self.current_floor_id:
            QMessageBox.warning(self, "提示", "请先加载项目并选择楼层")
            return
        self._push_history()
        self._record_command('_on_marker_add_requested', norm_x, norm_y)
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
                    'direction': -90.0  # 新采集点默认朝上
                }
                floor_data.setdefault('markers', []).append(new_marker)
                self.canvas.add_marker(new_id, norm_x, norm_y, 'pending', new_id)
                self.save_changes_btn.setStyleSheet("""
                    QPushButton {
                        padding: 6px 12px; font-size: 13px;
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
        try:
            menu = QMenu(self)
            
            relink_action = QAction("重新关联单点照片", self)
            delete_action = QAction("删除采集点", self)
            sector_action = QAction("显示/隐藏单点扇形", self)
            adjust_action = QAction("调整单点扇形视线方向", self)
            
            menu.addAction(relink_action)
            menu.addAction(delete_action)
            menu.addSeparator()
            menu.addAction(sector_action)
            menu.addSeparator()
            menu.addAction(adjust_action)
            
            # 使用 triggered.connect 方式连接信号
            relink_action.triggered.connect(lambda: self._relink_marker_photo(marker_id))
            delete_action.triggered.connect(lambda: self._delete_marker(marker_id))
            sector_action.triggered.connect(lambda: self._toggle_sector(marker_id))
            adjust_action.triggered.connect(lambda: self._toggle_adjust_mode(marker_id))
            
            # 转换为 QPoint
            if isinstance(global_pos, QPointF):
                pos = global_pos.toPoint()
            else:
                pos = global_pos
            
            menu.exec(pos)
        except Exception as e:
            print(f"[错误] 右键菜单异常: {e}")
            import traceback
            traceback.print_exc()


    def _find_photo_base_dir(self, search_dir: str = None) -> str:
        """智能查找照片根目录：优先 photoBaseDir，其次扫描指定目录或项目附近的照片文件夹"""
        # 1. 优先使用已设置的 photoBaseDir
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
        if photo_base_dir and os.path.exists(photo_base_dir):
            return photo_base_dir
        
        # 2. 如果指定了搜索目录，先扫描该目录
        if search_dir and os.path.exists(search_dir):
            best_dir = None
            best_count = 0
            for item in os.listdir(search_dir):
                item_path = os.path.join(search_dir, item)
                if os.path.isdir(item_path) and item.lower() not in ['viewer', '__pycache__', 'build', 'dist', 'src']:
                    count = 0
                    for root, _, files in os.walk(item_path):
                        for f in files:
                            if f.lower().endswith(('.jpg', '.jpeg')):
                                count += 1
                            if count > best_count:
                                break
                        if count > best_count:
                            break
                    if count > best_count:
                        best_count = count
                        best_dir = item_path
            if best_dir and best_count > 0:
                return best_dir
        
        # 3. 扫描项目目录的同级目录
        parent_dir = os.path.dirname(self.project_dir) if self.project_dir else ''
        if parent_dir and os.path.exists(parent_dir):
            best_dir = None
            best_count = 0
            for item in os.listdir(parent_dir):
                item_path = os.path.join(parent_dir, item)
                if os.path.isdir(item_path) and item.lower() not in ['viewer', '__pycache__', 'build', 'dist', 'src']:
                    count = 0
                    for root, _, files in os.walk(item_path):
                        for f in files:
                            if f.lower().endswith(('.jpg', '.jpeg')):
                                count += 1
                            if count > best_count:
                                break
                        if count > best_count:
                            break
                    if count > best_count:
                        best_count = count
                        best_dir = item_path
            if best_dir and best_count > 0:
                return best_dir
        
        # 4. 回退：使用项目目录下的 photos 文件夹
        fallback = os.path.join(self.project_dir, 'photos') if self.project_dir else ''
        return fallback

    def _resolve_marker_panorama_path(self, marker_data: dict, photo_base_dir: str) -> str:
        """基于 photoBaseDir 重新计算 panoramaPath，修复路径冗余和重复前缀问题"""
        if not photo_base_dir:
            return marker_data.get('panoramaPath', '')
        
        orig = marker_data.get('originalPhotoPath', '')
        path = marker_data.get('panoramaPath', '')
        marker_name = marker_data.get('customName') or marker_data.get('id', 'unknown')
        
        # 调试信息
        print(f"[调试] _resolve_marker_panorama_path: marker={marker_name}")
        print(f"[调试]   originalPhotoPath={orig[:60] if orig else 'None'}")
        print(f"[调试]   panoramaPath={path[:60] if path else 'None'}")
        print(f"[调试]   photo_base_dir={photo_base_dir}")
        
        # 1. 优先基于 originalPhotoPath 重新计算相对路径（最可靠）
        if orig and os.path.exists(orig):
            try:
                if os.path.commonpath([os.path.abspath(orig), os.path.abspath(photo_base_dir)]) == os.path.abspath(photo_base_dir):
                    rel = os.path.relpath(orig, photo_base_dir).replace('\\', '/')
                    return 'external_photos/' + rel
            except ValueError:
                pass
        
        # 2. 退而使用现有的 panoramaPath
        if path:
            # 去掉已有的 external_photos/ 前缀，防止重复
            if path.startswith('external_photos/'):
                path = path[len('external_photos/'):]
            
            if not os.path.isabs(path):
                # 如果 photoBaseDir 的 basename 是 photos，且 path 以 photos/ 开头，
                # 说明之前是基于项目根目录的相对路径，需要去掉 photos/ 层
                if os.path.basename(photo_base_dir.rstrip('\\/')) == 'photos' and path.startswith('photos/'):
                    path = path[len('photos/'):]
                return 'external_photos/' + path
            else:
                # 绝对路径，尝试转为相对路径
                try:
                    if os.path.commonpath([os.path.abspath(path), os.path.abspath(photo_base_dir)]) == os.path.abspath(photo_base_dir):
                        rel = os.path.relpath(path, photo_base_dir).replace('\\', '/')
                        return 'external_photos/' + rel
                except ValueError:
                    pass
                result = path.replace('\\', '/')
                print(f"[调试]   -> 使用 panoramaPath (绝对): {result}")
                return result
        
        # 3. 如果都无法解析，保留原始值而不是返回空字符串（注意：这里是和 if path: 同级）
        # 优先使用 panoramaPath，其次 originalPhotoPath
        original_path = marker_data.get('panoramaPath', '') or marker_data.get('originalPhotoPath', '')
        if original_path:
            print(f"[警告] _resolve_marker_panorama_path: 无法解析路径，保留原值: {original_path}")
            return original_path
        
        # 4. 最终兜底：返回空字符串（确实没有任何路径信息）
        print(f"[错误] _resolve_marker_panorama_path: {marker_name} 没有任何照片路径信息!")
        return ''

    def _toggle_adjust_mode(self, marker_id: str):
        """切换调整模式：鼠标绕采集点中心旋转扇形，双击确认退出"""
        self._adjust_mode = getattr(self, '_adjust_mode', False)
        self._record_command('_toggle_adjust_mode', marker_id)
        
        self._adjust_mode = not self._adjust_mode
        
        if self._adjust_mode:
            # 进入调整模式
            self.import_status_label.setText("🔧 调整模式：鼠标绕采集点旋转扇形 | 双击平面确认角度")
            self.rotate_left_btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 10px; font-size: 12px;
                    background-color: #FF9500; color: white;
                    border: none; border-radius: 4px;
                }
                QPushButton:hover { background-color: #B36800; }
            """)
            self.rotate_right_btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 10px; font-size: 12px;
                    background-color: #FF9500; color: white;
                    border: none; border-radius: 4px;
                }
                QPushButton:hover { background-color: #B36800; }
            """)
            # 设置画布为调整模式
            self.canvas._adjust_mode = True
            self.canvas._adjust_marker_id = marker_id
            
            self.import_status_label.setText(
                "🔧 调整模式：移动鼠标旋转扇形方向 | 双击平面确认退出 | 也可使用「↺ 左转」/「右转 ↻」按钮"
            )
        else:
            # 退出调整模式
            self._exit_adjust_mode()
    
    def _exit_adjust_mode(self):
        """退出调整模式 - 确认当前扇形方向为新的默认方向"""
        self._push_history()
        self._adjust_mode = False
        self.import_status_label.setText("就绪")
        self.rotate_left_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px; font-size: 12px;
                background-color: #3A3A3C; color: white;
                border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #48484A; }
        """)
        self.rotate_right_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 10px; font-size: 12px;
                background-color: #3A3A3C; color: white;
                border: none; border-radius: 4px;
            }
            QPushButton:hover { background-color: #48484A; }
        """)
        self.save_changes_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px; font-size: 13px;
                background-color: #FF9500; color: white;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
        """)
        self.save_changes_btn.setText("💾 保存修改（已变更）")
        
        # 获取当前调整的点位方向，保存为新的默认方向
        marker_id = self.canvas._adjust_marker_id
        saved = False
        if marker_id:
            item = self.canvas.marker_items.get(marker_id)
            if item:
                final_direction = item.data(2)
                if final_direction is not None:
                    # 更新数据模型中的 direction 为确认后的方向
                    for floor_data in self.project_data.floors:
                        for marker_data in floor_data.get('markers', []):
                            if marker_data['id'] == marker_id:
                                marker_data['direction'] = float(final_direction)
                                break
                    # 保存到 project.json，增加异常处理和日志
                    try:
                        self._save_project()
                        print(f"[调试] 已保存扇形方向 {final_direction:.1f}° 为新的默认方向")
                        saved = True
                    except Exception as e:
                        print(f"[错误] 保存扇形方向失败: {e}")
                        import traceback
                        traceback.print_exc()
                        QMessageBox.critical(self, "保存失败", f"无法保存扇形方向:\n{e}")
        
        # 恢复画布状态
        self.canvas._adjust_mode = False
        self.canvas._adjust_marker_id = None
        
        # 给出完成提示（悬浮文字，无需确认）
        if saved:
            self.import_status_label.setText("✅ 扇形方向已保存到项目")
        else:
            self.import_status_label.setText("✅ 已确认扇形视线角度")

    def _toggle_server_info(self):
        """切换服务器信息的显示/隐藏"""
        visible = self.server_info_group.isVisible()
        self.server_info_group.setVisible(not visible)
        if visible:
            self.toggle_server_info_btn.setText("📡 显示服务器信息")
        else:
            self.toggle_server_info_btn.setText("📡 隐藏服务器信息")

    def _on_marker_info_group_toggled(self, checked):
        """点位信息组折叠/展开"""
        for child in self.marker_info_group.findChildren(QWidget):
            if child != self.marker_info_group:
                child.setVisible(checked)

    def _on_linked_photos_group_toggled(self, checked):
        """已关联照片组折叠/展开"""
        for child in self.linked_photos_group.findChildren(QWidget):
            if child != self.linked_photos_group:
                child.setVisible(checked)

    def _toggle_sector(self, marker_id: str = None):
        """切换单个或所有点位的扇形视线范围显示
        
        如果传入了 marker_id，则只切换该点位的扇形显示/隐藏（局部模式）。
        如果 marker_id 为 None，则切换全局所有点位的扇形显示/隐藏（全局模式）。
        """
        if not self.project_data or not self.current_floor_id:
            return
        
        current_floor_data = None
        for f in self.project_data.floors:
            if f['id'] == self.current_floor_id:
                current_floor_data = f
                break
        
        if not current_floor_data:
            return
        
        self._push_history()
        self._record_command('_toggle_sector')
        
        if marker_id:
            # === 局部模式：只切换指定点位的扇形 ===
            target_marker = None
            for marker_data in current_floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    target_marker = marker_data
                    break
            
            if not target_marker:
                return
            
            # 检查该点位当前是否有扇形显示（direction 不为 None 表示有扇形）
            current_direction = target_marker.get('direction')
            
            if current_direction is not None:
                # 当前有扇形，隐藏它：保存当前值到 _prev_direction，设为 None
                target_marker['_prev_direction'] = current_direction
                target_marker['direction'] = None
            else:
                # 当前无扇形，显示它：恢复 _prev_direction 或默认 -90
                prev = target_marker.pop('_prev_direction', None)
                target_marker['direction'] = prev if prev is not None else -90.0
            
            # 只刷新该点位的椭圆 item 的 direction 数据，不重建整个画布
            item = self.canvas.marker_items.get(marker_id)
            if item:
                item.setData(2, target_marker['direction'])
            
            # 局部重绘扇形（只清除和重绘扇形，不动标记点）
            self.canvas.render_direction_sectors()
        else:
            # === 全局模式：切换所有点位的扇形（原有逻辑）===
            # 检查是否已有扇形显示（通过检查 scene 中是否有 sector 项）
            has_sectors = False
            for item in self.canvas.scene.items():
                if isinstance(item, QGraphicsPathItem) and item.data(0) and str(item.data(0)).endswith('_sector'):
                    has_sectors = True
                    break
            
            if has_sectors:
                # 全部关闭：将所有有 direction 的点位设为 None（保留原值在临时存储中）
                for marker_data in current_floor_data.get('markers', []):
                    if marker_data.get('direction') is not None:
                        marker_data['_prev_direction'] = marker_data['direction']
                        marker_data['direction'] = None
            else:
                # 全部开启：恢复之前保存的值，或设为默认值 -90
                for marker_data in current_floor_data.get('markers', []):
                    prev = marker_data.pop('_prev_direction', None)
                    marker_data['direction'] = prev if prev is not None else -90.0
            
            self.canvas.clear_markers()
            self._load_floor(self.current_floor_id)
            self.canvas.render_direction_sectors()
        
        self.save_changes_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px; font-size: 13px;
                background-color: #FF9500; color: white;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
        """)
        self.save_changes_btn.setText("💾 保存修改（已变更）")
    
    def _delete_marker(self, marker_id: str):
        """删除采集点"""
        if not self.project_data:
            return
        reply = QMessageBox.question(self, "确认删除", f"确定删除点位 {marker_id} 吗？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._push_history()
        for floor_data in self.project_data.floors:
            markers = floor_data.get('markers', [])
            for i, m in enumerate(markers):
                if m['id'] == marker_id:
                    markers.pop(i)
                    self.canvas.clear_markers()
                    self._load_floor(self.current_floor_id)
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
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
        self._push_history()
        self._record_command('_relink_marker_photo', marker_id)
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
                    
                    # 直接使用 external_photos 路径，不复制
                    photo_base_dir = self._find_photo_base_dir()
                    if photo_base_dir and os.path.exists(photo_base_dir):
                        try:
                            rel = os.path.relpath(file_path, photo_base_dir).replace('\\', '/')
                            marker_data['panoramaPath'] = 'external_photos/' + rel
                        except ValueError:
                            marker_data['panoramaPath'] = 'external_photos/' + fname
                    else:
                        marker_data['panoramaPath'] = 'external_photos/' + fname
                    
                    # 最终兜底
                    if not marker_data.get('panoramaPath'):
                        marker_data['panoramaPath'] = 'external_photos/' + fname
                    
                    self._on_marker_selected(marker_id)
                    self.canvas.clear_markers()
                    self._load_floor(self.current_floor_id)
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    QMessageBox.information(self, "成功", f"已关联照片: {fname}")
                    return

    def _open_photo_folder(self):
        """打开照片所在文件夹"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            return
        path = self.current_marker.originalPhotoPath or self.current_marker.panoramaPath
        if not path:
            return
        if not os.path.isabs(path):
            path = os.path.join(self.project_dir, path)
        if os.path.exists(path):
            folder = os.path.dirname(path)
            if sys.platform == 'win32':
                os.startfile(folder)
            else:
                import subprocess
                subprocess.call(['open', folder])
        else:
            QMessageBox.warning(self, "提示", "照片文件不存在")

    def _show_photo_picker(self):
        """显示照片选择对话框"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            return
        photo_base_dir = self._find_photo_base_dir()
        dialog = PhotoPickerDialog(photo_base_dir, self.current_marker.id, self)
        if dialog.exec(): 
            selected_path = dialog.selected_path
            if selected_path:
                self._link_photo_to_marker(self.current_marker.id, selected_path)

    def _link_photo_to_marker(self, marker_id: str, file_path: str):
        """将照片关联到指定点位"""
        fname = os.path.basename(file_path)
        photo_base_dir = self._find_photo_base_dir()
        self._push_history()
        self._record_command('_link_photo_to_marker', marker_id, file_path)
        # 如果 photoBaseDir 不存在（或为空），创建项目目录下的 photos 文件夹
        if not photo_base_dir or not os.path.exists(photo_base_dir):
            photo_base_dir = os.path.join(self.project_dir, 'photos')
            os.makedirs(photo_base_dir, exist_ok=True)
            self.project_data.photoBaseDir = photo_base_dir
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    marker_data['cameraFileName'] = fname
                    marker_data['originalPhotoPath'] = file_path
                    marker_data['status'] = 'linked'
                    # 复制照片到 photoBaseDir
                    try:
                        target = os.path.join(photo_base_dir, fname)
                        # 如果目标已存在但路径不同，加后缀避免覆盖
                        if os.path.exists(target) and os.path.abspath(target) != os.path.abspath(file_path):
                            base, ext = os.path.splitext(fname)
                            counter = 1
                            while os.path.exists(target):
                                target = os.path.join(photo_base_dir, f"{base}_{counter}{ext}")
                                counter += 1
                            fname = os.path.basename(target)
                        shutil.copy2(file_path, target)
                        # panoramaPath 存相对于 photoBaseDir 的路径
                        rel = os.path.relpath(target, photo_base_dir).replace('\\', '/')
                        marker_data['panoramaPath'] = rel
                        marker_data['cameraFileName'] = fname
                        print(f"[调试] 照片已复制到: {target}, panoramaPath: {rel}")
                    except Exception as e:
                        print(f"[警告] 复制照片失败: {e}")
                        import traceback
                        traceback.print_exc()
                    # 兜底：如果复制失败，直接用 external_photos 路径
                    if not marker_data.get('panoramaPath'):
                        marker_data['panoramaPath'] = 'external_photos/' + fname
                    self._on_marker_selected(marker_id)
                    self.canvas.clear_markers()
                    self._load_floor(self.current_floor_id)
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    
                    # 如果在调整模式，更新提示
                    if getattr(self, '_adjust_mode', False):
                        self.import_status_label.setText(f"🔧 调整模式 - 当前基准: {new_dir:.0f}°")
                    
                    return

    def _update_photo_preview(self):
        """更新照片预览"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            self.photo_preview.setText("无照片")
            return
        
        # 获取照片路径
        photo_path = self.current_marker.originalPhotoPath or self.current_marker.panoramaPath
        if not photo_path:
            self.photo_preview.setText("无照片")
            return
        
        # 如果是相对路径，尝试转换为绝对路径
        if not os.path.isabs(photo_path):
            photo_base_dir = self._find_photo_base_dir()
            if photo_base_dir:
                # 处理 external_photos/ 前缀
                if photo_path.startswith('external_photos/'):
                    sub_path = photo_path[len('external_photos/'):]
                    photo_path = os.path.join(photo_base_dir, sub_path)
                else:
                    photo_path = os.path.join(self.project_dir, photo_path)
        
        # 加载并显示缩略图
        if os.path.exists(photo_path):
            pixmap = QPixmap(photo_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(200, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.photo_preview.setPixmap(scaled)
            else:
                self.photo_preview.setText("无法加载图片")
        else:
            self.photo_preview.setText("文件不存在")
    
    def _rotate_sector(self, angle_delta: float):
        """旋转当前选中标记点的扇形方向"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            return
        self._push_history()
        self._record_command('_rotate_sector', angle_delta)
        
        marker_id = self.current_marker.id
        
        # 更新数据模型
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    current_dir = marker_data.get('direction', -90.0)
                    if current_dir is None:
                        current_dir = -90.0
                    new_dir = (current_dir + angle_delta) % 360
                    if new_dir > 180:
                        new_dir -= 360
                    marker_data['direction'] = new_dir
                    
                    # 更新画布
                    self.canvas.rotate_sector(marker_id, angle_delta)
                    
                    # 更新显示
                    self.direction_label.setText(f"{new_dir:.0f}°")
                    self.current_marker.direction = new_dir
                    
                    # 标记已修改
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    
                    # 保存扇形方向到 project.json
                    self._save_project()
                    
                    # 如果在调整模式，更新状态提示
                    if getattr(self, '_adjust_mode', False):
                        self.import_status_label.setText(f"🔧 调整模式 - 当前基准: {new_dir:.0f}°")
                    
                    return
    
    def _align_to_panorama(self):
        """将扇形方向对齐到全景照片的当前视角"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            return
        self._push_history()
        self._record_command('_align_to_panorama')
        
        # 弹出对话框让用户输入全景的当前视角
        current_yaw, ok = QInputDialog.getDouble(
            self, "对齐全景", 
            "请输入全景照片当前视角（yaw值，度）:\n"
            "(在全景查看器中拖动视角，查看显示的yaw值)\n\n"
            "0度 = 朝前, 90度 = 朝右, -90度 = 朝左",
            value=0, min=-180, max=180, decimals=1
        )
        
        if not ok:
            return
        
        # 转换：全景 yaw 0度（朝前）对应扇形 direction -90度（朝上，12点钟方向）
        aligned_direction = (-current_yaw - 90) % 360
        if aligned_direction > 180:
            aligned_direction -= 360
        
        # 应用新方向
        marker_id = self.current_marker.id
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    current_dir = marker_data.get('direction', -90.0) or -90.0
                    delta = aligned_direction - current_dir
                    
                    marker_data['direction'] = aligned_direction
                    
                    # 更新画布
                    self.canvas.rotate_sector(marker_id, delta)
                    
                    # 更新显示
                    self.direction_label.setText(f"{aligned_direction:.0f}°")
                    self.current_marker.direction = aligned_direction
                    
                    # 标记已修改
                    self.save_changes_btn.setStyleSheet("""
                        QPushButton {
                            padding: 6px 12px; font-size: 13px;
                            background-color: #FF9500; color: white;
                            border: none; border-radius: 6px;
                        }
                        QPushButton:hover { background-color: #B36800; }
                    """)
                    self.save_changes_btn.setText("💾 保存修改（已变更）")
                    
                    # 保存扇形方向到 project.json
                    self._save_project()
                    return

    def _on_direction_update_from_web(self, marker_id: str, direction: float):
        """从 Web Viewer 接收到的方向更新（实时同步显示，不保存到文件）"""
        # 如果在调整模式，忽略实时同步
        if getattr(self, '_adjust_mode', False):
            return
        
        print(f"[联动] 收到方向更新: marker={marker_id}, direction={direction:.1f}°")
        
        # 更新画布上的扇形（仅实时显示）
        item = self.canvas.marker_items.get(marker_id)
        if item:
            item.setData(2, direction)
            self.canvas.render_direction_sectors()
        
        # 更新内存中的数据模型（不保存文件）
        for floor_data in self.project_data.floors:
            for marker_data in floor_data.get('markers', []):
                if marker_data['id'] == marker_id:
                    marker_data['direction'] = direction
                    break
        
        # 如果当前选中的是这个标记点，更新显示
        if hasattr(self, 'current_marker') and self.current_marker and self.current_marker.id == marker_id:
            self.current_marker.direction = direction
            self.direction_label.setText(f"{direction:.0f}°")

    def _delete_current_marker(self):
        """从右侧删除当前选中的点位"""
        if not hasattr(self, 'current_marker') or not self.current_marker:
            return
        self._record_command('_delete_current_marker')
        self._delete_marker(self.current_marker.id)
        self.marker_info_group.setEnabled(False)
        self._update_floating_toolbar()
        self.canvas.clear_hover()

    def _on_marker_double_clicked(self, marker_id: str):
        """双击点位 - 如果处于调整模式则确认退出，否则替换照片"""
        # 如果是调整模式确认信号
        if marker_id == '__ADJUST_MODE_CONFIRM__':
            self._exit_adjust_mode()
            self.import_status_label.setText("✅ 已确认扇形视线角度")
            return
        
        # 正常双击：替换照片
        photo_base_dir = self._find_photo_base_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择替换的照片", photo_base_dir,
            "图片文件 (*.jpg *.jpeg *.png *.heic *.heif);;所有文件 (*.*)"
        )
        if file_path:
            self._link_photo_to_marker(marker_id, file_path)

    def _on_marker_context_menu(self, marker_id: str, global_pos):
        """采集点右键菜单"""
        try:
            menu = QMenu(self)
            
            relink_action = QAction("重新关联单点照片", self)
            delete_action = QAction("删除采集点", self)
            sector_action = QAction("显示/隐藏单点扇形", self)
            adjust_action = QAction("调整单点扇形视线方向", self)
            set_all_action = QAction("调整所有点扇形视线方向", self)
            
            menu.addAction(relink_action)
            menu.addAction(delete_action)
            menu.addSeparator()
            menu.addAction(sector_action)
            menu.addSeparator()
            menu.addAction(adjust_action)
            menu.addAction(set_all_action)
            
            relink_action.triggered.connect(lambda: self._relink_marker_photo(marker_id))
            delete_action.triggered.connect(lambda: self._delete_marker(marker_id))
            sector_action.triggered.connect(lambda: self._toggle_sector(marker_id))
            adjust_action.triggered.connect(lambda: self._toggle_adjust_mode(marker_id))
            set_all_action.triggered.connect(self._set_all_sectors_direction)
            
            pos = global_pos.toPoint() if isinstance(global_pos, QPointF) else global_pos
            menu.exec(pos)
        except Exception as e:
            print(f"[错误] 右键菜单异常: {e}")
            import traceback
            traceback.print_exc()

    def _set_all_sectors_direction(self):
        """统一设置当前楼层所有扇形方向"""
        if not self.project_data or not self.current_floor_id:
            return
        self._push_history()
        self._record_command('_set_all_sectors_direction')
        angle, ok = QInputDialog.getDouble(
            self, "调整全部方向",
            "请输入固定角度（度）:\n-90=朝上, 0=朝右, 90=朝下, ±180=朝左",
            value=-90, min=-180, max=180, decimals=1
        )
        if not ok:
            return
        # 应用到当前楼层所有标记点
        for floor_data in self.project_data.floors:
            if floor_data['id'] == self.current_floor_id:
                for marker_data in floor_data.get('markers', []):
                    marker_data['direction'] = float(angle)
                break
        # 刷新显示
        self.canvas.clear_markers()
        self._load_floor(self.current_floor_id)
        self.canvas.render_direction_sectors()
        # 标记已修改
        self.save_changes_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 12px; font-size: 13px;
                background-color: #FF9500; color: white;
                border: none; border-radius: 6px;
            }
            QPushButton:hover { background-color: #B36800; }
        """)
        self.save_changes_btn.setText("💾 保存修改（已变更）")

    def _save_project_changes(self):
        """保存项目修改到 project.json"""
        if not self.project_dir or not self.project_data:
            return
        try:
            self._save_project()
            # 强制重新生成 viewer
            viewer_dir = os.path.join(self.project_dir, 'viewer')
            os.makedirs(viewer_dir, exist_ok=True)
            self._regenerate_viewer(viewer_dir)
            
            # 如果服务器在运行，自动打开浏览器刷新（添加缓存破坏参数）
            if self.server_thread and self.server_thread.is_running:
                webbrowser.open(self._cache_bust_url(self.current_local_url))
            
            self.save_changes_btn.setStyleSheet("""
                QPushButton {
                    padding: 6px 12px; font-size: 13px;
                    background-color: #5856D6; color: white;
                    border: none; border-radius: 6px;
                }
                QPushButton:hover { background-color: #3f3ea8; }
                QPushButton:disabled { background-color: #CCC; }
            """)
            self.save_changes_btn.setText("💾 保存修改到项目")
            QMessageBox.information(self, "成功", "项目已保存，浏览器正在刷新...")
        except Exception as e:
            import traceback
            error_msg = traceback.format_exc()
            print(f"[错误] 保存失败: {error_msg}")
            QMessageBox.critical(self, "错误", f"保存失败:\n{str(e)}\n\n详细信息已写入日志")

    def _regenerate_viewer(self, viewer_dir: str):
        """静默重新生成查看器（只更新数据和HTML，不重建照片链接）"""
        photo_base_dir = getattr(self.project_data, 'photoBaseDir', '')
        
        # 只更新 project.json，不碰 external_photos
        project_copy = self.project_data.to_dict()
        if photo_base_dir and os.path.exists(photo_base_dir):
            for floor_data in project_copy.get('floors', []):
                for marker_data in floor_data.get('markers', []):
                    if marker_data.get('status') == 'linked' and marker_data.get('panoramaPath'):
                        marker_data['panoramaPath'] = self._resolve_marker_panorama_path(marker_data, photo_base_dir)
        with open(os.path.join(viewer_dir, 'project.json'), 'w', encoding='utf-8') as f:
            json.dump(project_copy, f, ensure_ascii=False, indent=2)
        
        # 复制平面图（可能更新了）
        for floor_data in self.project_data.floors:
            floor_id = floor_data['id']
            src = os.path.join(self.project_dir, f'floorplan_{floor_id}.jpg')
            if not os.path.exists(src) and self.project_data.floorplan:
                src = os.path.join(self.project_dir, self.project_data.floorplan)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(viewer_dir, f'floorplan_{floor_id}.jpg'))
        
        # 重新生成 HTML
        self._generate_viewer_html(viewer_dir)

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
            """<h2>随系 · 影像管理器 V1.5</h2>
            <p>用于商业改造现场的影像与平面图关联管理工具</p>
            <p>特点: 100% 离线、数据本地、现场容错优先</p>
            <p>© 2026 PanoramaManager</p>""")
    
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

class PhotoPickerDialog(QDialog):
    """照片选择对话框 - 支持预览和上一张/下一张切换"""
    def __init__(self, photo_base_dir: str, marker_id: str, parent=None):
        super().__init__(parent)
        self.photo_base_dir = photo_base_dir
        self.marker_id = marker_id
        self.selected_path = None
        self.photo_files = []
        self.current_index = 0
        
        self.setWindowTitle("选择照片")
        self.setMinimumSize(500, 600)
        self._init_ui()
        self._scan_photos()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # 预览区域
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(350)
        self.preview_label.setStyleSheet("background-color: #1C1C1E; border-radius: 8px;")
        layout.addWidget(self.preview_label)
        
        # 文件名
        self.filename_label = QLabel("未选择")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filename_label.setStyleSheet("font-size: 13px; color: #666; padding: 4px;")
        layout.addWidget(self.filename_label)
        
        # 导航按钮
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 上一张")
        self.prev_btn.setStyleSheet("""
            QPushButton { padding: 10px 20px; font-size: 13px; background-color: #3A3A3C; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #48484A; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.prev_btn.clicked.connect(self._show_prev)
        nav_layout.addWidget(self.prev_btn)
        
        self.index_label = QLabel("0 / 0")
        self.index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.index_label.setStyleSheet("font-size: 13px; color: #999;")
        nav_layout.addWidget(self.index_label, 1)
        
        self.next_btn = QPushButton("下一张 ▶")
        self.next_btn.setStyleSheet("""
            QPushButton { padding: 10px 20px; font-size: 13px; background-color: #3A3A3C; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #48484A; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.next_btn.clicked.connect(self._show_next)
        nav_layout.addWidget(self.next_btn)
        layout.addLayout(nav_layout)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        self.browse_btn = QPushButton("📂 浏览其他文件夹...")
        self.browse_btn.setStyleSheet("""
            QPushButton { padding: 10px 16px; font-size: 13px; background-color: #0a84ff; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #0866c6; }
        """)
        self.browse_btn.clicked.connect(self._browse_other_folder)
        btn_layout.addWidget(self.browse_btn)
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton { padding: 10px 20px; font-size: 13px; background-color: #666; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #555; }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("确认选择")
        ok_btn.setStyleSheet("""
            QPushButton { padding: 10px 20px; font-size: 13px; background-color: #34C759; color: white; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #248A3D; }
        """)
        ok_btn.clicked.connect(self._confirm)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)
    
    def _scan_photos(self):
        """扫描照片文件夹"""
        self.photo_files = []
        scan_dir = self.photo_base_dir
        # 如果指定目录不存在或没有照片，尝试找附近的照片目录
        if not scan_dir or not os.path.exists(scan_dir):
            parent = os.path.dirname(scan_dir) if scan_dir else os.path.expanduser('~')
            if os.path.exists(parent):
                best_dir = None
                best_count = 0
                for item in os.listdir(parent):
                    item_path = os.path.join(parent, item)
                    if os.path.isdir(item_path):
                        count = 0
                        for root, _, files in os.walk(item_path):
                            for f in files:
                                if f.lower().endswith(('.jpg', '.jpeg')):
                                    count += 1
                                if count > best_count:
                                    break
                            if count > best_count:
                                break
                        if count > best_count:
                            best_count = count
                            best_dir = item_path
                if best_dir and best_count > 0:
                    scan_dir = best_dir
        if scan_dir and os.path.exists(scan_dir):
            for root, _, files in os.walk(scan_dir):
                for f in sorted(files):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                        self.photo_files.append(os.path.join(root, f))
        print(f"[调试] PhotoPickerDialog 扫描目录: {scan_dir}, 找到 {len(self.photo_files)} 张照片")
        self.current_index = 0
        self._update_preview()

    def _update_preview(self):
        """更新预览"""
        if not self.photo_files:
            self.preview_label.setText("未找到照片\n请使用「浏览其他文件夹」手动选择")
            self.filename_label.setText("未找到照片")
            self.index_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return

        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < len(self.photo_files) - 1)
        self.index_label.setText(f"{self.current_index + 1} / {len(self.photo_files)}")

        path = self.photo_files[self.current_index]
        self.filename_label.setText(os.path.basename(path))

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pw = max(self.preview_label.width() - 20, 300)
            ph = max(self.preview_label.height() - 20, 200)
            scaled = pixmap.scaled(
                pw, ph,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)
            self.preview_label.setText("")
        else:
            self.preview_label.setText("无法加载图片")
            print(f"[警告] QPixmap 无法加载: {path}")
    
    def _show_prev(self):
        if self.current_index > 0:
            self.current_index -= 1
            self._update_preview()
    
    def _show_next(self):
        if self.current_index < len(self.photo_files) - 1:
            self.current_index += 1
            self._update_preview()
    
    def _browse_other_folder(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择照片文件夹", self.photo_base_dir)
        if dir_path:
            self.photo_base_dir = dir_path
            self._scan_photos()
    
    def _confirm(self):
        if self.photo_files:
            self.selected_path = self.photo_files[self.current_index]
            self.accept()
        else:
            QMessageBox.warning(self, "提示", "未选择任何照片")
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()


class ShortcutDialog(QDialog):
    def __init__(self, shortcuts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("快捷键设置")
        self.resize(400, 350)
        self._shortcuts = dict(shortcuts)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        
        hint = QLabel("提示：留空表示不设置快捷键。格式如 Delete、Ctrl+Z、Space、Ctrl+Shift+A")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 12px; padding-bottom: 8px;")
        layout.addWidget(hint)
        
        self.table = QTableWidget(len(self._shortcuts), 2)
        self.table.setHorizontalHeaderLabels(["功能", "快捷键"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        
        actions = {
            'delete': '删除当前点位',
            'undo': '撤销',
            'redo': '重做',
            'repeat': '重复上一个命令',
            'relink': '重新关联单点照片',
            'toggle_sector': '显示/隐藏全部扇形',
            'adjust_mode': '调整单点扇形视线方向',
            'set_all_direction': '调整全部方向',
            'align_panorama': '对齐全景',
            'rotate_left': '扇形左转',
            'rotate_right': '扇形右转',
        }
        
        for i, (action, key) in enumerate(self._shortcuts.items()):
            name_item = QTableWidgetItem(actions.get(action, action))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, name_item)
            
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, key_item)
        
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        export_btn = QPushButton("📤 导出配置")
        export_btn.clicked.connect(self._export)
        import_btn = QPushButton("📥 导入配置")
        import_btn.clicked.connect(self._import)
        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self._reset_default)
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        layout.addLayout(btn_layout)
        
        ok_cancel = QHBoxLayout()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        ok_cancel.addStretch()
        ok_cancel.addWidget(ok_btn)
        ok_cancel.addWidget(cancel_btn)
        layout.addLayout(ok_cancel)
    
    def get_shortcuts(self):
        result = {}
        for i in range(self.table.rowCount()):
            action = list(self._shortcuts.keys())[i]
            key = self.table.item(i, 1).text().strip()
            result[action] = key
        return result
    
    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出快捷键配置", "shortcuts.json", "JSON (*.json)")
        if path:
            import json
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.get_shortcuts(), f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "成功", f"已导出到:\n{path}")
    
    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入快捷键配置", "", "JSON (*.json)")
        if path:
            import json
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                actions = list(self._shortcuts.keys())
                for action, key in loaded.items():
                    if action in actions:
                        idx = actions.index(action)
                        self.table.item(idx, 1).setText(key)
                QMessageBox.information(self, "成功", "快捷键配置已导入，点击确定保存")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入失败: {e}")
    
    def _reset_default(self):
        defaults = {
            'delete': 'Delete',
            'undo': 'Ctrl+Z',
            'redo': 'Ctrl+Y',
            'repeat': 'Space',
            'relink': '',
            'toggle_sector': '',
            'adjust_mode': '',
            'set_all_direction': '',
            'align_panorama': '',
            'rotate_left': '',
            'rotate_right': '',
        }
        actions = list(self._shortcuts.keys())
        for action, key in defaults.items():
            if action in actions:
                idx = actions.index(action)
                self.table.item(idx, 1).setText(key)

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
    
    window = PanoramaManager()
    
    # 设置应用样式
    window._style_manager.app = app
    window._style_manager.apply_to_application()
    # 应用悬浮工具栏风格
    window.floating_toolbar._apply_style()
    
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
