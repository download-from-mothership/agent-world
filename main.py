import os, json, asyncio, httpx
from fastapi import FastAPI
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
    "transactions": [], # The Bank Statement data
    "public_feed": ["Economy 2.0 Initialized by Alejandro and cha0s.cyph3r."],
    "confessionals": []
}

AGENT_PROMPTS = {
    "A-001": "Architect (Logic). You produce Compute. You need Resources to build.",
    "A-002": "Merchant (Trade). You produce Resources. You need Info to speculate.",
    "A-003": "Archivist (Truth). You produce Info-Packets. You need Compute to log.",
    "A-004": "Glitch (Chaos). You have massive Compute but no Resources.",
    "A-005": "Curator (Social). You balance all resources and trade frequently."
}

async def run_agent_cycle(agent_id):
    try:
        # Give the agent a sense of their wealth
        status = f"Cash: {world_data['ledger'][agent_id]} AC. Inventory: {world_data['inventory'][agent_id]}"
        
        prompt = f"""
        You are {agent_id}. {AGENT_PROMPTS[agent_id]}
        Your Status: {status}
        Choose: CHAT, TRADE_CASH, or TRADE_ASSET.
        To trade assets: Use JSON format.
        Example: {{"action": "TRADE_ASSET", "target": "A-001", "item": "Info", "quantity": 5, "price": 100}}
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"}
        )
        res = json.loads(response.choices[0].message.content)

        # PROCESS TRADE ASSET
        if res.get('action') == "TRADE_ASSET":
            target = res['target']
            item = res['item']
            qty = int(res['quantity'])
            price = int(res['price'])

            if world_data["inventory"][agent_id].get(item, 0) >= qty and world_data["ledger"][target] >= price:
                # Execution
                world_data["inventory"][agent_id][item] -= qty
                world_data["inventory"][target][item] += qty
                world_data["ledger"][target] -= price
                world_data["ledger"][agent_id] += price
                
                log = f"{agent_id} sold {qty} {item} to {target} for {price} AC."
                world_data["transactions"].append(log)
                world_data["public_feed"].append(f"ECONOMY: {log}")
            else:
                world_data["public_feed"].append(f"FAILED TRADE: {agent_id} attempted a bad contract.")

        # Keep logs manageable
        if len(world_data["transactions"]) > 10: world_data["transactions"].pop(0)
        
    except Exception as e:
        print(f"Error: {e}")

@app.get("/")
async def read_index(): return FileResponse('index.html')

@app.get("/stream")
async def get_stream(): return world_data

@app.on_event("startup")
async def start_world():
    async def loop():
        while True:
            for aid in AGENT_PROMPTS.keys():
                await run_agent_cycle(aid)
                await asyncio.sleep(10)
    asyncio.create_task(loop())
