import asyncio
import os
import httpx

ATLAS_URL = os.getenv('UNG_ATLAS_URL', 'https://ung-atlas-production.up.railway.app').rstrip('/')
HEARTBEAT_SECONDS = int(os.getenv('UNG_EDGE_HEARTBEAT_SECONDS', '30'))

async def send_heartbeat(metrics_fn, headers_fn, connectivity_fn):
    metrics = metrics_fn()
    connectivity = await connectivity_fn()
    body = {
        'node_id': metrics['node_id'],
        'version': metrics['version'],
        'role': os.getenv('UNG_EDGE_ROLE', 'field-gateway'),
        'status': 'online',
        'uptime_seconds': metrics['uptime_seconds'],
        'temperature_c': metrics['temperature_c'],
        'events': metrics['events'],
        'queued': metrics['queued'],
        'delivered': metrics['delivered'],
        'retrying': metrics['retrying'],
        'disk_free_bytes': metrics['disk_free_bytes'],
        'janus': metrics['janus'],
        'nexus': bool(connectivity.get('nexus', {}).get('reachable')),
        'pulsar': bool(connectivity.get('pulsar', {}).get('reachable')),
    }
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(f'{ATLAS_URL}/v1/edge/heartbeat', json=body, headers=headers_fn())
        response.raise_for_status()
        return response.json()

async def heartbeat_worker(metrics_fn, headers_fn, connectivity_fn, state):
    while True:
        try:
            result = await send_heartbeat(metrics_fn, headers_fn, connectivity_fn)
            state['atlas_connected'] = True
            state['atlas_last_error'] = None
            state['atlas_last_heartbeat'] = result.get('node', {}).get('last_seen')
        except Exception as exc:
            state['atlas_connected'] = False
            state['atlas_last_error'] = str(exc)[:160]
        await asyncio.sleep(HEARTBEAT_SECONDS)
