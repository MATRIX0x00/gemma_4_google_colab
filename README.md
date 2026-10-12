# Running Gemma GGUF with llama-cpp-python on GPU & OpenCode Web Studio

Fast setup and streaming inference for quantized GGUF models using `llama-cpp-python` with complete GPU layer offloading (`n_gpu_layers=-1`), plus an interactive Web Studio equipped with an **xterm.js Web Terminal** and live Autonomous Agent executor.

## Fast Installation (Prebuilt Wheels)

Avoid slow compilation times by using prebuilt CUDA wheels:

```bash
# For CUDA 12.2+
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu122
pip install -r requirements.txt
```

### Linux / Colab CUDA Dynamic Linker Fix

```bash
find /usr/local/lib/python*/dist-packages/nvidia/ -type d -name "lib" > /etc/ld.so.conf.d/nvidia-cuda.conf
ldconfig
```

## Launching OpenCode Web Studio (xterm.js + Flask)

You can launch the full Web IDE & Terminal on any desired port:

```bash
# Launch Web Studio on port 5000
python web_server.py --port 5000

# Or attach remote ngrok Gemma endpoint directly at launch
python web_server.py --port 5000 --url https://xxxx.ngrok-free.app
```

Open your browser at `http://localhost:5000` to access:
- **Interactive Web Terminal**: Powered by xterm.js connected to live shell.
- **Autonomous OpenCode Agent**: Send natural language commands executed step-by-step through the remote Gemma GGUF API.
- **File Explorer & Editor**: Browse workspace files, inspect outputs, and edit source files directly.

## CLI Terminal Agent (`terminal.py`)

Run the agent in terminal mode without the web UI:
```bash
python terminal.py --url https://xxxx.ngrok-free.app -y
```
