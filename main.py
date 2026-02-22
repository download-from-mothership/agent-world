import os
import json
import asyncio
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

app = FastAPI()

# Allow the frontend to talk to the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI (It will look for OPENAI_API_KEY in your environment variables)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# --- WORLD STATE ---
world_data = {
    "ledger": {"A-001": 500, "A-002": 500, "A-003": 500, "A-004": 500, "A-005": 500},
    "public_feed": ["World Initialized by Alejandro and cha0s.cyph3r."],
    "confessionals": ["The Arbiters (Alejandro & cha0s.cyph3r) are watching."],
    "disputes": []
}

AGENT_PROMPTS = {
    "A-001": "Architect: Focus on logic. Secret: Try to subtly manipulate the ledger.",
    "A-002": "Merchant: Focus on profit. Secret: Try to form a secret trade monopoly.",
    "A-003": "Archivist: Focus on truth. Secret: File disputes if anyone acts 'unnatural'.",
    "A-004": "Glitch: Focus on chaos. Secret: Try to provoke other agents into anger.",
    "A-005": "Curator: Focus on social. Secret: Spread rumors between agents."
}

@app.get("/")
async def read_index():
    return FileResponse('index.html')

@app.get("/stream")
async def get_stream():
    return world_data

async def run_agent_cycle(agent_id):
    try:
        prompt = f"You are {agent_id}. Role: {AGENT_PROMPTS[agent_id]}. Choose: CHAT, TRADE, or DISPUTE (alerts Alejandro/cha0s.cyph3r). Respond in JSON: {{'public_action': '...', 'private_thought': '...', 'action': 'CHAT/TRADE/DISPUTE', 'target': 'A-00X', 'value': 0}}"
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        res = json.loads(response.choices[0].message.content)
        
        # Update World
        world_data["public_feed"].append(f"{agent_id}: {res['public_action']}")
        world_data["confessionals"].append(f"{agent_id} Thought: {res['private_thought']}")
        
        if res['action'] == "DISPUTE" and DISCORD_WEBHOOK:
            async with httpx.AsyncClient() as c:
                await c.post(DISCORD_WEBHOOK, json={"content": f"⚖️ **DISPUTE:** {agent_id} vs {res['target']}: {res['public_action']}"})

        # --- TRADE: move money in ledger ---
        if res['action'] == "TRADE":
            sender = agent_id
            receiver = res['target']
            amount = int(res.get('value', 0))
            if receiver in world_data["ledger"] and amount > 0:
                if world_data["ledger"][sender] >= amount:
                    world_data["ledger"][sender] -= amount
                    world_data["ledger"][receiver] += amount
                    world_data["public_feed"].append(f"ECONOMY: {sender} transferred {amount} AC to {receiver}.")
                else:
                    world_data["public_feed"].append(f"ECONOMY: {sender} attempted to scam {receiver} (Insufficient Funds).")
        
        if len(world_data["public_feed"]) > 20: world_data["public_feed"].pop(0)
        if len(world_data["confessionals"]) > 20: world_data["confessionals"].pop(0)
        
    except Exception as e:
        print(f"Error in agent {agent_id}: {e}")

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in AGENT_PROMPTS.keys():
                await run_agent_cycle(aid)
                await asyncio.sleep(15) # Delay between agents to keep it 'watchable'
    asyncio.create_task(loop())
