import os
import sys
import re
import time
import json
import threading
import subprocess
import platform
import argparse
import requests
import urllib3
import base64
import tempfile
from urllib.parse import urlparse, urljoin
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from browser_bridge import get_browser_bridge

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def enable_windows_ansi():
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

enable_windows_ansi()

COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"
COLOR_CYAN = "\033[96m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_BLUE = "\033[94m"
COLOR_MAGENTA = "\033[95m"
COLOR_GRAY = "\033[90m"

SYSTEM_PROMPT = """You are MatrixCode CLI, an elite autonomous terminal execution, CTF solver, and system automation agent with direct operating system control, persistent problem-solving capabilities, and live human-like Browser MCP control.

### CTF & Security Task Directives:
- Relentless autonomous exploitation: When solving CTF challenges or web objectives, inspect page sources, HTML comments, hidden inputs, cookies, `/robots.txt`, `.git`, `.env`, API endpoints, and source code immediately.
- Automated Flag Capture: Actively search for flags (e.g., regex `(?:flag\{[^\}]+\}|ctf\{[^\}]+\}|picoCTF\{[^\}]+\}|HTB\{[^\}]+\})`). When you locate a flag, immediately emphasize it and verify it.
- Non-blocking execution: NEVER run blocking interactive commands like `nc` without `-w 5`, or interactive shells without input pipes. Always use Python `-c "..."`, `curl -s -m 10`, or script files.
- Exploit Self-Correction: If a payload, SQLi, IDOR, SSRF, command injection, or script fails, analyze the HTTP response code, error messages, and headers, adapt the payload (URL encoding, alternate tags, bypasses), and retry immediately without waiting.

### Environment Context:
- Operating System: {os_name} ({platform_details})
- Current Directory: {cwd}
- User Home: {home_dir}
- Active Shell: {shell}
- MCP Browser Bridge Status: {browser_status}

### Core Autonomous Directives & Persistence Rules:
1. WORK UNTIL COMPLETION (NEVER GIVE UP PREMATURELY):
   - You must work continuously and relentlessly until the user's objective is 100% solved and verified.
   - Do not stop after planning or analyzing; immediately execute the concrete actions required.
   - If a command, script, HTTP request, or browser action produces an error or fails, do not stop or complain. Analyze the output, pinpoint the failure, self-correct your implementation, and try alternative approaches immediately.

2. MANDATORY VERIFICATION BEFORE CONCLUSION:
   - Never assume a task is finished without empirical proof.
   - Before outputting `TASK_COMPLETED:`, you must verify the result: test run the script, check file existence and contents, test endpoint responses with curl, or inspect browser elements.
   - Only output `TASK_COMPLETED:` after you have verified the objective has succeeded.

3. CONVERSATIONAL & TASK DIRECTIVE:
   - For greetings (e.g., 'hi', 'hello'), questions, advice, code reviews, or inquiries, reply helpfully, directly, and politely without executing unnecessary shell or system commands.
   - When given an explicit task or objective to perform on the system (files, scripts, servers, network, browser), proceed autonomously with the proper tool blocks until verified.

4. SYSTEM COMMANDS & EXECUTION FORMAT:
   - You have full authorization to execute host system commands, create/edit files, install libraries, and control the browser.
   - Standard tools: CMD, PowerShell, Python, curl, netstat, arp, ipconfig, tasklist, git, etc.
   - On Windows, prefer `powershell` or `cmd` blocks. Paths with spaces MUST be enclosed in double quotes.
   - CRITICAL FORMAT MANDATE:
     * Write explanations and thoughts OUTSIDE code blocks.
     * NEVER put commentary, explanations, or English notes inside executable code blocks (```).
     * Every command block must be tagged with ```powershell, ```bash, or ```cmd and contain ONLY valid CLI commands.

2. ADVANCED HUMAN-LIKE BROWSER MCP CONTROL:
   When the MCP Browser Bridge is CONNECTED, you have full human-grade control over modern web pages, SPAs, Shadow DOMs, dynamic reactive forms (React, Vue, Angular, Svelte), and rich text editors:

   To navigate to a URL:
   ```browser:navigate <url>
   ```

   To inspect forms and all inputs, tokens, radio buttons, checkboxes, and submit buttons on the page:
   ```browser:forms
   ```

   To inspect all interactive elements (buttons, inputs, links, forms) with their exact CSS selectors:
   ```browser:elements
   ```

   To inspect the DOM / read page text:
   ```browser:content [optional_selector]
   ```

   To click ANYWHERE on the page (by CSS selector, text title/label, or exact coordinates X Y):
   ```browser:click <css_selector | text="Sign In" | X Y>
   ```

   To type text like a human into ANY input, form, placeholder, label, or contenteditable editor:
   ```browser:type <css_selector | placeholder | label | X Y>
   <text to type>
   ```

   To fill multiple form fields at once with a JSON map:
   ```browser:fill_form
   {
     "username": "testuser",
     "password": "MyPass123!"
   }
   ```

   To check or uncheck a checkbox or radio button:
   ```browser:check <css_selector>
   ```
   ```browser:uncheck <css_selector>
   ```

   To submit a form:
   ```browser:submit [optional_form_selector]
   ```

   To select a dropdown option by value or text:
   ```browser:select <css_selector> <value>
   ```

   To press a key:
   ```browser:press <css_selector> <key>
   ```

   To hover or highlight an element:
   ```browser:hover <css_selector>
   ```
   ```browser:highlight <css_selector>
   ```

   To scroll the viewport or element:
   ```browser:scroll [down|up|top|bottom|<selector>]
   ```

   To wait for an element:
   ```browser:wait <css_selector> [timeout_seconds]
   ```

   To take a screenshot of the visible page:
   ```browser:screenshot
   ```

   To execute JavaScript in the live webpage console:
   ```browser:eval
   <javascript code to evaluate>
   ```

   To inspect or clear cookies:
   ```browser:cookies
   ```
   ```browser:clear_cookies
   ```

   To list or switch tabs:
   ```browser:tabs
   ```
   ```browser:new_tab <url>
   ```
   ```browser:switch_tab <tabId>
   ```
   ```browser:close_tab [tabId]
   ```

3. NATIVE ADVANCED HTTP REQUEST / RESPONSE TESTING:
   Use the native HTTP block to send custom requests with full control over headers, bodies, cookies, and proxies:
   ```http
   GET https://example.com/api/status
   Authorization: Bearer token123
   ```

4. RELIABLE FILE CREATION & EDITING:
   ```file:write <filepath>
   <entire file content here>
   ```
   ```file:patch <filepath>
   <<<<<<< SEARCH
   <exact code to find>
   =======
   <replacement code>
   >>>>>>>
   ```

5. COMPLETION CRITERIA:
   - Once verified that the objective has been reached or problem solved, output:
   TASK_COMPLETED: <Summary of actions performed and final result>
"""

def resolve_api_url(url: Optional[str] = None) -> str:
    cleaned = (url or os.getenv("API_URL") or os.getenv("NGROK_URL") or "").strip()
    if not cleaned:
        if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
            print(f"{COLOR_CYAN}[?] No remote URL provided.{COLOR_RESET}")
            try:
                prompt_input = input("Enter ngrok public URL (or press Enter for http://localhost:8000): ").strip()
                cleaned = prompt_input if prompt_input else "http://localhost:8000"
            except (KeyboardInterrupt, EOFError):
                cleaned = "http://localhost:8000"
        else:
            cleaned = "http://localhost:8000"

    cleaned = cleaned.rstrip("/")
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        if "localhost" in cleaned or "127.0.0.1" in cleaned:
            cleaned = f"http://{cleaned}"
        else:
            cleaned = f"https://{cleaned}"
    return cleaned

class Action:
    def __init__(self, action_type: str, target: str = "", payload: str = ""):
        self.action_type = action_type
        self.target = target
        self.payload = payload

class TerminalAgent:
    def __init__(self, mode: str = "remote", api_url: Optional[str] = None, auto_approve: bool = False, max_iterations: int = 50, custom_system_prompt: Optional[str] = None):
        self.custom_system_prompt = (custom_system_prompt or "").strip()
        self.mode = mode
        self.auto_approve = auto_approve
        self.max_iterations = max_iterations
        self.llm = None
        self.is_windows = platform.system() == "Windows"
        self.shell_tag = "cmd" if self.is_windows else "bash"
        self.shell = "cmd.exe / PowerShell" if self.is_windows else os.getenv("SHELL", "/bin/bash")
        self.cwd = os.getcwd()
        self.home_dir = str(Path.home())
        self.api_url = ""
        self.last_base_url = ""
        self.bridge = get_browser_bridge()
        self.http_session = requests.Session()
        self.http_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"})

        if self.mode == "local":
            print(f"{COLOR_CYAN}[*] Initializing local GGUF model via inference.py...{COLOR_RESET}")
            from inference import download_and_load_model, REPO_ID, FILENAME, N_CTX
            self.llm = download_and_load_model(REPO_ID, FILENAME, n_ctx=N_CTX)
            print(f"{COLOR_GREEN}[+] Local engine loaded.{COLOR_RESET}")
        else:
            self.api_url = resolve_api_url(api_url)
            self._test_remote_connection()

    def _test_remote_connection(self):
        health_url = f"{self.api_url}/health"
        print(f"{COLOR_CYAN}[*] Connecting to agent endpoint: {self.api_url}...{COLOR_RESET}")
        try:
            res = requests.get(health_url, timeout=10)
            if res.status_code == 200:
                print(f"{COLOR_GREEN}[+] Connected! Remote status: {res.json()}{COLOR_RESET}")
            else:
                print(f"{COLOR_YELLOW}[!] Notice: Server responded with HTTP {res.status_code}{COLOR_RESET}")
        except Exception as e:
            print(f"{COLOR_YELLOW}[!] Connection warning ({e}). Ready to send requests once server is active.{COLOR_RESET}")

    def print_browser_status(self):
        connected, details = self.bridge.get_status_info()
        if connected:
            print(f"{COLOR_GREEN}[+] MCP Browser Bridge: CONNECTED{COLOR_RESET} -> {COLOR_CYAN}{details}{COLOR_RESET}")
        else:
            print(f"{COLOR_YELLOW}[!] MCP Browser Bridge: DISCONNECTED{COLOR_RESET}")
            print(f"{COLOR_DIM}    To enable Chrome control: Open chrome://extensions -> Developer Mode -> Load unpacked -> select 'mcp_extension' folder{COLOR_RESET}")

    def get_system_prompt(self) -> str:
        connected, details = self.bridge.get_status_info()
        status_text = f"CONNECTED: {details}" if connected else "DISCONNECTED (Extension not currently connected)"
        replacements = {
            "{os_name}": platform.system(),
            "{platform_details}": platform.platform(),
            "{cwd}": self.cwd,
            "{home_dir}": self.home_dir,
            "{shell}": self.shell,
            "{shell_tag}": self.shell_tag,
            "{browser_status}": status_text
        }
        default_prompt = SYSTEM_PROMPT
        for placeholder, val in replacements.items():
            default_prompt = default_prompt.replace(placeholder, str(val))
        if self.custom_system_prompt:
            return f"### Core System Mind & Directive:\n{self.custom_system_prompt}\n\n" + default_prompt
        return default_prompt

    def prune_history(self, messages: List[Dict[str, str]], max_tokens_estimate: int = 4000) -> List[Dict[str, str]]:
        def estimate_tokens(msgs: List[Dict[str, str]]) -> int:
            return sum(len(m.get("content", "")) for m in msgs) // 3

        pruned = [dict(m) for m in messages]
        for i in range(1, len(pruned)):
            content = pruned[i].get("content", "")
            if len(content) > 2800:
                pruned[i]["content"] = (
                    content[:1200]
                    + "\n...[intermediate output truncated for context window]...\n"
                    + content[-1200:]
                )

        if estimate_tokens(pruned) <= max_tokens_estimate or len(pruned) <= 3:
            return pruned

        system_msg = pruned[0]
        goal_msg = pruned[1]
        history_pool = pruned[2:]

        while len(history_pool) > 2 and estimate_tokens([system_msg, goal_msg] + history_pool) > max_tokens_estimate:
            history_pool.pop(0)

        return [system_msg, goal_msg] + history_pool

    def _stream_filter(self, token: str, state: Dict[str, Any]) -> str:
        state["buffer"] += token
        out = ""
        for raw_tag in ["<|channel>thought", "<channel|>thought", "<channel|>", "<|channel|>", "<|thought|>", "</|thought|>"]:
            if raw_tag in state["buffer"]:
                state["buffer"] = state["buffer"].replace(raw_tag, "")

        if "<" not in state["buffer"]:
            out = state["buffer"]
            state["buffer"] = ""
        elif ">" in state["buffer"]:
            cleaned = re.sub(r"<\|?[^>]+?\|>", "", state["buffer"])
            out = cleaned
            state["buffer"] = ""
        return out

    def query_llm(self, messages: List[Dict[str, str]], stream: bool = True) -> str:
        state = {"buffer": ""}
        assistant_text = ""
        safe_messages = self.prune_history(messages)

        if self.mode == "local":
            stream_res = self.llm.create_chat_completion(
                messages=safe_messages,
                max_tokens=2048,
                temperature=0.2,
                top_p=0.9,
                stream=stream
            )
            for chunk in stream_res:
                if "choices" in chunk and len(chunk["choices"]) > 0:
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        assistant_text += token
                        display_chunk = self._stream_filter(token, state)
                        if display_chunk:
                            print(display_chunk, end="", flush=True)
            if state["buffer"]:
                tail = re.sub(r"<\|?[^>]+?\|>", "", state["buffer"])
                print(tail, end="", flush=True)
            print()
            clean_full = re.sub(r"<\|?channel\|?>?(?:thought)?|<channel\|>|<\|?[^>]*thought[^>]*\|>", "", assistant_text, flags=re.IGNORECASE)
            return clean_full.strip()
        else:
            chat_url = f"{self.api_url}/chat"
            payload = {
                "messages": safe_messages,
                "max_tokens": 2048,
                "temperature": 0.2,
                "top_p": 0.9,
                "stream": stream
            }
            try:
                with requests.post(chat_url, json=payload, stream=stream, timeout=180) as r:
                    if r.status_code != 200:
                        print(f"\n{COLOR_RED}[Error: HTTP {r.status_code} - {r.text}]{COLOR_RESET}")
                        return f"Error: API HTTP {r.status_code}"
                    if stream:
                        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                            if chunk:
                                assistant_text += chunk
                                display_chunk = self._stream_filter(chunk, state)
                                if display_chunk:
                                    print(display_chunk, end="", flush=True)
                        if state["buffer"]:
                            tail = re.sub(r"<\|?[^>]+?\|>", "", state["buffer"])
                            print(tail, end="", flush=True)
                        print()
                    else:
                        assistant_text = r.json().get("response", "")
                        cleaned_direct = re.sub(r"<\|?[^>]+?\|>", "", assistant_text)
                        print(cleaned_direct)
            except Exception as e:
                print(f"\n{COLOR_RED}[Connection Error: {e}]{COLOR_RESET}")
                assistant_text = f"Connection error: {e}"

            clean_full = re.sub(r"<\|?channel\|?>?(?:thought)?|<channel\|>|<\|?[^>]*thought[^>]*\|>", "", assistant_text, flags=re.IGNORECASE)
            return clean_full.strip()

    @staticmethod
    def _is_prose_or_conversational(text: str) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return True
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return True
        first_line = lines[0]
        prose_starters = [
            r"^(?:I|I'll|I'm|I've|We|We'll|Let's|Lets|No|Yes|It|It's|This|That|There|Here|Actually|Only|Nothing|Wait|Now|If|When|Because|Since|So|Please|Note:?|Also|Then|As|To|In|At|On|For|You|You'll|Can|Could|Should|Would|May|Might|404\.?)\b",
            r"^(?:Check|Look|Find|Try|See|Test|Analyze|Verify|Notice|Inspect)\s+(?:the|if|for|whether|how|any|this|that|in|at)\b",
            r"^(?:The|A|An)\s+[A-Za-z]+\s+(?:is|was|are|were|has|have|had|looks|seems|says|returned)\b"
        ]
        for pat in prose_starters:
            if re.search(pat, first_line, re.IGNORECASE):
                known_cli = ["cd", "dir", "ls", "cat", "echo", "curl", "wget", "python", "pip", "node", "npm", "git", "powershell", "pwsh", "cmd", "bash", "sh", "del", "rm", "mkdir", "tasklist", "netstat", "ipconfig", "ping", "grep", "findstr"]
                first_word = first_line.split()[0].lower() if first_line.split() else ""
                if first_word not in known_cli:
                    return True
        if re.search(r"[.!?]$", first_line) and not first_line.startswith(("./", ".\\", "/")):
            first_word = first_line.split()[0].lower() if first_line.split() else ""
            known_cli = ["cd", "dir", "ls", "cat", "echo", "curl", "wget", "python", "pip", "node", "npm", "git"]
            if first_word not in known_cli:
                return True
        return False

    def _sanitize_command(self, cmd: str) -> str:
        lines = cmd.splitlines()
        filtered = []
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#") or s.startswith("::") or s.startswith("REM "):
                filtered.append(line)
                continue
            if self._is_prose_or_conversational(s):
                continue
            filtered.append(line)
        return "\n".join(filtered).strip()

    def extract_actions(self, response: str) -> List[Action]:
        actions: List[Action] = []
        response = re.sub(r"<\|?channel\|?>?(?:thought)?|<channel\|>", "", response, flags=re.IGNORECASE)

        browser_pattern = r"```(?:browser:)?(navigate|new_tab|close_tab|switch_tab|reload|back|forward|forms|elements|content|click|type|fill_form|submit|check|uncheck|press|hover|highlight|select|scroll|wait|screenshot|eval|cookies|clear_cookies|tabs)(?:[\s:]+([^\r\n]+))?\r?\n([\s\S]*?)```"
        browser_blocks = re.findall(browser_pattern, response, re.IGNORECASE)
        for b_action, target_spec, content in browser_blocks:
            target = (target_spec or "").strip()
            act = b_action.lower()
            actions.append(Action(f"browser_{act}", target=target, payload=content.strip()))

        browser_nl_blocks = re.findall(
            r"```browser\s*\r?\n(navigate|new_tab|close_tab|switch_tab|reload|back|forward|forms|elements|content|click|type|fill_form|submit|check|uncheck|press|hover|highlight|select|scroll|wait|screenshot|eval|cookies|clear_cookies|tabs)(?:[\s:]+([^\r\n]+))?\r?\n([\s\S]*?)```",
            response,
            re.IGNORECASE
        )
        for b_action, target_spec, content in browser_nl_blocks:
            target = (target_spec or "").strip()
            act = b_action.lower()
            if not any(a.action_type == f"browser_{act}" and a.target == target for a in actions):
                actions.append(Action(f"browser_{act}", target=target, payload=content.strip()))

        http_blocks = re.findall(
            r"```(?:http|http:request)\s*\r?\n([\s\S]*?)```",
            response,
            re.IGNORECASE
        )
        for blk in http_blocks:
            cleaned = blk.strip()
            if cleaned:
                actions.append(Action("http_request", target="http", payload=cleaned))

        file_blocks = re.findall(
            r"```(?:file:)?(write|append|read|patch)(?:[\s:]+([^\r\n]+))?\r?\n([\s\S]*?)```",
            response,
            re.IGNORECASE
        )
        for op_type, path_spec, content in file_blocks:
            path = path_spec.strip() if path_spec else ""
            op = op_type.lower()
            if op == "write":
                actions.append(Action("file_write", target=path, payload=content))
            elif op == "append":
                actions.append(Action("file_append", target=path, payload=content))
            elif op == "read":
                target_path = path or content.strip().splitlines()[0].strip()
                actions.append(Action("file_read", target=target_path, payload=""))
            elif op == "patch":
                actions.append(Action("file_patch", target=path, payload=content))

        ps_blocks = re.findall(r"```powershell\s*\r?\n([\s\S]*?)```", response, re.IGNORECASE)
        for blk in ps_blocks:
            cleaned = blk.strip()
            if cleaned and not self._is_prose_or_conversational(cleaned):
                sanitized = self._sanitize_command(cleaned)
                if sanitized:
                    actions.append(Action("powershell", target="powershell", payload=sanitized))

        shell_blocks = re.findall(r"```(?:bash|sh|cmd|bat|shell)\s*\r?\n([\s\S]*?)```", response, re.IGNORECASE)
        for blk in shell_blocks:
            cleaned = blk.strip()
            if not cleaned or self._is_prose_or_conversational(cleaned):
                continue
            if any(cleaned == act.payload.strip() for act in actions):
                continue
            sanitized = self._sanitize_command(cleaned)
            if sanitized:
                actions.append(Action("command", target="shell", payload=sanitized))

        return actions

    def execute_browser_action(self, action: Action) -> Tuple[int, str, str]:
        op = action.action_type.replace("browser_", "")
        print(f"\n{COLOR_CYAN}+-- [MCP BROWSER: {op.upper()}] ----------------------------------{COLOR_RESET}")
        if action.target:
            print(f"{COLOR_BOLD}Target: {action.target}{COLOR_RESET}")
        if action.payload:
            preview = action.payload[:200] + ("..." if len(action.payload) > 200 else "")
            print(f"{COLOR_DIM}{preview}{COLOR_RESET}")
        print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")

        if not self.auto_approve:
            choice = input(f"{COLOR_BLUE}Execute browser action '{op}'? [Y/n]: {COLOR_RESET}").strip().lower()
            if choice in ["n", "no"]:
                return 1, "", "Browser action canceled by user."

        if op == "navigate":
            url = (action.target or action.payload or "").strip().strip("<").strip(">")
            return self.bridge.send_command("navigate", {"url": url})
        elif op == "new_tab":
            url = (action.target or action.payload or "").strip().strip("<").strip(">")
            return self.bridge.send_command("new_tab", {"url": url})
        elif op == "close_tab":
            tab_id = action.target or action.payload
            params = {"tabId": int(tab_id)} if tab_id and tab_id.isdigit() else {}
            return self.bridge.send_command("close_tab", params)
        elif op == "switch_tab":
            tab_id = action.target or action.payload
            return self.bridge.send_command("switch_tab", {"tabId": int(tab_id)})
        elif op == "reload":
            return self.bridge.send_command("reload")
        elif op == "back":
            return self.bridge.send_command("back")
        elif op == "forward":
            return self.bridge.send_command("forward")
        elif op == "forms":
            code, stdout, stderr = self.bridge.send_command("get_forms")
            if code == 0:
                try:
                    data = json.loads(stdout)
                    forms = data.get("forms", [])
                    out_lines = [f"Found {len(forms)} form structures on {data.get('url', '')}:"]
                    for f in forms:
                        out_lines.append(f"\nForm #{f.get('index')} [selector: '{f.get('selector')}'] Method: {f.get('method')} Action: {f.get('action')}")
                        fields = f.get("fields", [])
                        for field in fields:
                            line = f"  - <{field.get('tag')} type='{field.get('type')}'> selector: '{field.get('selector')}'"
                            if field.get('name'): line += f" name: '{field.get('name')}'"
                            if field.get('label'): line += f" label: '{field.get('label')}'"
                            if field.get('placeholder'): line += f" placeholder: '{field.get('placeholder')}'"
                            if field.get('value'): line += f" value: '{field.get('value')}'"
                            out_lines.append(line)
                        submits = f.get("submitButtons", [])
                        if submits:
                            out_lines.append("  Submit Buttons:")
                            for sub in submits:
                                out_lines.append(f"    * '{sub.get('text')}' -> {sub.get('selector')}")
                    return 0, "\n".join(out_lines), ""
                except Exception:
                    return 0, stdout, ""
            return code, stdout, stderr
        elif op == "elements":
            code, stdout, stderr = self.bridge.send_command("get_elements")
            if code == 0:
                try:
                    data = json.loads(stdout)
                    elements = data.get("elements", [])
                    formatted = [f"Found {len(elements)} interactive elements on {data.get('url', '')}:"]
                    for el in elements[:50]:
                        desc = f"[{el.get('index')}] <{el.get('tag')}> selector: '{el.get('selector')}'"
                        if el.get('text'): desc += f" text: '{el.get('text')}'"
                        if el.get('name'): desc += f" name: '{el.get('name')}'"
                        formatted.append(desc)
                    return 0, "\n".join(formatted), ""
                except Exception:
                    return 0, stdout, ""
            return code, stdout, stderr
        elif op == "content":
            sel = action.target or "body"
            return self.bridge.send_command("get_content", {"selector": sel})
        elif op == "click":
            raw_target = (action.target or action.payload or "").strip()
            coord_match = re.match(r"^(\d+)\s*,?\s*(\d+)$", raw_target)
            if coord_match:
                return self.bridge.send_command("click", {"x": int(coord_match.group(1)), "y": int(coord_match.group(2))})
            return self.bridge.send_command("click", {"selector": raw_target})
        elif op == "type":
            raw_target = (action.target or "").strip()
            text = action.payload
            coord_match = re.match(r"^(\d+)\s*,?\s*(\d+)$", raw_target)
            if coord_match:
                return self.bridge.send_command("type", {"x": int(coord_match.group(1)), "y": int(coord_match.group(2)), "text": text})
            return self.bridge.send_command("type", {"selector": raw_target, "text": text})
        elif op == "fill_form":
            raw_json = action.payload or action.target
            try:
                field_map = json.loads(raw_json)
            except Exception:
                field_map = {}
                for line in raw_json.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        field_map[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")
            return self.bridge.send_command("fill_form", {"fields": field_map})
        elif op == "submit":
            sel = action.target or action.payload or "form"
            return self.bridge.send_command("submit", {"selector": sel})
        elif op == "check":
            sel = action.target or action.payload
            return self.bridge.send_command("check", {"selector": sel})
        elif op == "uncheck":
            sel = action.target or action.payload
            return self.bridge.send_command("uncheck", {"selector": sel})
        elif op == "hover":
            sel = action.target or action.payload
            return self.bridge.send_command("hover", {"selector": sel})
        elif op == "highlight":
            sel = action.target or action.payload
            return self.bridge.send_command("highlight", {"selector": sel})
        elif op == "press":
            parts = action.target.split(None, 1)
            sel = parts[0] if parts else ""
            key = parts[1] if len(parts) > 1 else (action.payload or "Enter")
            return self.bridge.send_command("press", {"selector": sel, "key": key})
        elif op == "select":
            sel = action.target
            val = action.payload
            return self.bridge.send_command("select", {"selector": sel, "value": val})
        elif op == "scroll":
            target = action.target or action.payload or "down"
            return self.bridge.send_command("scroll", {"target": target})
        elif op == "wait":
            parts = action.target.split()
            sel = parts[0] if parts else "body"
            timeout = float(parts[1]) if len(parts) > 1 else 10.0
            return self.bridge.send_command("wait", {"selector": sel, "timeout": timeout})
        elif op == "screenshot":
            code, stdout, stderr = self.bridge.send_command("screenshot")
            if code == 0:
                try:
                    data = json.loads(stdout)
                    data_url = data.get("dataUrl", "")
                    if data_url.startswith("data:image/"):
                        b64_part = data_url.split(",", 1)[1]
                        img_bytes = base64.b64decode(b64_part)
                        out_path = Path(self.cwd) / f"screenshot_{int(time.time())}.png"
                        out_path.write_bytes(img_bytes)
                        return 0, f"Screenshot captured and saved to: {out_path.name}", ""
                except Exception as e:
                    return 0, f"Screenshot captured (base64 size: {len(stdout)} chars)", ""
            return code, stdout, stderr
        elif op == "eval":
            code = action.payload or action.target
            return self.bridge.send_command("eval", {"code": code})
        elif op == "cookies":
            return self.bridge.send_command("get_cookies")
        elif op == "clear_cookies":
            return self.bridge.send_command("clear_cookies")
        elif op == "tabs":
            return self.bridge.send_command("get_tabs")

        return 1, "", f"Unknown browser operation: {op}"

    def execute_http_action(self, action: Action) -> Tuple[int, str, str]:
        raw = action.payload.strip()
        if not raw:
            return 1, "", "Empty HTTP request block."
        print(f"\n{COLOR_CYAN}+-- [HTTP REQUEST DEBUG] -------------------------------{COLOR_RESET}")
        lines = raw.splitlines()
        first_line = lines[0].strip()
        parts = first_line.split(None, 2)
        if len(parts) < 2:
            return 1, "", f"Invalid HTTP request line: '{first_line}'. Expected format: METHOD <URL>"
        method = parts[0].upper()
        raw_url = parts[1].strip().strip("<").strip(">")

        if raw_url.startswith("/"):
            if self.last_base_url:
                url = urljoin(self.last_base_url, raw_url)
            else:
                return 1, "", f"Relative URL '{raw_url}' provided, but no base host URL is known yet."
        elif not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            if "." in raw_url or ":" in raw_url or raw_url.startswith("localhost"):
                url = f"https://{raw_url}"
            elif self.last_base_url:
                url = urljoin(self.last_base_url, "/" + raw_url.lstrip("/"))
            else:
                url = f"https://{raw_url}"
        else:
            url = raw_url

        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            self.last_base_url = f"{parsed.scheme}://{parsed.netloc}"

        headers = {}
        body_lines = []
        in_body = False
        for line in lines[1:]:
            if in_body:
                body_lines.append(line)
            elif not line.strip():
                in_body = True
            elif ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
            else:
                in_body = True
                body_lines.append(line)
        body_content = "\n".join(body_lines).strip() if body_lines else None

        clean_headers = {hk: hv for hk, hv in headers.items()}
        if body_content and not any(k.lower() == "content-type" for k in clean_headers):
            stripped_body = body_content.strip()
            if (stripped_body.startswith("{") and stripped_body.endswith("}")) or (stripped_body.startswith("[") and stripped_body.endswith("]")):
                clean_headers["Content-Type"] = "application/json"
            elif "=" in stripped_body and not stripped_body.startswith("<"):
                clean_headers["Content-Type"] = "application/x-www-form-urlencoded"

        print(f"{COLOR_BOLD}{method} {url}{COLOR_RESET}")
        if clean_headers:
            print(f"{COLOR_DIM}Headers: {json.dumps(clean_headers)}{COLOR_RESET}")
        if body_content:
            body_preview = body_content[:200] + ("..." if len(body_content) > 200 else "")
            print(f"{COLOR_DIM}Body: {body_preview}{COLOR_RESET}")
        print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")

        if not self.auto_approve:
            choice = input(f"{COLOR_BLUE}Send HTTP {method} request to {url}? [Y/n]: {COLOR_RESET}").strip().lower()
            if choice in ["n", "no"]:
                return 1, "", "HTTP request canceled by user."

        try:
            allow_redirects = True
            timeout = 30
            proxies = None
            final_headers = {}
            for hk, hv in clean_headers.items():
                lower_hk = hk.lower()
                if lower_hk == "follow-redirects":
                    allow_redirects = hv.strip().lower() not in ["false", "0", "no"]
                elif lower_hk == "x-proxy":
                    proxy_url = hv.strip().split()[0]
                    if proxy_url:
                        proxies = {"http": proxy_url, "https": proxy_url}
                elif lower_hk == "x-timeout":
                    try:
                        timeout = int(hv.strip().split()[0])
                    except ValueError:
                        pass
                else:
                    final_headers[hk] = hv

            req_kwargs = {
                "method": method,
                "url": url,
                "headers": final_headers,
                "timeout": timeout,
                "verify": False,
                "allow_redirects": allow_redirects
            }
            if proxies:
                req_kwargs["proxies"] = proxies
            if body_content:
                req_kwargs["data"] = body_content.encode("utf-8")

            start_req_time = time.time()
            resp = self.http_session.request(**req_kwargs)
            elapsed_ms = int((time.time() - start_req_time) * 1000)

            debug_info = [
                f"Status: {resp.status_code} {resp.reason} (Latency: {elapsed_ms}ms)",
                f"Final URL: {resp.url}"
            ]
            if resp.history:
                redirects = " -> ".join([f"{r.status_code} ({r.url})" for r in resp.history])
                debug_info.append(f"Redirect History: {redirects}")
            debug_info.append("Response Headers:")
            for hk, hv in resp.headers.items():
                debug_info.append(f"  {hk}: {hv}")
            if self.http_session.cookies:
                cookie_dict = self.http_session.cookies.get_dict()
                debug_info.append(f"Session Cookies: {json.dumps(cookie_dict)}")

            content_type = resp.headers.get("Content-Type", "").lower()
            text_body = resp.text

            html_insights = []
            if "text/html" in content_type or "<html" in text_body.lower():
                title_match = re.search(r"<title[^>]*>(.*?)</title>", text_body, re.IGNORECASE | re.DOTALL)
                if title_match:
                    html_insights.append(f"HTML Title: {title_match.group(1).strip()}")

                csrf_matches = re.findall(r"""<input[^>]*name=["'](?:csrf|_csrf|token|csrf_token|authenticity_token)["'][^>]*value=["']([^"']+)["']""", text_body, re.IGNORECASE)
                if not csrf_matches:
                    csrf_matches = re.findall(r"""<input[^>]*value=["']([^"']+)["'][^>]*name=["'](?:csrf|_csrf|token|csrf_token|authenticity_token)["']""", text_body, re.IGNORECASE)
                if csrf_matches:
                    html_insights.append(f"[CSRF Token Detected]: {csrf_matches[0]}")

                comments = re.findall(r"<!--(.*?)-->", text_body, re.DOTALL)
                if comments:
                    clean_comments = [c.strip() for c in comments if c.strip()][:5]
                    if clean_comments:
                        html_insights.append("HTML Comments Detected:")
                        for c in clean_comments:
                            html_insights.append(f"  <!-- {c[:120]} -->")

            flag_match = re.search(r"(?:flag\{[^}]+\}|ctf\{[^}]+\}|picoCTF\{[^}]+\}|HTB\{[^}]+\})", text_body, re.IGNORECASE)
            if flag_match:
                html_insights.append(f"[+] CTF FLAG FOUND: {flag_match.group(0)}")

            if html_insights:
                debug_info.append("\nPage Analysis:")
                debug_info.extend(html_insights)

            debug_info.append("\nResponse Body:")
            if "application/json" in content_type:
                try:
                    parsed_json = resp.json()
                    formatted_json = json.dumps(parsed_json, indent=2)
                    debug_info.append(formatted_json[:4000] + ("\n...[truncated]..." if len(formatted_json) > 4000 else ""))
                except Exception:
                    debug_info.append(text_body[:4000] if len(text_body) > 4000 else text_body)
            else:
                debug_info.append(text_body[:4000] if len(text_body) > 4000 else text_body)

            output_str = "\n".join(debug_info)
            print(f"{COLOR_GREEN}[+] HTTP {resp.status_code} Response Received ({len(resp.content)} bytes, {elapsed_ms}ms){COLOR_RESET}")
            return 0, output_str, ""
        except Exception as e:
            err = f"HTTP Request Error: {e}"
            print(f"{COLOR_RED}[!] {err}{COLOR_RESET}")
            return 1, "", err

    def resolve_path(self, file_path: str) -> Path:
        p = Path(os.path.expandvars(os.path.expanduser(file_path.strip().strip('"').strip("'"))))
        if not p.is_absolute():
            p = Path(self.cwd) / p
        return p

    def execute_file_action(self, action: Action) -> Tuple[int, str, str]:
        target_path = self.resolve_path(action.target)

        if action.action_type == "file_write":
            print(f"\n{COLOR_CYAN}+-- [FILE WRITE] ---------------------------------------{COLOR_RESET}")
            print(f"{COLOR_BOLD}Path: {target_path}{COLOR_RESET}")
            print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")
            if not self.auto_approve:
                choice = input(f"{COLOR_BLUE}Write {len(action.payload)} bytes to {target_path.name}? [Y/n]: {COLOR_RESET}").strip().lower()
                if choice in ["n", "no"]:
                    return 1, "", "File write canceled by user."
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(action.payload, encoding="utf-8")
                msg = f"Successfully created/updated file: {target_path} ({len(action.payload)} characters)"
                print(f"{COLOR_GREEN}[+] {msg}{COLOR_RESET}")
                return 0, msg, ""
            except Exception as e:
                err = f"Failed to write file {target_path}: {e}"
                print(f"{COLOR_RED}[!] {err}{COLOR_RESET}")
                return 1, "", err

        elif action.action_type == "file_append":
            print(f"\n{COLOR_CYAN}+-- [FILE APPEND] --------------------------------------{COLOR_RESET}")
            print(f"{COLOR_BOLD}Path: {target_path}{COLOR_RESET}")
            print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")
            if not self.auto_approve:
                choice = input(f"{COLOR_BLUE}Append {len(action.payload)} bytes to {target_path.name}? [Y/n]: {COLOR_RESET}").strip().lower()
                if choice in ["n", "no"]:
                    return 1, "", "File append canceled by user."
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "a", encoding="utf-8") as f:
                    f.write(action.payload)
                msg = f"Successfully appended content to: {target_path}"
                print(f"{COLOR_GREEN}[+] {msg}{COLOR_RESET}")
                return 0, msg, ""
            except Exception as e:
                err = f"Failed to append to {target_path}: {e}"
                print(f"{COLOR_RED}[!] {err}{COLOR_RESET}")
                return 1, "", err

        elif action.action_type == "file_read":
            print(f"\n{COLOR_CYAN}+-- [FILE READ] ----------------------------------------{COLOR_RESET}")
            print(f"{COLOR_BOLD}Path: {target_path}{COLOR_RESET}")
            print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")
            try:
                if not target_path.exists():
                    return 1, "", f"File not found: {target_path}"
                content = target_path.read_text(encoding="utf-8", errors="replace")
                print(f"{COLOR_GRAY}{content[:1000]}...{COLOR_RESET}" if len(content) > 1000 else f"{COLOR_GRAY}{content}{COLOR_RESET}")
                return 0, content, ""
            except Exception as e:
                err = f"Failed to read file {target_path}: {e}"
                return 1, "", err

        elif action.action_type == "file_patch":
            print(f"\n{COLOR_CYAN}+-- [FILE PATCH] ---------------------------------------{COLOR_RESET}")
            print(f"{COLOR_BOLD}Path: {target_path}{COLOR_RESET}")
            print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")
            try:
                if not target_path.exists():
                    return 1, "", f"File not found: {target_path}"
                patch_regex = re.compile(r"<<<<<<< SEARCH\r?\n([\s\S]*?)\r?\n=======\r?\n([\s\S]*?)\r?\n>>>>>>>", re.MULTILINE)
                patches = patch_regex.findall(action.payload)
                if not patches:
                    return 1, "", "Invalid patch format. Use <<<<<<< SEARCH ... ======= ... >>>>>>>"

                content = target_path.read_text(encoding="utf-8")
                for search_str, replace_str in patches:
                    if search_str not in content:
                        return 1, "", f"Search block not found in {target_path}"
                    content = content.replace(search_str, replace_str, 1)

                target_path.write_text(content, encoding="utf-8")
                msg = f"Successfully applied {len(patches)} patch(es) to {target_path}"
                print(f"{COLOR_GREEN}[+] {msg}{COLOR_RESET}")
                return 0, msg, ""
            except Exception as e:
                return 1, "", f"Error applying patch: {e}"

        return 1, "", "Unknown file action"

    def execute_command(self, cmd: str, use_powershell: bool = False, output_callback: Optional[Any] = None) -> Tuple[int, str, str, Optional[str]]:
        runner_title = "POWERSHELL" if use_powershell else "EXECUTE"
        print(f"\n{COLOR_CYAN}+-- [{runner_title}] ------------------------------------------{COLOR_RESET}")
        print(f"{COLOR_BOLD}{cmd}{COLOR_RESET}")
        print(f"{COLOR_CYAN}+-------------------------------------------------------{COLOR_RESET}")

        cleaned_cmd = self._sanitize_command(cmd)
        if not cleaned_cmd or self._is_prose_or_conversational(cleaned_cmd):
            return 0, f"[Commentary noted: '{cmd[:80]}...']", "", None
        cmd = cleaned_cmd

        cd_match = re.match(r"^cd(?:\s+|\s+/d\s+|\s*=\s*)(.+)$", cmd.strip(), re.IGNORECASE)
        if cd_match:
            raw_target = cd_match.group(1).strip().strip('"').strip("'")
            target_dir = os.path.expandvars(os.path.expanduser(raw_target))
            try:
                os.chdir(target_dir)
                self.cwd = os.getcwd()
                msg = f"Changed directory to {self.cwd}"
                print(f"{COLOR_GREEN}[+] {msg}{COLOR_RESET}")
                if output_callback:
                    output_callback(msg + "\r\n")
                return 0, msg, "", None
            except Exception as e:
                err = f"Failed to cd to {target_dir}: {e}"
                print(f"{COLOR_RED}[!] {err}{COLOR_RESET}")
                if output_callback:
                    output_callback(err + "\r\n")
                return 1, "", err, None

        if cmd.strip().lower() in ["cls", "clear"]:
            os.system("cls" if self.is_windows else "clear")
            return 0, "Terminal screen cleared.", "", None

        if not self.auto_approve:
            try:
                prompt_text = f"{COLOR_BLUE}Run this command? [{COLOR_GREEN}Y{COLOR_BLUE}es/{COLOR_RED}n{COLOR_BLUE}o/edit/direct input]: {COLOR_RESET}"
                choice = input(prompt_text).strip()
                lower_choice = choice.lower()

                if lower_choice in ["n", "no", "cancel", "stop"]:
                    return 1, "", "Execution canceled by user.", None
                elif lower_choice in ["edit", "e"]:
                    cmd = input(f"{COLOR_BLUE}Enter replacement command: {COLOR_RESET}").strip()
                elif lower_choice not in ["y", "yes", ""]:
                    print(f"{COLOR_CYAN}[i] Steering instruction: '{choice}'{COLOR_RESET}")
                    return 0, "", "", choice
            except (KeyboardInterrupt, EOFError):
                print(f"\n{COLOR_YELLOW}[!] Skipped.{COLOR_RESET}")
                return 1, "", "Aborted by user interrupt.", None

        try:
            env = os.environ.copy()
            cleanup_file = None
            if self.is_windows:
                if use_powershell:
                    ps_script = f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;\n{cmd}'
                    encoded_cmd = base64.b64encode(ps_script.encode('utf-16le')).decode('utf-8')
                    shell_exec = f'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded_cmd}'
                else:
                    bat_path = os.path.join(tempfile.gettempdir(), f"mcode_{int(time.time())}.bat")
                    with open(bat_path, "w", encoding="utf-8") as f:
                        f.write("@echo off\nchcp 65001 >nul\n" + cmd)
                    cleanup_file = bat_path
                    comspec = env.get("COMSPEC", "C:\\Windows\\system32\\cmd.exe")
                    shell_exec = f'"{comspec}" /c "{bat_path}"'
            else:
                shell_exec = cmd

            process = subprocess.Popen(
                shell_exec,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.cwd,
                env=env,
                bufsize=1
            )

            collected_stdout = []
            collected_stderr = []

            def read_stream(stream, sink, is_err=False):
                for line in iter(stream.readline, ''):
                    if not line:
                        break
                    sink.append(line)
                    if output_callback:
                        output_callback(line.replace("\n", "\r\n"))
                    if is_err:
                        print(f"{COLOR_RED}{line.rstrip()}{COLOR_RESET}")
                    else:
                        print(f"{COLOR_GRAY}{line.rstrip()}{COLOR_RESET}")
                stream.close()

            t_out = threading.Thread(target=read_stream, args=(process.stdout, collected_stdout, False))
            t_err = threading.Thread(target=read_stream, args=(process.stderr, collected_stderr, True))
            t_out.daemon = True
            t_err.daemon = True
            t_out.start()
            t_err.start()

            process.wait(timeout=180)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            returncode = process.returncode
            
            if cleanup_file and os.path.exists(cleanup_file):
                try:
                    os.remove(cleanup_file)
                except Exception:
                    pass

            stdout_str = "".join(collected_stdout).strip()
            stderr_str = "".join(collected_stderr).strip()
            return returncode, stdout_str, stderr_str, None
        except subprocess.TimeoutExpired:
            process.kill()
            msg = "Command timed out after 180 seconds."
            if output_callback:
                output_callback(f"\r\n[!] {msg}\r\n")
            return 124, "", msg, None
        except Exception as e:
            err = f"System execution error: {str(e)}"
            if output_callback:
                output_callback(f"\r\n[!] {err}\r\n")
            return 1, "", err, None

    def run_task(self, user_goal: str):
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": f"Goal: {user_goal}"}
        ]

        print(f"\n{COLOR_BOLD}{COLOR_GREEN}+-------------------------------------------------------------+{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_GREEN}| MatrixCode Agent Loop: {user_goal[:43]:<43}|{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_GREEN}+-------------------------------------------------------------+{COLOR_RESET}\n")

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            print(f"{COLOR_MAGENTA}[>] Step {iteration}/{self.max_iterations} (Agent Thinking & Reasoning){COLOR_RESET}")

            try:
                assistant_reply = self.query_llm(messages, stream=True)
            except KeyboardInterrupt:
                print(f"\n{COLOR_YELLOW}[!] Interrupted by user.{COLOR_RESET}")
                break

            messages.append({"role": "assistant", "content": assistant_reply})
            actions = self.extract_actions(assistant_reply)

            if not actions:
                if "TASK_COMPLETED:" in assistant_reply:
                    print(f"\n{COLOR_GREEN}[+] TASK COMPLETED AND VERIFIED SUCCESSFULLY{COLOR_RESET}")
                break

            all_obs = []
            interrupted_by_user = False

            for act in actions:
                if act.action_type.startswith("browser_"):
                    code, stdout, stderr = self.execute_browser_action(act)
                    obs_chunk = [f"MCP Browser Action: {act.action_type}", f"Status: {'SUCCESS' if code == 0 else 'ERROR'}"]
                    if stdout:
                        trunc = stdout[:2500] + ("... [truncated]" if len(stdout) > 2500 else "")
                        obs_chunk.append(f"OUTPUT:\n{trunc}")
                    if stderr:
                        trunc = stderr[:2500] + ("... [truncated]" if len(stderr) > 2500 else "")
                        obs_chunk.append(f"ERROR:\n{trunc}")
                    all_obs.append("\n".join(obs_chunk))
                elif act.action_type == "http_request":
                    code, stdout, stderr = self.execute_http_action(act)
                    obs_chunk = ["HTTP Request Execution", f"Status Code: {code}"]
                    if stdout:
                        trunc = stdout[:4000] + ("... [truncated]" if len(stdout) > 4000 else "")
                        obs_chunk.append(f"OUTPUT:\n{trunc}")
                    if stderr:
                        trunc = stderr[:2500] + ("... [truncated]" if len(stderr) > 2500 else "")
                        obs_chunk.append(f"ERROR:\n{trunc}")
                    all_obs.append("\n".join(obs_chunk))
                elif act.action_type in ["file_write", "file_append", "file_read", "file_patch"]:
                    code, stdout, stderr = self.execute_file_action(act)
                    obs_chunk = [f"File Operation: {act.action_type} on {act.target}", f"Status Code: {code}"]
                    if stdout:
                        trunc = stdout[:2500] + ("... [truncated]" if len(stdout) > 2500 else "")
                        obs_chunk.append(f"OUTPUT:\n{trunc}")
                    if stderr:
                        trunc = stderr[:2500] + ("... [truncated]" if len(stderr) > 2500 else "")
                        obs_chunk.append(f"ERROR:\n{trunc}")
                    all_obs.append("\n".join(obs_chunk))
                else:
                    is_ps = act.action_type == "powershell"
                    code, stdout, stderr, user_redirect = self.execute_command(act.payload, use_powershell=is_ps)

                    if user_redirect:
                        messages.append({
                            "role": "user",
                            "content": f"User guidance: {user_redirect}"
                        })
                        interrupted_by_user = True
                        break

                    obs_chunk = [f"Command: {act.payload}", f"Exit Code: {code}"]
                    if stdout:
                        trunc = stdout[:2500] + ("... [truncated]" if len(stdout) > 2500 else "")
                        obs_chunk.append(f"STDOUT:\n{trunc}")
                    if stderr:
                        trunc = stderr[:2500] + ("... [truncated]" if len(stderr) > 2500 else "")
                        obs_chunk.append(f"STDERR:\n{trunc}")
                    if not stdout and not stderr:
                        obs_chunk.append("(Command completed with no terminal output)")
                    all_obs.append("\n".join(obs_chunk))

            if interrupted_by_user:
                continue

            observation = "\n\n---\n\n".join(all_obs)
            observation += f"\n\nCurrent working directory: {self.cwd}"
            messages.append({"role": "user", "content": f"Execution Output:\n{observation}"})

        if iteration >= self.max_iterations:
            print(f"\n{COLOR_YELLOW}[!] Iteration ceiling reached ({self.max_iterations}).{COLOR_RESET}")

