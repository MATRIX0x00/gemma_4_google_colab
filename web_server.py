import os
import sys
import re
import time
import json
import threading
import subprocess
import platform
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, disconnect

from browser_bridge import get_browser_bridge

try:
    import winpty
    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

try:
    import pty
    import tty
    import termios
    import struct
    import fcntl
    UNIX_SYSTEM = True
except ImportError:
    UNIX_SYSTEM = False

app = Flask(__name__)
app.config["SECRET_KEY"] = "matrixcode-opencode-secret-999"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Ensure browser bridge server is actively running in background
browser_bridge = get_browser_bridge()

CONFIG_FILE = "agent_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({k: v for k, v in cfg.items() if k != "active_task"}, f, indent=4)
    except Exception:
        pass

_saved = load_config()

AGENT_CONFIG = {
    "ngrok_url": _saved.get("ngrok_url", os.getenv("NGROK_URL", "").rstrip("/")),
    "auto_approve": _saved.get("auto_approve", True),
    "system_instruction": _saved.get("system_instruction", ""),
    "max_iterations": _saved.get("max_iterations", 50),
    "active_task": None
}

active_terminal_sessions: Dict[str, Any] = {}
active_agent_runs: Dict[str, Dict[str, Any]] = {}
matrix_terminals: Dict[str, Dict[str, Any]] = {}

@app.route("/")
def index():
    return render_template("index.html", config=AGENT_CONFIG)

@app.route("/api/config", methods=["GET", "POST"])
def handle_config():
    if request.method == "POST":
        data = request.json or {}
        if "ngrok_url" in data:
            url = data["ngrok_url"].strip().rstrip("/")
            if url and not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"
            AGENT_CONFIG["ngrok_url"] = url
        if "auto_approve" in data:
            AGENT_CONFIG["auto_approve"] = bool(data["auto_approve"])
        if "system_instruction" in data:
            AGENT_CONFIG["system_instruction"] = str(data["system_instruction"]).strip()
        if "max_iterations" in data:
            AGENT_CONFIG["max_iterations"] = int(data["max_iterations"])
        save_config(AGENT_CONFIG)
        return jsonify({"status": "ok", "config": AGENT_CONFIG})
    return jsonify(AGENT_CONFIG)

@app.route("/api/browser/status", methods=["GET"])
def get_browser_status():
    connected, details = browser_bridge.get_status_info()
    return jsonify({
        "connected": connected,
        "details": details,
        "activeTab": browser_bridge.active_tab_info
    })

@app.route("/api/browser/action", methods=["POST"])
def run_browser_action():
    data = request.json or {}
    action = data.get("action", "").strip()
    params = data.get("params", {})
    if not action:
        return jsonify({"error": "Action required"}), 400
    code, stdout, stderr = browser_bridge.send_command(action, params)
    return jsonify({"status": code, "stdout": stdout, "stderr": stderr})

