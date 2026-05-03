import Foundation
import CoreBluetooth
import UIKit

// MARK: - 相机管理协议
protocol CameraManagerDelegate: AnyObject {
    func cameraManager(_ manager: CameraManager, didUpdateState state: CameraState)
    func cameraManager(_ manager: CameraManager, didReceiveFileName fileName: String)
    func cameraManager(_ manager: CameraManager, didEncounterError error: CameraError)
}

// MARK: - 相机状态
enum CameraState {
    case disconnected
    case scanning
    case connecting
    case connected(batteryLevel: Int)
    case shooting
}

// MARK: - 相机错误
enum CameraError: Error, LocalizedError {
    case bluetoothUnavailable
    case cameraNotFound
    case connectionFailed
    case shootFailed
    case fileNameTimeout
    case sdkNotAvailable
    
    var errorDescription: String? {
        switch self {
        case .bluetoothUnavailable:
            return "蓝牙不可用，请检查蓝牙是否已开启"
        case .cameraNotFound:
            return "未找到 DJI Osmo 360 相机"
        case .connectionFailed:
            return "连接相机失败，请重试"
        case .shootFailed:
            return "拍摄失败"
        case .fileNameTimeout:
            return "获取文件名超时，请使用手动输入模式"
        case .sdkNotAvailable:
            return "未检测到 DJI SDK，请使用手动输入模式"
        }
    }
}

// MARK: - 相机管理器
class CameraManager: NSObject, ObservableObject {
    @Published var state: CameraState = .disconnected
    @Published var discoveredDevices: [CameraDevice] = []
    @Published var isManualMode: Bool = false
    
    weak var delegate: CameraManagerDelegate?
    
    private var centralManager: CBCentralManager?
    private var cameraPeripheral: CBPeripheral?
    private var fileNameCallback: ((String?) -> Void)?
    private var timeoutTimer: Timer?
    
    // 模拟模式（用于开发测试）
    private let isSimulationMode = false
    
    static let shared = CameraManager()
    
    private override init() {
        super.init()
    }
    
    // MARK: - 公共方法
    
    /// 开始扫描相机
    func startScanning() {
        guard !isManualMode else {
            state = .disconnected
            return
        }
        
        // 检查 DJI SDK 是否可用
        guard isDJISDKAvailable() else {
            state = .disconnected
            delegate?.cameraManager(self, didEncounterError: .sdkNotAvailable)
            return
        }
        
        state = .scanning
        discoveredDevices.removeAll()
        
        // 初始化蓝牙管理器
        centralManager = CBCentralManager(delegate: self, queue: .main)
    }
    
    /// 连接指定相机
    func connect(to device: CameraDevice) {
        guard let peripheral = device.peripheral else { return }
        
        state = .connecting
        centralManager?.connect(peripheral, options: nil)
    }
    
    /// 断开连接
    func disconnect() {
        if let peripheral = cameraPeripheral {
            centralManager?.cancelPeripheralConnection(peripheral)
        }
        cameraPeripheral = nil
        state = .disconnected
    }
    
    /// 拍摄照片
    func shootPhoto(completion: @escaping (String?) -> Void) {
        // 手动模式
        guard !isManualMode else {
            completion(nil)
            return
        }
        
        // 检查连接状态
        guard case .connected = state else {
            completion(nil)
            return
        }
        
        state = .shooting
        fileNameCallback = completion
        
        // 发送拍摄指令
        sendShootCommand()
        
        // 设置超时
        timeoutTimer?.invalidate()
        timeoutTimer = Timer.scheduledTimer(withTimeInterval: 10.0, repeats: false) { [weak self] _ in
            self?.state = .connected(batteryLevel: 100) // 恢复状态
            self?.fileNameCallback?(nil)
            self?.fileNameCallback = nil
            self?.delegate?.cameraManager(self!, didEncounterError: .fileNameTimeout)
        }
    }
    
    /// 切换到手动模式
    func enableManualMode() {
        isManualMode = true
        disconnect()
        state = .disconnected
    }
    
    /// 切换到自动模式
    func disableManualMode() {
        isManualMode = false
    }
    
    // MARK: - 私有方法
    
    private func isDJISDKAvailable() -> Bool {
        // 实际项目中检查 DJI SDK 是否初始化
        // 这里返回 false 表示使用手动模式作为默认
        return false
    }
    
    private func sendShootCommand() {
        // 实际项目中使用 DJI SDK 发送拍摄指令
        // 这里是模拟实现
        
        if isSimulationMode {
            // 模拟拍摄延迟
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak self] in
                guard let self = self else { return }
                
                let dateFormatter = DateFormatter()
                dateFormatter.dateFormat = "yyyyMMdd_HHmmss"
                let fileName = "DJI_\(dateFormatter.string(from: Date())).JPG"
                
                self.state = .connected(batteryLevel: 100)
                self.timeoutTimer?.invalidate()
                self.fileNameCallback?(fileName)
                self.fileNameCallback = nil
                self.delegate?.cameraManager(self, didReceiveFileName: fileName)
            }
        }
    }
}

// MARK: - 相机设备模型
struct CameraDevice: Identifiable {
    let id = UUID()
    let name: String
    let rssi: Int
    var peripheral: CBPeripheral?
}

// MARK: - CBCentralManagerDelegate
extension CameraManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            // 开始扫描 DJI 设备
            central.scanForPeripherals(withServices: nil, options: nil)
        case .poweredOff, .unauthorized, .unsupported:
            state = .disconnected
            delegate?.cameraManager(self, didEncounterError: .bluetoothUnavailable)
        default:
            break
        }
    }
    
    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard let name = peripheral.name else { return }
        
        // 过滤 DJI 设备
        if name.contains("DJI") || name.contains("Osmo") {
            let device = CameraDevice(name: name, rssi: RSSI.intValue, peripheral: peripheral)
            
            if !discoveredDevices.contains(where: { $0.name == name }) {
                discoveredDevices.append(device)
            }
        }
    }
    
    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        cameraPeripheral = peripheral
        cameraPeripheral?.delegate = self
        cameraPeripheral?.discoverServices(nil)
        
        state = .connected(batteryLevel: 100)
        central.stopScan()
    }
    
    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        state = .disconnected
        delegate?.cameraManager(self, didEncounterError: .connectionFailed)
    }
    
    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        cameraPeripheral = nil
        state = .disconnected
        
        // 自动重连
        // startScanning()
    }
}

// MARK: - CBPeripheralDelegate
extension CameraManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let services = peripheral.services else { return }
        
        for service in services {
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }
    
    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        // 处理特征值发现
    }
}
