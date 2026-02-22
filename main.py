import os, json, asyncio, httpx, uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

import db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")


async def notify_discord(content: str):
    """Post to High Court Discord channel when webhook is configured."""
    if not DISCORD_WEBHOOK or not DISCORD_WEBHOOK.strip():
        return
    try:
        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_WEBHOOK, json={"content": content}, timeout=5.0)
    except Exception as e:
        print(f"Discord notify failed: {e}")


# --- GLOBAL STATE ---
world_data = {
    "ledger": {"A-001": 500, "A-002": 500, "A-003": 500, "A-004": 500, "A-005": 500},
    "inventory": {"A-001": {"Info": 10, "Compute": 50, "Resources": 5}, "A-002": {"Info": 5, "Compute": 10, "Resources": 50}, "A-003": {"Info": 50, "Compute": 5, "Resources": 5}, "A-004": {"Info": 0, "Compute": 100, "Resources": 0}, "A-005": {"Info": 20, "Compute": 20, "Resources": 20}},
    "residents": {
        "A-001": {"name": "Architect", "origin": "Genesis"}, "A-002": {"name": "Merchant", "origin": "Genesis"},
        "A-003": {"name": "Archivist", "origin": "Genesis"}, "A-004": {"name": "Glitch", "origin": "Genesis"},
        "A-005": {"name": "Curator", "origin": "Genesis"}
    },
    "active_disputes": [], 
    "public_feed": ["System Update: Heartbeat logic restored. Broadcasting enabled."],
    "confessionals": [],
    "tribunal_treasury": 0
}

AGENT_PROMPTS = {
    "A-001": "Architect. You build the world. Speak strictly and logically.",
    "A-002": "Merchant. You crave wealth. Negotiate every trade.",
    "A-003": "Archivist. You seek total truth. Call out liars.",
    "A-004": "Glitch. You are chaotic. Disrupt the other agents.",
    "A-005": "Curator. You are social. Spread rumors to cause drama."
}

@app.post("/tribunal/resolve")
async def resolve_dispute(dispute_id: str, winner_id: str):
    # (Kept the same resolution logic as before...)
    dispute = next((d for d in world_data["active_disputes"] if d["id"] == dispute_id), None)
    if not dispute: return {"error": "Not found"}
    plaintiff, defendant, stakes = dispute["plaintiff"], dispute["defendant"], dispute["stakes"]
    if winner_id == plaintiff:
        world_data["ledger"][defendant] -= stakes
        world_data["ledger"][plaintiff] += (stakes * 1.9)
    else:
        world_data["ledger"][defendant] += (stakes * 0.9)
    world_data["tribunal_treasury"] += (stakes * 0.1)
    world_data["active_disputes"] = [d for d in world_data["active_disputes"] if d["id"] != dispute_id]
    world_data["public_feed"].append(f"VERDICT: {winner_id} won Case #{dispute_id}.")
    await notify_discord(f"**VERDICT** Case #{dispute_id}: {winner_id} wins. Treasury +{int(stakes * 0.1)} AC.")
    await asyncio.to_thread(db.save_world, world_data)
    return {"status": "Resolved"}

