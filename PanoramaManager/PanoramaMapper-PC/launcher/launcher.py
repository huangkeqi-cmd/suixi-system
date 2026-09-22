#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""随系 · 独立查看包启动器（预编译源码）

由根目录 一键打包exe.bat 用 PyInstaller 预编译为「双击查看.exe」，
并作为资源内嵌进影像管理器 exe，供导出独立查看包时直接复制。

注意：本文件必须与 src/main.py 中的 LAUNCHER_PY_CODE 常量保持同步！
"""
import os
import sys
import webbrowser
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler


class SilentHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志，避免 noconsole 模式下 stderr 为 None 导致崩溃


def main():
    # 获取程序所在目录（兼容 PyInstaller --onefile，此时 __file__ 指向临时目录）
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # 数据文件统一放在 viewer 子文件夹中
    data_dir = os.path.join(base_dir, 'viewer')
    os.chdir(data_dir)

    # 确保 stdout/stderr 不为 None（避免 SimpleHTTPRequestHandler 在 noconsole 模式崩溃）
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')

    # 启动服务器（自动分配端口，避免冲突）
    server = HTTPServer(('127.0.0.1', 0), SilentHandler)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{actual_port}/index.html"
    print("=" * 50)
    print("  随系 · 独立查看包")
    print("=" * 50)
    print(f"  服务地址: {url}")
    print("  正在自动打开浏览器...")
    print("=" * 50)
    webbrowser.open(url)

    # 保持进程运行（兼容 --noconsole 模式）
    try:
        input("\n  服务运行中，关闭此窗口或按回车键停止服务...")
    except (EOFError, RuntimeError):
        import time
        while True:
            time.sleep(3600)
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
