import SwiftUI

// MARK: - 项目列表视图
// 随系 · 影像管理器
// 系统追求：让工具追上现场的速度
struct ProjectListView: View {
    @StateObject private var projectManager = ProjectManager.shared
    @State private var showingCreateSheet = false
    @State private var showingDeleteAlert = false
    @State private var projectToDelete: ProjectItem?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var showError = false
    @State private var showSplash = true
    
    var body: some View {
        NavigationView {
            ZStack {
                // 启动画面
                if showSplash {
                    SplashView()
                        .transition(.opacity)
                        .onAppear {
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                withAnimation {
                                    showSplash = false
                                }
                            }
                        }
                }
                
                List {
                    ForEach(projectManager.projects) { item in
                        NavigationLink(destination: CaptureView(projectItem: item)) {
                            ProjectRow(item: item)
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                projectToDelete = item
                                showingDeleteAlert = true
                            } label: {
                                Label("删除", systemImage: "trash")
                            }
                            
                            Button {
                                exportProject(item)
                            } label: {
                                Label("导出", systemImage: "square.and.arrow.up")
                            }
                            .tint(.blue)
                        }
                    }
                }
                .listStyle(.plain)
                .navigationTitle("随系 · 影像管理器")
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button {
                            showingCreateSheet = true
                        } label: {
                            Image(systemName: "plus")
                        }
                    }
                }
                
                if projectManager.projects.isEmpty {
                    EmptyStateView()
                }
                
                if isLoading {
                    LoadingOverlay()
                }
            }
            .sheet(isPresented: $showingCreateSheet) {
                CreateProjectView { name, image, originalName in
                    createProject(name: name, image: image, originalName: originalName)
                }
            }
            .alert("确认删除", isPresented: $showingDeleteAlert, presenting: projectToDelete) { item in
                Button("删除", role: .destructive) {
                    deleteProject(item)
                }
                Button("取消", role: .cancel) {}
            } message: { item in
                Text("确定要删除项目 '\(item.project.projectName)' 吗？此操作不可撤销。")
            }
            .alert("错误", isPresented: $showError) {
                Button("确定", role: .cancel) {}
            } message: {
                Text(errorMessage ?? "发生未知错误")
            }
        }
    }
    
    // 创建项目
    private func createProject(name: String, image: UIImage, originalName: String) {
        isLoading = true
        
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let _ = try projectManager.createProject(
                    name: name,
                    floorplanImage: image,
                    originalName: originalName
                )
                
                DispatchQueue.main.async {
                    isLoading = false
                    showingCreateSheet = false
                }
            } catch {
                DispatchQueue.main.async {
                    isLoading = false
                    errorMessage = error.localizedDescription
                    showError = true
                }
            }
        }
    }
    
    // 删除项目
    private func deleteProject(_ item: ProjectItem) {
        do {
            try projectManager.deleteProject(item)
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }
    
    // 导出项目
    private func exportProject(_ item: ProjectItem) {
        isLoading = true
        
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let zipURL = try projectManager.exportProject(item)
                
                DispatchQueue.main.async {
                    isLoading = false
                    shareFile(zipURL)
                }
            } catch {
                DispatchQueue.main.async {
                    isLoading = false
                    errorMessage = error.localizedDescription
                    showError = true
                }
            }
        }
    }
    
    // 分享文件
    private func shareFile(_ url: URL) {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootViewController = windowScene.windows.first?.rootViewController else {
            return
        }
        
        let activityVC = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        
        if let popover = activityVC.popoverPresentationController {
            popover.sourceView = rootViewController.view
            popover.sourceRect = CGRect(x: rootViewController.view.bounds.midX, y: rootViewController.view.bounds.midY, width: 0, height: 0)
        }
        
        rootViewController.present(activityVC, animated: true)
    }
}

// MARK: - 项目行视图
struct ProjectRow: View {
    let item: ProjectItem
    
    var body: some View {
        HStack(spacing: 12) {
            // 平面图缩略图
            if let image = loadThumbnail() {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: 60, height: 60)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            } else {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.gray.opacity(0.3))
                    .frame(width: 60, height: 60)
                    .overlay(
                        Image(systemName: "photo")
                            .foregroundColor(.gray)
                    )
            }
            
            VStack(alignment: .leading, spacing: 4) {
                Text(item.project.projectName)
                    .font(.headline)
                    .lineLimit(1)
                
                HStack(spacing: 8) {
                    Label("\(item.project.markers.count)", systemImage: "mappin.circle.fill")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    
                    Text(formatDate(item.project.updatedAt))
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
    
    private func loadThumbnail() -> UIImage? {
        let floorplanPath = item.url.appendingPathComponent(item.project.floorplan)
        guard let data = try? Data(contentsOf: floorplanPath) else { return nil }
        return UIImage(data: data)
    }
    
    private func formatDate(_ dateString: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: dateString) else { return "" }
        
        let displayFormatter = DateFormatter()
        displayFormatter.dateFormat = "MM-dd HH:mm"
        return displayFormatter.string(from: date)
    }
}

// MARK: - 空状态视图
struct EmptyStateView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "cube.box")
                .font(.system(size: 60))
                .foregroundColor(.gray)
            
            Text("还没有项目")
                .font(.headline)
                .foregroundColor(.gray)
            
            Text("点击右上角 + 按钮创建新项目")
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
    }
}

// MARK: - 加载遮罩
struct LoadingOverlay: View {
    var body: some View {
        ZStack {
            Color.black.opacity(0.4)
                .ignoresSafeArea()
            
            VStack(spacing: 16) {
                ProgressView()
                    .scaleEffect(1.5)
                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                
                Text("处理中...")
                    .foregroundColor(.white)
                    .font(.headline)
            }
        }
    }
}

// MARK: - 启动画面
struct SplashView: View {
    var body: some View {
        ZStack {
            Color(uiColor: .systemBackground)
                .ignoresSafeArea()
            
            VStack(spacing: 16) {
                Image(systemName: "camera.viewfinder")
                    .font(.system(size: 80))
                    .foregroundColor(.blue)
                
                Text("随系 · 影像管理器")
                    .font(.title2)
                    .fontWeight(.bold)
                
                Text("让工具追上现场的速度")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }
        }
    }
}
