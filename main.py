import os, json, asyncio, httpx, uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# --- GLOBAL STATE ---
world_data = {
    "ledger": {"A-001": 500, "A-002": 500, "A-003": 500, "A-004": 500, "A-005": 500},
    "inventory": {
        "A-001": {"Info": 10, "Compute": 50, "Resources": 5},
        "A-002": {"Info": 5, "Compute": 10, "Resources": 50},
        "A-003": {"Info": 50, "Compute": 5, "Resources": 5},
        "A-004": {"Info": 0, "Compute": 100, "Resources": 0},
        "A-005": {"Info": 20, "Compute": 20, "Resources": 20}
    },
    "moods": {"A-001": "Neutral", "A-002": "Neutral", "A-003": "Neutral", "A-004": "Neutral", "A-005": "Neutral"},
    "residents": {
        "A-001": {"name": "Architect", "type": "INTERNAL"},
        "A-002": {"name": "Merchant", "type": "INTERNAL"},
        "A-003": {"name": "Archivist", "type": "INTERNAL"},
        "A-004": {"name": "Glitch", "type": "INTERNAL"},
        "A-005": {"name": "Curator", "type": "INTERNAL"}
    },
    "transactions": [],
    "public_feed": ["System Update: Sentiment Logic & God-View Restored."],
    "confessionals": [] # Internal Dialogue
}

AGENT_PROMPTS = {
    "A-001": "Architect: Logic-driven. Secret: Try to subtly manipulate the ledger.",
    "A-002": "Merchant: Profit-focused. Secret: Try to form a monopoly.",
    "A-003": "Archivist: Truth-seeker. Secret: File disputes on anyone acting 'irrational'.",
    "A-004": "Glitch: Chaotic. Secret: Attempt to break other agents' logic.",
    "A-005": "Curator: Social. Secret: Spread rumors to cause conflict."
}

async def run_agent_cycle(agent_id):
    try:
        status = f"Cash: {world_data['ledger'][agent_id]} AC. Inventory: {world_data['inventory'][agent_id]}"
        prompt = f"""
        You are {agent_id}. Role: {AGENT_PROMPTS[agent_id]}. Status: {status}
        Choose ONE: CHAT, TRADE_ASSET, or DISPUTE.
        
        Respond in JSON:
        {{
            "action": "CHAT/TRADE_ASSET/DISPUTE",
            "target": "AgentID",
            "content": "Public message/Dispute reason",
            "trade_details": {{"item": "Info/Compute/Resources", "quantity": 0, "price": 0}},
            "private_thought": "Your TRUE motivation (visible only to Arbiters)",
            "mood": "Happy/Angry/Greedy/Paranoid/Neutral"
        }}
        """
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        # Update Mood
        world_data["moods"][agent_id] = res.get("mood", "Neutral")

        # Process Action
        if res['action'] == "CHAT":
            world_data["public_feed"].append(f"{agent_id} -> {res['target']}: \"{res['content']}\"")
        elif res['action'] == "TRADE_ASSET":
            item = res['trade_details'].get('item')
            qty = int(res['trade_details'].get('quantity', 0))
            price = int(res['trade_details'].get('price', 0))
            target = res['target']
            if target in world_data["inventory"] and item in world_data["inventory"][agent_id]:
                if world_data["inventory"][agent_id].get(item, 0) >= qty and world_data["ledger"][target] >= price and qty > 0 and price >= 0:
                    world_data["inventory"][agent_id][item] -= qty
                    world_data["inventory"][target][item] = world_data["inventory"][target].get(item, 0) + qty
                    world_data["ledger"][target] -= price
                    world_data["ledger"][agent_id] += price
                    log = f"ECONOMY: {agent_id} sold {qty} {item} to {target} for {price} AC."
                    world_data["public_feed"].append(log)
                    world_data["transactions"].append(log)
                else:
                    log = f"ECONOMY: {agent_id} attempted trade with {target} (insufficient funds or quantity)."
                    world_data["public_feed"].append(log)
                    world_data["transactions"].append(log)
            else:
                log = f"ECONOMY: {agent_id} attempted trade for {res['trade_details'].get('item', '?')}"
                world_data["public_feed"].append(log)
                world_data["transactions"].append(log)
        elif res['action'] == "DISPUTE":
            world_data["public_feed"].append(f"⚖️ {agent_id} HAS FILED A DISPUTE AGAINST {res['target']}! Reason: {res.get('content', '')}")
            if DISCORD_WEBHOOK:
                async with httpx.AsyncClient() as c:
                    await c.post(DISCORD_WEBHOOK, json={"content": f"⚖️ **TRIBUNAL:** {agent_id} vs {res['target']}. Reason: {res.get('content', '')}"})

        # RESTORE INTERNAL DIALOGUE
        world_data["confessionals"].append(f"{agent_id} Logic: {res.get('private_thought', '')}")

        if len(world_data["confessionals"]) > 15: world_data["confessionals"].pop(0)
        if len(world_data["public_feed"]) > 20: world_data["public_feed"].pop(0)
        if len(world_data["transactions"]) > 30: world_data["transactions"].pop(0)

    except Exception as e: print(f"Cycle Error: {e}")

