# 影像管理器

> **模块名称**: 随系 · 随管  
> **版本**: v1.0  
> **用途**: 商业改造现场影像与平面图快速空间关联管理  
> **核心原则**: 100% 离线、数据本地、现场容错优先

---

## 系统架构

```
┌─────────────┐      蓝牙指令       ┌─────────────┐
│   iOS App   │ ◄────────────────► │ DJI Osmo 360 │
│  (M1 采集)   │                    │  (SD卡存照片) │
└──────┬──────┘                    └──────┬──────┘
       │ 导出 project.zip                  │ 拷贝照片
       ▼                                   ▼
┌─────────────────────────────────────────────────┐
│              PC 端 随管 (M2)                      │
│  解压项目 → 导入照片 → 文件名匹配 → 生成 viewer    │
└─────────────────────────────────────────────────┘
       │
       ▼ 生成 viewer/ 文件夹
┌─────────────────────────────────────────────────┐
│           本地网页查看器 (M3)                      │
│      内嵌 HTTP 服务 + Pannellum 全景渲染           │
│         局域网 IP + 二维码 → 手机扫码访问           │
└─────────────────────────────────────────────────┘
```

---

## 项目结构

```
PanoramaManager/
├── THIRD_PARTY_LICENSES.txt    # 第三方许可证清单
├── 使用说明.txt                 # 详细使用文档
├── README.md                   # 项目说明
│
├── PanoramaMapper-iOS/         # M1: iOS 移动端
│   └── PanoramaManager/
│       ├── PanoramaManagerApp.swift
│       ├── Info.plist
│       ├── Models/
│       │   └── Project.swift      # 数据模型
│       ├── Utils/
│       │   └── CameraManager.swift # 相机管理
│       └── Views/
│           ├── ProjectListView.swift   # 项目列表
│           ├── CreateProjectView.swift # 创建项目
│           ├── CaptureView.swift       # 采集界面
│           └── ShootControlView.swift  # 拍摄控制
│
└── PanoramaMapper-PC/          # M2: PC 端
    ├── src/
    │   └── main.py             # 主程序
    ├── requirements.txt        # Python依赖
    └── build.py                # 打包脚本
```

---

## 功能特性

### M1: iOS 移动端采集 App

| 功能 | 说明 |
|------|------|
| 项目管理 | 创建、查看、删除、导出项目 |
| 平面图导入 | 支持 JPG/PNG/PDF，PDF自动转换 |
| 交互式标记 | 双指缩放、单指拖拽、长按添加标记 |
| 蓝牙相机控制 | 连接 DJI Osmo 360，一键拍摄 |
| 手动输入模式 | 蓝牙不可用时的兜底方案 |
| 标记点管理 | 增删改、位置微调、状态显示 |
| 项目导出 | ZIP 格式，支持 AirDrop/微信分享 |

**标记点状态颜色:**
- 灰色空心: `pending` - 仅标记，未拍摄
- 蓝色实心: `captured` - 已拍摄，未传 PC
- 绿色实心: `linked` - PC 端已关联
- 红色实心: `missing` - 文件缺失

### M2: PC 端管理器

| 功能 | 说明 |
|------|------|
| 项目导入 | 解压 ZIP，校验 schemaVersion |
| 智能照片匹配 | 精确匹配 → 相似匹配(5秒容错) → 手动指定 |
| 可视化编辑 | 平面图上拖拽调整标记位置 |
| 网页生成 | 生成完整离线 viewer/ 文件夹 |
| 本地服务器 | 内置 HTTP 服务 + 二维码分享 |

### M3: 本地网页查看器

| 功能 | 说明 |
|------|------|
| 全景渲染 | Pannellum 引擎，支持触摸/鼠标操作 |
| 双端适配 | 桌面端分栏布局，移动端全屏+浮层 |
| 热点导航 | 点击平面图标记切换 |
| 离线可用 | 不依赖任何外部 CDN |

---

## 快速开始

### iOS 端

1. 使用 Xcode 15.0+ 打开 `PanoramaMapper-iOS/PanoramaManager.xcodeproj`
2. 连接 iPhone（iOS 16.0+）
3. 配置签名 Team
4. 编译运行

### PC 端

```bash
# 1. 进入目录
cd PanoramaMapper-PC

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行程序
python src/main.py

# 4. 打包为 exe（可选）
python build.py
```

---

## 开发里程碑

| 阶段 | 状态 | 交付物 |
|:---|:---|:---|
| Phase 0 | ✅ | 项目结构、文档、许可证 |
| Phase 1 | ✅ | M1 iOS App 基础框架 |
| Phase 2 | ✅ | M1 核心功能（蓝牙、拍摄、导出） |
| Phase 3 | ✅ | M2 PC 端基础（导入、显示、编辑） |
| Phase 4 | ✅ | M2 核心功能（匹配、生成、服务器） |
| Phase 5 | ✅ | M3 网页查看器 |
| Phase 6 | ✅ | 打包配置、最终交付 |

---

## 技术栈

| 端 | 技术 |
|:---|:---|
| iOS | Swift 5.9+, SwiftUI, CoreBluetooth |
| PC | Python 3.10+, PyQt6, Pillow, qrcode |
| Web | Pannellum 2.5, HTML5, CSS3, JavaScript |

---

## 数据格式

### project.json 结构

```json
{
  "schemaVersion": "1.0",
  "projectName": "XX商业改造现场",
  "createdAt": "2025-01-22T14:00:00",
  "updatedAt": "2025-01-22T16:30:00",
  "floorplan": "floorplan.jpg",
  "floorplanOriginalName": "1F平面图.pdf",
  "markers": [
    {
      "id": "m1",
      "status": "linked",
      "cameraFileName": "DJI_20250122_143015.JPG",
      "customName": "主入口大堂",
      "x": 0.35,
      "y": 0.42,
      "timestamp": "2025-01-22T14:30:15",
      "panoramaPath": "panoramas/DJI_20250122_143015.JPG"
    }
  ]
}
```

---

## 第三方组件

本项目采用第三方组件，详见 `THIRD_PARTY_LICENSES.txt`。

---

## 注意事项

1. **DJI SDK 集成**: iOS 项目需要额外集成 DJI Mobile SDK 才能实现完整的蓝牙相机控制功能。当前代码已预留接口，支持手动模式作为降级方案。

2. **蓝牙权限**: iOS App 需要用户在设置中授予蓝牙权限。

3. **防火墙**: PC 端启动 HTTP 服务器时可能需要配置防火墙允许访问。

4. **存储空间**: 影像文件占用空间较大，确保设备有足够存储。

---

## 更新日志

### v1.0 (2025-01-22)
- 初始版本发布
- 完整实现 M1/M2/M3 三端功能
- 支持精确/相似/手动三级照片匹配
- 支持离线网页查看器

---

**随系 · 让工具追上现场的速度**
