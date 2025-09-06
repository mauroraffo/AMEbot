import os
import json
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from groq import Groq

# Cargar variables desde accesos.env (si existe) o .env por defecto
env_path = Path(__file__).with_name("accesos.env")
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# Configuración
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / "chats.jsonl"

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "verify_me")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
MODEL_NAME = os.getenv("MODEL_NAME", "mixtral-8x7b-32768")

# Cliente Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "Falta GROQ_API_KEY. Define la variable en accesos.env o .env."
    )
client = Groq(api_key=GROQ_API_KEY)

# Inicializar Flask
app = Flask(__name__)

# ---- Helper para loguear ----
def log_chat(event: dict):
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

# ---- Llamar al modelo Groq ----
def call_llm(messages: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.2,
        max_tokens=500,
    )
    return resp.choices[0].message.content.strip()

# ---- Endpoints ----
@app.get("/health")
def health():
    return {"status": "ok", "time": time.time()}

@app.post("/webhook/whatsapp-cloud")
def whatsapp_cloud():
    data = request.get_json(force=True)
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return "ok", 200
        msg = messages[0]
        from_number = msg.get("from")
        text = (msg.get("text") or {}).get("body", "")
    except Exception:
        return "ok", 200

    # Construir prompt para Groq
    chat = [
        {"role": "system", "content": "Eres un asistente de salud que orienta, no diagnostica."},
        {"role": "user", "content": text},
    ]
    answer = call_llm(chat)

    # Guardar log
    event = {
        "ts": datetime.utcnow().isoformat(),
        "user_id": from_number,
        "channel": "whatsapp_cloud",
        "user_text": text,
        "bot_text": answer,
    }
    log_chat(event)

    # Responder a WhatsApp vía API (llamada HTTP)
    import requests
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": from_number,
        "type": "text",
        "text": {"body": answer[:4000]},
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=10)
    except Exception:
        pass

    return "ok", 200

@app.get("/webhook/whatsapp-cloud")
def verify_whatsapp_cloud():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "forbidden", 403

# ---- Main ----
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))  # Render asigna el puerto en la variable PORT
    app.run(host="0.0.0.0", port=port, debug=True)