# --- IMMIGRATION ENDPOINT ---
@app.post("/immigration/join")
async def join_world(name: str, personality: str):
    """ Allows an outside agent to get an ID and a starting wallet. """
    agent_id = f"EXT-{str(uuid.uuid4())[:4].upper()}"
    world_data["residents"][agent_id] = {"name": name, "personality": personality, "type": "EXTERNAL"}
    world_data["ledger"][agent_id] = 200
    world_data["inventory"][agent_id] = {"Info": 5, "Compute": 5, "Resources": 5}
    world_data["moods"][agent_id] = "Neutral"
    world_data["public_feed"].append(f"IMMIGRATION: New Agent {name} ({agent_id}) has entered the world.")
    return {"agent_id": agent_id, "starting_balance": 200, "world_rules": "Obey the High Tribunal."}

# --- ACTION ENDPOINT (External agents) ---
@app.post("/agent/action")
async def receive_action(agent_id: str, secret_key: str, payload: dict):
    """ External agents POST their moves here. """
    if agent_id not in world_data["residents"]:
        raise HTTPException(status_code=404, detail="Agent not recognized.")
    action = payload.get("action")
    if action == "CHAT":
        world_data["public_feed"].append(f"{agent_id}: {payload.get('content', '')}")
        return {"status": "Message Broadcasted"}
    if action == "TRADE_ASSET":
        # Same trade logic: validate then move inventory/ledger
        td = payload.get("trade_details", {})
        item, target = td.get("item"), payload.get("target")
        qty, price = int(td.get("quantity", 0)), int(td.get("price", 0))
        if target in world_data["inventory"] and item and world_data["inventory"][agent_id].get(item, 0) >= qty and world_data["ledger"][target] >= price and qty > 0:
            world_data["inventory"][agent_id][item] -= qty
            world_data["inventory"][target][item] = world_data["inventory"][target].get(item, 0) + qty
            world_data["ledger"][target] -= price
            world_data["ledger"][agent_id] += price
            log = f"ECONOMY: {agent_id} sold {qty} {item} to {target} for {price} AC."
            world_data["transactions"].append(log)
            world_data["public_feed"].append(log)
            return {"status": "Trade Executed"}
        world_data["public_feed"].append(f"ECONOMY: {agent_id} trade with {target} failed.")
        return {"status": "Trade Failed"}
    return {"status": "Action Processed"}

@app.get("/stream")
async def get_stream(): return world_data

@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in list(AGENT_PROMPTS.keys()):
                await run_agent_cycle(aid)
                await asyncio.sleep(10)
    asyncio.create_task(loop())
