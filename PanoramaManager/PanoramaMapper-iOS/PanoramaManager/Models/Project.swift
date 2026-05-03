import Foundation

// MARK: - 标记点模型
struct Marker: Codable, Identifiable {
    var id: String
    var status: MarkerStatus
    var cameraFileName: String
    var customName: String
    var x: Double  // 归一化坐标 0-1
    var y: Double
    var timestamp: String
    var panoramaPath: String
    
    init(id: String = UUID().uuidString,
         status: MarkerStatus = .pending,
         cameraFileName: String = "",
         customName: String = "",
         x: Double = 0,
         y: Double = 0,
         timestamp: String = "",
         panoramaPath: String = "") {
        self.id = id
        self.status = status
        self.cameraFileName = cameraFileName
        self.customName = customName
        self.x = x
        self.y = y
        self.timestamp = timestamp
        self.panoramaPath = panoramaPath
    }
}

enum MarkerStatus: String, Codable {
    case pending = "pending"      // 仅标记，未拍摄
    case captured = "captured"    // 已拍摄，未传 PC
    case linked = "linked"        // PC 端已关联
    case missing = "missing"      // 照片缺失
}

// MARK: - 项目模型
struct Project: Codable {
    var schemaVersion: String
    var projectName: String
    var createdAt: String
    var updatedAt: String
    var floorplan: String
    var floorplanOriginalName: String
    var markers: [Marker]
    
    init(projectName: String,
         floorplan: String,
         floorplanOriginalName: String) {
        self.schemaVersion = "1.0"
        self.projectName = projectName
        self.createdAt = ISO8601DateFormatter().string(from: Date())
        self.updatedAt = self.createdAt
        self.floorplan = floorplan
        self.floorplanOriginalName = floorplanOriginalName
        self.markers = []
    }
}

// MARK: - 项目文件管理
class ProjectManager: ObservableObject {
    @Published var projects: [ProjectItem] = []
    
    static let shared = ProjectManager()
    
    private let projectsDirectory: URL
    
    init() {
        let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        projectsDirectory = documentsPath.appendingPathComponent("SuixiProjects", isDirectory: true)
        
        try? FileManager.default.createDirectory(at: projectsDirectory, withIntermediateDirectories: true)
        
        loadProjects()
    }
    
    // 加载所有项目
    func loadProjects() {
        guard let contents = try? FileManager.default.contentsOfDirectory(at: projectsDirectory, includingPropertiesForKeys: nil) else {
            return
        }
        
        projects = contents
            .filter { $0.hasDirectoryPath }
            .compactMap { url -> ProjectItem? in
                let jsonPath = url.appendingPathComponent("project.json")
                guard let data = try? Data(contentsOf: jsonPath),
                      let project = try? JSONDecoder().decode(Project.self, from: data) else {
                    return nil
                }
                return ProjectItem(id: url.lastPathComponent, project: project, url: url)
            }
            .sorted { $0.project.updatedAt > $1.project.updatedAt }
    }
    
    // 创建新项目
    func createProject(name: String, floorplanImage: UIImage, originalName: String) throws -> ProjectItem {
        // 验证项目名称
        let sanitizedName = sanitizeFileName(name)
        guard !sanitizedName.isEmpty else {
            throw ProjectError.invalidName
        }
        
        // 创建项目目录
        let projectId = UUID().uuidString
        let projectDir = projectsDirectory.appendingPathComponent(projectId, isDirectory: true)
        try FileManager.default.createDirectory(at: projectDir, withIntermediateDirectories: true)
        
        // 保存平面图
        let floorplanName = "floorplan.jpg"
        let floorplanPath = projectDir.appendingPathComponent(floorplanName)
        
        guard let imageData = floorplanImage.jpegData(compressionQuality: 0.9) else {
            throw ProjectError.imageConversionFailed
        }
        try imageData.write(to: floorplanPath)
        
        // 创建项目数据
        let project = Project(
            projectName: name,
            floorplan: floorplanName,
            floorplanOriginalName: originalName
        )
        
        // 保存 project.json
        let jsonPath = projectDir.appendingPathComponent("project.json")
        let jsonData = try JSONEncoder().encode(project)
        try jsonData.write(to: jsonPath)
        
        let item = ProjectItem(id: projectId, project: project, url: projectDir)
        projects.insert(item, at: 0)
        
        return item
    }
    
    // 更新项目
    func updateProject(_ item: ProjectItem) throws {
        var updatedProject = item.project
        updatedProject.updatedAt = ISO8601DateFormatter().string(from: Date())
        
        let jsonPath = item.url.appendingPathComponent("project.json")
        let jsonData = try JSONEncoder().encode(updatedProject)
        try jsonData.write(to: jsonPath)
        
        // 更新内存中的数据
        if let index = projects.firstIndex(where: { $0.id == item.id }) {
            projects[index] = ProjectItem(id: item.id, project: updatedProject, url: item.url)
        }
        
        // 重新排序
        projects.sort { $0.project.updatedAt > $1.project.updatedAt }
    }
    
    // 删除项目
    func deleteProject(_ item: ProjectItem) throws {
        try FileManager.default.removeItem(at: item.url)
        projects.removeAll { $0.id == item.id }
    }
    
    // 导出项目为 ZIP
    func exportProject(_ item: ProjectItem) throws -> URL {
        let zipName = "\(item.project.projectName)_\(formatDate(Date())).zip"
        let zipURL = FileManager.default.temporaryDirectory.appendingPathComponent(zipName)
        
        // 创建 ZIP
        try createZip(from: item.url, to: zipURL)
        
        return zipURL
    }
    
    // 清理文件名
    private func sanitizeFileName(_ name: String) -> String {
        let invalidCharacters = CharacterSet(charactersIn: "\\/:*?\"<>|")
        return name.components(separatedBy: invalidCharacters).joined(separator: "_")
    }
    
    // 格式化日期
    private func formatDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd"
        return formatter.string(from: date)
    }
    
    // 创建 ZIP 文件
    private func createZip(from directory: URL, to zipURL: URL) throws {
        let coordinator = NSFileCoordinator()
        var error: NSError?
        
        coordinator.coordinate(readingItemAt: directory, options: .forUploading, error: &error) { url in
            try? FileManager.default.moveItem(at: url, to: zipURL)
        }
        
        if let error = error {
            throw error
        }
    }
}

// MARK: - 项目项
struct ProjectItem: Identifiable {
    let id: String
    var project: Project
    let url: URL
}

// MARK: - 错误类型
enum ProjectError: Error, LocalizedError {
    case invalidName
    case imageConversionFailed
    case fileNotFound
    case saveFailed
    
    var errorDescription: String? {
        switch self {
        case .invalidName:
            return "项目名称无效"
        case .imageConversionFailed:
            return "图片转换失败"
        case .fileNotFound:
            return "文件未找到"
        case .saveFailed:
            return "保存失败"
        }
    }
}
