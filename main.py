import os, json, asyncio, uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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

# --- NEW: IMMIGRATION ENDPOINT ---
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
