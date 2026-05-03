import SwiftUI

// MARK: - 采集视图（核心界面）
struct CaptureView: View {
    @State var projectItem: ProjectItem
    @StateObject private var cameraManager = CameraManager.shared
    
    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var selectedMarker: Marker?
    @State private var showingShootSheet = false
    @State private var showingManualInput = false
    @State private var manualFileName = ""
    @State private var showingDeviceList = false
    @State private var isHighContrastMode = false
    @State private var showingMarkerDetail = false
    @State private var isEditMode = false
    @State private var showDeleteConfirm = false
    @State private var isAutoShowShootSheet = true
    @State private var showingSettings = false
    
    private let minScale: CGFloat = 0.5
    private let maxScale: CGFloat = 5.0
    
    private var floorplanImage: UIImage? {
        let path = projectItem.url.appendingPathComponent(projectItem.project.floorplan)
        guard let data = try? Data(contentsOf: path) else { return nil }
        return UIImage(data: data)
    }
    
    var body: some View {
        ZStack {
            // 背景
            Color(isHighContrastMode ? .black : UIColor.systemBackground)
                .ignoresSafeArea()
            
            VStack(spacing: 0) {
                // 顶部工具栏
                HStack {
                    // 连接状态
                    ConnectionStatusView(
                        state: cameraManager.state,
                        isManualMode: cameraManager.isManualMode
                    )
                    .onTapGesture {
                        if case .disconnected = cameraManager.state {
                            showingDeviceList = true
                        }
                    }
                    
                    Spacer()
                    
                    // 高对比度模式切换
                    Button {
                        isHighContrastMode.toggle()
                    } label: {
                        Image(systemName: isHighContrastMode ? "sun.max.fill" : "sun.min")
                            .foregroundColor(isHighContrastMode ? .yellow : .primary)
                    }
                    
                    // 编辑模式切换
                    Button {
                        isEditMode.toggle()
                    } label: {
                        Image(systemName: isEditMode ? "checkmark.circle.fill" : "pencil.circle")
                            .foregroundColor(isEditMode ? .green : .primary)
                    }
                    
                    // 设置
                    Button {
                        showingSettings = true
                    } label: {
                        Image(systemName: "gear")
                            .foregroundColor(.primary)
                    }
                }
                .padding()
                .background(Color(.systemBackground).opacity(0.9))
                
                // 平面图画布
                GeometryReader { geometry in
                    ZStack {
                        if let image = floorplanImage {
                            Image(uiImage: image)
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .scaleEffect(scale)
                                .offset(offset)
                                .gesture(
                                    MagnificationGesture()
                                        .onChanged { value in
                                            let delta = value / lastScale
                                            lastScale = value
                                            scale = min(max(scale * delta, minScale), maxScale)
                                        }
                                        .onEnded { _ in
                                            lastScale = 1.0
                                        }
                                )
                                .simultaneousGesture(
                                    DragGesture()
                                        .onChanged { value in
                                            offset = CGSize(
                                                width: lastOffset.width + value.translation.width,
                                                height: lastOffset.height + value.translation.height
                                            )
                                        }
                                        .onEnded { _ in
                                            lastOffset = offset
                                        }
                                )
                                .onTapGesture(count: 2) {
                                    // 双击重置
                                    withAnimation {
                                        scale = 1.0
                                        offset = .zero
                                        lastOffset = .zero
                                    }
                                }
                                .onLongPressGesture(minimumDuration: 0.3) { value in
                                    // 长按添加标记（移除 iOS 限制，始终允许）
                                    let location = value.location
                                    addMarker(at: location, in: geometry.size)
                                }
                        }
                        
                        // 标记点层
                        ForEach(projectItem.project.markers, id: \.id) { marker in
                            MarkerView(
                                marker: marker,
                                isHighContrast: isHighContrastMode,
                                isSelected: selectedMarker?.id == marker.id,
                                scale: scale
                            )
                            .position(
                                x: marker.x * geometry.size.width,
                                y: marker.y * geometry.size.height
                            )
                            .onTapGesture {
                                if isEditMode {
                                    selectedMarker = marker
                                    showingMarkerDetail = true
                                } else {
                                    selectedMarker = marker
                                    showingShootSheet = true
                                }
                            }
                            .gesture(
                                LongPressGesture(minimumDuration: 0.5)
                                    .onEnded { _ in
                                        if isEditMode {
                                            selectedMarker = marker
                                            showDeleteConfirm = true
                                        }
                                    }
                            )
                        }
                    }
                }
                
                // 底部状态栏
                HStack {
                    Text("点位: \(projectItem.project.markers.count)")
                        .font(.caption)
                    
                    Spacer()
                    
                    if let selected = selectedMarker {
                        Text(selected.customName.isEmpty ? selected.id : selected.customName)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .padding()
                .background(Color(.systemBackground).opacity(0.9))
            }
        }
        .navigationTitle(projectItem.project.projectName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button {
                    exportProject()
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
            }
        }
        .sheet(isPresented: $showingDeviceList) {
            DeviceListView(cameraManager: cameraManager)
        }
        .sheet(isPresented: $showingShootSheet) {
            if let marker = selectedMarker {
                ShootControlView(
                    marker: marker,
                    cameraManager: cameraManager,
                    onShoot: { fileName in
                        updateMarker(marker, withFileName: fileName)
                    },
                    onManualInput: {
                        showingManualInput = true
                    },
                    onNoteUpdate: { note in
                        var updatedMarker = marker
                        updatedMarker.customName = note
                        updateMarkerInProject(updatedMarker)
                    }
                )
            }
        }
        .alert("手动输入文件名", isPresented: $showingManualInput) {
            TextField("如: DJI_20250122_143015.JPG", text: $manualFileName)
            Button("确认") {
                if let marker = selectedMarker {
                    updateMarker(marker, withFileName: manualFileName)
                }
                manualFileName = ""
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("请输入相机 SD 卡中显示的文件名")
        }
        .alert("删除点位", isPresented: $showDeleteConfirm) {
            Button("删除", role: .destructive) {
                if let marker = selectedMarker {
                    deleteMarker(marker)
                }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("确定要删除这个点位吗？")
        }
        .sheet(isPresented: $showingMarkerDetail) {
            if let marker = selectedMarker {
                MarkerDetailView(marker: marker) { updatedMarker in
                    updateMarkerInProject(updatedMarker)
                }
            }
        }
        .sheet(isPresented: $showingSettings) {
            NavigationView {
                Form {
                    Section(header: Text("采集流程")) {
                        Toggle("放置后自动弹出拍摄面板", isOn: $isAutoShowShootSheet)
                        Text("关闭后，放置采集点不会自动弹出拍摄面板，需手动点击点位")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                    
                    Section(header: Text("显示")) {
                        Toggle("高对比度模式", isOn: $isHighContrastMode)
                    }
                    
                    Section(header: Text("编辑")) {
                        Toggle("编辑模式", isOn: $isEditMode)
                    }
                }
                .navigationTitle("采集设置")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button("完成") {
                            showingSettings = false
                        }
                    }
                }
            }
        }
    }
    
    // 添加标记
    private func addMarker(at location: CGPoint, in size: CGSize) {
        let normalizedX = location.x / size.width
        let normalizedY = location.y / size.height
        
        let newMarker = Marker(
            id: "m\(projectItem.project.markers.count + 1)",
            status: .pending,
            x: normalizedX,
            y: normalizedY,
            timestamp: ISO8601DateFormatter().string(from: Date())
        )
        
        var updatedProject = projectItem.project
        updatedProject.markers.append(newMarker)
        
        do {
            try ProjectManager.shared.updateProject(ProjectItem(
                id: projectItem.id,
                project: updatedProject,
                url: projectItem.url
            ))
            projectItem.project = updatedProject
            
            // 默认弹出弹窗，可在设置中关闭
            selectedMarker = newMarker
            if isAutoShowShootSheet {
                showingShootSheet = true
            }
        } catch {
            print("保存失败: \(error)")
        }
    }
    
    // 删除标记
    private func deleteMarker(_ marker: Marker) {
        var updatedProject = projectItem.project
        updatedProject.markers.removeAll { $0.id == marker.id }
        
        do {
            try ProjectManager.shared.updateProject(ProjectItem(
                id: projectItem.id,
                project: updatedProject,
                url: projectItem.url
            ))
            projectItem.project = updatedProject
        } catch {
            print("删除失败: \(error)")
        }
    }
    
    // 更新标记（拍摄后）
    private func updateMarker(_ marker: Marker, withFileName fileName: String) {
        var updatedMarker = marker
        updatedMarker.cameraFileName = fileName
        updatedMarker.status = .captured
        updatedMarker.timestamp = ISO8601DateFormatter().string(from: Date())
        
        var updatedProject = projectItem.project
        if let index = updatedProject.markers.firstIndex(where: { $0.id == marker.id }) {
            updatedProject.markers[index] = updatedMarker
        }
        
        do {
            try ProjectManager.shared.updateProject(ProjectItem(
                id: projectItem.id,
                project: updatedProject,
                url: projectItem.url
            ))
            projectItem.project = updatedProject
        } catch {
            print("更新失败: \(error)")
        }
        
        showingShootSheet = false
    }
    
    // 更新标记详情
    private func updateMarkerInProject(_ marker: Marker) {
        var updatedProject = projectItem.project
        if let index = updatedProject.markers.firstIndex(where: { $0.id == marker.id }) {
            updatedProject.markers[index] = marker
        }
        
        do {
            try ProjectManager.shared.updateProject(ProjectItem(
                id: projectItem.id,
                project: updatedProject,
                url: projectItem.url
            ))
            projectItem.project = updatedProject
        } catch {
            print("更新失败: \(error)")
        }
    }
    
    // 导出项目
    private func exportProject() {
        do {
            let zipURL = try ProjectManager.shared.exportProject(projectItem)
            shareFile(zipURL)
        } catch {
            print("导出失败: \(error)")
        }
    }
    
    private func shareFile(_ url: URL) {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootViewController = windowScene.windows.first?.rootViewController else {
            return
        }
        
        let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        
        if let popover = activityVC.popoverPresentationController {
            popover.sourceView = rootViewController.view
            popover.sourceRect = CGRect(x: rootViewController.view.bounds.midX,
                                        y: rootViewController.view.bounds.midY,
                                        width: 0, height: 0)
        }
        
        rootViewController.present(activityVC, animated: true)
    }
}

// MARK: - 连接状态视图
struct ConnectionStatusView: View {
    let state: CameraState
    let isManualMode: Bool
    
    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)
            
            Text(statusText)
                .font(.caption)
                .fontWeight(.medium)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(statusColor.opacity(0.15))
        .cornerRadius(12)
    }
    
    var statusColor: Color {
        if isManualMode {
            return .orange
        }
        switch state {
        case .disconnected:
            return .gray
        case .scanning, .connecting:
            return .yellow
        case .connected:
            return .green
        case .shooting:
            return .blue
        }
    }
    
    var statusText: String {
        if isManualMode {
            return "手动模式"
        }
        switch state {
        case .disconnected:
            return "连接相机"
        case .scanning:
            return "搜索中..."
        case .connecting:
            return "连接中..."
        case .connected(let battery):
            return "已连接 | 电量 \(battery)%"
        case .shooting:
            return "拍摄中..."
        }
    }
}

// MARK: - 标记点视图
struct MarkerView: View {
    let marker: Marker
    let isHighContrast: Bool
    let isSelected: Bool
    let scale: CGFloat
    
    var body: some View {
        ZStack {
            Circle()
                .fill(markerColor)
                .frame(width: isSelected ? 28 : 24, height: isSelected ? 28 : 24)
            
            if marker.status == .pending {
                Circle()
                    .stroke(borderColor, lineWidth: 2)
                    .frame(width: isSelected ? 28 : 24, height: isSelected ? 28 : 24)
            }
            
            if isSelected {
                Circle()
                    .stroke(Color.white, lineWidth: 2)
                    .frame(width: 32, height: 32)
            }
        }
        .scaleEffect(1.0 / max(scale, 0.5)) // 保持标记点大小不变
        .animation(.easeInOut(duration: 0.2), value: isSelected)
    }
    
    var markerColor: Color {
        if isHighContrast {
            return Color.yellow
        }
        
        switch marker.status {
        case .pending:
            return Color.gray.opacity(0.3)
        case .captured:
            return Color.blue
        case .linked:
            return Color.green
        case .missing:
            return Color.red
        }
    }
    
    var borderColor: Color {
        isHighContrast ? .black : .gray
    }
}
