#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
随系 · 影像管理器 - 简易版
系统追求：让工具追上现场的速度

使用方式：
1. 将本程序（或打包后的exe）放到数据包和照片文件夹的同级目录
2. 双击运行，全自动处理：
   - 先检查同级目录是否已有 viewer/index.html，有则直接打开
   - 没有则自动识别 ZIP 数据包和照片文件夹，解压、关联、生成查看器
   - 自动启动本地服务器并用浏览器打开
"""

import sys
import os
import json
import zipfile
import shutil
import webbrowser
import subprocess

# 路径设置
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

# 添加 src 到路径
sys.path.insert(0, os.path.join(base_dir, 'src'))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QProgressBar, QMessageBox, QPushButton, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QAction

# 导入核心类
from main import Project, Marker, HttpServerThread, extract_exif_datetime


class WorkerThread(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(bool, str, str, object)
    
    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.project_dir = None
    
    def run(self):
        try:
            # 1. 优先检查是否已有 viewer
            viewer_dir = os.path.join(self.base_dir, 'viewer')
            index_path = os.path.join(viewer_dir, 'index.html')
            if os.path.exists(index_path):
                # 尝试找到对应的项目目录（用于后续关联）
                project_json_path = os.path.join(viewer_dir, 'project.json')
                project = None
                if os.path.exists(project_json_path):
                    with open(project_json_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    project = Project.from_dict(data)
                self.progress.emit("发现已有查看器，准备启动...", 90)
                self.finished.emit(True, "", viewer_dir, project)
                return
            
            # 2. 扫描
            self.progress.emit("正在扫描文件夹...", 10)
            zip_files = []
            photo_dirs = []
            
            for item in os.listdir(self.base_dir):
                item_path = os.path.join(self.base_dir, item)
                if os.path.isfile(item_path) and item.lower().endswith('.zip'):
                    zip_files.append(item_path)
                elif os.path.isdir(item_path) and item.lower() not in ['viewer', '__pycache__', 'build', 'dist', 'src']:
                    jpg_count = 0
                    for root, _, files in os.walk(item_path):
                        for f in files:
                            if f.lower().endswith(('.jpg', '.jpeg')):
                                jpg_count += 1
                            if jpg_count > 5:
                                break
                        if jpg_count > 5:
                            break
                    if jpg_count > 5:
                        photo_dirs.append((item_path, jpg_count))
            
            if not zip_files:
                self.finished.emit(False, "未找到 ZIP 项目数据包\n请将项目 ZIP 文件放在此程序同级目录", "", None)
                return
            
            # 按照片数量排序，选择照片最多的文件夹
            photo_dir = None
            if photo_dirs:
                photo_dirs.sort(key=lambda x: x[1], reverse=True)
                photo_dir = photo_dirs[0][0]
            
            # 3. 解压 ZIP（只处理第一个）
            self.progress.emit("正在解压项目...", 30)
            zip_path = zip_files[0]
            zip_name = os.path.splitext(os.path.basename(zip_path))[0]
            extract_dir = os.path.join(self.base_dir, zip_name)
            
            if not os.path.exists(extract_dir):
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(extract_dir)
            
            # 4. 加载项目
            self.progress.emit("正在加载项目...", 50)
            project_json_path = None
            for root, _, files in os.walk(extract_dir):
                if 'project.json' in files:
                    project_json_path = os.path.join(root, 'project.json')
                    self.project_dir = root
                    break
            
            if not project_json_path:
                self.finished.emit(False, "解压后的文件夹中未找到 project.json", "", None)
                return
            
            with open(project_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            project = Project.from_dict(data)
            project.photoBaseDir = photo_dir or ''
            
            # 5. 关联照片（不复制）
            if photo_dir:
                self.progress.emit("正在关联照片...", 70)
                self._link_photos(project, photo_dir)
            
            # 保存项目
            with open(project_json_path, 'w', encoding='utf-8') as f:
                json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
            
            self.finished.emit(True, "", self.project_dir, project)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.finished.emit(False, str(e), "", None)
    
    def _link_photos(self, project, photo_dir):
        """自动关联照片 - 同一采集点多张照片时只识别第一张"""
        from datetime import timedelta
        
        photo_files = []
        for root, _, files in os.walk(photo_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg')):
                    photo_files.append(os.path.join(root, f))
        
        # 预提取 EXIF 时间
        photo_times = {}
        for pf in photo_files:
            dt = extract_exif_datetime(pf)
            if dt:
                photo_times[pf] = dt
        
        for floor in project.floors:
            for marker_data in floor.get('markers', []):
                if marker_data.get('status') != 'captured':
                    continue
                
                marker = Marker.from_dict(marker_data)
                time_range = marker.get_time_range()
                if not time_range:
                    continue
                
                start_time, end_time = time_range
                adjusted_start = start_time + timedelta(seconds=project.timeOffset)
                adjusted_end = end_time + timedelta(seconds=project.timeOffset)
                if adjusted_start.tzinfo:
                    adjusted_start = adjusted_start.replace(tzinfo=None)
                if adjusted_end.tzinfo:
                    adjusted_end = adjusted_end.replace(tzinfo=None)
                
                range_seconds = (adjusted_end - adjusted_start).total_seconds()
                
                # 收集候选并按时间排序，取第一个匹配的
                candidates = []
                for pf, pt in photo_times.items():
                    if pt.tzinfo:
                        pt = pt.replace(tzinfo=None)
                    if range_seconds > 0:
                        center = adjusted_start + timedelta(seconds=range_seconds / 2)
                        diff = abs((pt - center).total_seconds())
                    else:
                        diff = abs((pt - adjusted_start).total_seconds())
                    candidates.append((pf, diff, pt))
                
                candidates.sort(key=lambda x: x[1])
                for pf, diff, pt in candidates:
                    if diff <= 300:  # 5分钟阈值
                        marker_data['status'] = 'linked'
                        marker_data['originalPhotoPath'] = pf
                        rel = os.path.relpath(pf, photo_dir).replace('\\', '/')
                        marker_data['panoramaPath'] = rel
                        marker_data['cameraFileName'] = os.path.basename(pf)
                        break


class SimpleWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("随系 · 影像管理器（简易版）")
        self.setGeometry(400, 300, 480, 280)
        
        # 创建临时 PanoramaManager 用于生成 HTML（隐藏）
        from main import PanoramaManager
        self.temp_manager = PanoramaManager()
        self.temp_manager.hide()
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        self.label = QLabel("正在自动处理项目数据...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(self.label)
        
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 8px;
                text-align: center;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #0A84FF;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.progress)
        
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("color: #666; font-size: 13px; padding: 5px;")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        
        self.open_btn = QPushButton("在浏览器中打开")
        self.open_btn.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                background-color: #34C759;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #248A3D; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.open_btn.clicked.connect(self._open_browser)
        self.open_btn.setEnabled(False)
        layout.addWidget(self.open_btn)
        
        self.server_thread = None
        self.server_url = ""
        
        # 启动后台处理
        self.worker = WorkerThread(base_dir)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
        
        # 系统托盘
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setToolTip("影像管理器 - 简易版")
        tray_menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.showNormal)
        tray_menu.addAction(show_action)
        open_action = QAction("打开查看器", self)
        open_action.triggered.connect(self._open_browser)
        tray_menu.addAction(open_action)
        tray_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
    
    def _on_progress(self, msg, value):
        self.label.setText(msg)
        self.progress.setValue(value)
    
    def _on_finished(self, success, error_msg, project_dir, project):
        if not success:
            QMessageBox.critical(self, "处理失败", error_msg)
            self.label.setText("处理失败")
            self.info_label.setText(error_msg)
            return
        
        self.label.setText("正在生成查看器...")
        self.progress.setValue(90)
        
        # 在主线程生成 viewer（Qt 控件操作必须在主线程）
        try:
            viewer_dir = os.path.join(project_dir, 'viewer') if project_dir else os.path.join(base_dir, 'viewer')
            os.makedirs(viewer_dir, exist_ok=True)
            
            photo_base_dir = getattr(project, 'photoBaseDir', '') if project else ''
            
            # 创建外部照片链接
            if photo_base_dir and os.path.exists(photo_base_dir):
                link_path = os.path.join(viewer_dir, 'external_photos')
                if os.path.exists(link_path):
                    if os.path.islink(link_path):
                        os.remove(link_path)
                    else:
                        shutil.rmtree(link_path)
                try:
                    if sys.platform == 'win32':
                        subprocess.run(['cmd', '/c', 'mklink', '/J', link_path, photo_base_dir],
                                     check=True, capture_output=True)
                    else:
                        os.symlink(photo_base_dir, link_path)
                except Exception:
                    shutil.copytree(photo_base_dir, link_path, dirs_exist_ok=True)
            
            # 复制 project.json（调整 panoramaPath）
            if project:
                project_copy = project.to_dict()
                if photo_base_dir and os.path.exists(photo_base_dir):
                    for floor_data in project_copy.get('floors', []):
                        for marker_data in floor_data.get('markers', []):
                            if marker_data.get('panoramaPath') and not os.path.isabs(marker_data['panoramaPath']):
                                marker_data['panoramaPath'] = 'external_photos/' + marker_data['panoramaPath']
                
                with open(os.path.join(viewer_dir, 'project.json'), 'w', encoding='utf-8') as f:
                    json.dump(project_copy, f, ensure_ascii=False, indent=2)
                
                # 复制平面图
                for floor_data in project.floors:
                    floor_id = floor_data['id']
                    src = os.path.join(project_dir, f'floorplan_{floor_id}.jpg')
                    if not os.path.exists(src) and project.floorplan:
                        src = os.path.join(project_dir, project.floorplan)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(viewer_dir, f'floorplan_{floor_id}.jpg'))
                
                # 生成 HTML
                self.temp_manager.project_dir = project_dir
                self.temp_manager.project_data = project
                self.temp_manager._generate_viewer_html(viewer_dir)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"生成查看器失败: {e}")
            return
        
        self.progress.setValue(100)
        self.label.setText("服务运行中")
        
        # 启动 HTTP 服务器
        for port in [8888, 9000, 9999, 0]:
            try:
                self.server_thread = HttpServerThread(viewer_dir, port)
                self.server_thread.server_started.connect(self._on_server_started)
                self.server_thread.start()
                import time
                time.sleep(0.5)
                if self.server_thread.is_running:
                    break
            except Exception:
                continue
        
        if not self.server_thread or not self.server_thread.is_running:
            QMessageBox.critical(self, "错误", "无法启动 HTTP 服务器")
            return
    
    def _on_server_started(self, ip, port):
        self.server_url = f"http://localhost:{port}"
        self.info_label.setText(f"查看器地址: {self.server_url}\n最小化窗口后可在系统托盘找到")
        self.open_btn.setEnabled(True)
        self.open_btn.setText("在浏览器中打开")
        webbrowser.open(self.server_url)
        self.showMinimized()
    
    def _open_browser(self):
        if self.server_url:
            webbrowser.open(self.server_url)
    
    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
    
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "影像管理器",
            "程序已在后台运行，双击托盘图标可重新打开",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )
    
    def _quit(self):
        if self.server_thread and self.server_thread.is_running:
            self.server_thread.stop()
        QApplication.instance().quit()


def main():
    # 随系系统启动提示
    print("\n" + "="*50)
    print("  随系 · 影像管理器（简易版）")
    print("  系统追求：让工具追上现场的速度")
    print("="*50 + "\n")
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = SimpleWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
