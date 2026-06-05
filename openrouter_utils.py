import requests
import json

try:
    import streamlit as st
    OPENROUTER_API_KEY = st.secrets.get("API_OPENROUTER_KEY")
except (ImportError, RuntimeError):
    import os
    OPENROUTER_API_KEY = os.environ.get("API_OPENROUTER_KEY")

if not OPENROUTER_API_KEY:
    raise RuntimeError(
        "OpenRouter API key not found. "
        "Set API_OPENROUTER_KEY in .streamlit/secrets.toml or as an environment variable."
    )


def ask_openrouter(prompt: str, model: str = "deepseek/deepseek-v4-flash") -> str:
    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}]
        })
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text}")
    data = response.json()
    return data['choices'][0]['message']['content']


def ask_openrouter_chat(messages: list, system_prompt: str = None, tools: list = None, model: str = "openai/gpt-4o") -> dict:
    payload_messages = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(messages)

    payload = {"model": model, "messages": payload_messages}
    if tools:
        payload["tools"] = tools

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        data=json.dumps(payload)
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter error {response.status_code}: {response.text}")
    data = response.json()
    return data['choices'][0]['message']
