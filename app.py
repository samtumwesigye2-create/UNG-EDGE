from __future__ import annotations
import asyncio, json, os, platform, socket, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

APP_VERSION = "0.2.0"
NODE_ID = os.getenv("UNG_EDGE_NODE_ID", socket.gethostname())
DATA_DIR = Path(os.getenv("UNG_EDGE_DATA_DIR", str(Path.home() / "ung-edge" / "data")))
DB_PATH = DATA_DIR / "edge.db"
NEXUS_URL = os.getenv("UNG_NEXUS_URL", "").rstrip("/")
PULSAR_URL = os.getenv("UNG_PULSAR_URL", "https://ung-pulsar-production.up.railway.app").rstrip("/")
SERVICE_TOKEN = os.getenv("UNG_EDGE_SERVICE_TOKEN", "")
SYNC_INTERVAL = int(os.getenv("UNG_EDGE_SYNC_INTERVAL_SECONDS", "15"))

app = FastAPI(title="UNG-EDGE", version=APP_VERSION)

class EventIn(BaseModel):
    topic: str
    payload: dict[str, Any]
    priority: int = 5

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS outbound_queue(
        id TEXT PRIMARY KEY, topic TEXT NOT NULL, payload TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 5, created_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, delivered_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS local_events(
        id TEXT PRIMARY KEY, topic TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)""")
    conn.commit()
    return conn

def headers():
    h = {"User-Agent": f"UNG-EDGE/{APP_VERSION}", "X-UNG-Node": NODE_ID}
    if SERVICE_TOKEN:
        h["Authorization"] = f"Bearer {SERVICE_TOKEN}"
    return h

async def post_json(url: str, body: dict[str, Any]):
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.post(url, json=body, headers=headers())
        r.raise_for_status()
        return r.json() if r.content else {"ok": True}

async def relay_event(row):
    body = {"message_id": row["id"], "source": NODE_ID, "topic": row["topic"],
            "payload": json.loads(row["payload"]), "created_at": row["created_at"], "priority": row["priority"]}
    if NEXUS_URL:
        return await post_json(f"{NEXUS_URL}/v1/messages/outbound", body)
    return await post_json(f"{PULSAR_URL}/v1/nexus/inbound", body)

async def sync_once():
    conn = db()
    rows = conn.execute("SELECT * FROM outbound_queue WHERE delivered_at IS NULL ORDER BY priority ASC, created_at ASC LIMIT 50").fetchall()
    delivered = 0
    for row in rows:
        try:
            await relay_event(row)
            conn.execute("UPDATE outbound_queue SET delivered_at=?, last_error=NULL WHERE id=?", (utcnow(), row["id"]))
            delivered += 1
        except Exception as e:
            conn.execute("UPDATE outbound_queue SET attempts=attempts+1,last_error=? WHERE id=?", (str(e)[:500], row["id"]))
        conn.commit()
    conn.close()
    return delivered

async def worker():
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        try: await sync_once()
        except Exception: pass

async def endpoint_probe(url: str):
    if not url:
        return {"configured": False, "reachable": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url.rstrip("/") + "/health", headers=headers())
        return {"configured": True, "reachable": r.status_code < 500, "status_code": r.status_code}
    except Exception as e:
        return {"configured": True, "reachable": False, "error": str(e)[:160]}

@app.on_event("startup")
async def startup():
    db().close(); app.state.worker = asyncio.create_task(worker())

@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "worker", None)
    if task: task.cancel()

@app.get("/")
def root():
    return {"system":"UNG-EDGE","node_id":NODE_ID,"version":APP_VERSION,"status":"online"}

@app.get("/health")
def health():
    conn=db(); queued=conn.execute("SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NULL").fetchone()["n"]; conn.close()
    return {"ok":True,"node_id":NODE_ID,"version":APP_VERSION,"queued":queued,"time":utcnow()}

@app.get("/v1/status")
def status():
    conn=db(); queued=conn.execute("SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NULL").fetchone()["n"]
    retrying=conn.execute("SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NULL AND attempts>0").fetchone()["n"]; conn.close()
    disk=os.statvfs("/")
    return {"node_id":NODE_ID,"hostname":socket.gethostname(),"version":APP_VERSION,"platform":platform.platform(),
            "machine":platform.machine(),"python":platform.python_version(),"queued":queued,"retrying":retrying,
            "service_token_configured":bool(SERVICE_TOKEN),"disk_free_bytes":disk.f_bavail*disk.f_frsize,
            "disk_total_bytes":disk.f_blocks*disk.f_frsize,"time":utcnow()}

@app.get("/v1/commission")
async def commission():
    conn=db()
    try:
        conn.execute("INSERT OR REPLACE INTO local_events(id,topic,payload,created_at) VALUES(?,?,?,?)",
                     ("commission-storage-probe","edge.commission.storage",json.dumps({"node":NODE_ID}),utcnow()))
        conn.commit()
        storage_ok=conn.execute("SELECT COUNT(*) n FROM local_events WHERE id='commission-storage-probe'").fetchone()["n"]==1
    finally: conn.close()
    pulsar=await endpoint_probe(PULSAR_URL)
    nexus=await endpoint_probe(NEXUS_URL)
    return {"node_id":NODE_ID,"version":APP_VERSION,"runtime":True,"sqlite":storage_ok,"queue":True,
            "pulsar":pulsar,"nexus":nexus,"janus_token_configured":bool(SERVICE_TOKEN),
            "commissioned": bool(storage_ok and (pulsar.get("reachable") or nexus.get("reachable")) and SERVICE_TOKEN),"time":utcnow()}

@app.post("/v1/events")
def ingest(event: EventIn):
    eid=str(uuid.uuid4()); now=utcnow(); payload=json.dumps(event.payload,separators=(",",":")); conn=db()
    conn.execute("INSERT INTO local_events(id,topic,payload,created_at) VALUES(?,?,?,?)",(eid,event.topic,payload,now))
    conn.execute("INSERT INTO outbound_queue(id,topic,payload,priority,created_at) VALUES(?,?,?,?,?)",(eid,event.topic,payload,event.priority,now))
    conn.commit(); conn.close(); return {"accepted":True,"event_id":eid,"queued":True}

@app.post("/v1/sync")
async def sync(): return {"ok":True,"delivered":await sync_once()}

@app.get("/v1/queue")
def queue(limit:int=100):
    limit=max(1,min(limit,500)); conn=db()
    rows=conn.execute("SELECT id,topic,priority,created_at,attempts,last_error,delivered_at FROM outbound_queue ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
    conn.close(); return {"items":[dict(r) for r in rows]}