@app.route("/api/http/test", methods=["POST"])
def test_http_request():
    data = request.json or {}
    method = data.get("method", "GET").upper()
    url = data.get("url", "").strip()
    headers = data.get("headers", {})
    body = data.get("body", "")
    if not url:
        return jsonify({"error": "URL is required"}), 400
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    try:
        start_time = time.time()
        req_headers = {k: v for k, v in headers.items()} if isinstance(headers, dict) else {}
        if "User-Agent" not in req_headers:
            req_headers["User-Agent"] = "MatrixCode-Agent/2.0"
        resp = requests.request(method=method, url=url, headers=req_headers, data=body.encode("utf-8") if body else None, timeout=20, verify=False)
        elapsed = int((time.time() - start_time) * 1000)
        req_text = f"{method} {url}\n" + "\n".join(f"{k}: {v}" for k, v in req_headers.items()) + (f"\n\n{body}" if body else "")
        res_header_lines = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        res_text = f"Status: {resp.status_code} {resp.reason} ({elapsed}ms)\n{res_header_lines}\n\n{resp.text}"
        socketio.emit("matrix_http_event", {
            "raw_request": req_text,
            "output": res_text,
            "status": resp.status_code,
            "elapsed_ms": elapsed,
            "step": "manual"
        })
        return jsonify({"status": resp.status_code, "request": req_text, "response": res_text, "elapsed_ms": elapsed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/files", methods=["GET"])
def list_files():
    dir_path = request.args.get("path", ".").strip()
    try:
        base = Path(dir_path).resolve()
        items = []
        for entry in os.scandir(base):
            if entry.name.startswith(".git") or entry.name == "__pycache__":
                continue
            items.append({
                "name": entry.name,
                "path": str(Path(entry.path).relative_to(Path.cwd()) if Path(entry.path).is_relative_to(Path.cwd()) else entry.path),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if not entry.is_dir() else 0
            })
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return jsonify({"path": str(base), "files": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/file/read", methods=["GET"])
def read_file():
    fpath = request.args.get("path", "").strip()
    if not fpath:
        return jsonify({"error": "Path required"}), 400
    try:
        target = Path(fpath).resolve()
        content = target.read_text(encoding="utf-8", errors="replace")
        return jsonify({"path": str(target), "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/file/save", methods=["POST"])
def save_file():
    data = request.json or {}
    fpath = data.get("path", "").strip()
    content = data.get("content", "")
    if not fpath:
        return jsonify({"error": "Path required"}), 400
    try:
        target = Path(fpath).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return jsonify({"status": "ok", "message": f"Saved {target.name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/file/create", methods=["POST"])
def create_file():
    data = request.json or {}
    fpath = data.get("path", "").strip()
    if not fpath:
        return jsonify({"error": "Path required"}), 400
    try:
        target = Path(fpath).resolve()
        if target.exists():
            return jsonify({"error": "File or directory already exists"}), 400
        if data.get("is_dir"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        return jsonify({"status": "ok", "message": f"Created {target.name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/file/delete", methods=["POST"])
def delete_file():
    data = request.json or {}
    fpath = data.get("path", "").strip()
    if not fpath:
        return jsonify({"error": "Path required"}), 400
    try:
        target = Path(fpath).resolve()
        if not target.exists():
            return jsonify({"error": "File does not exist"}), 404
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()
        return jsonify({"status": "ok", "message": f"Deleted {target.name}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@socketio.on("terminal_init")
def handle_terminal_init(data=None):
    sid = request.sid
    data = data or {}
    cols = int(data.get("cols", 80))
    rows = int(data.get("rows", 24))
    is_windows = platform.system() == "Windows"

    if is_windows and HAS_WINPTY:
        try:
            pty = winpty.PtyProcess.spawn(
                ["powershell.exe", "-NoLogo", "-ExecutionPolicy", "Bypass"],
                dimensions=(rows, cols)
            )
            active_terminal_sessions[sid] = {"type": "pty", "proc": pty}

            def read_winpty():
                while True:
                    try:
                        if not pty.isalive():
                            break
                        chunk = pty.read(1024)
                        if chunk:
                            socketio.emit("terminal_output", {"data": chunk}, room=sid)
                        else:
                            time.sleep(0.01)
                    except Exception:
                        break

            t = threading.Thread(target=read_winpty, daemon=True)
            t.start()
            socketio.emit("terminal_output", {"data": "\r\n\x1b[32m[+] ConPTY Windows Interactive Session Connected\x1b[0m\r\n"}, room=sid)
            return
        except Exception as e:
            print(f"WinPTY initialization fallback: {e}")

    cmd = ["powershell.exe", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass"] if is_windows else [os.environ.get("SHELL", "/bin/bash"), "-i"]
    env = os.environ.copy()
    if is_windows:
        env["PYTHONIOENCODING"] = "utf-8"

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env
        )
        active_terminal_sessions[sid] = {"type": "pipe", "proc": proc}

        def read_pipe():
            decoder = "utf-8"
            while True:
                try:
                    if proc.poll() is not None:
                        break
                    raw_chunk = proc.stdout.read(1024)
                    if not raw_chunk:
                        time.sleep(0.01)
                        continue
                    text = raw_chunk.decode(decoder, errors="replace")
                    text = re.sub(r"(?<!\r)\n", "\r\n", text)
                    socketio.emit("terminal_output", {"data": text}, room=sid)
                except Exception:
                    break

        t = threading.Thread(target=read_pipe, daemon=True)
        t.start()
        socketio.emit("terminal_output", {"data": f"\r\n\x1b[32m[+] Interactive Session Connected ({platform.system()})\x1b[0m\r\n"}, room=sid)
    except Exception as e:
        socketio.emit("terminal_output", {"data": f"\r\n[Error initializing terminal: {e}]\r\n"}, room=sid)

@socketio.on("terminal_input")
def handle_terminal_input(data):
    sid = request.sid
    session = active_terminal_sessions.get(sid)
    if not session:
        return
    inp = data.get("input", "")
    if not inp:
        return

    sess_type = session.get("type")
    proc = session.get("proc")

    if sess_type == "pty" and proc:
        try:
            proc.write(inp)
        except Exception:
            pass
    elif sess_type == "pipe" and proc and proc.stdin and proc.poll() is None:
        try:
            proc.stdin.write(inp.encode("utf-8", errors="replace"))
            proc.stdin.flush()
        except Exception:
            pass

def read_matrix_process(term_id, process):
    """Character-by-character real-time streaming for cmd.exe sessions."""
    while process.poll() is None:
        try:
            char = process.stdout.read(1)
            if char:
                socketio.emit('matrix_term_output', {'term_id': term_id, 'data': char.decode('utf-8', errors='ignore')})
            else:
                time.sleep(0.01)
        except Exception:
            break

def read_matrix_pty(term_id, master_fd):
    """Reads data from Unix PTY and sends to client."""
    while True:
        try:
            data = os.read(master_fd, 1024)
            if data:
                socketio.emit('matrix_term_output', {'term_id': term_id, 'data': data.decode('utf-8', errors='ignore')})
            else:
                break
        except Exception:
            break

@socketio.on("matrix_term_create")
def handle_matrix_term_create(data=None):
    sid = request.sid
    data = data or {}
    term_id = data.get("term_id") or f"term_{int(time.time()*1000)%100000}"
    term_name = data.get("name") or f"cmd-{len(matrix_terminals) + 1}"

    if UNIX_SYSTEM:
        master_fd, slave_fd = pty.openpty()
        env = dict(os.environ, TERM='xterm-256color', PYTHONUNBUFFERED='1')
        shell_process = subprocess.Popen(
            ['/bin/bash'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            universal_newlines=True,
            env=env
        )
        reader_thread = threading.Thread(target=read_matrix_pty, args=(term_id, master_fd))
        reader_thread.daemon = True
        reader_thread.start()

        matrix_terminals[term_id] = {
            'type': 'pty',
            'master_fd': master_fd,
            'slave_fd': slave_fd,
            'process': shell_process,
            'reader_thread': reader_thread,
            'name': term_name,
            'sid': sid
        }
    else:
        # Windows interactive cmd.exe identical to tabbed web terminal engine
        shell_process = subprocess.Popen(
            ['cmd.exe'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=False,
            bufsize=0,
            env=dict(os.environ, PYTHONUNBUFFERED='1')
        )
        reader_thread = threading.Thread(target=read_matrix_process, args=(term_id, shell_process))
        reader_thread.daemon = True
        reader_thread.start()

        matrix_terminals[term_id] = {
            'type': 'cmd',
            'process': shell_process,
            'reader_thread': reader_thread,
            'name': term_name,
            'sid': sid,
            'buffer': '',
            'has_set_encoding': False,
            'in_interactive_mode': False,
            'interactive_process': None,
            'interactive_reader_thread': None
        }

    socketio.emit("matrix_term_created", {"term_id": term_id, "name": term_name})

@socketio.on("matrix_term_input")
def handle_matrix_term_input(data):
    term_id = data.get("term_id")
    command_char = data.get("input", "")
    session = matrix_terminals.get(term_id)
    if not session or not command_char:
        return

    if session.get('type') == 'pty' and session.get('master_fd'):
        try:
            os.write(session['master_fd'], command_char.encode('utf-8'))
        except Exception:
            pass
        return

    shell_process = session.get('process')
    if not shell_process or not shell_process.stdin:
        return

    try:
        # Handle interactive mode (e.g. Python CLI interpreter inside cmd)
        if session.get('in_interactive_mode'):
            int_proc = session.get('interactive_process')
            if int_proc and int_proc.stdin:
                try:
                    int_proc.stdin.write(command_char.encode('utf-8'))
                    int_proc.stdin.flush()
                    if session['buffer'].strip() == 'exit()' and command_char == '\r':
                        int_proc.terminate()
                        session['in_interactive_mode'] = False
                        session['interactive_process'] = None
                        session['interactive_reader_thread'] = None
                        session['buffer'] = ''
                except OSError:
                    session['in_interactive_mode'] = False
                    session['interactive_process'] = None
                    session['interactive_reader_thread'] = None
                    session['buffer'] = ''
                finally:
                    if command_char != '\r':
                        session['buffer'] += command_char
                    else:
                        session['buffer'] = ''
            return

        # Backspace handling
        if command_char == '\x7f' or command_char == '\b':
            if len(session['buffer']) > 0:
                session['buffer'] = session['buffer'][:-1]
                socketio.emit('matrix_term_output', {'term_id': term_id, 'data': '\b \b'})
        elif command_char == '\r':
            socketio.emit('matrix_term_output', {'term_id': term_id, 'data': '\r\n'})
            command_to_execute = session['buffer'].strip()

            # Handle cls screen clearing
            if command_to_execute.lower() == 'cls':
                socketio.emit('matrix_term_output', {'term_id': term_id, 'data': '\x1bc'})
                session['buffer'] = ''
                return

            # Handle python interactive mode
            if command_to_execute.lower().startswith('python'):
                try:
                    python_process = subprocess.Popen(
                        ['python'],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        universal_newlines=False,
                        bufsize=0
                    )
                    session['in_interactive_mode'] = True
                    session['interactive_process'] = python_process
                    session['interactive_reader_thread'] = threading.Thread(target=read_matrix_process, args=(term_id, python_process))
                    session['interactive_reader_thread'].daemon = True
                    session['interactive_reader_thread'].start()
                    session['buffer'] = ''
                except FileNotFoundError:
                    socketio.emit('matrix_term_output', {'term_id': term_id, 'data': 'Error: Python interpreter not found.\r\n'})
                    session['buffer'] = ''
                return

            if not session['has_set_encoding']:
                shell_process.stdin.write(b'chcp 65001\n')
                shell_process.stdin.flush()
                session['has_set_encoding'] = True

            full_command_bytes = (command_to_execute + '\n').encode('utf-8')
            shell_process.stdin.write(full_command_bytes)
            shell_process.stdin.flush()
            session['buffer'] = ''
        else:
            session['buffer'] += command_char
            socketio.emit('matrix_term_output', {'term_id': term_id, 'data': command_char})
    except OSError:
        pass

@socketio.on("matrix_term_resize")
def handle_matrix_term_resize(data):
    term_id = data.get("term_id")
    cols = int(data.get("cols", 80))
    rows = int(data.get("rows", 24))
    session = matrix_terminals.get(term_id)
    if UNIX_SYSTEM and session and session.get('type') == 'pty' and session.get('master_fd'):
        try:
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(session['master_fd'], termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

@socketio.on("matrix_term_close")
def handle_matrix_term_close(data):
    term_id = data.get("term_id")
    session = matrix_terminals.pop(term_id, None)
    if session:
        if session.get('type') == 'pty':
            try:
                os.close(session.get('master_fd'))
                os.close(session.get('slave_fd'))
            except Exception:
                pass
        proc = session.get("process")
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        int_proc = session.get("interactive_process")
        if int_proc and int_proc.poll() is None:
            try:
                int_proc.terminate()
            except Exception:
                pass
        socketio.emit("matrix_term_closed", {"term_id": term_id})

@socketio.on("terminal_resize")
def handle_terminal_resize(data):
    sid = request.sid
    session = active_terminal_sessions.get(sid)
    if not session:
        return
    cols = int(data.get("cols", 80))
    rows = int(data.get("rows", 24))
    if session.get("type") == "pty":
        try:
            session["proc"].set_size(rows, cols)
        except Exception:
            pass

@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    if sid in active_agent_runs:
        active_agent_runs[sid]["cancel"] = True
        active_agent_runs.pop(sid, None)
    session = active_terminal_sessions.pop(sid, None)
    if session:
        proc = session.get("proc")
        try:
            if session.get("type") == "pty":
                proc.close()
            elif proc:
                proc.terminate()
        except Exception:
            pass

@socketio.on("cancel_agent_task")
def handle_cancel_agent_task():
    sid = request.sid
    if sid in active_agent_runs:
        active_agent_runs[sid]["cancel"] = True
        socketio.emit("agent_status", {"status": "cancelled", "message": "Task canceled by user."}, room=sid)

@socketio.on("agent_user_guidance")
def handle_agent_guidance(data):
    sid = request.sid
    text = data.get("guidance", "").strip()
    if sid in active_agent_runs and text:
        active_agent_runs[sid]["guidance_queue"].append(text)
        socketio.emit("agent_status", {"status": "guidance_received", "message": f"Guidance queued: {text}"}, room=sid)

@socketio.on("agent_action_decision")
def handle_agent_action_decision(data):
    sid = request.sid
    approval_id = data.get("approval_id")
    approved = bool(data.get("approved", True))
    run_state = active_agent_runs.get(sid)
    if not run_state:
        for s_id, r_state in active_agent_runs.items():
            if approval_id in r_state.get("pending_approvals", {}):
                run_state = r_state
                break
    if run_state:
        pending = run_state.get("pending_approvals", {})
        if approval_id in pending:
            pending[approval_id]["decision"] = approved
            pending[approval_id]["event"].set()

@socketio.on("start_agent_task")
def handle_agent_task(data):
    goal = data.get("goal", "").strip()
    if not goal:
        return
    sid = request.sid

    run_state = {
        "cancel": False,
        "guidance_queue": [],
        "pending_approvals": {},
        "active": True
    }
    active_agent_runs[sid] = run_state

    def run_agent_loop():
        try:
            from terminal import TerminalAgent
            custom_prompt = AGENT_CONFIG.get("system_instruction", "").strip()
            auto_appr = bool(AGENT_CONFIG.get("auto_approve", True))
            agent = TerminalAgent(
                mode="remote",
                api_url=AGENT_CONFIG.get("ngrok_url") or None,
                auto_approve=True,
                max_iterations=AGENT_CONFIG.get("max_iterations", 50),
                custom_system_prompt=custom_prompt or None
            )
            socketio.emit("agent_status", {"status": "running", "message": f"Task started: {goal}"}, room=sid)

            messages = [
                {"role": "system", "content": agent.get_system_prompt()},
                {"role": "user", "content": f"Goal: {goal}"}
            ]

            for step in range(1, agent.max_iterations + 1):
                if run_state.get("cancel"):
                    socketio.emit("agent_status", {"status": "stopped", "message": "Agent execution halted."}, room=sid)
                    break
                if run_state.get("cancel"):
                    socketio.emit("agent_status", {"status": "stopped", "message": "Agent execution halted."}, room=sid)
                    break

                while run_state["guidance_queue"]:
                    user_guide = run_state["guidance_queue"].pop(0)
                    messages.append({"role": "user", "content": f"User steering input: {user_guide}"})
                    socketio.emit("agent_steer_injected", {"guidance": user_guide}, room=sid)

                socketio.emit("agent_status", {"status": "thinking", "step": step, "message": f"Step {step}/{agent.max_iterations}: Reasoning..."}, room=sid)

                stream_buffer = []
                def stream_callback(token_chunk):
                    if run_state.get("cancel"):
                        return
                    stream_buffer.append(token_chunk)
                    socketio.emit("agent_stream_token", {"step": step, "chunk": token_chunk}, room=sid)

                reply = ""
                safe_messages = agent.prune_history(messages)
                chat_url = f"{agent.api_url}/chat"
                payload = {
                    "messages": safe_messages,
                    "max_tokens": 2048,
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "stream": True
                }
                try:
                    with requests.post(chat_url, json=payload, stream=True, timeout=180) as r:
                        if r.status_code == 200:
                            filter_state = {"buffer": ""}
                            for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                                if run_state.get("cancel"):
                                    break
                                if chunk:
                                    reply += chunk
                                    clean_token = agent._stream_filter(chunk, filter_state)
                                    if clean_token:
                                        stream_callback(clean_token)
                            if filter_state["buffer"]:
                                tail = re.sub(r"<\|?[^>]+?\|>", "", filter_state["buffer"])
                                if tail:
                                    stream_callback(tail)
                        else:
                            reply = f"Server Error: HTTP {r.status_code}"
                            stream_callback(reply)
                except Exception as e:
                    reply = f"Connection Error: {e}"
                    stream_callback(reply)

                clean_full = re.sub(r"<\|?channel\|?>?(?:thought)?|<channel\|>|<\|?[^>]*thought[^>]*\|>", "", reply, flags=re.IGNORECASE).strip()
                messages.append({"role": "assistant", "content": clean_full})
                socketio.emit("agent_thought_complete", {"step": step, "full_text": clean_full}, room=sid)

                if run_state.get("cancel"):
                    socketio.emit("agent_status", {"status": "stopped", "message": "Halted by user."}, room=sid)
                    break

                actions = agent.extract_actions(clean_full)
                if not actions:
                    summary = clean_full
                    if "TASK_COMPLETED:" in clean_full:
                        parts = clean_full.split("TASK_COMPLETED:", 1)
                        before_text = parts[0].strip()
                        after_text = parts[1].strip()
                        if before_text and after_text:
                            summary = f"{before_text}\n\n🎯 Verified & Completed: {after_text}"
                        elif after_text:
                            summary = after_text
                        elif before_text:
                            summary = before_text
                    socketio.emit("agent_final_response", {"step": step, "content": summary}, room=sid)
                    socketio.emit("agent_status", {"status": "completed", "message": "Response delivered."}, room=sid)
                    break

                all_obs = []
                for act_idx, act in enumerate(actions, 1):
                    if run_state.get("cancel"):
                        break

                    if not auto_appr:
                        approval_id = f"appr_{step}_{act_idx}_{int(time.time()*1000)}"
                        event = threading.Event()
                        run_state["pending_approvals"][approval_id] = {"event": event, "decision": None}
                        socketio.emit("agent_action_approval_request", {
                            "approval_id": approval_id,
                            "step": step,
                            "action_num": act_idx,
                            "total_actions": len(actions),
                            "action": act.action_type,
                            "target": act.target,
                            "payload": act.payload
                        }, room=sid)

                        event.wait(timeout=300)
                        decision = run_state["pending_approvals"].pop(approval_id, {}).get("decision", False)
                        if run_state.get("cancel"):
                            break
                        if not decision:
                            obs = f"Action '{act.action_type}' rejected by user. Please reconsider or propose an alternative path."
                            all_obs.append(obs)
                            socketio.emit("agent_action_result", {
                                "step": step,
                                "action_num": act_idx,
                                "action": act.action_type,
                                "status": 1,
                                "output": "[Action rejected by user]"
                            }, room=sid)
                            continue

                    socketio.emit("agent_action", {
                        "step": step,
                        "action_num": act_idx,
                        "total_actions": len(actions),
                        "action": act.action_type,
                        "target": act.target,
                        "payload": act.payload
                    }, room=sid)

                    if act.action_type in ["file_write", "file_append", "file_read", "file_patch"]:
                        code, stdout, stderr = agent.execute_file_action(act)
                    elif act.action_type == "http_request":
                        # Mirror into matrix terminals visual log
                        for tid, _ in matrix_terminals.items():
                            socketio.emit("matrix_term_output", {"term_id": tid, "data": f"\r\n\x1b[36m[HTTP Agent Request Step {step}]\x1b[0m\r\n"})
                        code, stdout, stderr = agent.execute_http_action(act)
                        socketio.emit("matrix_http_event", {
                            "raw_request": act.payload,
                            "output": stdout or stderr,
                            "status": code,
                            "step": step
                        })
                    elif act.action_type.startswith("term_") or act.action_type.startswith("termux_") or act.action_type.startswith("cmd_"):
                        target_tid = act.target or (list(matrix_terminals.keys())[0] if matrix_terminals else None)
                        if target_tid and target_tid in matrix_terminals:
                            m_sess = matrix_terminals[target_tid]
                            cmd_payload = act.payload + "\n"
                            socketio.emit("matrix_term_output", {"term_id": target_tid, "data": f"\r\n\x1b[33m{m_sess.get('name', 'cmd')}> {act.payload}\x1b[0m\r\n"})
                            if m_sess.get("type") == "pty" and m_sess.get("master_fd"):
                                os.write(m_sess["master_fd"], cmd_payload.encode("utf-8"))
                            elif m_sess.get("process") and m_sess["process"].stdin:
                                m_sess["process"].stdin.write(cmd_payload.encode("utf-8"))
                                m_sess["process"].stdin.flush()
                            code = 0
                            stdout = f"Dispatched to CMD console: {m_sess.get('name', target_tid)}"
                            stderr = ""
                        else:
                            is_ps = platform.system() == "Windows"
                            code, stdout, stderr, _ = agent.execute_command(act.payload, use_powershell=is_ps)
                    elif act.action_type.startswith("browser_"):
                        code, stdout, stderr = agent.execute_browser_action(act)
                    else:
                        is_ps = act.action_type == "powershell"
                        # Stream command invocation directly to live Matrix terminals
                        for tid, _ in matrix_terminals.items():
                            socketio.emit("matrix_term_output", {"term_id": tid, "data": f"\r\n\x1b[32m[Agent Executing Step {step}] $ {act.payload}\x1b[0m\r\n"})

                        def stream_term_chunk(chunk):
                            for tid, _ in matrix_terminals.items():
                                socketio.emit("matrix_term_output", {"term_id": tid, "data": chunk})
                            socketio.emit("agent_action_stream", {
                                "step": step,
                                "action_num": act_idx,
                                "chunk": chunk
                            }, room=sid)

                        code, stdout, stderr, _ = agent.execute_command(act.payload, use_powershell=is_ps, output_callback=stream_term_chunk)

                        # Auto-extract CTF flag if present in output
                        flag_match = re.search(r"(?:flag\{[^\}]+\}|ctf\{[^\}]+\}|picoCTF\{[^\}]+\}|HTB\{[^\}]+\})", (stdout or ""), re.IGNORECASE)
                        if flag_match:
                            flag_str = flag_match.group(0)
                            for tid, _ in matrix_terminals.items():
                                socketio.emit("matrix_term_output", {"term_id": tid, "data": f"\r\n\x1b[35m[+] CTF FLAG CAPTURED: {flag_str}\x1b[0m\r\n"})

                        # Check if command was curl / http-like to auto-populate the HTTP inspector
                        if "curl " in act.payload.lower() or "http" in act.payload.lower():
                            socketio.emit("matrix_http_event", {
                                "raw_request": act.payload,
                                "output": stdout or stderr,
                                "status": code,
                                "step": step
                            })

                    if stdout and stderr:
                        out_content = f"{stdout}\nSTDERR:\n{stderr}"
                    else:
                        out_content = stdout or stderr or "(Command completed with exit code 0 and no output)"
                    if len(out_content) > 2000:
                        out_content = out_content[:900] + "\n...[truncated output]...\n" + out_content[-900:]
                    obs = f"Status: {code}\nOutput: {out_content}"
                    all_obs.append(obs)
                    socketio.emit("agent_action_result", {
                        "step": step,
                        "action_num": act_idx,
                        "action": act.action_type,
                        "status": code,
                        "output": out_content
                    }, room=sid)

                if run_state.get("cancel"):
                    socketio.emit("agent_status", {"status": "stopped", "message": "Stopped prior to next iteration."}, room=sid)
                    break

                messages.append({"role": "user", "content": "Execution Observation:\n" + "\n---\n".join(all_obs)})
                time.sleep(0.3)
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = f"Agent execution exception: {str(e)}"
            socketio.emit("agent_final_response", {"step": 0, "content": err_msg}, room=sid)
            socketio.emit("agent_status", {"status": "finished", "message": err_msg}, room=sid)
        finally:
            active_agent_runs.pop(sid, None)
            socketio.emit("agent_status", {"status": "finished", "message": "Session finished."}, room=sid)

    t = threading.Thread(target=run_agent_loop, daemon=True)
    t.start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenCode Web Studio")
    parser.add_argument("--port", type=int, default=5000, help="HTTP Port to run web server on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface to bind to")
    parser.add_argument("--url", type=str, default="", help="Initial ngrok GGUF endpoint URL")
    args = parser.parse_args()

    if args.url:
        AGENT_CONFIG["ngrok_url"] = args.url.strip().rstrip("/")
        save_config(AGENT_CONFIG)

    print(f"\n[+] Browser Bridge WebSocket active on ws://127.0.0.1:8765")
    print(f"[+] OpenCode Web Studio running on http://{args.host}:{args.port}")
    socketio.run(app, host=args.host, port=args.port, allow_unsafe_werkzeug=True)
