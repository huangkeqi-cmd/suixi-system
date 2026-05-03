# 随心系统 / Suixin System

📷 随拍 · 🗂️ 随管 · 👁️ 随看  
面向城市更新与商业改造现场的**离线影像工作流工具**。

> 核心理念：怎么方便怎么做，先跑起来，再慢慢长。

---

## 模块总览

| 模块 | 功能 | 状态 | 入口 |
|------|------|------|------|
| 📷 **随拍** | 手机端现场影像采集、点位标记、照片/录像记录、扇形视线方向、陀螺仪对齐 | ✅ 已上线 | [在线访问](https://huangkeqi-cmd.github.io/suixi-system/PanoramaCapture/capture.html) |
| 🗂️ **随管** | PC 端影像管理、智能匹配、全景网页生成、ZIP 导出 | ✅ 已上线 | 本地运行 |
| 👁️ **随看** | 离线全景查看、热点导航、汇报展示、VR 模式 | ✅ 已集成 | 由随管自动生成 |

---

## 在线预览

项目静态页面已部署至 GitHub Pages：

👉 **[https://huangkeqi-cmd.github.io/suixi-system/](https://huangkeqi-cmd.github.io/suixi-system/)**

在首页可以直接进入「随拍」采集端。由于随拍是**离线优先**设计，在线打开后仍然可以将数据保存在浏览器本地存储中，无需后端服务。

---

## 技术特性

- 📱 **移动端第一**：大按钮、防误触、触摸友好、安全区适配
- 🔌 **离线优先**：LocalStorage / IndexedDB，无网可用，数据不丢失
- 🚀 **零部署**：核心模块纯 HTML5 + Vanilla JS，双击就能跑
- 🧩 **模块即插即用**：各模块独立运行，保留 JSON 数据联动接口
- 📦 **数据可迁移**：导出 JSON / CSV / ZIP，随时备份与恢复
- 🧭 **方向导航**：陀螺仪驱动的平面旋转与指北针对齐

---

## 本地预览

### 1. 克隆仓库

```bash
git clone https://github.com/huangkeqi-cmd/suixi-system.git
cd suixi-system
```

### 2. 启动本地服务器

由于浏览器安全策略，部分功能（如文件导入、相机调用）需要在本地服务器环境下运行。

**方式 A：使用 Python 简易服务器**

```bash
python -m http.server 8080
```

然后访问 `http://localhost:8080/PanoramaCapture/capture.html`

**方式 B：使用仓库自带的启动脚本（Windows）**

双击运行仓库根目录的 `start_server.bat`

### 3. PC 端管理器（随管）

```bash
cd PanoramaManager/PanoramaMapper-PC
pip install -r requirements.txt
python src/main.py
```

---

## 部署到 GitHub Pages

1. 进入仓库 **Settings** → **Pages**（左侧菜单）。
2. 在 **Build and deployment** 区域：
   - **Source**：选择 `Deploy from a branch`
   - **Branch**：选择 `main`（或 `master`），文件夹选择 `/(root)`
3. 点击 **Save**，等待 1-2 分钟后即可通过 `https://huangkeqi-cmd.github.io/suixi-system/` 访问。

> 所有静态资源均使用相对路径（如 `./PanoramaCapture/capture.html`、`./css/capture.css`），确保在 GitHub Pages 子路径下正常工作。

---

## 扩展规划

以下是一些后续可以考虑加入的能力方向，均以技术中性的方式描述，供社区参考与贡献：

| 方向 | 说明 |
|------|------|
| **数据云端同步** | 在现有 LocalStorage 基础上，增加可选的云端同步接口（如 WebDAV、Firebase、私有服务器），实现多端数据互通。 |
| **协同标注** | 支持多人对同一项目平面图进行实时或异步标注，通过操作日志合并策略解决冲突。 |
| **更丰富的导出格式** | 除现有 JSON / ZIP 外，探索导出为 PDF 汇报文档、CAD 点位文件、PPT 演示文稿等格式。 |
| **地图图层叠加** | 在平面图模式外，增加卫星地图或矢量地图作为底图，便于在宏观层面定位项目。 |
| **自动化工作流** | 通过 GitHub Actions 等 CI 工具，实现采集数据包的自动校验、格式转换与版本归档。 |
| **Web Component 化** | 将现有采集端的功能模块拆分为独立 Web Component，提高复用性与可测试性。 |

> 以上规划仅为方向性展望，不代表开发承诺。欢迎通过 Issue 或 PR 提出你的想法。

---

## 许可证

本项目采用 [MIT License](./LICENSE) 开源，保留原始版权声明即可自由使用、修改与分发。

---

## 关于商用

本项目目前为个人工作流工具，核心模块计划逐步开源。
如需企业级授权、定制开发或商业合作，请联系：376524686@qq.com

版本理念：怎么方便怎么做，先跑起来，再慢慢长。
