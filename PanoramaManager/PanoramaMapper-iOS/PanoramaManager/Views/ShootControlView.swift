import SwiftUI

// MARK: - 拍摄控制视图（底部弹窗）
struct ShootControlView: View {
    let marker: Marker
    @ObservedObject var cameraManager: CameraManager
    let onShoot: (String) -> Void
    let onManualInput: () -> Void
    var onNoteUpdate: ((String) -> Void)? = nil
    
    @Environment(\.dismiss) private var dismiss
    @State private var isShooting = false
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var noteText = ""
    
    var body: some View {
        NavigationView {
            VStack(spacing: 30) {
                // 标记点信息
                VStack(spacing: 8) {
                    Text(marker.customName.isEmpty ? "点位 \(marker.id)" : marker.customName)
                        .font(.title2)
                        .fontWeight(.bold)
                    
                    HStack(spacing: 4) {
                        StatusBadge(status: marker.status)
                        
                        if !marker.cameraFileName.isEmpty {
                            Text("•")
                                .foregroundColor(.secondary)
                            Text(marker.cameraFileName)
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
                .padding(.top, 20)
                
                // 备注输入（流程中间的其他功能）
                VStack(spacing: 8) {
                    TextField("添加备注...", text: $noteText)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .padding(.horizontal)
                    if !noteText.isEmpty {
                        Button("保存备注") {
                            onNoteUpdate?(noteText)
                        }
                        .font(.caption)
                        .foregroundColor(.blue)
                    }
                }
                
                Spacer()
                
                // 快门按钮
                if cameraManager.isManualMode {
                    // 手动模式
                    VStack(spacing: 20) {
                        Image(systemName: "hand.tap.fill")
                            .font(.system(size: 60))
                            .foregroundColor(.orange)
                        
                        Text("手动输入模式")
                            .font(.headline)
                        
                        Text("请在相机拍摄完成后，手动输入 SD 卡中的文件名")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                        
                        Button {
                            onManualInput()
                            dismiss()
                        } label: {
                            HStack {
                                Image(systemName: "keyboard")
                                Text("输入文件名")
                            }
                            .font(.headline)
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.orange)
                            .cornerRadius(12)
                        }
                        .padding(.horizontal, 40)
                    }
                } else {
                    // 自动模式 - 大快门按钮
                    VStack(spacing: 20) {
                        Button {
                            shootPhoto()
                        } label: {
                            ZStack {
                                Circle()
                                    .fill(isShooting ? Color.gray : Color.red)
                                    .frame(width: 100, height: 100)
                                
                                Circle()
                                    .stroke(Color.white, lineWidth: 3)
                                    .frame(width: 90, height: 90)
                                
                                if isShooting {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                        .scaleEffect(1.2)
                                }
                            }
                        }
                        .disabled(isShooting)
                        
                        Text(isShooting ? "拍摄中..." : "点击拍摄")
                            .font(.headline)
                            .foregroundColor(isShooting ? .secondary : .primary)
                    }
                }
                
                Spacer()
                
                // 备用选项
                VStack(spacing: 12) {
                    if !cameraManager.isManualMode {
                        Button {
                            cameraManager.enableManualMode()
                        } label: {
                            Text("切换到手动输入模式")
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                        }
                    }
                    
                    if marker.status != .pending {
                        Button(role: .destructive) {
                            reshoot()
                        } label: {
                            Text("重新拍摄")
                                .font(.subheadline)
                        }
                    }
                }
                .padding(.bottom, 30)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("关闭") {
                        dismiss()
                    }
                }
            }
            .alert("拍摄失败", isPresented: $showError) {
                Button("确定", role: .cancel) {}
                Button("手动输入") {
                    onManualInput()
                    dismiss()
                }
            } message: {
                Text(errorMessage)
            }
        }
    }
    
    private func shootPhoto() {
        if !noteText.isEmpty {
            onNoteUpdate?(noteText)
        }
        isShooting = true
        
        cameraManager.shootPhoto { fileName in
            DispatchQueue.main.async {
                isShooting = false
                
                if let fileName = fileName {
                    onShoot(fileName)
                    dismiss()
                } else {
                    errorMessage = "无法获取文件名，请检查相机连接或切换到手动模式"
                    showError = true
                }
            }
        }
    }
    
    private func reshoot() {
        if !noteText.isEmpty {
            onNoteUpdate?(noteText)
        }
        isShooting = true
        
        cameraManager.shootPhoto { fileName in
            DispatchQueue.main.async {
                isShooting = false
                
                if let fileName = fileName {
                    onShoot(fileName)
                    dismiss()
                } else {
                    errorMessage = "无法获取文件名"
                    showError = true
                }
            }
        }
    }
}

// MARK: - 状态徽章
struct StatusBadge: View {
    let status: MarkerStatus
    
    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(color)
                .frame(width: 6, height: 6)
            
