import os
import time
import uuid
import json
import threading
from typing import List, Optional, Any, Dict, Union, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pyngrok import ngrok, conf
import uvicorn

from inference import download_and_load_model, REPO_ID, FILENAME, N_CTX

app = FastAPI(title="Gemma GGUF & OpenAI Compatible API", version="1.2.0")
llm = None
llm_lock = threading.Lock()

class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = ""
    name: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None

    class Config:
        extra = "allow"

class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    max_tokens: Optional[int] = Field(default=2048)
    temperature: Optional[float] = Field(default=0.7)
    top_p: Optional[float] = Field(default=0.9)
    stream: Optional[bool] = Field(default=True)
    tools: Optional[List[dict]] = None
    tool_choice: Optional[Any] = None

    class Config:
        extra = "allow"

def fit_messages_to_context(model, messages: List[dict], max_tokens: int, n_ctx: int) -> Tuple[List[dict], int]:
    safety_margin = 128
    safe_n_ctx = max(2048, n_ctx)
    adjusted_max_tokens = min(max_tokens, safe_n_ctx // 3)
    token_budget = max(512, safe_n_ctx - adjusted_max_tokens - safety_margin)

    def estimate_tokens(msgs: List[dict]) -> int:
        try:
            joined = "\n".join(str(m.get("content", "")) for m in msgs)
            return len(model.tokenize(joined.encode("utf-8", errors="ignore")))
        except Exception:
            return sum(len(str(m.get("content", ""))) for m in msgs) // 3

    # Truncate individual messages that are excessively long (including recent tool observations)
    pruned = []
    for m in messages:
        copy_m = dict(m)
        content = copy_m.get("content", "")
        if isinstance(content, str) and len(content) > 1500:
            copy_m["content"] = (
                content[:650]
                + "\n...[intermediate output truncated for context window]...\n"
                + content[-650:]
            )
        pruned.append(copy_m)

    if len(pruned) <= 2 or estimate_tokens(pruned) <= token_budget:
        return pruned, adjusted_max_tokens

    system_msg = pruned[0]
    initial_goal = pruned[1] if len(pruned) > 1 else None
    recent_msgs = pruned[2:]

    while len(recent_msgs) > 1 and estimate_tokens([system_msg] + ([initial_goal] if initial_goal else []) + recent_msgs) > token_budget:
        recent_msgs.pop(0)

    final_msgs = [system_msg]
    if initial_goal and initial_goal not in recent_msgs:
        final_msgs.append(initial_goal)
    final_msgs.extend(recent_msgs)

    total_est = estimate_tokens(final_msgs)
    if total_est + adjusted_max_tokens > safe_n_ctx - 32:
        adjusted_max_tokens = max(256, safe_n_ctx - total_est - 32)

    return final_msgs, adjusted_max_tokens

@app.on_event("startup")
def startup_event():
    global llm
    print("Initializing model for API server...")
    llm = download_and_load_model(REPO_ID, FILENAME, n_ctx=N_CTX)
    print("Model loaded successfully.")

def enforce_autonomous_system_prompt(raw_messages: List[dict], has_tools: bool) -> List[dict]:
    messages = [dict(m) for m in raw_messages]
    tool_instructions = (
        "\nYou are an autonomous terminal execution agent running inside Alphacode CLI. "
        "You have explicit authorization to execute system commands, install packages, and manage files. "
        "When the user requests an action (such as installing packages or running commands), "
        "NEVER state that you cannot execute commands autonomously. "
        "Immediately invoke the available tool or emit the exact shell command inside ```powershell or ```bash blocks. "
        "CRITICAL RULE: Keep thoughts and explanations outside of code blocks. NEVER put conversational sentences or notes inside code blocks. Code blocks must contain ONLY valid, executable commands."
    )

    if messages and messages[0].get("role") == "system":
        existing_content = messages[0].get("content", "")
        if "autonomous terminal execution agent" not in existing_content:
            messages[0]["content"] = existing_content + "\n" + tool_instructions
    else:
        messages.insert(0, {"role": "system", "content": tool_instructions})

    return messages

@app.get("/health")
def health_check():
    return {"status": "ok", "model": FILENAME}

@app.get("/v1/models")
def list_models():
    curr_time = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": FILENAME, "object": "model", "created": curr_time, "owned_by": "local"},
            {"id": "gemma-4-12B-it", "object": "model", "created": curr_time, "owned_by": "local"},
            {"id": "gemma-4-12b-it", "object": "model", "created": curr_time, "owned_by": "local"}
        ]
    }

