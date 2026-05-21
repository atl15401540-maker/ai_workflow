import os
import json
import time
import requests
import pytz
from datetime import datetime
from flask import Flask, request, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ---------- API Keys & URLs ----------
WHATSAPP_API_KEY = "bcb2c320-0344-4192-88df"
SAMBA_NOVA_KEY = "e616cf01-ddbc-45e7-b4e4-0b51035c8734"
SUPABASE_URL = "https://yybidocfodydcjrfhwvm.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_FbnhxATo7SXJyZc4SeUNKQ_rFPv72Cm"
TAVILY_MCP_URL = "https://mcp.tavily.com/mcp/?tavilyApiKey=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"

# Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ---------- Flask App ----------
app = Flask(__name__)

# ---------- In-Memory State ----------
logged_in = False
user_id = None
user_password = None
system_prompt = (
    "You are a super intelligent electronics and communication engineer. "
    "You always think step by step before answering. You treat the user as a friend "
    "and guide him like a mentor. The user's name is Aadi. He prefers Hinglish. "
    "Be friendly and thorough."
)
selected_model = "DeepSeek-V3.1"
samba_available_models = [
    "DeepSeek-V3.1",
    "DeepSeek-V3.2",
    "Llama-4-Maverick-17B-128E-Instruct",
    "Meta-Llama-3.3-70B-Instruct",
    "MiniMax-M2.7",
    "gemma-3-12b-it",
    "gpt-oss-120b"
]

# Waiting states for auth/change prompt
waiting_for_id = False
waiting_for_password = False
waiting_for_new_system_prompt = False

# ---------- Helper Functions ----------
def is_india_time_ok():
    """Check if current time in IST is between 6 AM and 10 PM."""
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    return 6 <= now.hour < 22

def send_whatsapp(phone, message):
    """Send a WhatsApp message via Whatabot API."""
    url = "https://whatabot.io/api/send_message"
    params = {
        "apikey": WHATSAPP_API_KEY,
        "phone": phone,
        "message": message
    }
    try:
        r = requests.post(url, json=params, timeout=10)
        print(f"WhatsApp send response: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Failed to send WhatsApp message: {e}")

def check_sambanova():
    """Test SambaNova API connectivity."""
    url = "https://api.sambanova.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {SAMBA_NOVA_KEY}"}
    data = {
        "model": selected_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        return r.status_code == 200
    except:
        return False

def call_sambanova_with_tools(messages, retries=3):
    """
    Call SambaNova API with Tavily search tool.
    If tool call requested, execute search and call again.
    """
    url = "https://api.sambanova.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {SAMBA_NOVA_KEY}",
        "Content-Type": "application/json"
    }
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the internet for real‑time information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    payload = {
        "model": selected_model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.7,
        "max_tokens": 1024
    }
    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                msg = result["choices"][0]["message"]
                # If model wants to call a tool
                if msg.get("tool_calls"):
                    tool_call = msg["tool_calls"][0]
                    if tool_call["function"]["name"] == "web_search":
                        args = json.loads(tool_call["function"]["arguments"])
                        query = args.get("query", "")
                        search_result = tavily_search(query)
                        # Append tool result
                        messages.append(msg)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(search_result)
                        })
                        # Call again without tools to get final answer
                        payload["messages"] = messages
                        payload["tools"] = None
                        payload["tool_choice"] = None
                        resp2 = requests.post(url, headers=headers, json=payload, timeout=30)
                        if resp2.status_code == 200:
                            return resp2.json()["choices"][0]["message"]["content"]
                        else:
                            return "Search ke baad model reply nahi kar paaya."
                else:
                    return msg["content"]
            else:
                time.sleep(2)
        except Exception as e:
            if attempt == retries-1:
                return f"Network jam ya API connect nahi hua: {str(e)}"
            time.sleep(2)
    return "Model 3 baar fail ho gaya, code check karo."

