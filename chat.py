import sys
import os
import re
import requests

def main():
    print("=" * 55)
    print("Gemma GGUF Remote Chat Client (via ngrok)")
    print("=" * 55)

    base_url = os.getenv("NGROK_URL", "").strip()
    if not base_url:
        if len(sys.argv) > 1:
            base_url = sys.argv[1].strip()
        else:
            base_url = input("Enter your ngrok public URL (e.g. https://xxxx.ngrok-free.app): ").strip()

    base_url = base_url.rstrip("/")
    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = f"https://{base_url}"

    chat_endpoint = f"{base_url}/chat"
    health_endpoint = f"{base_url}/health"

    print(f"Connecting to server at {base_url}...")
    try:
        res = requests.get(health_endpoint, timeout=10)
        if res.status_code == 200:
            print(f"Connected! Server health: {res.json()}")
        else:
            print(f"Warning: Server responded with status code {res.status_code}")
    except Exception as e:
        print(f"Connection warning (check if URL is valid and server is running): {e}")

    print("\nStarting conversation. Type 'exit' or 'quit' to exit.\n" + "-" * 55)

    messages = [
        {"role": "system", "content": "You are a helpful AI assistant."}
    ]

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting session.")
            break

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit"]:
            print("Exiting chat client. Goodbye!")
            break

        messages.append({"role": "user", "content": user_input})
        if len(messages) > 16:
            messages = [messages[0]] + messages[-12:]

        print("\nAI: ", end="", flush=True)

        payload = {
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.7,
            "top_p": 0.9,
            "stream": True
        }

        assistant_response = ""
        try:
            with requests.post(chat_endpoint, json=payload, stream=True, timeout=120) as r:
                if r.status_code != 200:
                    print(f"\n[Error from server: HTTP {r.status_code} - {r.text}]")
                    continue
                buf = ""
                for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        assistant_response += chunk
                        buf += chunk
                        for tag in ["<|channel>thought", "<channel|>", "<|channel|>", "<|thought|>", "</|thought|>"]:
                            buf = buf.replace(tag, "")
                        if "<" not in buf:
                            print(buf, end="", flush=True)
                            buf = ""
                        elif ">" in buf:
                            cleaned = re.sub(r"<\|?[^>]+?\|>", "", buf)
                            print(cleaned, end="", flush=True)
                            buf = ""
                if buf:
                    print(re.sub(r"<\|?[^>]+?\|>", "", buf), end="", flush=True)
            print()
            cleaned_response = re.sub(r"<\|?[^>]+?\|>", "", assistant_response)
            messages.append({"role": "assistant", "content": cleaned_response.strip()})
        except Exception as e:
            print(f"\n[Request failed: {e}]")

if __name__ == "__main__":
    main()
