/**
 * 随心系统 / Suixin System
 * Copyright (c) 2026 huangkeqi
 * 保留所有权利。
 * 
 * 本软件目前为个人工作流工具，未经授权不得用于商业用途。
 * 商业合作请联系：376524686@qq.com
 */

/**
 * 影像位置采集系统 - 全局配置
 * 可根据项目需求调整以下参数
 */
const CONFIG = {
    // 应用信息
    appName: '随系 · 影像位置采集系统',
    version: '3.0.0',
    
    // 地图与采集
    defaultZoom: 15,
    maxZoom: 20,
    minZoom: 3,
    
    // 照片关联时间容差（秒）
    photoTimeTolerance: 300,
    
    // 平面图加载质量
    floorplanQuality: 0.92,
    
    // 本地存储键前缀
    storagePrefix: 'panorama_capture_',
    
    // 陀螺仪平滑系数（0~1，越大越平滑但延迟越高）
    gyroSmoothAlpha: 0.15,
    
    // 扇形预览默认角度
    defaultSectorAngle: 120,
    
    // 是否默认启用离线模式
    defaultOfflineMode: false
};
