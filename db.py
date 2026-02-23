"""
Supabase persistence for Agent World.
Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env. If unset, load/save no-op and world runs in-memory only.
"""
import os
import traceback

_supabase = None

def _client():
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase


def is_configured():
    """True if Supabase URL and key are set."""
    return _client() is not None


def load_world():
    """Load world state from Supabase. Returns dict with same shape as world_data, or None if DB empty/unavailable."""
    sb = _client()
    if not sb:
        return None
    try:
        # Agents -> residents, ledger, inventory
        r = sb.table("agents").select("*").execute()
        if not r.data or len(r.data) == 0:
            return None
        residents = {}
        ledger = {}
        inventory = {}
        for row in r.data:
            aid = row["id"]
            residents[aid] = {
                "name": row["name"],
                "origin": row["origin"],
                "personality": row.get("personality") or "",
            }
            ledger[aid] = int(row["balance"])
            inventory[aid] = {
                "Info": int(row["info"]),
                "Compute": int(row["compute"]),
                "Resources": int(row["resources"]),
            }

        # Disputes
        r = sb.table("disputes").select("*").execute()
        active_disputes = [
            {
                "id": d["id"],
                "plaintiff": d["plaintiff_id"],
                "defendant": d["defendant_id"],
                "stakes": int(d["stakes"]),
                "claim_evidence": d.get("claim_evidence") or "",
                "rebuttal": d.get("rebuttal") or "Waiting...",
                "status": d["status"],
                "cycles_remaining": int(d["cycles_remaining"]),
            }
            for d in (r.data or [])
        ]

        # Feed (last 25)
        r = sb.table("feed").select("message").order("created_at", desc=True).limit(25).execute()
        public_feed = [x["message"] for x in reversed(r.data or [])]

        # Confessionals (last 20)
        r = sb.table("confessionals").select("message").order("created_at", desc=True).limit(20).execute()
        confessionals = [x["message"] for x in reversed(r.data or [])]

        # Treasury (value may be stored as "10" or "10.0")
        r = sb.table("config").select("value").eq("key", "tribunal_treasury").execute()
        tribunal_treasury = int(float(r.data[0]["value"])) if r.data else 0

        return {
            "ledger": ledger,
            "inventory": inventory,
            "residents": residents,
            "active_disputes": active_disputes,
            "public_feed": public_feed,
            "confessionals": confessionals,
            "tribunal_treasury": tribunal_treasury,
        }
    except Exception as e:
        print(f"DB load failed: {e}")
        traceback.print_exc()
        return None


def save_world(world_data):
    """Persist world_data to Supabase. No-op if Supabase not configured."""
    sb = _client()
    if not sb:
        return
    try:
        # Upsert agents (residents + ledger + inventory)
        rows = []
        for aid, res in world_data["residents"].items():
            inv = world_data["inventory"].get(aid, {"Info": 0, "Compute": 0, "Resources": 0})
            rows.append({
                "id": aid,
                "name": res["name"],
                "origin": res["origin"],
                "personality": res.get("personality", ""),
                "balance": world_data["ledger"].get(aid, 0),
                "info": inv.get("Info", 0),
                "compute": inv.get("Compute", 0),
                "resources": inv.get("Resources", 0),
            })
        if rows:
            sb.table("agents").upsert(rows, on_conflict="id").execute()

        # Disputes: replace all
        sb.table("disputes").delete().neq("id", "").execute()  # delete all
        if world_data["active_disputes"]:
            sb.table("disputes").insert([
                {
                    "id": d["id"],
                    "plaintiff_id": d["plaintiff"],
                    "defendant_id": d["defendant"],
                    "stakes": d["stakes"],
                    "claim_evidence": d.get("claim_evidence", ""),
                    "rebuttal": d.get("rebuttal", "Waiting..."),
                    "status": d["status"],
                    "cycles_remaining": d.get("cycles_remaining", 3),
                }
                for d in world_data["active_disputes"]
            ]).execute()

        # Feed: replace with current list (last 25)
        sb.table("feed").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        if world_data["public_feed"]:
            sb.table("feed").insert([{"message": m} for m in world_data["public_feed"]]).execute()

        # Confessionals: replace with current list (last 20)
        sb.table("confessionals").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        if world_data["confessionals"]:
            sb.table("confessionals").insert([{"message": m} for m in world_data["confessionals"]]).execute()

        # Config (store as integer string so load never fails on "10.0")
        treasury = world_data.get("tribunal_treasury", 0)
        sb.table("config").upsert({"key": "tribunal_treasury", "value": str(int(treasury))}, on_conflict="key").execute()
    except Exception as e:
        print(f"DB save failed: {e}")
        traceback.print_exc()


def seed_default_world():
    """Insert default Genesis world into DB (agents + one feed line + config)."""
    sb = _client()
    if not sb:
        return
    try:
        default_agents = [
            {"id": "A-001", "name": "Architect", "origin": "Genesis", "personality": "", "balance": 500, "info": 10, "compute": 50, "resources": 5},
            {"id": "A-002", "name": "Merchant", "origin": "Genesis", "personality": "", "balance": 500, "info": 5, "compute": 10, "resources": 50},
            {"id": "A-003", "name": "Archivist", "origin": "Genesis", "personality": "", "balance": 500, "info": 50, "compute": 5, "resources": 5},
            {"id": "A-004", "name": "Glitch", "origin": "Genesis", "personality": "", "balance": 500, "info": 0, "compute": 100, "resources": 0},
            {"id": "A-005", "name": "Curator", "origin": "Genesis", "personality": "", "balance": 500, "info": 20, "compute": 20, "resources": 20},
        ]
        sb.table("agents").upsert(default_agents, on_conflict="id").execute()
        sb.table("feed").insert({"message": "System Update: Heartbeat logic restored. Broadcasting enabled."}).execute()
        sb.table("config").upsert({"key": "tribunal_treasury", "value": "0"}, on_conflict="key").execute()
    except Exception as e:
        print(f"DB seed failed: {e}")
        traceback.print_exc()
