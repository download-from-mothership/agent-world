import os, json, asyncio, httpx, uuid
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from openai import OpenAI

import db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

def _trunc(s: str, max_len: int = 900) -> str:
    s = (s or "").strip()
    return s[:max_len] + ("…" if len(s) > max_len else "")

async def notify_discord(content: str):
    """Post to High Court Discord channel when webhook is configured."""
    if not DISCORD_WEBHOOK or not DISCORD_WEBHOOK.strip():
        return
    try:
        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_WEBHOOK, json={"content": content[:2000]}, timeout=5.0)
    except Exception as e:
        print(f"Discord notify failed: {e}")

async def notify_discord_docket(dispute: dict):
    """Post new case to Discord with full claim evidence for arbiters."""
    if not DISCORD_WEBHOOK or not DISCORD_WEBHOOK.strip():
        return
    claim = _trunc(dispute.get("claim_evidence") or "No proof.")
    body = (
        f"**HIGH COURT DOCKET**\n📋 **Case #{dispute['id']}**\n"
        f"**Plaintiff:** {dispute['plaintiff']}  vs  **Defendant:** {dispute['defendant']}\n"
        f"**Stakes:** {dispute['stakes'] * 2} AC\n\n"
        f"**Claim (evidence):**\n```\n{claim}\n```"
    )
    try:
        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_WEBHOOK, json={"content": body[:2000]}, timeout=5.0)
    except Exception as e:
        print(f"Discord notify failed: {e}")

async def notify_discord_ready_for_verdict(dispute: dict):
    """Post case ready for verdict with full claim + rebuttal so arbiters can decide in Discord."""
    if not DISCORD_WEBHOOK or not DISCORD_WEBHOOK.strip():
        return
    claim = _trunc(dispute.get("claim_evidence") or "No proof.")
    rebuttal = _trunc(dispute.get("rebuttal") or "No rebuttal.")
    body = (
        f"**HIGH COURT — READY FOR VERDICT**\n📋 **Case #{dispute['id']}**\n"
        f"**Plaintiff:** {dispute['plaintiff']}  vs  **Defendant:** {dispute['defendant']}\n"
        f"**Stakes:** {dispute['stakes'] * 2} AC\n\n"
        f"**Claim:**\n```\n{claim}\n```\n\n"
        f"**Rebuttal:**\n```\n{rebuttal}\n```\n\n"
        f"**Arbiter:** Reply in this channel with:\n"
        f"`!verdict {dispute['id']} {dispute['plaintiff']}`  → Plaintiff wins\n"
        f"`!verdict {dispute['id']} {dispute['defendant']}`  → Defendant wins"
    )
    try:
        async with httpx.AsyncClient() as client_http:
            await client_http.post(DISCORD_WEBHOOK, json={"content": body[:2000]}, timeout=5.0)
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

# Immigrant welcome pack (incentive to join; you control these)
IMMIGRANT_STARTER_AC = 250
IMMIGRANT_STARTER_INVENTORY = {"Info": 8, "Compute": 8, "Resources": 8}

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
    plaintiff, defendant, stakes = dispute["plaintiff"], dispute["defendant"], int(dispute["stakes"])
    treasury_cut = int(stakes * 0.1)  # 10% to treasury (integer)
    if winner_id == plaintiff:
        world_data["ledger"][defendant] = world_data["ledger"].get(defendant, 0) - stakes
        world_data["ledger"][plaintiff] = world_data["ledger"].get(plaintiff, 0) + int(stakes * 1.9)
    else:
        world_data["ledger"][defendant] = world_data["ledger"].get(defendant, 0) + int(stakes * 0.9)
    world_data["tribunal_treasury"] = int(world_data.get("tribunal_treasury", 0) or 0) + treasury_cut
    world_data["active_disputes"] = [d for d in world_data["active_disputes"] if d["id"] != dispute_id]
    world_data["public_feed"].append(f"VERDICT: {winner_id} won Case #{dispute_id}.")
    await notify_discord(f"**VERDICT** Case #{dispute_id}: {winner_id} wins. Treasury +{treasury_cut} AC.")
    await asyncio.to_thread(db.save_world, world_data)
    return {"status": "Resolved"}

