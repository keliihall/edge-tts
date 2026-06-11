import os
import sys
import webbrowser
import threading
import time
import json
import socket
from urllib.request import urlopen
from urllib.error import URLError
from app import app, run_periodic_cleanup, get_app_temp_dir, load_settings, APP_VERSION

DEFAULT_PORT = 5013

def runtime_state_path():
    return os.path.join(get_app_temp_dir(), "runtime.json")

def can_connect(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False

def health_ok(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False

def read_runtime_state():
    try:
        with open(runtime_state_path(), "r", encoding="utf-8") as state_file:
            return json.load(state_file)
    except (OSError, json.JSONDecodeError):
        return {}

def write_runtime_state(port):
    state = {
        "version": APP_VERSION,
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "pid": os.getpid(),
        "started_at": time.time(),
    }
    with open(runtime_state_path(), "w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)
    return state

def clear_runtime_state():
    """仅清理由当前进程创建的运行状态。"""
    path = runtime_state_path()
    state = read_runtime_state()
    if state.get("pid") != os.getpid():
        return
    try:
        os.unlink(path)
    except OSError:
        pass

def find_available_port(preferred_port=DEFAULT_PORT):
    if not can_connect(preferred_port):
        return preferred_port

    for port in range(preferred_port + 1, preferred_port + 100):
        if not can_connect(port):
            return port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

def open_browser(port):
    """等待服务器启动后打开浏览器"""
    time.sleep(1.5)  # 等待服务器启动
    webbrowser.open(f'http://127.0.0.1:{port}')

def main():
    """主函数"""
    settings = load_settings()

    # 确保在打包后也能找到静态文件和模板
    if getattr(sys, 'frozen', False):
        template_folder = os.path.join(sys._MEIPASS, 'templates')
        static_folder = os.path.join(sys._MEIPASS, 'static')
        app.template_folder = template_folder
        app.static_folder = static_folder

    run_periodic_cleanup(force=True)

    runtime_state = read_runtime_state()
    existing_port = runtime_state.get("port")
    if existing_port and health_ok(existing_port):
        webbrowser.open(runtime_state.get("url", f"http://127.0.0.1:{existing_port}"))
        return

    port = find_available_port(DEFAULT_PORT)
    write_runtime_state(port)

    # 启动浏览器线程
    if settings.get("auto_open_browser", True):
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    
    # 启动 Flask 应用，并在正常退出或中断时清理单实例状态。
    try:
        app.run(host="127.0.0.1", port=port)
    except KeyboardInterrupt:
        pass
    finally:
        clear_runtime_state()

if __name__ == '__main__':
    main() 
