import os
import time
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

REPO_ID = os.getenv("REPO_ID", "ggml-org/gemma-4-12B-it-GGUF")
FILENAME = os.getenv("FILENAME", "gemma-4-12B-it-Q4_0.gguf")
N_CTX = int(os.getenv("N_CTX", "8192"))

def download_and_load_model(repo_id: str, filename: str, n_ctx: int = 8192) -> Llama:
    print(f"Downloading {filename} from {repo_id}...")
    model_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir="./models",
        local_dir_use_symlinks=False
    )
    print(f"Model downloaded and saved to: {model_path}")

    print("Loading model layers directly to GPU...")
    llm = Llama(
        model_path=model_path,
        n_gpu_layers=-1,
        n_ctx=n_ctx,
        n_batch=512,
        verbose=False
    )
    return llm

def chat_interactive(llm: Llama):
    print("\n" + "=" * 50)
    print("Chat loop initialized! Type 'exit' or 'quit' to stop.")
    print("=" * 50)

    messages = [
        {"role": "system", "content": "You are a helpful AI assistant."}
    ]

    while True:
        try:
            user_input = input("\nYou: ")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break

        if user_input.strip().lower() in ["exit", "quit"]:
            print("Stopping chat loop. Goodbye!")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})
        if len(messages) > 16:
            messages = [messages[0]] + messages[-12:]

        print("\nAI: ", end="", flush=True)

        response_stream = llm.create_chat_completion(
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
            top_p=0.9,
            stream=True
        )

        assistant_response = ""
        token_count = 0
        start_time = None

        for chunk in response_stream:
            if "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                if "content" in delta:
                    token = delta["content"]
                    if token:
                        if start_time is None:
                            start_time = time.time()
                        token_count += 1
                        assistant_response += token
                        print(token, end="", flush=True)

        end_time = time.time()
        print()

        if start_time and token_count > 0:
            elapsed_time = end_time - start_time
            tokens_per_second = token_count / elapsed_time
            print(f"[Speed: {tokens_per_second:.2f} tok/sec | Generated: {token_count} tokens | Time: {elapsed_time:.2f}s]")
        else:
            print("[Speed: 0.00 tok/sec (Empty or instant response)]")

        messages.append({"role": "assistant", "content": assistant_response})

if __name__ == "__main__":
    print("System CUDA configuration checked.")
    llm = download_and_load_model(REPO_ID, FILENAME, n_ctx=N_CTX)
    print("\nModel fully loaded and ready for queries!")
    chat_interactive(llm)