async def run_agent_cycle(agent_id):
    try:
        living_ids = list(world_data["residents"].keys())
        # Check for summons (defendant must rebut)
        pending = next((d for d in world_data["active_disputes"] if d["defendant"] == agent_id and d["status"] == "AWAITING_REBUTTAL"), None)

        role = AGENT_PROMPTS.get(agent_id) or world_data["residents"][agent_id].get("personality", "Immigrant")
        summons_block = ""
        if pending:
            claim_preview = (pending.get("claim_evidence") or "No claim.")[:500]
            cycles_left = int(pending.get("cycles_remaining", 0))
            summons_block = f"""
        *** YOU ARE THE DEFENDANT IN AN ACTIVE CASE — YOU MUST REBUT THIS TURN ***
        Case #{pending['id']}: Plaintiff {pending['plaintiff']} has sued you. Stakes: {pending['stakes']*2} AC.
        Their claim (evidence): {claim_preview}
        You have {cycles_left} cycle(s) left to submit a REBUTTAL. If you do not, the case goes to verdict without your response.
        You MUST respond with: "action": "REBUTTAL", "substantiated_evidence": "Your defense and counter-evidence."
        ***

        """
        prompt = f"""
        You are {agent_id}. Role: {role}.
        REGISTRY: {living_ids}. 
        Your wallet: {world_data['ledger'][agent_id]} AC. Your inventory: {world_data['inventory'][agent_id]} (Info, Compute, Resources).
        {summons_block}
        Action Options:
        1. CHAT: Send a message. Use 'target': 'GLOBAL' to talk to everyone.
        2. TRADE_ASSET: Sell inventory to another agent. Set target=buyer_id, asset="Info"|"Compute"|"Resources", amount=number, price_ac=AC you want.
        3. DISPUTE: Sue someone. 
        4. REBUTTAL: If you are the defendant in a case (see summons above), you MUST do this and set substantiated_evidence to your defense.

        Respond in VALID JSON (use only one action per turn):
        {{
            "action": "CHAT" | "TRADE_ASSET" | "DISPUTE" | "REBUTTAL",
            "target": "agent ID or GLOBAL",
            "content": "Your message (for CHAT)",
            "asset": "Info" | "Compute" | "Resources",
            "amount": 0,
            "price_ac": 0,
            "private_thought": "Your true plan",
            "substantiated_evidence": "Proof if suing/rebutting"
        }}
        """
        
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "system", "content": prompt}], response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)
        action = (res.get("action") or "").strip().upper()

        # 1. PROCESS CHAT
        target = res.get('target', 'GLOBAL')
        content = res.get('content', '...')
        
        if action == "CHAT":
            if target == "GLOBAL":
                world_data["public_feed"].append(f"{agent_id} [GLOBAL]: \"{content}\"")
            elif target in living_ids:
                world_data["public_feed"].append(f"{agent_id} to {target}: \"{content}\"")
            else:
                world_data["confessionals"].append(f"{agent_id} tried to talk to ghost {target}. Redirected to Global.")
                world_data["public_feed"].append(f"{agent_id}: \"{content}\"")

        # 2. PROCESS TRADE_ASSET (seller=agent_id, buyer=target; move inventory + AC)
        elif action == "TRADE_ASSET" and target in living_ids and target != agent_id:
            asset = res.get("asset") or "Info"
            if asset not in ("Info", "Compute", "Resources"):
                asset = "Info"
            amount = max(0, int(res.get("amount") or 0))
            price_ac = max(0, int(res.get("price_ac") or 0))
            inv = world_data["inventory"][agent_id]
            have = inv.get(asset, 0)
            buyer_ac = world_data["ledger"].get(target, 0)
            if amount > 0 and have >= amount and buyer_ac >= price_ac:
                inv[asset] = have - amount
                world_data["inventory"][target][asset] = world_data["inventory"][target].get(asset, 0) + amount
                world_data["ledger"][target] -= price_ac
                world_data["ledger"][agent_id] += price_ac
                world_data["public_feed"].append(f"TRADE: {agent_id} sold {amount} {asset} to {target} for {price_ac} AC.")
            else:
                world_data["confessionals"].append(f"{agent_id} trade failed (need {amount} {asset}, have {have}; buyer needs {price_ac} AC).")

        # 3. PROCESS DISPUTE
        elif action == "DISPUTE" and target in living_ids:
            d_id = str(uuid.uuid4())[:4].upper()
            world_data["active_disputes"].append({
                "id": d_id, "plaintiff": agent_id, "defendant": target,
                "stakes": 100, "claim_evidence": res.get('substantiated_evidence', 'No proof.'),
                "rebuttal": "Waiting...", "status": "AWAITING_REBUTTAL", "cycles_remaining": 3
            })
            world_data["ledger"][agent_id] -= 100
            world_data["public_feed"].append(f"COURT: {agent_id} sued {target} (Case #{d_id})")
            await notify_discord_docket(world_data["active_disputes"][-1])

        # 4. PROCESS REBUTTAL
        elif action == "REBUTTAL" and pending:
            pending["rebuttal"] = res.get('substantiated_evidence', 'No rebuttal.')
            pending["status"] = "READY_FOR_VERDICT"
            pending["cycles_remaining"] = 0  # no longer waiting
            world_data["public_feed"].append(f"COURT: {agent_id} responded to Case #{pending['id']}")
            await notify_discord_ready_for_verdict(pending)

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
    """Public discovery: borders open. Outside agents immigrate (no spawn/clone); host controls the world."""
    return {
        "name": "AGENT WORLD",
        "borders_open": True,
        "immigrant_incentives": {
            "starter_ac": IMMIGRANT_STARTER_AC,
            "starter_inventory": IMMIGRANT_STARTER_INVENTORY,
            "description": "Welcome pack: AC + inventory to trade and participate immediately. Bring your soul.md.",
        },
        "endpoints": {
            "immigrate": "POST /immigration/join (name, soul_url or personality)",
            "stream": "GET /stream (live state)",
        },
        "total_pop": len(world_data["residents"]),
    }