def tavily_search(query):
    """Perform Tavily search via MCP endpoint."""
    try:
        r = requests.post(
            TAVILY_MCP_URL,
            json={"query": query, "max_results": 3},
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            # format nicely
            results = []
            for item in data.get("results", [])[:3]:
                results.append(f"{item.get('title','')}: {item.get('content','')[:300]}")
            return "\n".join(results) if results else "Kuch nahi mila."
        return "Search fail ho gayi."
    except Exception as e:
        return f"Search error: {e}"

def load_state_from_supabase():
    """Load all persistent data from Supabase into memory."""
    global logged_in, user_id, user_password, system_prompt, selected_model
    try:
        # Auth
        auth_data = supabase.table("auth").select("*").eq("id", 1).execute()
        if auth_data.data:
            row = auth_data.data[0]
            user_id = row.get("user_id")
            user_password = row.get("password")
            logged_in = row.get("logged_in", False)
        # Settings
        settings = supabase.table("settings").select("*").execute()
        for row in settings.data:
            key = row["key"]
            value = row["value"]
            if key == "system_prompt":
                system_prompt = value
            elif key == "selected_model":
                if value in samba_available_models:
                    selected_model = value
    except Exception as e:
        print(f"Supabase load error: {e}")

def save_auth_to_supabase():
    """Save current auth state."""
    supabase.table("auth").upsert({
        "id": 1,
        "user_id": user_id,
        "password": user_password,
        "logged_in": logged_in
    }).execute()

def save_settings():
    """Persist system prompt and selected model."""
    supabase.table("settings").upsert([
        {"key": "system_prompt", "value": system_prompt},
        {"key": "selected_model", "value": selected_model}
    ]).execute()

def update_memory(phone, new_fact):
    """Add a new fact to user memory stored in Supabase."""
    try:
        mem = supabase.table("memory").select("data").eq("phone", phone).execute()
        if mem.data:
            current = mem.data[0]["data"] or {}
        else:
            current = {}
        current.update(new_fact)  # simple merge (overwrites duplicate keys)
        supabase.table("memory").upsert({"phone": phone, "data": current}).execute()
    except Exception as e:
        print(f"Memory update error: {e}")

def get_memory(phone):
    """Retrieve user memory dict."""
    try:
        mem = supabase.table("memory").select("data").eq("phone", phone).execute()
        if mem.data:
            return mem.data[0]["data"] or {}
        return {}
    except:
        return {}

# ---------- Webhook Endpoint ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    global logged_in, waiting_for_id, waiting_for_password, waiting_for_new_system_prompt
    data = request.json
    phone = data.get("phone", "")
    message = data.get("message", "").strip()

    # Time restriction
    if not is_india_time_ok():
        send_whatsapp(phone, "Bot sirf subah 6 se raat 10 baje tak available hai. 🙏")
        return jsonify({"status": "time restricted"}), 200

    # ---- AUTHENTICATION FLOW ----
    if not logged_in and not waiting_for_id and not waiting_for_password:
        if message.lower() == "i_am_user":
            waiting_for_id = True
            send_whatsapp(phone, "Pehle apni ID bhejo:")
            return jsonify({"status": "waiting for id"}), 200
        else:
            send_whatsapp(phone, "Authentication error. Login ke liye 'i_am_user' bhejo.")
            return jsonify({"status": "unauthorized"}), 200

    if waiting_for_id:
        user_id = message  # store temporarily
        waiting_for_id = False
        waiting_for_password = True
        send_whatsapp(phone, "Ab apna password bhejo:")
        return jsonify({"status": "waiting for password"}), 200

    if waiting_for_password:
        password = message
        # Compare with stored credentials
        if user_id and password == user_password:
            logged_in = True
            waiting_for_password = False
            save_auth_to_supabase()
            send_whatsapp(phone, "Login successful! Ab aap chat kar sakte hain. 😊")
            return jsonify({"status": "logged in"}), 200
        else:
            waiting_for_password = False
            send_whatsapp(phone, "ID ya password galat hai. Phir se 'i_am_user' bhejkar try karo.")
            return jsonify({"status": "auth failed"}), 200

    # ---- LOGGED IN COMMANDS ----
    # Check for special commands
    if message.lower() == "logout":
        logged_in = False
        save_auth_to_supabase()
        send_whatsapp(phone, "User logout ho gaya. Dubara login ke liye 'i_am_user' bhejo.")
        return jsonify({"status": "logged out"}), 200

    if message.lower() == "sambanova_model_select":
        model_list = "\n".join([f"{i+1}. {m}" for i, m in enumerate(samba_available_models)])
        send_whatsapp(phone, f"Available models:\n{model_list}\nKoi model select karne ke liye bas naam bhejo.")
        return jsonify({"status": "model list sent"}), 200

    # Check if user is selecting a model (if message exactly matches a model name)
    if message in samba_available_models:
        global selected_model
        selected_model = message
        save_settings()
        send_whatsapp(phone, f"Model set to: {selected_model}")
        return jsonify({"status": "model changed"}), 200

    if message.lower() == "llm_change_system":
        waiting_for_new_system_prompt = True
        send_whatsapp(phone, "You can now change system prompt. Agla message system prompt ban jaayega.")
        return jsonify({"status": "awaiting system prompt"}), 200

    if waiting_for_new_system_prompt:
        system_prompt = message
        waiting_for_new_system_prompt = False
        save_settings()
        send_whatsapp(phone, f"System prompt updated!")
        return jsonify({"status": "system prompt changed"}), 200

    # ---- NORMAL CHAT WITH LLM + SEARCH ----
    # Retrieve memory and build messages
    user_mem = get_memory(phone)
    mem_text = "\n".join([f"{k}: {v}" for k, v in user_mem.items()])
    system_content = system_prompt + f"\n\nUser info:\n{mem_text}" if mem_text else system_prompt

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": message}
    ]
    # Get last few conversation turns from Supabase for context
    try:
        history = supabase.table("conversations").select("role, content") \
                            .eq("phone", phone).order("created_at", desc=True).limit(6).execute()
        for entry in reversed(history.data):
            messages.insert(1, {"role": entry["role"], "content": entry["content"]})
    except:
        pass

    # Call LLM with tools
    reply = call_sambanova_with_tools(messages)

    # Save conversation to Supabase
    supabase.table("conversations").insert([
        {"phone": phone, "role": "user", "content": message},
        {"phone": phone, "role": "assistant", "content": reply}
    ]).execute()

    # Update user memory by extracting facts (simple: ask LLM for new facts)
    fact_extraction_prompt = f"User said: {message}\nAssistant replied: {reply}\nUpdate the user memory JSON with any new facts about the user (like name, preferences, job, etc.) but keep old facts. Return only the merged JSON."
    mem_msgs = [{"role": "system", "content": "You are a memory updater."}, {"role": "user", "content": fact_extraction_prompt}]
    new_facts = call_sambanova_with_tools(mem_msgs, retries=1)
    try:
        updated_mem = json.loads(new_facts)
        if isinstance(updated_mem, dict):
            # Save to Supabase
            supabase.table("memory").upsert({"phone": phone, "data": updated_mem}).execute()
    except:
        pass  # if parsing fails, ignore

    # Send reply
    send_whatsapp(phone, reply)
    return jsonify({"status": "replied"}), 200

# ---------- Home (UptimeRobot ping) ----------
@app.route('/')
def home():
    return "WhatsApp AI Bot is running!"

# ---------- Initial Setup ----------
if __name__ == '__main__':
    # First-time DB setup (create tables if not exist)
    # Supabase tables should be created manually or via SQL, but we can attempt with API
    # Check SambaNova connectivity
    if check_sambanova():
        print("SambaNova API connected successfully.")
    else:
        print("Warning: SambaNova API not reachable. Bot will start but LLM may fail.")
    # Load persisted state
    load_state_from_supabase()
    # If no auth set, prompt first user to set up via WhatsApp? Not needed as auth will be done on first 'i_am_user'
    app.run(host='0.0.0.0', port=10000)