            Text(text)
                .font(.caption)
                .fontWeight(.medium)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.15))
        .cornerRadius(8)
    }
    
    var color: Color {
        switch status {
        case .pending:
            return .gray
        case .captured:
            return .blue
        case .linked:
            return .green
        case .missing:
            return .red
        }
    }
    
    var text: String {
        switch status {
        case .pending:
            return "待拍摄"
        case .captured:
            return "已拍摄"
        case .linked:
            return "已关联"
        case .missing:
            return "照片缺失"
        }
    }
}

// MARK: - 设备列表视图
struct DeviceListView: View {
    @ObservedObject var cameraManager: CameraManager
    @Environment(\.dismiss) private var dismiss
    
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("附近设备")) {
                    if cameraManager.discoveredDevices.isEmpty {
                        HStack {
                            Spacer()
                            VStack(spacing: 8) {
                                ProgressView()
                                Text("正在搜索 DJI 相机...")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                            .padding()
                            Spacer()
                        }
                    } else {
                        ForEach(cameraManager.discoveredDevices) { device in
                            DeviceRow(device: device)
                                .contentShape(Rectangle())
                                .onTapGesture {
                                    cameraManager.connect(to: device)
                                    dismiss()
                                }
                        }
                    }
                }
                
                Section {
                    Button {
                        cameraManager.enableManualMode()
                        dismiss()
                    } label: {
                        HStack {
                            Image(systemName: "hand.tap")
                            Text("使用手动输入模式")
                        }
                        .foregroundColor(.orange)
                    }
                } footer: {
                    Text("如果无法连接相机，可以使用手动模式，在相机拍摄后手动输入文件名")
                        .font(.caption)
                }
            }
            .navigationTitle("连接相机")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("关闭") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarLeading) {
                    Button {
                        cameraManager.startScanning()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .onAppear {
                cameraManager.startScanning()
            }
        }
    }
}

// MARK: - 设备行
struct DeviceRow: View {
    let device: CameraDevice
    
    var body: some View {
        HStack {
            Image(systemName: "camera.fill")
                .foregroundColor(.blue)
                .frame(width: 40, height: 40)
                .background(Color.blue.opacity(0.1))
                .cornerRadius(8)
            
            VStack(alignment: .leading, spacing: 4) {
                Text(device.name)
                    .font(.body)
                
                HStack(spacing: 4) {
                    Image(systemName: "wifi")
                        .font(.caption2)
                    Text("\(abs(device.rssi)) dBm")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
            
            Spacer()
            
            Image(systemName: "chevron.right")
                .foregroundColor(.gray)
                .font(.caption)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - 标记点详情视图
struct MarkerDetailView: View {
    let marker: Marker
    let onSave: (Marker) -> Void
    
    @Environment(\.dismiss) private var dismiss
    @State private var customName: String
    @State private var editedMarker: Marker
    
    init(marker: Marker, onSave: @escaping (Marker) -> Void) {
        self.marker = marker
        self.onSave = onSave
        _customName = State(initialValue: marker.customName)
        _editedMarker = State(initialValue: marker)
    }
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("基本信息")) {
                    LabeledContent("点位 ID", value: marker.id)
                    
                    HStack {
                        Text("状态")
                        Spacer()
                        StatusBadge(status: marker.status)
                    }
                    
                    if !marker.cameraFileName.isEmpty {
                        LabeledContent("文件名", value: marker.cameraFileName)
                    }
                    
                    if !marker.timestamp.isEmpty {
                        LabeledContent("拍摄时间", value: formatDate(marker.timestamp))
                    }
                }
                
                Section(header: Text("坐标")) {
                    LabeledContent("X", value: String(format: "%.4f", marker.x))
                    LabeledContent("Y", value: String(format: "%.4f", marker.y))
                }
                
                Section(header: Text("编辑")) {
                    TextField("自定义名称", text: $customName)
                        .onChange(of: customName) { newValue in
                            editedMarker.customName = newValue
                        }
                }
            }
            .navigationTitle("点位详情")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("取消") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("保存") {
                        onSave(editedMarker)
                        dismiss()
                    }
                }
            }
        }
    }
    
    private func formatDate(_ dateString: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: dateString) else { return dateString }
        
        let displayFormatter = DateFormatter()
        displayFormatter.dateFormat = "MM-dd HH:mm:ss"
        return displayFormatter.string(from: date)
    }
}
