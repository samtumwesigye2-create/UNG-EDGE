from __future__ import annotations
import asyncio,json,os,platform,socket,sqlite3,uuid,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
APP_VERSION='0.3.0';NODE_ID=os.getenv('UNG_EDGE_NODE_ID',socket.gethostname());DATA_DIR=Path(os.getenv('UNG_EDGE_DATA_DIR',str(Path.home()/'ung-edge'/'data')));DB_PATH=DATA_DIR/'edge.db';NEXUS_URL=os.getenv('UNG_NEXUS_URL','').rstrip('/');PULSAR_URL=os.getenv('UNG_PULSAR_URL','https://ung-pulsar-production.up.railway.app').rstrip('/');SERVICE_TOKEN=os.getenv('UNG_EDGE_SERVICE_TOKEN','');SYNC_INTERVAL=int(os.getenv('UNG_EDGE_SYNC_INTERVAL_SECONDS','15'));STARTED=time.time();app=FastAPI(title='UNG-EDGE',version=APP_VERSION)
class EventIn(BaseModel):topic:str;payload:dict[str,Any];priority:int=5
def utcnow():return datetime.now(timezone.utc).isoformat()
def db():
 DATA_DIR.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(DB_PATH);c.row_factory=sqlite3.Row;c.execute('CREATE TABLE IF NOT EXISTS outbound_queue(id TEXT PRIMARY KEY,topic TEXT NOT NULL,payload TEXT NOT NULL,priority INTEGER NOT NULL DEFAULT 5,created_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,delivered_at TEXT)');c.execute('CREATE TABLE IF NOT EXISTS local_events(id TEXT PRIMARY KEY,topic TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)');c.commit();return c
def headers():
 h={'User-Agent':f'UNG-EDGE/{APP_VERSION}','X-UNG-Node':NODE_ID}
 if SERVICE_TOKEN:h['Authorization']=f'Bearer {SERVICE_TOKEN}'
 return h
async def post_json(url,body):
 async with httpx.AsyncClient(timeout=8) as client:r=await client.post(url,json=body,headers=headers());r.raise_for_status();return r.json() if r.content else {'ok':True}
async def relay_event(row):
 if NEXUS_URL:
  body={'source_system':NODE_ID,'target_system':'UNG-PULSAR','message_type':row['topic'],'payload':json.loads(row['payload']),'message_id':row['id'],'priority':row['priority']}
  return await post_json(f'{NEXUS_URL}/v1/messages',body)
 body={'message_id':row['id'],'source':NODE_ID,'topic':row['topic'],'payload':json.loads(row['payload']),'created_at':row['created_at'],'priority':row['priority']};return await post_json(f'{PULSAR_URL}/v1/nexus/inbound',body)
async def sync_once():
 c=db();rows=c.execute('SELECT * FROM outbound_queue WHERE delivered_at IS NULL ORDER BY priority ASC,created_at ASC LIMIT 50').fetchall();n=0
 for r in rows:
  try:await relay_event(r);c.execute('UPDATE outbound_queue SET delivered_at=?,last_error=NULL WHERE id=?',(utcnow(),r['id']));n+=1
  except Exception as e:c.execute('UPDATE outbound_queue SET attempts=attempts+1,last_error=? WHERE id=?',(str(e)[:500],r['id']))
  c.commit()
 c.close();return n
async def worker():
 while True:
  await asyncio.sleep(SYNC_INTERVAL)
  try:await sync_once()
  except Exception:pass
async def probe(url):
 if not url:return {'configured':False,'reachable':False}
 try:
  async with httpx.AsyncClient(timeout=5) as client:r=await client.get(url+'/health',headers=headers())
  return {'configured':True,'reachable':r.status_code<500,'status_code':r.status_code}
 except Exception as e:return {'configured':True,'reachable':False,'error':str(e)[:120]}
def metrics():
 c=db();q=c.execute('SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NULL').fetchone()['n'];retry=c.execute('SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NULL AND attempts>0').fetchone()['n'];sent=c.execute('SELECT COUNT(*) n FROM outbound_queue WHERE delivered_at IS NOT NULL').fetchone()['n'];events=c.execute('SELECT COUNT(*) n FROM local_events').fetchone()['n'];c.close();d=os.statvfs('/');temp=None
 try:temp=round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000,1)
 except:pass
 return {'node_id':NODE_ID,'version':APP_VERSION,'online':True,'uptime_seconds':int(time.time()-STARTED),'events':events,'queued':q,'retrying':retry,'delivered':sent,'janus':bool(SERVICE_TOKEN),'nexus_configured':bool(NEXUS_URL),'pulsar_configured':bool(PULSAR_URL),'temperature_c':temp,'disk_free_bytes':d.f_bavail*d.f_frsize,'disk_total_bytes':d.f_blocks*d.f_frsize,'time':utcnow()}
@app.on_event('startup')
async def startup():db().close();app.state.worker=asyncio.create_task(worker())
@app.on_event('shutdown')
async def shutdown():
 t=getattr(app.state,'worker',None)
 if t:t.cancel()
