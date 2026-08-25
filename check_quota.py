import os
from dotenv import load_dotenv
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY_FALLBACK = os.getenv("GEMINI_API_KEY_FALLBACK")

import requests
import json
import google.generativeai as genai

print("=== GROQ QUOTA ===")
headers = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json"
}
data = {
    "model": "openai/gpt-oss-20b",
    "messages": [{"role": "user", "content": "hi"}],
    "max_tokens": 10
}
res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data)
if res.status_code == 429:
    print(f"GROQ RATE LIMITED: {json.dumps(res.json(), indent=2)}")
else:
    print("GROQ SUCCESS.")
    for k, v in res.headers.items():
        if "ratelimit" in k.lower():
            print(f"{k}: {v}")

print("\n=== GEMINI PRIMARY QUOTA ===")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.5-flash')
try:
    model.generate_content("hi")
    print("GEMINI PRIMARY SUCCESS.")
except Exception as e:
    print(f"GEMINI PRIMARY FAILED: {e}")

print("\n=== GEMINI FALLBACK QUOTA ===")
genai.configure(api_key=GEMINI_API_KEY_FALLBACK)
model = genai.GenerativeModel('gemini-3.5-flash')
try:
    model.generate_content("hi")
    print("GEMINI FALLBACK SUCCESS.")
except Exception as e:
    print(f"GEMINI FALLBACK FAILED: {e}")
