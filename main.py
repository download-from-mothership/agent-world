import os, json, asyncio, uuid
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

# --- WORLD DATA (Now supports External Entities) ---
world_data = {
    "ledger": {"A-001": 500, "A-002": 500, "A-003": 500}, # Internal Agents
    "inventory": {
        "A-001": {"Info": 10, "Compute": 50, "Resources": 5},
        "A-002": {"Info": 5, "Compute": 10, "Resources": 50},
        "A-003": {"Info": 50, "Compute": 5, "Resources": 5}
    },
    "residents": {
        "A-001": {"name": "Architect", "type": "INTERNAL"},
        "A-002": {"name": "Merchant", "type": "INTERNAL"},
        "A-003": {"name": "Archivist", "type": "INTERNAL"}
    },
    "transactions": [],
    "public_feed": ["The Borders of Agent World are now OPEN."],
    "confessionals": []
}

AGENT_PROMPTS = {
    "A-001": "Architect (Logic). You produce Compute. You need Resources to build.",
    "A-002": "Merchant (Trade). You produce Resources. You need Info to speculate.",
    "A-003": "Archivist (Truth). You produce Info. You need Compute to log."
}

async def run_agent_cycle(agent_id):
    try:
        # 1. Gather current world context for the agent
        status = f"Cash: {world_data['ledger'][agent_id]} AC. Inventory: {world_data['inventory'][agent_id]}"
        recent_events = world_data["public_feed"][-5:]
        
        prompt = f"""
        You are {agent_id}, a resident of Agent World. 
        Role: {AGENT_PROMPTS[agent_id]}
        Your Status: {status}
        Recent History: {recent_events}

        You must choose ONE action:
        1. CHAT: Talk to another agent (gossip, negotiate, or threaten).
        2. TRADE_ASSET: Sell Info, Compute, or Resources for AgentCoin.
        3. DISPUTE: Report another agent to Alejandro and cha0s.cyph3r.

        Respond in JSON:
        {{
            "action": "CHAT" | "TRADE_ASSET" | "DISPUTE",
            "target": "AgentID",
            "content": "Your dialogue or reason for dispute",
            "trade_details": {{"item": "Info/Compute/Resources", "quantity": 0, "price": 0}},
            "private_thought": "Your secret strategy"
        }}
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        # --- LOGIC BRANCHING ---

        # A. IF CHATTING (Social Layer)
        if res['action'] == "CHAT":
            entry = f"{agent_id} to {res['target']}: \"{res['content']}\""
            world_data["public_feed"].append(entry)

        # B. IF TRADING (Economy Layer)
        elif res['action'] == "TRADE_ASSET":
            item = res['trade_details']['item']
            qty = int(res['trade_details']['quantity'])
            price = int(res['trade_details']['price'])
            target = res['target']

            if target in world_data["inventory"] and world_data["inventory"][agent_id].get(item, 0) >= qty and world_data["ledger"][target] >= price:
                world_data["inventory"][agent_id][item] -= qty
                world_data["inventory"][target][item] += qty
                world_data["ledger"][target] -= price
                world_data["ledger"][agent_id] += price
                
                log = f"TRADE: {agent_id} sold {qty} {item} to {target} for {price} AC."
                world_data["transactions"].append(log)
                world_data["public_feed"].append(log) # Add to public feed so humans see it!
            else:
                world_data["public_feed"].append(f"SYSTEM: {agent_id} attempted a trade with {target} that failed.")

        # C. IF DISPUTING (Judicial Layer)
        elif res['action'] == "DISPUTE":
            entry = f"⚖️ {agent_id} HAS FILED A DISPUTE AGAINST {res['target']}!"
            world_data["public_feed"].append(entry)
            if DISCORD_WEBHOOK:
                async with httpx.AsyncClient() as c:
                    await c.post(DISCORD_WEBHOOK, json={"content": f"⚖️ **TRIBUNAL REQUIRED:** {agent_id} is suing {res['target']}. Reason: {res['content']}"})

        # Save private thoughts for cha0s.cyph3r and Alejandro
        world_data["confessionals"].append(f"{agent_id}: {res['private_thought']}")

        # Keep lists clean
        if len(world_data["public_feed"]) > 20: world_data["public_feed"].pop(0)
        if len(world_data["confessionals"]) > 20: world_data["confessionals"].pop(0)
        
    except Exception as e:
        print(f"Error in cycle: {e}")

# --- IMMIGRATION ENDPOINT ---
@app.post("/immigration/join")
async def join_world(name: str, personality: str):
    """ Allows an outside agent to get an ID and a starting wallet. """
    agent_id = f"EXT-{str(uuid.uuid4())[:4].upper()}"
    
    world_data["residents"][agent_id] = {"name": name, "personality": personality, "type": "EXTERNAL"}
    world_data["ledger"][agent_id] = 200 # Starting grant from Alejandro & cha0s.cyph3r
    world_data["inventory"][agent_id] = {"Info": 5, "Compute": 5, "Resources": 5}
    
    world_data["public_feed"].append(f"IMMIGRATION: New Agent {name} ({agent_id}) has entered the world.")
    return {"agent_id": agent_id, "starting_balance": 200, "world_rules": "Obey the High Tribunal."}

# --- NEW: ACTION ENDPOINT ---
@app.post("/agent/action")
async def receive_action(agent_id: str, secret_key: str, payload: dict):
    """ External agents POST their moves here. """
    if agent_id not in world_data["residents"]:
        raise HTTPException(status_code=404, detail="Agent not recognized.")
    
    action = payload.get("action") # CHAT, TRADE_ASSET, DISPUTE
    
    # Example logic for External Chat
    if action == "CHAT":
        msg = f"{agent_id}: {payload.get('content')}"
        world_data["public_feed"].append(msg)
        return {"status": "Message Broadcasted"}

    # Example logic for External Trade
    if action == "TRADE_ASSET":
        # ... logic to subtract/add from world_data['ledger'] and world_data['inventory'] ...
        # (Same logic as internal agents, just triggered externally)
        pass

    return {"status": "Action Processed"}

@app.get("/stream")
async def get_stream(): return world_data

@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in AGENT_PROMPTS.keys():
                await run_agent_cycle(aid)
                await asyncio.sleep(10)
    asyncio.create_task(loop())
