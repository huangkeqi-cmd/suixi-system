#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
随系 · 影像采集配套工具 - PC端处理器
系统追求：让工具追上现场的速度
功能：导入项目、匹配影像、生成交互式网页查看器
"""

import sys
import os
import json
import shutil
import webbrowser
import re
from pathlib import Path
from datetime import datetime
from tkinter import *
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont
import qrcode


class PanoramaProcessor:
    def __init__(self, root):
        self.root = root
        self.root.title("随系 · 影像采集配套工具")
        self.root.geometry("1200x800")
        self.root.configure(bg='#1e1e1e')
        
        # 数据
        self.project_data = None
        self.project_dir = None
        self.floorplan_image = None
        self.current_floor_id = None
        self.markers = {}
        self.photos_dir = None
        self.photo_files = []
        
        self.setup_ui()
        
    def setup_ui(self):
        # 顶部工具栏
        toolbar = Frame(self.root, bg='#2d2d2d', height=50)
        toolbar.pack(fill=X, padx=0, pady=0)
        toolbar.pack_propagate(False)
        
        Button(toolbar, text="📁 导入项目", bg='#0a84ff', fg='white',
               command=self.import_project, font=('微软雅黑', 10),
               padx=15, pady=5).pack(side=LEFT, padx=10, pady=8)
        
        Button(toolbar, text="📷 导入照片", bg='#30d158', fg='black',
               command=self.import_photos, font=('微软雅黑', 10),
               padx=15, pady=5).pack(side=LEFT, padx=5, pady=8)
        
        Button(toolbar, text="🌐 生成查看器", bg='#ff9500', fg='white',
               command=self.generate_viewer, font=('微软雅黑', 10),
               padx=15, pady=5).pack(side=LEFT, padx=5, pady=8)
        
        Button(toolbar, text="▶️ 启动服务", bg='#5856d6', fg='white',
               command=self.start_server, font=('微软雅黑', 10),
               padx=15, pady=5).pack(side=LEFT, padx=5, pady=8)
        
        # 主区域
        main_frame = Frame(self.root, bg='#1e1e1e')
        main_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
        
        # 左侧：楼层选择
        left_frame = Frame(main_frame, bg='#2d2d2d', width=200)
        left_frame.pack(side=LEFT, fill=Y, padx=(0, 10))
        left_frame.pack_propagate(False)
        
        Label(left_frame, text="楼层选择", bg='#2d2d2d', fg='white',
              font=('微软雅黑', 12, 'bold')).pack(pady=10)
        
        self.floor_listbox = Listbox(left_frame, bg='#1e1e1e', fg='white',
                                     selectmode=SINGLE, font=('微软雅黑', 11),
                                     highlightthickness=0, bd=0)
        self.floor_listbox.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.floor_listbox.bind('<<ListboxSelect>>', self.on_floor_select)
        
        # 中间：平面图
        center_frame = Frame(main_frame, bg='#2d2d2d')
        center_frame.pack(side=LEFT, fill=BOTH, expand=True)
        
        self.canvas = Canvas(center_frame, bg='#0a0a0a', highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True, padx=5, pady=5)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        
        # 右侧：点位列表和详情
        right_frame = Frame(main_frame, bg='#2d2d2d', width=350)
        right_frame.pack(side=LEFT, fill=Y, padx=(10, 0))
        right_frame.pack_propagate(False)
        
        Label(right_frame, text="点位列表", bg='#2d2d2d', fg='white',
              font=('微软雅黑', 12, 'bold')).pack(pady=10)
        
        # 统计信息
        self.stats_label = Label(right_frame, text="未加载项目", bg='#2d2d2d',
                                fg='#8e8e93', font=('微软雅黑', 10))
        self.stats_label.pack(pady=5)
        
        # 点位列表
        self.marker_listbox = Listbox(right_frame, bg='#1e1e1e', fg='white',
                                      selectmode=SINGLE, font=('微软雅黑', 10),
                                      highlightthickness=0, bd=0)
        self.marker_listbox.pack(fill=BOTH, expand=True, padx=10, pady=5)
        self.marker_listbox.bind('<<ListboxSelect>>', self.on_marker_select)
        
        # 匹配状态
        self.match_frame = Frame(right_frame, bg='#2d2d2d')
        self.match_frame.pack(fill=X, padx=10, pady=5)
        
        Label(self.match_frame, text="照片匹配", bg='#2d2d2d', fg='white',
              font=('微软雅黑', 11, 'bold')).pack(anchor=W, pady=5)
        
        self.match_status = Label(self.match_frame, text="未匹配",
                                 bg='#2d2d2d', fg='#8e8e93',
                                 font=('微软雅黑', 10))
        self.match_status.pack(anchor=W)
        
        Button(self.match_frame, text="手动选择照片", bg='#0a84ff', fg='white',
               command=self.manual_select_photo, font=('微软雅黑', 9),
               padx=10, pady=3).pack(fill=X, pady=5)
        
        # 底部状态栏
        self.status_bar = Label(self.root, text="就绪", bg='#2d2d2d',
                               fg='#8e8e93', anchor=W, padx=10)
        self.status_bar.pack(fill=X, side=BOTTOM)
        
    def import_project(self):
        """导入采集工具导出的项目"""
        # 选择 project.json
        json_path = filedialog.askopenfilename(
            title="选择 project.json",
            filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
        )
        if not json_path:
            return
            
        # 选择平面图
        img_path = filedialog.askopenfilename(
            title="选择平面图",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")]
        )
        if not img_path:
            return
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                self.project_data = json.load(f)
            
            self.project_dir = os.path.dirname(json_path)
            
            # 加载平面图
            self.floorplan_image = Image.open(img_path)
            
            # 提取数据
            self.markers = {}
            for floor in self.project_data.get('floors', []):
                fid = floor['id']
                self.markers[fid] = floor.get('markers', [])
            
            # 更新楼层列表
            self.floor_listbox.delete(0, END)
            for floor in self.project_data.get('floors', []):
                self.floor_listbox.insert(END, floor['name'])
            
            # 显示第一张平面图
            if self.project_data.get('floors'):
                self.current_floor_id = self.project_data['floors'][0]['id']
                self.show_floorplan()
            
            self.stats_label.config(
                text=f"项目: {self.project_data.get('projectName', '未命名')}\n"
                     f"楼层: {len(self.project_data.get('floors', []))} 层"
            )
            self.status_bar.config(text=f"已导入项目: {self.project_data.get('projectName', '')}")
            messagebox.showinfo("成功", "项目导入成功！")
            
        except Exception as e:
            messagebox.showerror("错误", f"导入失败: {str(e)}")
            
    def import_photos(self):
        """导入影像文件夹"""
        if not self.project_data:
            messagebox.showwarning("提示", "请先导入项目")
            return
            
        self.photos_dir = filedialog.askdirectory(title="选择影像文件夹")
        if not self.photos_dir:
            return
            
        # 扫描照片文件
        self.photo_files = []
        for root, dirs, files in os.walk(self.photos_dir):
            for f in files:
                if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                    self.photo_files.append(os.path.join(root, f))
        
        self.status_bar.config(text=f"找到 {len(self.photo_files)} 张照片，正在匹配...")
        
        # 自动匹配
        self.auto_match_photos()
        
    def auto_match_photos(self):
        """根据时间戳自动匹配照片"""
        if not self.project_data or not self.photo_files:
            return
            
        matched_count = 0
        
        # 提取所有照片的时间戳
        photo_times = []
        for photo_path in self.photo_files:
            filename = os.path.basename(photo_path)
            # 尝试从文件名提取时间
            time_match = re.search(r'(\d{8})[_-]?(\d{6})', filename)
            if time_match:
                date_str = time_match.group(1)
                time_str = time_match.group(2)
                try:
                    dt = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
                    photo_times.append((dt, photo_path))
                except:
                    pass
        
        # 匹配每个标记点
        for floor_id, markers in self.markers.items():
            for marker in markers:
                if marker.get('status') == 'captured' and marker.get('captureTime'):
                    try:
                        marker_time = datetime.fromisoformat(marker['captureTime'].replace('Z', '+00:00'))
                        
                        # 查找最接近的照片（30秒容差）
                        best_match = None
                        best_diff = float('inf')
                        
                        for photo_dt, photo_path in photo_times:
                            diff = abs((photo_dt - marker_time).total_seconds())
                            if diff < 30 and diff < best_diff:
                                best_diff = diff
                                best_match = photo_path
                        
                        if best_match:
                            marker['photo_path'] = best_match
                            matched_count += 1
                    except:
                        pass
        
        self.status_bar.config(text=f"自动匹配完成: {matched_count} 个点位")
        messagebox.showinfo("匹配完成", f"成功匹配 {matched_count} 张照片\n\n未匹配的点位可手动选择照片")
        
        # 刷新显示
        if self.current_floor_id:
            self.show_floorplan()
            
    def show_floorplan(self):
        """显示当前楼层的平面图和标记点"""
        if not self.floorplan_image:
            return
            
        # 调整图片大小以适应画布
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width < 100:
            canvas_width = 800
            canvas_height = 600
        
        img_ratio = self.floorplan_image.width / self.floorplan_image.height
        canvas_ratio = canvas_width / canvas_height
        
        if img_ratio > canvas_ratio:
            new_width = canvas_width
            new_height = int(canvas_width / img_ratio)
        else:
            new_height = canvas_height
            new_width = int(canvas_height * img_ratio)
        
        resized = self.floorplan_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 转换为 Tkinter 可用格式
        self.tk_image = ImageTk.PhotoImage(resized)
        
        # 清空画布并显示
        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_width//2, canvas_height//2,
            image=self.tk_image, anchor=CENTER
        )
        
        # 计算偏移和缩放
        self.img_offset_x = (canvas_width - new_width) // 2
        self.img_offset_y = (canvas_height - new_height) // 2
        self.img_scale_x = new_width / self.floorplan_image.width
        self.img_scale_y = new_height / self.floorplan_image.height
        
        # 绘制标记点
        self.draw_markers()
        self.update_marker_list()
        
    def draw_markers(self):
        """在平面图上绘制标记点"""
        if not self.current_floor_id:
            return
            
        markers = self.markers.get(self.current_floor_id, [])
        
        for i, marker in enumerate(markers):
            x = self.img_offset_x + marker['x'] * self.floorplan_image.width * self.img_scale_x
            y = self.img_offset_y + marker['y'] * self.floorplan_image.height * self.img_scale_y
            
            # 根据状态设置颜色
            has_photo = 'photo_path' in marker
            color = '#30d158' if has_photo else ('#ff9500' if marker.get('status') == 'captured' else '#8e8e93')
            
            # 绘制圆形标记
            r = 12
            self.canvas.create_oval(
                x-r, y-r, x+r, y+r,
                fill=color, outline='white', width=2,
                tags=f"marker_{i}"
            )
            
            # 绘制序号
            self.canvas.create_text(
                x, y, text=str(i+1),
                fill='white', font=('微软雅黑', 9, 'bold'),
                tags=f"text_{i}"
            )
            
    def update_marker_list(self):
        """更新右侧点位列表"""
        self.marker_listbox.delete(0, END)
        
        if not self.current_floor_id:
            return
            
        markers = self.markers.get(self.current_floor_id, [])
        
        for i, marker in enumerate(markers):
            status = "✓" if 'photo_path' in marker else ("○" if marker.get('status') == 'captured' else "·")
            name = marker.get('customName', '') or f"点位 {i+1}"
            self.marker_listbox.insert(END, f"{status} {name}")
            
    def on_floor_select(self, event):
        """选择楼层"""
        selection = self.floor_listbox.curselection()
        if selection:
            index = selection[0]
            floors = self.project_data.get('floors', [])
            if index < len(floors):
                self.current_floor_id = floors[index]['id']
                self.show_floorplan()
                
    def on_marker_select(self, event):
        """选择点位"""
        selection = self.marker_listbox.curselection()
        if selection and self.current_floor_id:
            index = selection[0]
            markers = self.markers.get(self.current_floor_id, [])
            if index < len(markers):
                marker = markers[index]
                
                # 更新匹配状态
                if 'photo_path' in marker:
                    photo_name = os.path.basename(marker['photo_path'])
                    self.match_status.config(
                        text=f"已匹配: {photo_name}",
                        fg='#30d158'
                    )
                else:
                    self.match_status.config(
                        text="未匹配照片",
                        fg='#ff453a'
                    )
                    
    def on_canvas_click(self, event):
        """点击平面图"""
        # 可以添加点击选中点位的功能
        pass
        
    def manual_select_photo(self):
        """手动为当前选中的点位选择照片"""
        selection = self.marker_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先选择点位")
            return
            
        if not self.current_floor_id:
            return
            
        index = selection[0]
        markers = self.markers.get(self.current_floor_id, [])
        if index >= len(markers):
            return
            
        # 选择照片
        photo_path = filedialog.askopenfilename(
            title="选择影像",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")]
        )
        
        if photo_path:
            markers[index]['photo_path'] = photo_path
            self.match_status.config(
                text=f"已匹配: {os.path.basename(photo_path)}",
                fg='#30d158'
            )
            self.show_floorplan()
            messagebox.showinfo("成功", "照片匹配成功！")
            
    def generate_viewer(self):
        """生成网页查看器"""
        if not self.project_data:
            messagebox.showwarning("提示", "请先导入项目")
            return
            
        output_dir = filedialog.askdirectory(title="选择输出目录")
        if not output_dir:
            return
            
        try:
            viewer_dir = os.path.join(output_dir, "viewer")
            os.makedirs(viewer_dir, exist_ok=True)
            
            # 复制平面图
            if self.floorplan_image:
                self.floorplan_image.save(
                    os.path.join(viewer_dir, "floorplan.jpg"),
                    quality=90
                )
            
            # 复制照片
            photos_dir = os.path.join(viewer_dir, "photos")
            os.makedirs(photos_dir, exist_ok=True)
            
            export_data = {
                "schemaVersion": "3.0",
                "projectName": self.project_data.get("projectName", "未命名项目"),
                "floors": []
            }
            
            for floor in self.project_data.get("floors", []):
                fid = floor["id"]
                floor_data = {
                    "id": fid,
                    "name": floor["name"],
                    "markers": []
                }
                
                for marker in self.markers.get(fid, []):
                    marker_data = {
                        "id": marker["id"],
                        "x": marker["x"],
                        "y": marker["y"],
                        "name": marker.get("customName", ""),
                        "status": marker.get("status", "pending")
                    }
                    
                    # 复制照片
                    if "photo_path" in marker:
                        src = marker["photo_path"]
                        ext = os.path.splitext(src)[1]
                        dst_name = f"{marker['id']}{ext}"
                        dst = os.path.join(photos_dir, dst_name)
                        shutil.copy2(src, dst)
                        marker_data["photo"] = f"photos/{dst_name}"
                    
                    floor_data["markers"].append(marker_data)
                
                export_data["floors"].append(floor_data)
            
            # 保存项目数据
            with open(os.path.join(viewer_dir, "data.json"), "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            # 生成 HTML
            self.create_viewer_html(viewer_dir)
            
            messagebox.showinfo("成功", f"查看器已生成到:\n{viewer_dir}")
            self.status_bar.config(text=f"查看器已生成: {viewer_dir}")
            
        except Exception as e:
            messagebox.showerror("错误", f"生成失败: {str(e)}")
            
    def create_viewer_html(self, viewer_dir):
        """创建查看器 HTML 文件"""
        html_content = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>影像查看器</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css"/>
    <script src="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js"></script>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#000; }
        
        .container { display:flex; height:100vh; }
        .floorplan { width:40%; background:#1a1a1a; position:relative; overflow:hidden; }
        .panorama { width:60%; position:relative; }
        
        @media (max-width:768px) {
            .container { flex-direction:column; }
            .floorplan { width:100%; height:40%; }
            .panorama { width:100%; height:60%; }
        }
        
        #pano { width:100%; height:100%; }
        
        #fp-img { width:100%; height:100%; object-fit:contain; }
        .marker { position:absolute; width:30px; height:30px; background:#30d158; border:3px solid white; border-radius:50%; transform:translate(-50%,-50%); cursor:pointer; box-shadow:0 2px 8px rgba(0,0,0,0.5); }
        .marker.active { background:#ffcc00; box-shadow:0 0 0 4px rgba(255,204,0,0.5); }
        .marker.no-photo { background:#ff453a; }
        
        .floor-tabs { position:absolute; top:10px; left:10px; display:flex; gap:5px; }
        .floor-tab { padding:8px 16px; background:rgba(0,0,0,0.7); color:#fff; border-radius:6px; cursor:pointer; font-size:13px; }
        .floor-tab.active { background:#0a84ff; }
        
        .info { position:absolute; top:10px; left:10px; color:#fff; background:rgba(0,0,0,0.7); padding:10px 15px; border-radius:6px; font-size:14px; z-index:100; }
        
        .nav-btns { position:absolute; bottom:20px; left:50%; transform:translateX(-50%); display:flex; gap:10px; z-index:100; }
        .nav-btn { padding:10px 20px; background:rgba(0,0,0,0.6); color:#fff; border:none; border-radius:20px; cursor:pointer; backdrop-filter:blur(10px); }
    </style>
</head>
<body>
    <div class="container">
        <div class="floorplan" id="floorplan">
            <div class="floor-tabs" id="floorTabs"></div>
            <div style="position:relative;width:100%;height:100%;" id="fpContainer">
                <img id="fp-img" src="floorplan.jpg" alt="平面图">
            </div>
        </div>
        <div class="panorama">
            <div class="info" id="info">请选择点位查看影像</div>
            <div id="pano"></div>
            <div class="nav-btns">
                <button class="nav-btn" onclick="prevMarker()">◀ 上一个</button>
                <button class="nav-btn" onclick="nextMarker()">下一个 ▶</button>
            </div>
        </div>
    </div>

<script>
let data = null;
let viewer = null;
let currentFloor = 0;
let currentMarker = -1;
let markersWithPhoto = [];

fetch('data.json')
    .then(r => r.json())
    .then(d => {
        data = d;
        initFloors();
        loadFloor(0);
    });

function initFloors() {
    const tabs = document.getElementById('floorTabs');
    data.floors.forEach((f, i) => {
        const tab = document.createElement('div');
        tab.className = 'floor-tab' + (i === 0 ? ' active' : '');
        tab.textContent = f.name;
        tab.onclick = () => loadFloor(i);
        tabs.appendChild(tab);
    });
}

function loadFloor(idx) {
    currentFloor = idx;
    currentMarker = -1;
    
    // 更新标签
    document.querySelectorAll('.floor-tab').forEach((t, i) => {
        t.classList.toggle('active', i === idx);
    });
    
    // 清除旧标记
    document.querySelectorAll('.marker').forEach(m => m.remove());
    
    const floor = data.floors[idx];
    const container = document.getElementById('fpContainer');
    const img = document.getElementById('fp-img');
    
    // 计算标记点位置
    img.onload = () => {
        markersWithPhoto = floor.markers.filter(m => m.photo);
        
        floor.markers.forEach((m, i) => {
            const marker = document.createElement('div');
            marker.className = 'marker' + (m.photo ? '' : ' no-photo');
            marker.style.left = (m.x * 100) + '%';
            marker.style.top = (m.y * 100) + '%';
            marker.onclick = () => selectMarker(i);
            container.appendChild(marker);
        });
        
        // 自动选择第一个有照片的点位
        const firstPhoto = floor.markers.findIndex(m => m.photo);
        if (firstPhoto >= 0) selectMarker(firstPhoto);
    };
}

function selectMarker(idx) {
    const floor = data.floors[currentFloor];
    const m = floor.markers[idx];
    if (!m.photo) {
        alert('该点位没有匹配照片');
        return;
    }
    
    currentMarker = idx;
    
    // 更新标记样式
    document.querySelectorAll('.marker').forEach((el, i) => {
        el.classList.toggle('active', i === idx);
    });
    
    // 更新信息
    document.getElementById('info').textContent = m.name || ('点位 ' + (idx + 1));
    
    // 加载影像
    if (viewer) viewer.destroy();
    viewer = pannellum.viewer('pano', {
        type: 'equirectangular',
        panorama: m.photo,
        autoLoad: true,
        compass: true,
        showFullscreenCtrl: true
    });
}

function prevMarker() {
    const floor = data.floors[currentFloor];
    const photoMarkers = floor.markers.map((m, i) => m.photo ? i : -1).filter(i => i >= 0);
    if (photoMarkers.length === 0) return;
    
    const currentIdx = photoMarkers.indexOf(currentMarker);
    const prevIdx = currentIdx <= 0 ? photoMarkers.length - 1 : currentIdx - 1;
    selectMarker(photoMarkers[prevIdx]);
}

function nextMarker() {
    const floor = data.floors[currentFloor];
    const photoMarkers = floor.markers.map((m, i) => m.photo ? i : -1).filter(i => i >= 0);
    if (photoMarkers.length === 0) return;
    
    const currentIdx = photoMarkers.indexOf(currentMarker);
    const nextIdx = currentIdx >= photoMarkers.length - 1 ? 0 : currentIdx + 1;
    selectMarker(photoMarkers[nextIdx]);
}
</script>
</body>
</html>'''
        
        with open(os.path.join(viewer_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)
            
    def start_server(self):
        """启动本地 HTTP 服务器"""
        viewer_dir = filedialog.askdirectory(title="选择 viewer 文件夹")
        if not viewer_dir:
            return
            
        if not os.path.exists(os.path.join(viewer_dir, "index.html")):
            messagebox.showerror("错误", "所选文件夹中没有 index.html")
            return
        
        import http.server
        import socketserver
        import threading
        import socket
        
        # 查找可用端口
        port = 8080
        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result != 0:
                    break
                port += 1
            except:
                break
        
        # 获取本机 IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except:
            ip = "127.0.0.1"
        
        # 启动服务器
        os.chdir(viewer_dir)
        
        handler = http.server.SimpleHTTPRequestHandler
        httpd = socketserver.TCPServer(("", port), handler)
        
        server_thread = threading.Thread(target=httpd.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        # 生成二维码
        try:
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(f"http://{ip}:{port}")
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            qr_path = os.path.join(viewer_dir, "qr.png")
            img.save(qr_path)
            
            # 显示二维码
            qr_window = Toplevel(self.root)
            qr_window.title("扫码访问")
            qr_window.geometry("300x400")
            qr_window.configure(bg='#1e1e1e')
            
            Label(qr_window, text="使用手机扫描二维码访问", 
                 bg='#1e1e1e', fg='white', font=('微软雅黑', 12)).pack(pady=10)
            
            qr_img = Image.open(qr_path)
            qr_tk = ImageTk.PhotoImage(qr_img)
            
            lbl = Label(qr_window, image=qr_tk, bg='#1e1e1e')
            lbl.image = qr_tk
            lbl.pack(pady=10)
            
            Label(qr_window, text=f"http://{ip}:{port}", 
                 bg='#1e1e1e', fg='#0a84ff', font=('微软雅黑', 10)).pack(pady=5)
            
            Button(qr_window, text="在浏览器中打开", bg='#0a84ff', fg='white',
                  command=lambda: webbrowser.open(f"http://localhost:{port}")).pack(pady=10)
            
        except Exception as e:
            messagebox.showwarning("提示", f"二维码生成失败，但服务器已启动\n地址: http://{ip}:{port}")
        
        self.status_bar.config(text=f"服务已启动: http://{ip}:{port}")
        messagebox.showinfo("成功", f"服务器已启动！\n本地: http://localhost:{port}\n局域网: http://{ip}:{port}")


def main():
    root = Tk()
    app = PanoramaProcessor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
