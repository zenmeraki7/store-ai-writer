"""Run once to confirm your key/model work:  python check_model.py"""
from app.llm import chat

text, provider = chat([{"role": "user", "content": "Write one sentence about a red maxi dress."}], max_tokens=80)
print(f"[{provider}] {text}")
