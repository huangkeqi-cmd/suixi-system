#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 使用 PyInstaller 生成单文件 exe
"""

import os
import sys
import subprocess
import shutil


def build():
    """打包应用程序"""
    
    # 清理旧构建
    for dir_name in ['build', 'dist']:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    
    # PyInstaller 参数 - 完整版
    args = [
        'pyinstaller',
        '--name=影像管理器',
        '--onefile',
        '--windowed',
        '--clean',
        '--noconfirm',
        'src/main.py'
    ]
    
    print("[开始] 打包完整版...")
    result = subprocess.run(args, capture_output=False, text=True)
    
    if result.returncode != 0:
        print("[失败] 完整版打包失败")
        return False
    
    # PyInstaller 参数 - 简易版
    simple_args = [
        'pyinstaller',
        '--name=影像管理器-简易版',
        '--onefile',
        '--windowed',
        '--clean',
        '--noconfirm',
        'src/simple_main.py'
    ]
    
    print("[开始] 打包简易版...")
    result = subprocess.run(simple_args, capture_output=False, text=True)
    
    if result.returncode != 0:
        print("[失败] 简易版打包失败")
        return False
    
    print("[成功] 打包完成!")
    print(f"输出目录: {os.path.abspath('dist')}")
    return True


def create_distribution():
    """创建最终分发包"""
    
    dist_dir = '影像管理器_分发包'
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    
    os.makedirs(dist_dir)
    
    # 复制 exe
    for exe_name in ['影像管理器.exe', '影像管理器-简易版.exe']:
        src_exe = os.path.join('dist', exe_name)
        if os.path.exists(src_exe):
            shutil.copy2(src_exe, dist_dir)
    
    # 复制文档
    for doc in ['../使用说明.txt', '../THIRD_PARTY_LICENSES.txt']:
        if os.path.exists(doc):
            shutil.copy2(doc, dist_dir)
    
    print(f"[成功] 分发包已创建: {dist_dir}/")


if __name__ == '__main__':
    if build():
        create_distribution()
