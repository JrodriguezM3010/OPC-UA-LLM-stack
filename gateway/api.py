"""HTTP API behind the chat UI's Tag mapping panel.

Runs on a thread beside the sync loop. The panel lists the runtimes and nodes
on the OPC UA server; saving checks the mapping against the live server, stores
it, and the loop re-binds on its next cycle, with no restart.
"""

import logging
import threading
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from opcua_client import node_id

logger = logging.getLogger(__name__)

app = FastAPI(title="OPC UA gateway", docs_url=None, redoc_url=None)
ctx = SimpleNamespace()  # opc, db, store, tags, reload; set by serve()
_node_cache = {}         # runtime -> {path: kind}


def serve(port, **deps):
    """Start the API on a background thread."""
    ctx.__dict__.update(deps)
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_config=None, access_log=False)
    threading.Thread(target=uvicorn.Server(config).run, name="api", daemon=True).start()
    logger.info(f"Tag mapping API on port {port}")


def _require_connection():
    if not ctx.opc.connected:
        raise HTTPException(409, "Not connected to the OPC UA server")


def _ask_server(fn, *args):
    """Run an OPC UA call for a request; a failure becomes a 502."""
    try:
        return fn(*args)
    except Exception as e:
        raise HTTPException(502, f"OPC UA server error: {e}") from None


@app.get("/api/tagmap")
def get_tagmap():
    """Every tag, the node it is mapped to, and whether that node reads."""
    runtime, paths = ctx.store.snapshot()
    opc = ctx.opc
    rows = []
    for key, tag in ctx.tags.items():
        path = paths.get(key, "")
        bound = bool(opc.runtime) and opc.node_ids.get(key) == node_id(opc.runtime, path)
        if not path:
            status = "unmapped"
        elif not (opc.connected and bound):
            status = "waiting"
        elif key in opc.unresolved:
            status = "missing"
        else:
            status = "good"
        rows.append({
            "key": key, "column": tag["column"], "writable": tag["writable"],
            "kind": ctx.db.column_kind(tag["column"]), "path": path, "status": status,
        })
    return {"runtime": runtime, "active_runtime": opc.runtime, "connected": opc.connected, "tags": rows}


@app.get("/api/runtimes")
def get_runtimes():
    _require_connection()
    return {"runtimes": _ask_server(ctx.opc.runtimes), "active": ctx.opc.runtime}


@app.get("/api/nodes")
def get_nodes(runtime: str, refresh: bool = False):
    """Bool and numeric variables under `runtime`, as paths below it. Cached:
    a full browse is hundreds of round trips."""
    if refresh or runtime not in _node_cache:
        _require_connection()
        _node_cache[runtime] = _ask_server(ctx.opc.browse, runtime)
        logger.info(f"Browsed {len(_node_cache[runtime])} nodes under runtime '{runtime}'")
    nodes = _node_cache[runtime]
    return {"runtime": runtime, "nodes": [{"path": p, "kind": k} for p, k in sorted(nodes.items())]}


class TagMap(BaseModel):
    runtime: str = ""  # empty = detect from the server
    paths: dict[str, str] = Field(default_factory=dict)  # tag -> path below the runtime; empty = unmapped


@app.put("/api/tagmap")
def put_tagmap(req: TagMap):
    """Check the mapping against the live server, then save it. Every mapped
    node must exist, match its DB column's type, and be writable if it is a
    command, so a wrong pick never reaches the sync loop."""
    unknown = set(req.paths) - set(ctx.tags)
    if unknown:
        raise HTTPException(400, f"Unknown tag(s): {', '.join(sorted(unknown))}")
    runtime = req.runtime.strip()
    paths = {k: p.strip() for k, p in req.paths.items() if p.strip()}

    if runtime or paths:
        _require_connection()
    if runtime and runtime not in _ask_server(ctx.opc.runtimes):
        raise HTTPException(400, f"Runtime '{runtime}' is not on the OPC UA server")

    if paths:
        if ctx.db.table is None:
            raise HTTPException(503, "Not connected to the database yet")
        target = runtime or _ask_server(ctx.opc.detect_runtime, paths)
        if not target:
            raise HTTPException(400, "Could not detect the runtime; select one")
        found = _ask_server(ctx.opc.inspect, target, paths)
        errors = {}
        for key in paths:
            node, tag = found[key], ctx.tags[key]
            want = ctx.db.column_kind(tag["column"])
            if node is None:
                errors[key] = f"Not found on runtime '{target}'"
            elif want and node["kind"] != want:
                errors[key] = f"Column {tag['column']} holds a {want}, but this node is {node['kind'] or 'neither bool nor number'}"
            elif tag["writable"] and not node["writable"]:
                errors[key] = "Node is read-only, but the AI writes this tag"
        if errors:
            raise HTTPException(400, {"message": "Some tags do not match the server", "errors": errors})

    ctx.store.save(runtime, paths)
    ctx.reload.set()
    return get_tagmap()
