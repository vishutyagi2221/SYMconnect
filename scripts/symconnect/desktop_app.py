import os
import sys
import platform

# Monkeypatch platform.machine to fix pywebview ARM64 bug on x64 emulated python
original_machine = platform.machine
def patched_machine():
    m = original_machine()
    if m.lower() in ('arm64', 'aarch64'):
        return 'AMD64'
    return m
platform.machine = patched_machine

if getattr(sys, 'frozen', False):
    os.environ['PYTHONNET_PYDLL'] = os.path.join(sys._MEIPASS, 'python312.dll')
os.environ['PYTHONNET_RUNTIME'] = 'netfx'
import threading
import asyncio
import webview
from symconnect.agent import HostAgent, default_session_id, default_pairing_code, read_server_url_config

class Api:
    def __init__(self, session_id, pairing_code, base_url):
        self.session_id = session_id
        self.pairing_code = pairing_code
        self.base_url = base_url
        self.window = None
        self._status_lock = threading.Lock()
        self._host_status = {
            "state": "connecting",
            "detail": "Connecting to secure server...",
        }

    def attach_window(self, window):
        self.window = window
        
    def get_credentials(self):
        # Called from Javascript via window.pywebview.api.get_credentials()
        return {"id": self.session_id, "pass": self.pairing_code}
        
    def get_server_url(self):
        # Called from Javascript to know where to connect as a viewer
        return self.base_url

    def get_host_status(self):
        with self._status_lock:
            return dict(self._host_status)

    def set_host_status(self, state, detail):
        with self._status_lock:
            self._host_status = {"state": state, "detail": detail}

    def confirm_control_request(self):
        if self.window is None:
            return False
        return self.window.create_confirmation_dialog(
            "Remote control request",
            "A supporter is requesting control of your mouse and keyboard.\n\n"
            "Select OK to allow or Cancel to deny.",
        )

def start_agent(session_id, pairing_code, server_url, api):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        agent = HostAgent(
            server=server_url,
            session_id=session_id,
            pairing_code=pairing_code,
            fps=12,
            monitor=1,
            max_width=1920,
            quality=75,
            control_approval=api.confirm_control_request,
            on_registered=lambda: api.set_host_status(
                "ready",
                "Live session ready - share your ID and password.",
            ),
        )
        loop.run_until_complete(agent.run())
        api.set_host_status("error", "Secure server connection closed.")
    except Exception as e:
        detail = str(e).strip() or type(e).__name__
        api.set_host_status("error", f"Connection failed: {detail}")
    finally:
        loop.close()

def main():
    session_id = default_session_id()
    pairing_code = default_pairing_code()
    
    host_url = read_server_url_config()
    if not host_url:
        host_url = "wss://diabetes-haven-stamp-enhancing.trycloudflare.com/ws/host"
        
    if host_url.startswith("ws"):
        viewer_base_ws = host_url.replace("/ws/host", "")
    else:
        viewer_base_ws = host_url
        
    api = Api(session_id, pairing_code, viewer_base_ws)
    
    import sys
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        html_path = os.path.join(base_path, "symconnect", "static", "index.html")
    else:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(current_dir, "static", "index.html")
        
    file_url = f"file:///{html_path.replace(chr(92), '/')}"
    
    window = webview.create_window(
        "SYMconnect", 
        file_url, 
        js_api=api, 
        width=1100, 
        height=750, 
        min_size=(900, 600),
        background_color='#0a0a0a'
    )
    api.attach_window(window)

    # Start the host after the window exists so control approval can use a native dialog.
    t = threading.Thread(
        target=start_agent,
        args=(session_id, pairing_code, host_url, api),
        daemon=True,
    )
    t.start()

    webview.start()

if __name__ == "__main__":
    main()