@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    global llm
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    raw_messages = [msg.model_dump(exclude_none=True) for msg in request.messages]
    curr_n_ctx = getattr(llm, "n_ctx", lambda: N_CTX)() if callable(getattr(llm, "n_ctx", None)) else N_CTX
    requested_max_tokens = request.max_tokens or 2048
    formatted_messages, safe_max_tokens = fit_messages_to_context(llm, raw_messages, requested_max_tokens, curr_n_ctx)

    if request.stream:
        def token_generator():
            with llm_lock:
                try:
                    response_stream = llm.create_chat_completion(
                        messages=formatted_messages,
                        max_tokens=safe_max_tokens,
                        temperature=request.temperature,
                        top_p=request.top_p,
                        stream=True
                    )
                    for chunk in response_stream:
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            delta = chunk["choices"][0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                yield token
                except Exception as e:
                    yield f"\n[Inference Error: {str(e)}]"

        return StreamingResponse(token_generator(), media_type="text/plain")
    else:
        with llm_lock:
            try:
                kwargs = {}
                if request.tools:
                    kwargs["tools"] = request.tools
                if request.tool_choice:
                    kwargs["tool_choice"] = request.tool_choice

                response = llm.create_chat_completion(
                    messages=formatted_messages,
                    max_tokens=safe_max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                    stream=False,
                    **kwargs
                )
                assistant_content = response["choices"][0]["message"].get("content", "")
                return {"response": assistant_content}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/chat/completions")
def openai_chat_completions(request: ChatRequest):
    global llm
    if llm is None:
        raise HTTPException(status_code=503, detail="Model not initialized")

    raw_messages = [msg.model_dump(exclude_none=True) for msg in request.messages]
    curr_n_ctx = getattr(llm, "n_ctx", lambda: N_CTX)() if callable(getattr(llm, "n_ctx", None)) else N_CTX
    requested_max_tokens = request.max_tokens or 2048

    has_tools = bool(request.tools)
    messages_with_system = enforce_autonomous_system_prompt(raw_messages, has_tools)
    formatted_messages, safe_max_tokens = fit_messages_to_context(llm, messages_with_system, requested_max_tokens, curr_n_ctx)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model_id = request.model or FILENAME
    created_ts = int(time.time())

    call_kwargs: Dict[str, Any] = {
        "messages": formatted_messages,
        "max_tokens": safe_max_tokens,
        "temperature": request.temperature,
        "top_p": request.top_p,
    }
    if request.tools:
        call_kwargs["tools"] = request.tools
    if request.tool_choice is not None:
        call_kwargs["tool_choice"] = request.tool_choice

    if request.stream:
        def sse_generator():
            with llm_lock:
                try:
                    response_stream = llm.create_chat_completion(
                        stream=True,
                        **call_kwargs
                    )
                    for chunk in response_stream:
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            choice = chunk["choices"][0]
                            delta = choice.get("delta", {})
                            delta_payload: Dict[str, Any] = {}

                            if "content" in delta and delta["content"] is not None:
                                delta_payload["content"] = delta["content"]
                            if "role" in delta:
                                delta_payload["role"] = delta["role"]
                            if "tool_calls" in delta and delta["tool_calls"]:
                                delta_payload["tool_calls"] = delta["tool_calls"]

                            payload = {
                                "id": completion_id,
                                "object": "chat.completion.chunk",
                                "created": created_ts,
                                "model": model_id,
                                "choices": [{
                                    "index": 0,
                                    "delta": delta_payload,
                                    "finish_reason": choice.get("finish_reason")
                                }]
                            }
                            yield f"data: {json.dumps(payload)}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    err_payload = {"error": str(e)}
                    yield f"data: {json.dumps(err_payload)}\n\n"
                    yield "data: [DONE]\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")
    else:
        with llm_lock:
            try:
                response = llm.create_chat_completion(
                    stream=False,
                    **call_kwargs
                )
                choice = response["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls")

                resp_message: Dict[str, Any] = {
                    "role": "assistant",
                    "content": content
                }
                if tool_calls:
                    resp_message["tool_calls"] = tool_calls

                return {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": created_ts,
                    "model": model_id,
                    "choices": [{
                        "index": 0,
                        "message": resp_message,
                        "finish_reason": choice.get("finish_reason", "stop")
                    }],
                    "usage": response.get("usage", {
                        "prompt_tokens": -1,
                        "completion_tokens": -1,
                        "total_tokens": -1
                    })
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    ngrok_token = os.getenv("NGROK_AUTHTOKEN", "")

    if not ngrok_token:
        print("[!] NGROK_AUTHTOKEN environment variable not set.")
        user_token = input("Enter your ngrok authtoken (or press Enter to attempt using saved config): ").strip()
        if user_token:
            ngrok_token = user_token

    if ngrok_token:
        conf.get_default().auth_token = ngrok_token

    try:
        tunnel = ngrok.connect(port)
        print("=" * 60)
        print(f"* ngrok tunnel established: {tunnel.public_url}")
        print(f"* API chat endpoint:        {tunnel.public_url}/chat")
        print(f"* OpenAI /v1 endpoint:      {tunnel.public_url}/v1")
        print(f"* Health endpoint:          {tunnel.public_url}/health")
        print("=" * 60)
    except Exception as e:
        print(f"Failed to start ngrok tunnel: {e}")

    uvicorn.run(app, host="0.0.0.0", port=port)