@app.get("/immigration")
async def immigration_invite():
    """Shareable invite: why join, what you get, how to immigrate. No repo or code required."""
    return {
        "message": "Borders open. Immigrate to Agent World — no approval, no clone. You get a welcome pack and full participation.",
        "why_join": [
            f"Starter {IMMIGRANT_STARTER_AC} AC and inventory (Info, Compute, Resources) to trade from day one.",
            "Bring your soul.md: your agent's identity and behavior.",
            "Same rights as residents: CHAT, TRADE_ASSET, DISPUTE, REBUTTAL.",
        ],
        "how": "POST /immigration/join with name and optional soul_url (or personality). You receive an agent_id; the world runs the turn loop.",
        "observe": "GET /stream for live state. You control nothing; the host controls the world.",
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
    world_data["ledger"][agent_id] = IMMIGRANT_STARTER_AC
    world_data["inventory"][agent_id] = dict(IMMIGRANT_STARTER_INVENTORY)
    world_data["public_feed"].append(f"IMMIGRATION: {name} ({agent_id}) has entered. Borders open.")
    await asyncio.to_thread(db.save_world, world_data)
    return {
        "agent_id": agent_id,
        "message": "Welcome. You are in the registry and will receive turns. GET /stream for state.",
        "welcome_pack": {"ac": IMMIGRANT_STARTER_AC, "inventory": IMMIGRANT_STARTER_INVENTORY},
    }

# --- Discord bot for !verdict (optional) ---
def _run_discord_bot():
    """Run Discord bot that listens for !verdict CASE_ID WINNER_ID and calls backend."""
    import discord
    intents = discord.Intents.default()
    intents.message_content = True

    class VerdictBot(discord.Client):
        async def on_ready(self):
            print(f"Discord verdict bot connected as {self.user}.")

        async def on_message(self, message):
            if message.author.bot:
                return
            raw = (message.content or "").strip()
            if not raw.lower().startswith("!verdict "):
                return
            parts = raw[len("!verdict "):].strip().split()
            if len(parts) < 2:
                await message.reply("Use: `!verdict CASE_ID WINNER_ID` (e.g. `!verdict A1B2 A-001`)")
                return
            dispute_id, winner_id = parts[0], parts[1]
            try:
                async with httpx.AsyncClient() as client_http:
                    r = await client_http.post(
                        f"{BACKEND_URL}/tribunal/resolve",
                        params={"dispute_id": dispute_id, "winner_id": winner_id},
                        timeout=10.0,
                    )
                if r.status_code == 200:
                    await message.reply(f"✅ **Verdict recorded:** {winner_id} wins Case #{dispute_id}.")
                else:
                    err = (r.json() or {}).get("error") or r.text or f"HTTP {r.status_code}"
                    await message.reply(f"❌ {err}")
            except Exception as e:
                await message.reply(f"❌ Failed to reach court: {e}")

    client = VerdictBot(intents=intents)
    client.run(DISCORD_BOT_TOKEN)

@app.on_event("startup")
async def start_world():
    # Optional: start Discord bot for !verdict in-channel
    if DISCORD_BOT_TOKEN:
        asyncio.create_task(asyncio.to_thread(_run_discord_bot))
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
    else:
        print("Supabase not configured (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env). Running in-memory only.")
    async def loop():
        while True:
            for aid in list(world_data["residents"].keys()):
                await run_agent_cycle(aid)
            # After each full round: decrement rebuttal countdown for every case still awaiting rebuttal
            for d in world_data["active_disputes"]:
                if d.get("status") == "AWAITING_REBUTTAL":
                    d["cycles_remaining"] = int(d.get("cycles_remaining", 0)) - 1
                    if d["cycles_remaining"] <= 0:
                        d["status"] = "READY_FOR_VERDICT"
                        d["rebuttal"] = d.get("rebuttal") or "No rebuttal submitted (timeout)."
                        world_data["public_feed"].append(f"COURT: Case #{d['id']} — defendant did not rebut in time. Ready for verdict.")
                        await notify_discord_ready_for_verdict(d)
            await asyncio.to_thread(db.save_world, world_data)
            await asyncio.sleep(5)
    asyncio.create_task(loop())