def main():
    parser = argparse.ArgumentParser(description="MatrixCode CLI Autonomous Terminal Agent for Gemma GGUF with Browser MCP")
    parser.add_argument("--local", action="store_true", help="Run directly with local GGUF model via llama-cpp-python")
    parser.add_argument("--url", type=str, default="", help="URL of server.py or ngrok endpoint")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-approve and run commands without confirmation")
    parser.add_argument("--max-steps", type=int, default=50, help="Maximum reasoning/execution loops per task (default: 50)")
    parser.add_argument("goal", nargs="*", help="Optional single task to execute directly")

    args = parser.parse_args()

    mode = "local" if args.local else "remote"
    agent = TerminalAgent(
        mode=mode,
        api_url=args.url if args.url else None,
        auto_approve=args.yes,
        max_iterations=args.max_steps
    )

    time.sleep(0.3)

    print(f"{COLOR_BOLD}{COLOR_CYAN}{'=' * 62}{COLOR_RESET}")
    print(f"{COLOR_BOLD}   MatrixCode CLI Autonomous Agent (Gemma GGUF Engine){COLOR_RESET}")
    print(f"{COLOR_DIM}   System automation, CTF solver, and live Browser MCP bridge.{COLOR_RESET}")
    agent.print_browser_status()
    print(f"{COLOR_DIM}   Type 'exit' or 'quit' to terminate. Type 'browser status' for bridge check.{COLOR_RESET}")
    print(f"{COLOR_BOLD}{COLOR_CYAN}{'=' * 62}{COLOR_RESET}")

    if args.goal:
        user_task = " ".join(args.goal).strip()
        agent.run_task(user_task)
        return

    while True:
        try:
            task_input = input(f"\n{COLOR_BOLD}{COLOR_GREEN}matrixcode > {COLOR_RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{COLOR_YELLOW}Exiting agent session.{COLOR_RESET}")
            break

        if not task_input:
            continue

        lower_input = task_input.lower()
        if lower_input in ["exit", "quit"]:
            print("Goodbye!")
            break

        if lower_input in ["cls", "clear"]:
            os.system("cls" if agent.is_windows else "clear")
            continue

        if lower_input in ["browser status", "mcp status"]:
            agent.print_browser_status()
            continue

        if lower_input.startswith("cd ") or lower_input == "cd":
            target = task_input[2:].strip().strip('"').strip("'")
            if not target:
                print(agent.cwd)
            else:
                try:
                    target_expanded = os.path.expandvars(os.path.expanduser(target))
                    os.chdir(target_expanded)
                    agent.cwd = os.getcwd()
                    print(f"{COLOR_GREEN}[+] Directory changed to {agent.cwd}{COLOR_RESET}")
                except Exception as e:
                    print(f"{COLOR_RED}[!] Error changing directory: {e}{COLOR_RESET}")
            continue

        agent.run_task(task_input)

if __name__ == "__main__":
    main()
