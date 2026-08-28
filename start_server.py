import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8999
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # Allow cross-origin and proper mime types for wasm
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        super().end_headers()

    def guess_type(self, path):
        if path.endswith('.wasm'):
            return 'application/wasm'
        if path.endswith('.mjs') or path.endswith('.js'):
            return 'application/javascript'
        return super().guess_type(path)

print(f"🚀 正在启动音乐播放器音效 DSP 演示服务器...")
print(f"📂 根目录: {DIRECTORY}")
print(f"🔗 服务地址: http://localhost:{PORT}/demos/web_demo.html")

# Open browser
webbrowser.open(f"http://localhost:{PORT}/demos/web_demo.html")

try:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("✅ 服务已就绪！可在浏览器中直接试听与切换音效 (按 Ctrl+C 停止)")
        httpd.serve_forever()
except KeyboardInterrupt:
    print("\n服务已关闭。")
except Exception as e:
    print(f"错误: {e}")
