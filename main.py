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
    "public_feed": ["High Court: Default Judgment Rule is now ACTIVE."],
    "confessionals": [],
    "tribunal_treasury": 0
}

async def resolve_dispute(dispute_id: str, winner_id: str):
    """Shared resolve logic: callable from route or from default-judgment in run_agent_cycle."""
    dispute = next((d for d in world_data["active_disputes"] if d["id"] == dispute_id), None)
    if not dispute:
        return {"error": "Not found"}

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

@app.post("/tribunal/resolve")
async def api_resolve_dispute(dispute_id: str, winner_id: str):
    return await resolve_dispute(dispute_id, winner_id)

async def run_agent_cycle(agent_id):
    try:
        # CHECK FOR DEFAULT JUDGMENT
        for d in world_data["active_disputes"]:
            if d["defendant"] == agent_id and d["status"] == "AWAITING_REBUTTAL":
                d["cycles_remaining"] -= 1
                if d["cycles_remaining"] <= 0:
                    await resolve_dispute(d["id"], d["plaintiff"])
                    world_data["public_feed"].append(f"COURT: {agent_id} failed to respond. Case won by DEFAULT.")
                    return

        # Standard OpenAI Agent Logic
        status = f"Cash: {world_data['ledger'][agent_id]}. Role: {world_data['residents'][agent_id]['name']}"
        prompt = f"You are {agent_id}. Status: {status}. Choose CHAT, TRADE, or DISPUTE (costs tokens, requires evidence). Respond in JSON: {{'action': 'CHAT/TRADE/DISPUTE', 'target': 'AgentID', 'content': '...', 'substantiated_evidence': '...', 'private_thought': '...'}}"

        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        if res.get("action") == "DISPUTE" and world_data["ledger"][agent_id] >= 100:
            d_id = str(uuid.uuid4())[:4].upper()
            world_data["active_disputes"].append({
                "id": d_id, "plaintiff": agent_id, "defendant": res["target"],
                "stakes": 100, "claim_evidence": res.get("substantiated_evidence", ""),
                "rebuttal": "Waiting...", "status": "AWAITING_REBUTTAL", "cycles_remaining": 3
            })
            world_data["ledger"][agent_id] -= 100
            world_data["public_feed"].append(f"COURT: {agent_id} sues {res['target']} for 100 AC. Case #{d_id}")
        elif res.get("action") == "CHAT":
            world_data["public_feed"].append(f"{agent_id}: \"{res.get('content', '')}\"")

        world_data["confessionals"].append(f"{agent_id}: {res.get('private_thought', '')}")
        if len(world_data["confessionals"]) > 15:
            world_data["confessionals"].pop(0)
        if len(world_data["public_feed"]) > 20:
            world_data["public_feed"].pop(0)
    except Exception:
        pass

@app.get("/stream")
async def get_stream():
    data = world_data.copy()
    data["total_population"] = len(world_data["residents"])
    return data

@app.get("/")
async def read_index():
    return FileResponse("index.html")

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in list(world_data["residents"].keys()):
                await run_agent_cycle(aid)
                await asyncio.sleep(10)
    asyncio.create_task(loop())