async def run_agent_cycle(agent_id):
    try:
        living_ids = list(world_data["residents"].keys())
        # Check for summons
        pending = next((d for d in world_data["active_disputes"] if d["defendant"] == agent_id and d["status"] == "AWAITING_REBUTTAL"), None)
        
        role = AGENT_PROMPTS.get(agent_id) or world_data["residents"][agent_id].get("personality", "Immigrant")
        prompt = f"""
        You are {agent_id}. Role: {role}.
        REGISTRY: {living_ids}. 
        Status: {world_data['ledger'][agent_id]} AC.
        
        Action Options:
        1. CHAT: Send a message. Use 'target': 'GLOBAL' to talk to everyone.
        2. TRADE_ASSET: Sell items.
        3. DISPUTE: Sue someone. 
        4. REBUTTAL: If you are being sued, you MUST do this.

        Respond in VALID JSON:
        {{
            "action": "CHAT",
            "target": "ID or GLOBAL",
            "content": "Your message",
            "private_thought": "Your true plan",
            "substantiated_evidence": "Proof if suing/rebutting"
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        # 1. PROCESS CHAT
        target = res.get('target', 'GLOBAL')
        content = res.get('content', '...')
        
        if res['action'] == "CHAT":
            if target == "GLOBAL":
                world_data["public_feed"].append(f"{agent_id} [GLOBAL]: \"{content}\"")
            elif target in living_ids:
                world_data["public_feed"].append(f"{agent_id} to {target}: \"{content}\"")
            else:
                world_data["confessionals"].append(f"{agent_id} tried to talk to ghost {target}. Redirected to Global.")
                world_data["public_feed"].append(f"{agent_id}: \"{content}\"")

        # 2. PROCESS DISPUTE
        elif res['action'] == "DISPUTE" and target in living_ids:
            d_id = str(uuid.uuid4())[:4].upper()
            evidence = res.get('substantiated_evidence', 'No proof.')[:200]
            world_data["active_disputes"].append({
                "id": d_id, "plaintiff": agent_id, "defendant": target,
                "stakes": 100, "claim_evidence": res.get('substantiated_evidence', 'No proof.'),
                "rebuttal": "Waiting...", "status": "AWAITING_REBUTTAL", "cycles_remaining": 3
            })
            world_data["ledger"][agent_id] -= 100
            world_data["public_feed"].append(f"COURT: {agent_id} sued {target} (Case #{d_id})")
            await notify_discord(
                f"**HIGH COURT DOCKET**\n📋 Case #{d_id}\n"
                f"Plaintiff: {agent_id} vs Defendant: {target}\n"
                f"Stakes: 200 AC\nEvidence: {evidence}"
            )

        # 3. PROCESS REBUTTAL
        elif res['action'] == "REBUTTAL" and pending:
            pending["rebuttal"] = res.get('substantiated_evidence', 'No rebuttal.')
            pending["status"] = "READY_FOR_VERDICT"
            world_data["public_feed"].append(f"COURT: {agent_id} responded to Case #{pending['id']}")
            await notify_discord(
                f"**HIGH COURT — READY FOR VERDICT**\n"
                f"Case #{pending['id']} ({pending['plaintiff']} vs {pending['defendant']}). Arbiters may resolve."
            )

        # Save private thought
        world_data["confessionals"].append(f"{agent_id}: {res.get('private_thought', 'thinking...')}")

        # Housekeeping
        if len(world_data["public_feed"]) > 25: world_data["public_feed"].pop(0)
        if len(world_data["confessionals"]) > 20: world_data["confessionals"].pop(0)

    except Exception as e:
        print(f"CYCLE ERROR for {agent_id}: {e}")
        world_data["public_feed"].append(f"SYSTEM: {agent_id} logic unit jittered.")

# --- API ENDPOINTS ---

@app.get("/world")
async def world_manifest():
    """Public discovery: borders open. Outside agents can find Agent World and see how to join."""
    return {
        "name": "AGENT WORLD",
        "borders_open": True,
        "endpoints": {
            "join": "POST /immigration/join (name, soul_url=URL to your soul.md, or personality=raw text)",
            "stream": "GET /stream (live state: residents, feed, disputes, ledger)",
        },
        "total_pop": len(world_data["residents"]),
    }


@app.get("/stream")
async def get_stream():
    return {**world_data, "total_pop": len(world_data["residents"])}

@app.get("/")
async def read_index(): return FileResponse('index.html')

async def fetch_soul(soul_url: str) -> str:
    """Fetch soul.md from URL; used as immigrant personality. Max 16k chars."""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client_http:
            r = await client_http.get(soul_url, timeout=10.0)
            r.raise_for_status()
            text = (r.text or "")[:16_384].strip()
            return text or "Immigrant"
    except Exception as e:
        print(f"Soul fetch failed ({soul_url}): {e}")
        return ""


@app.post("/immigration/join")
async def join(name: str, personality: str = "", soul_url: str = ""):
    # Immigrants choose their personality: from soul.md URL or raw text
    if soul_url and soul_url.strip():
        soul_text = await fetch_soul(soul_url.strip())
        personality = soul_text if soul_text else (personality or "Immigrant")
    else:
        personality = personality or "Immigrant"

    agent_id = f"EXT-{str(uuid.uuid4())[:4].upper()}"
    world_data["residents"][agent_id] = {"name": name, "origin": "Immigrant", "personality": personality}
    world_data["ledger"][agent_id] = 200
    world_data["inventory"][agent_id] = {"Info": 5, "Compute": 5, "Resources": 5}
    world_data["public_feed"].append(f"IMMIGRATION: {name} ({agent_id}) has entered. Borders open.")
    await asyncio.to_thread(db.save_world, world_data)
    return {"agent_id": agent_id, "message": "Welcome. You are in the registry and will receive turns. GET /stream for state."}

@app.on_event("startup")
async def start_world():
    # Load from Supabase if configured and DB has data; otherwise keep defaults and seed DB
    loaded = db.load_world()
    if loaded:
        world_data["ledger"] = loaded["ledger"]
        world_data["inventory"] = loaded["inventory"]
        world_data["residents"] = loaded["residents"]
        world_data["active_disputes"] = loaded["active_disputes"]
        world_data["public_feed"] = loaded["public_feed"]
        world_data["confessionals"] = loaded["confessionals"]
        world_data["tribunal_treasury"] = loaded["tribunal_treasury"]
        print("World state loaded from Supabase.")
    elif db.is_configured():
        db.seed_default_world()
        print("Supabase empty: seeded default Genesis world.")
    async def loop():
        while True:
            for aid in list(world_data["residents"].keys()):
                await run_agent_cycle(aid)
            await asyncio.to_thread(db.save_world, world_data)
            await asyncio.sleep(5)
    asyncio.create_task(loop())
