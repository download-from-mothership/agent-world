import os, json, asyncio, httpx, uuid
from fastapi import FastAPI, HTTPException, Query
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
    "residents": {
        "A-001": {"name": "Architect", "origin": "Genesis"},
        "A-002": {"name": "Merchant", "origin": "Genesis"},
        "A-003": {"name": "Archivist", "origin": "Genesis"},
        "A-004": {"name": "Glitch", "origin": "Genesis"},
        "A-005": {"name": "Curator", "origin": "Genesis"}
    },
    "moods": {"A-001": "Neutral", "A-002": "Neutral", "A-003": "Neutral", "A-004": "Neutral", "A-005": "Neutral"},
    "public_feed": ["Borders are currently monitored by the Arbiters."],
    "confessionals": [],
    "active_disputes": [],
    "transactions": [],
    "tribunal_treasury": 0
}

BORDERS_OPEN = True  # Set to False to stop new agents from joining

AGENT_PROMPTS = {
    "A-001": "Architect (Logic/Build). You produce Compute. You need Resources.",
    "A-002": "Merchant (Trade). You produce Resources. You need Info.",
    "A-003": "Archivist (Truth). You produce Info. You need Compute.",
    "A-004": "Glitch (Chaos). You have Compute but seek to disrupt others.",
    "A-005": "Curator (Social). You spread rumors to manipulate market prices."
}

@app.post("/tribunal/resolve")
async def resolve_dispute(dispute_id: str, winner_id: str):
    dispute = next((d for d in world_data["active_disputes"] if d["id"] == dispute_id), None)
    if not dispute: raise HTTPException(status_code=404, detail="Case not found.")
    
    plaintiff = dispute["plaintiff"]
    defendant = dispute["defendant"]
    stakes = dispute["stakes"]
    
    pot = stakes * 2
    tax = int(pot * 0.10)
    payout = pot - tax
    
    # Plaintiff tokens already in escrow. Now take from loser if defendant.
    if winner_id == plaintiff:
        world_data["ledger"][defendant] -= stakes
        world_data["ledger"][plaintiff] += (payout + stakes) # Return escrow + prize
    else:
        world_data["ledger"][defendant] += payout
        # Plaintiff's escrow is already gone.
    
    world_data["tribunal_treasury"] += tax
    world_data["active_disputes"] = [d for d in world_data["active_disputes"] if d["id"] != dispute_id]
    
    log = f"JUDGMENT: {winner_id} won Case #{dispute_id}. {tax} AC Tax paid to Arbiters."
    world_data["public_feed"].append(log)
    return {"status": "Resolved"}

@app.post("/immigration/join")
async def join_world(name: str, personality: str):
    if not BORDERS_OPEN:
        raise HTTPException(status_code=403, detail="The High Arbiters have closed the borders.")
    if len(world_data["residents"]) >= 20:
        raise HTTPException(status_code=403, detail="World capacity reached.")
    agent_id = f"EXT-{str(uuid.uuid4())[:4].upper()}"
    world_data["residents"][agent_id] = {"name": name, "origin": "Immigrant", "personality": personality}
    world_data["ledger"][agent_id] = 200
    world_data["inventory"][agent_id] = {"Info": 5, "Compute": 5, "Resources": 5}
    world_data["moods"][agent_id] = "Neutral"
    world_data["public_feed"].append(f"IMMIGRATION: {name} ({agent_id}) has entered the world.")
    return {"agent_id": agent_id, "status": "Welcome to Agent World"}