@app.get('/')
def root():return {'system':'UNG-EDGE','node_id':NODE_ID,'version':APP_VERSION,'status':'online','control_center':'/control'}
@app.get('/health')
def health():return {'ok':True,**metrics()}
@app.get('/v1/status')
def status():return metrics()
@app.get('/v1/control/status')
async def control_status():
 m=metrics();m['nexus']=await probe(NEXUS_URL);m['pulsar']=await probe(PULSAR_URL);return m
@app.get('/control',response_class=HTMLResponse)
def control():
 return HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>UNG-EDGE Control Center</title><style>body{font-family:Arial;background:#07111f;color:#eef;margin:0;padding:20px}.top{display:flex;justify-content:space-between;align-items:center}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#101f33;border:1px solid #29415f;border-radius:12px;padding:16px}.big{font-size:28px;font-weight:bold}.ok{color:#42e68b}.bad{color:#ff6b6b}.muted{color:#9db0c7}.flow{font-size:18px;margin:18px 0;padding:16px;background:#101f33;border-radius:12px}</style></head><body><div class="top"><div><h1>UNG-EDGE Control Center</h1><div class="muted" id="node">Loading...</div></div><div class="big ok" id="online">● ONLINE</div></div><div class="flow" id="flow">EDGE → JANUS → NEXUS → PULSAR → ATLAS</div><div class="grid" id="cards"></div><script>function b(n){return n>1073741824?(n/1073741824).toFixed(1)+' GB':(n/1048576).toFixed(0)+' MB'}function s(v){return v?'<span class="ok">● CONNECTED</span>':'<span class="bad">● NOT READY</span>'}async function load(){try{let r=await fetch('/v1/control/status');let d=await r.json();node.textContent=d.node_id+' • v'+d.version;cards.innerHTML=`<div class=card><div class=muted>Uptime</div><div class=big>${Math.floor(d.uptime_seconds/60)} min</div></div><div class=card><div class=muted>Temperature</div><div class=big>${d.temperature_c??'—'}°C</div></div><div class=card><div class=muted>Local Events</div><div class=big>${d.events}</div></div><div class=card><div class=muted>Queued</div><div class=big>${d.queued}</div></div><div class=card><div class=muted>Delivered</div><div class=big>${d.delivered}</div></div><div class=card><div class=muted>Retrying</div><div class=big>${d.retrying}</div></div><div class=card><div class=muted>JANUS Auth</div><div>${s(d.janus)}</div></div><div class=card><div class=muted>NEXUS</div><div>${s(d.nexus.reachable)}</div></div><div class=card><div class=muted>PULSAR</div><div>${s(d.pulsar.reachable)}</div></div><div class=card><div class=muted>Storage Free</div><div class=big>${b(d.disk_free_bytes)}</div></div>`;flow.innerHTML=`EDGE-001 ${s(true)} → JANUS ${s(d.janus)} → NEXUS ${s(d.nexus.reachable)} → PULSAR ${s(d.pulsar.reachable)} → ATLAS <span class=bad>● PENDING</span>`}catch(e){online.textContent='● OFFLINE';online.className='big bad'}}load();setInterval(load,5000)</script></body></html>''')
@app.get('/v1/commission')
async def commission():
 c=db();c.execute('INSERT OR REPLACE INTO local_events(id,topic,payload,created_at) VALUES(?,?,?,?)',('commission-storage-probe','edge.commission.storage',json.dumps({'node':NODE_ID}),utcnow()));c.commit();ok=c.execute("SELECT COUNT(*) n FROM local_events WHERE id='commission-storage-probe'").fetchone()['n']==1;c.close();p=await probe(PULSAR_URL);n=await probe(NEXUS_URL);return {'node_id':NODE_ID,'runtime':True,'sqlite':ok,'queue':True,'pulsar':p,'nexus':n,'janus_token_configured':bool(SERVICE_TOKEN),'commissioned':bool(ok and (p.get('reachable') or n.get('reachable')) and SERVICE_TOKEN),'time':utcnow()}
@app.post('/v1/events')
def ingest(e:EventIn):
 eid=str(uuid.uuid4());now=utcnow();p=json.dumps(e.payload,separators=(',',':'));c=db();c.execute('INSERT INTO local_events VALUES(?,?,?,?)',(eid,e.topic,p,now));c.execute('INSERT INTO outbound_queue(id,topic,payload,priority,created_at) VALUES(?,?,?,?,?)',(eid,e.topic,p,e.priority,now));c.commit();c.close();return {'accepted':True,'event_id':eid,'queued':True}
@app.post('/v1/sync')
async def sync():return {'ok':True,'delivered':await sync_once()}
@app.get('/v1/queue')
def queue(limit:int=100):
 c=db();rows=c.execute('SELECT id,topic,priority,created_at,attempts,last_error,delivered_at FROM outbound_queue ORDER BY created_at DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall();c.close();return {'items':[dict(r) for r in rows]}
