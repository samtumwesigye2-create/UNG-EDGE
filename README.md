# UNG-EDGE

Physical edge-compute runtime for Uganda National Grid nodes.

## EDGE-001 bootstrap

From Raspberry Pi OS:

```bash
curl -fsSL https://raw.githubusercontent.com/samtumwesigye2-create/UNG-EDGE/main/bootstrap.sh | bash
```

The bootstrap installs/updates the runtime under `~/ung-edge`, creates a systemd service, and starts the node on port 8080.

Runtime capabilities: local FastAPI control API, durable SQLite event store, offline-first outbound queue, retry/sync worker, NEXUS/PULSAR relay hooks, JANUS service-token slot, health/status/queue/event endpoints, and systemd auto-start.

Secrets are never committed. Provision `UNG_EDGE_SERVICE_TOKEN` only in `~/ung-edge/edge.env` on the node.
