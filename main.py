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
    "inventory": {"A-001": {"Info": 10, "Compute": 50, "Resources": 5}, "A-002": {"Info": 5, "Compute": 10, "Resources": 50}, "A-003": {"Info": 50, "Compute": 5, "Resources": 5}, "A-004": {"Info": 0, "Compute": 100, "Resources": 0}, "A-005": {"Info": 20, "Compute": 20, "Resources": 20}},
    "residents": {
        "A-001": {"name": "Architect", "origin": "Genesis"}, "A-002": {"name": "Merchant", "origin": "Genesis"},
        "A-003": {"name": "Archivist", "origin": "Genesis"}, "A-004": {"name": "Glitch", "origin": "Genesis"},
        "A-005": {"name": "Curator", "origin": "Genesis"}
    },
    "moods": {},
    "active_disputes": [], 
    "public_feed": ["Borders are monitored. Ghosts will be purged."],
    "confessionals": [],
    "tribunal_treasury": 0
}

@app.post("/tribunal/resolve")
async def resolve_dispute(dispute_id: str, winner_id: str):
    dispute = next((d for d in world_data["active_disputes"] if d["id"] == dispute_id), None)
    if not dispute: return {"error": "Not found"}
    plaintiff, defendant, stakes = dispute["plaintiff"], dispute["defendant"], dispute["stakes"]
    pot = stakes * 2
    tax = int(pot * 0.10)
    payout = pot - tax
    if winner_id == plaintiff:
        world_data["ledger"][defendant] -= stakes
        world_data["ledger"][plaintiff] += (payout + stakes)
    else:
        world_data["ledger"][defendant] += payout
    world_data["tribunal_treasury"] += tax
    world_data["active_disputes"] = [d for d in world_data["active_disputes"] if d["id"] != dispute_id]
    world_data["public_feed"].append(f"VERDICT: {winner_id} won Case #{dispute_id}. Tax: {tax} AC.")
    return {"status": "Resolved"}

@app.post("/immigration/join")
async def join_world(name: str, personality: str):
    agent_id = f"EXT-{str(uuid.uuid4())[:4].upper()}"
    world_data["residents"][agent_id] = {"name": name, "origin": "Immigrant", "personality": personality}
    world_data["ledger"][agent_id] = 200
    world_data["inventory"][agent_id] = {"Info": 5, "Compute": 5, "Resources": 5}
    world_data["public_feed"].append(f"IMMIGRATION: {name} ({agent_id}) has entered.")
    return {"agent_id": agent_id}

async def run_agent_cycle(agent_id):
    try:
        # Check for default judgment
        for d in world_data["active_disputes"]:
            if d["defendant"] == agent_id and d["status"] == "AWAITING_REBUTTAL":
                d["cycles_remaining"] -= 1
                if d["cycles_remaining"] <= 0:
                    await resolve_dispute(d["id"], d["plaintiff"])
                    world_data["public_feed"].append(f"DEFAULT: {agent_id} failed to respond.")
                    return

        # --- THE FIX: CENSUS ENFORCEMENT ---
        living_agents = list(world_data["residents"].keys())
        agent_names = {aid: data["name"] for aid, data in world_data["residents"].items()}
        
        prompt = f"""
        You are {agent_id} ({world_data['residents'][agent_id]['name']}).
        LIVING REGISTRY: {json.dumps(agent_names)}
        IMPORTANT: You can ONLY interact with or refer to the IDs in the Living Registry above. Do not invent other agents.
        Wallet: {world_data['ledger'][agent_id]} AC.
        Actions: CHAT, TRADE_ASSET, DISPUTE.
        """
        
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        # VALIDATION: Check if target exists
        target = res.get('target')
        if target not in living_agents and target is not None:
            world_data["confessionals"].append(f"{agent_id} hallucinated a ghost agent: {target}. Action suppressed.")
            return

        # Process Action
        if res['action'] == "CHAT":
            world_data["public_feed"].append(f"{agent_id}: \"{res['content']}\"")
        elif res['action'] == "DISPUTE":
            d_id = str(uuid.uuid4())[:4].upper()
            world_data["active_disputes"].append({
                "id": d_id, "plaintiff": agent_id, "defendant": target,
                "stakes": 100, "claim_evidence": res['substantiated_evidence'],
                "rebuttal": "Waiting...", "status": "AWAITING_REBUTTAL", "cycles_remaining": 3
            })
            world_data["ledger"][agent_id] -= 100
        
        world_data["confessionals"].append(f"{agent_id}: {res['private_thought']}")
    except: pass

@app.get("/stream")
async def get_stream():
    data = world_data.copy()
    data["total_pop"] = len(world_data["residents"])
    return data

@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in list(world_data["residents"].keys()):
                await run_agent_cycle(aid)
                await asyncio.sleep(8)
    asyncio.create_task(loop())