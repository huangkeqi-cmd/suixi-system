import SwiftUI
import PhotosUI

// MARK: - 创建项目视图
struct CreateProjectView: View {
    let onCreate: (String, UIImage, String) -> Void
    
    @Environment(\.dismiss) private var dismiss
    
    @State private var projectName = ""
    @State private var selectedImage: UIImage?
    @State private var originalFileName = ""
    @State private var showingImagePicker = false
    @State private var showingFileImporter = false
    @State private var showingCamera = false
    @State private var imageSourceType: UIImagePickerController.SourceType = .photoLibrary
    
    private let maxNameLength = 50
    private let invalidCharacters = CharacterSet(charactersIn: "\\/:*?\"<>|")
    
    var isValid: Bool {
        !projectName.trimmingCharacters(in: .whitespaces).isEmpty &&
        selectedImage != nil &&
        !projectName.contains(where: { invalidCharacters.contains($0.unicodeScalars.first!) })
    }
    
    var body: some View {
        NavigationView {
            Form {
                // 项目名称
                Section(header: Text("项目信息")) {
                    TextField("项目名称", text: $projectName)
                        .onChange(of: projectName) { newValue in
                            if newValue.count > maxNameLength {
                                projectName = String(newValue.prefix(maxNameLength))
                            }
                        }
                    
                    Text("\(projectName.count)/\(maxNameLength) 字符")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                // 平面图
                Section(header: Text("平面图")) {
                    if let image = selectedImage {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFit
                            .frame(maxHeight: 300)
                            .cornerRadius(8)
                    } else {
                        VStack(spacing: 20) {
                            Button {
                                showingImagePicker = true
                                imageSourceType = .photoLibrary
                            } label: {
                                ImportButton(
                                    icon: "photo.on.rectangle",
                                    title: "从相册选择",
                                    subtitle: "JPG / PNG"
                                )
                            }
                            
                            Button {
                                showingFileImporter = true
                            } label: {
                                ImportButton(
                                    icon: "doc.viewfinder",
                                    title: "从文件导入",
                                    subtitle: "支持 PDF"
                                )
                            }
                            
                            Button {
                                showingCamera = true
                                imageSourceType = .camera
                            } label: {
                                ImportButton(
                                    icon: "camera.fill",
                                    title: "拍照",
                                    subtitle: "直接拍摄平面图"
                                )
                            }
                        }
                        .padding(.vertical, 20)
                    }
                }
                
                // 已选文件信息
                if !originalFileName.isEmpty {
                    Section(header: Text("源文件")) {
                        Text(originalFileName)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("新建项目")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("取消") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("创建") {
                        if let image = selectedImage {
                            onCreate(projectName.trimmingCharacters(in: .whitespaces), image, originalFileName)
                        }
                    }
                    .disabled(!isValid)
                }
            }
            .sheet(isPresented: $showingImagePicker) {
                ImagePicker(sourceType: imageSourceType, selectedImage: $selectedImage, onComplete: { url in
                    if let url = url {
                        originalFileName = url.lastPathComponent
                    }
                })
            }
            .sheet(isPresented: $showingFileImporter) {
                DocumentPicker(selectedImage: $selectedImage, fileName: $originalFileName)
            }
            .sheet(isPresented: $showingCamera) {
                ImagePicker(sourceType: .camera, selectedImage: $selectedImage, onComplete: { url in
                    originalFileName = "camera_\(Date().timeIntervalSince1970).jpg"
                })
            }
        }
    }
}

// MARK: - 导入按钮
struct ImportButton: View {
    let icon: String
    let title: String
    let subtitle: String
    
    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: icon)
                .font(.title2)
                .frame(width: 40, height: 40)
                .background(Color.blue.opacity(0.1))
                .foregroundColor(.blue)
                .cornerRadius(8)
            
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body)
                    .fontWeight(.medium)
                
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            Spacer()
            
            Image(systemName: "chevron.right")
                .foregroundColor(.gray)
                .font(.caption)
        }
        .padding()
        .background(Color(.systemGray6))
        .cornerRadius(12)
    }
}

// MARK: - 图片选择器
struct ImagePicker: UIViewControllerRepresentable {
    let sourceType: UIImagePickerController.SourceType
    @Binding var selectedImage: UIImage?
    let onComplete: (URL?) -> Void
    @Environment(\.dismiss) private var dismiss
    
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = sourceType
        picker.delegate = context.coordinator
        return picker
    }
    
    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: ImagePicker
        
        init(_ parent: ImagePicker) {
            self.parent = parent
        }
        
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage {
                parent.selectedImage = image
            }
            
            if let imageURL = info[.imageURL] as? URL {
                parent.onComplete(imageURL)
            } else {
                parent.onComplete(nil)
            }
            
            parent.dismiss()
        }
        
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.dismiss()
        }
    }
}

// MARK: - 文档选择器（支持 PDF）
struct DocumentPicker: UIViewControllerRepresentable {
    @Binding var selectedImage: UIImage?
    @Binding var fileName: String
    @Environment(\.dismiss) private var dismiss
    
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let supportedTypes: [UTType] = [.pdf, .image, .jpeg, .png]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: supportedTypes)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        return picker
    }
    
    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let parent: DocumentPicker
        
        init(_ parent: DocumentPicker) {
            self.parent = parent
        }
        
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else {
                parent.dismiss()
                return
            }
            
            parent.fileName = url.lastPathComponent
            
            // 处理 PDF
            if url.pathExtension.lowercased() == "pdf" {
                if let image = convertPDFToImage(url: url) {
                    parent.selectedImage = image
                }
            } else {
                // 图片文件
                if let data = try? Data(contentsOf: url),
                   let image = UIImage(data: data) {
                    parent.selectedImage = image
                }
            }
            
            parent.dismiss()
        }
        
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            parent.dismiss()
        }
        
        private func convertPDFToImage(url: URL) -> UIImage? {
            guard let document = CGPDFDocument(url as CFURL),
                  let page = document.page(at: 1) else {
                return nil
            }
            
            let pageRect = page.getBoxRect(.mediaBox)
            
            // 计算缩放比例，确保宽度至少 2048px
            let targetWidth: CGFloat = 2048
            let scale = max(targetWidth / pageRect.width, 1.0)
            let scaledSize = CGSize(width: pageRect.width * scale, height: pageRect.height * scale)
            
            UIGraphicsBeginImageContextWithOptions(scaledSize, false, 1.0)
            defer { UIGraphicsEndImageContext() }
            
            guard let context = UIGraphicsGetCurrentContext() else { return nil }
            
            context.setFillColor(UIColor.white.cgColor)
            context.fill(CGRect(origin: .zero, size: scaledSize))
            
            context.translateBy(x: 0, y: scaledSize.height)
            context.scaleBy(x: scale, y: -scale)
            
            context.drawPDFPage(page)
            
            return UIGraphicsGetImageFromCurrentImageContext()
        }
    }
}
