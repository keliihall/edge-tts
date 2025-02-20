import os
import sys
import webbrowser
import threading
import time
from app import app

def open_browser():
    """等待服务器启动后打开浏览器"""
    time.sleep(1.5)  # 等待服务器启动
    webbrowser.open('http://127.0.0.1:5013')

def main():
    """主函数"""
    # 确保在打包后也能找到静态文件和模板
    if getattr(sys, 'frozen', False):
        template_folder = os.path.join(sys._MEIPASS, 'templates')
        static_folder = os.path.join(sys._MEIPASS, 'static')
        app.template_folder = template_folder
        app.static_folder = static_folder

    # 启动浏览器线程
    threading.Thread(target=open_browser, daemon=True).start()
    
    # 启动Flask应用
    app.run(port=5013)

if __name__ == '__main__':
    main() 