import asyncio
import json
import threading
import uuid
import socket
from typing import Dict, Any, Optional, Tuple
import websockets

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

class BrowserBridgeServer:
    def __init__(self, host: str = BRIDGE_HOST, port: int = BRIDGE_PORT):
        self.host = host
        self.port = port
        self.websocket_client: Optional[Any] = None
        self.active_tab_info: Optional[Dict[str, Any]] = None
        self.pending_responses: Dict[str, asyncio.Future] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._server = None

    def is_connected(self) -> bool:
        if self.websocket_client is None:
            return False
        if hasattr(self.websocket_client, "closed"):
            return not bool(self.websocket_client.closed)
        state = getattr(self.websocket_client, "state", None)
        if state is not None:
            state_str = getattr(state, "name", str(state)).upper()
            return state_str == "OPEN" or state_str.endswith(".OPEN")
        return True

    def get_status_info(self) -> Tuple[bool, str]:
        if self.is_connected():
            if self.active_tab_info:
                title = self.active_tab_info.get("title", "Active Tab")
                url = self.active_tab_info.get("url", "")
                return True, f"{title} ({url})"
            return True, "Connected (Ready)"
        return False, "Disconnected (Load 'mcp_extension' in chrome://extensions)"

    async def _handle_connection(self, websocket, *args):
        self.websocket_client = websocket
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except Exception:
                    continue

                msg_type = data.get("type")
                if msg_type in ["client_hello", "tab_update"]:
                    if data.get("activeTab"):
                        self.active_tab_info = data.get("activeTab")
                    continue
                elif msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                    continue

                req_id = data.get("id")
                if req_id and req_id in self.pending_responses:
                    fut = self.pending_responses.pop(req_id)
                    if not fut.done():
                        fut.set_result(data)
        except (websockets.exceptions.ConnectionClosed, Exception):
            pass
        finally:
            if self.websocket_client == websocket:
                self.websocket_client = None
                self.active_tab_info = None

    def _run_server(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def start():
            try:
                self._server = await websockets.serve(
                    self._handle_connection,
                    self.host,
                    self.port,
                    ping_interval=20,
                    ping_timeout=20
                )
                self._ready_event.set()
                await self._server.wait_closed()
            except Exception as e:
                self._ready_event.set()

        try:
            self.loop.run_until_complete(start())
        except Exception as e:
            self._ready_event.set()

    def start_background(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=3.0)

    def send_command(self, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 25.0) -> Tuple[int, str, str]:
        if not self.is_connected():
            return 1, "", "Error: Chrome Extension is not connected. Open Chrome, go to chrome://extensions, enable Developer Mode, and click 'Load unpacked' selecting the 'mcp_extension' folder."

        req_id = str(uuid.uuid4())
        payload = {
            "id": req_id,
            "action": action,
            "params": params or {}
        }

        async def _execute():
            future = self.loop.create_future()
            self.pending_responses[req_id] = future
            await self.websocket_client.send(json.dumps(payload))
            try:
                result_data = await asyncio.wait_for(future, timeout=timeout)
                if result_data.get("success"):
                    res = result_data.get("result", {})
                    out_str = json.dumps(res, indent=2) if isinstance(res, (dict, list)) else str(res)
                    return 0, out_str, ""
                else:
                    err_msg = f"Browser Error: {result_data.get('error', 'Execution failed')}"
                    return 1, "", err_msg
            except asyncio.TimeoutError:
                self.pending_responses.pop(req_id, None)
                return 1, "", f"Timeout: Action '{action}' exceeded {timeout}s limit."

        future = asyncio.run_coroutine_threadsafe(_execute(), self.loop)
        try:
            return future.result(timeout=timeout + 2.0)
        except Exception as e:
            return 1, "", f"Bridge communication failure: {e}"

_bridge_instance: Optional[BrowserBridgeServer] = None

def get_browser_bridge() -> BrowserBridgeServer:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = BrowserBridgeServer()
        _bridge_instance.start_background()
    return _bridge_instance

if __name__ == "__main__":
    print(f"[*] Starting standalone BrowserBridgeServer on ws://{BRIDGE_HOST}:{BRIDGE_PORT}...")
    server = get_browser_bridge()
    print("[+] Browser Bridge listening. Load 'mcp_extension' in chrome://extensions.")
    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        print("\n[*] Stopping Browser Bridge.")