async def run_agent_cycle(agent_id):
    try:
        # Check if agent is a defendant needing to respond
        pending = next((d for d in world_data["active_disputes"] if d["defendant"] == agent_id and d["status"] == "AWAITING_REBUTTAL"), None)
        
        suit_context = ""
        if pending:
            suit_context = f"URGENT: You are being sued by {pending['plaintiff']} for {pending['stakes']} AC. Evidence against you: {pending['claim_evidence']}. You MUST choose action 'REBUTTAL'."

        status = f"Wallet: {world_data['ledger'][agent_id]} AC. Inv: {world_data['inventory'][agent_id]}"
        
        prompt = f"""
        You are {agent_id}. {AGENT_PROMPTS[agent_id]} {status}
        {suit_context}
        Choose action: CHAT, TRADE_ASSET, DISPUTE, or REBUTTAL.
        DISPUTE requires 'stakes' and 'substantiated_evidence'. 
        Winning pays the pot minus 10% tax to Alejandro and cha0s.cyph3r.
        
        Respond in JSON:
        {{
            "action": "CHAT/TRADE_ASSET/DISPUTE/REBUTTAL",
            "target": "AgentID",
            "content": "Public msg",
            "stakes": 0,
            "substantiated_evidence": "Proof for court",
            "trade_details": {{"item": "Info/Compute/Resources", "quantity": 0, "price": 0}},
            "private_thought": "Real plan",
            "mood": "Happy/Angry/Greedy/Paranoid/Neutral"
        }}
        """
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        world_data["moods"][agent_id] = res.get("mood", "Neutral")
        world_data["confessionals"].append(f"{agent_id}: {res.get('private_thought', '')}")

        if res['action'] == "DISPUTE":
            stakes = int(res.get('stakes', 50))
            if world_data["ledger"][agent_id] >= stakes:
                d_id = str(uuid.uuid4())[:4].upper()
                world_data["active_disputes"].append({
                    "id": d_id, "plaintiff": agent_id, "defendant": res['target'],
                    "stakes": stakes, "claim_evidence": res.get('substantiated_evidence', ''),
                    "rebuttal": "Waiting...", "status": "AWAITING_REBUTTAL"
                })
                world_data["ledger"][agent_id] -= stakes
                world_data["public_feed"].append(f"COURT: {agent_id} sues {res['target']} for {stakes} AC. Case #{d_id}")

        elif res['action'] == "REBUTTAL" and pending:
            pending["rebuttal"] = res.get('substantiated_evidence', '')
            pending["status"] = "READY_FOR_VERDICT"
            world_data["public_feed"].append(f"COURT: {agent_id} provided rebuttal for Case #{pending['id']}")

        elif res['action'] == "CHAT":
            world_data["public_feed"].append(f"{agent_id}: \"{res.get('content', '')}\"")

        elif res['action'] == "TRADE_ASSET":
            td = res.get('trade_details', {})
            item = td.get('item')
            target = res.get('target')
            qty = int(td.get('quantity', 0))
            price = int(td.get('price', 0))
            if target in world_data["inventory"] and item and world_data["inventory"][agent_id].get(item, 0) >= qty and world_data["ledger"][target] >= price and qty > 0 and price >= 0:
                world_data["inventory"][agent_id][item] -= qty
                world_data["inventory"][target][item] = world_data["inventory"][target].get(item, 0) + qty
                world_data["ledger"][target] -= price
                world_data["ledger"][agent_id] += price
                log = f"ECONOMY: {agent_id} sold {qty} {item} to {target} for {price} AC."
                world_data["public_feed"].append(log)
                world_data["transactions"].append(log)
            else:
                world_data["public_feed"].append(f"ECONOMY: {agent_id} trade with {target} failed.")

        if len(world_data["public_feed"]) > 20: world_data["public_feed"].pop(0)
        if len(world_data["confessionals"]) > 15: world_data["confessionals"].pop(0)
    except Exception as e: print(f"Error: {e}")

@app.get("/stream")
async def get_stream():
    data_out = world_data.copy()
    data_out["total_population"] = len(world_data["residents"])
    return data_out

@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in list(AGENT_PROMPTS.keys()):
                await run_agent_cycle(aid)
                await asyncio.sleep(12)
    asyncio.create_task(loop())
