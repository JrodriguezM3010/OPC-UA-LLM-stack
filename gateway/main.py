import os
import threading
import time
import logging
import logging.config
import yaml
import api
from config_loader import load_config, tag_definitions
from opcua_client import OPCUAClient, node_id
from postgres_client import PostgresClient
from change_detector import ChangeDetector
from sync_engine import SyncEngine
from tag_store import TagStore

# load logging configuration
with open('config/logging.yaml', 'r') as f:
    logging_config = yaml.safe_load(f)
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)

# With no runtime selected, re-detect it this often while none of the tags read
REDETECT_SECONDS = 10

def bind_nodes(opc, store):
    """Point the OPC UA client at the stored mapping. With no runtime selected,
    use the one the server offers. Does nothing when nothing changed."""
    runtime, paths = store.snapshot()
    if not runtime:
        try:
            runtime = opc.detect_runtime(paths)
        except Exception as e:
            logger.warning(f"Could not detect the runtime: {e}")
            return
    node_ids = {k: node_id(runtime, p) for k, p in paths.items()} if runtime else {}
    if runtime == opc.runtime and node_ids == opc.node_ids:
        return
    opc.load_nodes(runtime, node_ids)

def main():
    config = load_config()
    mapping = config['mapping']['opc_to_db']
    tags = tag_definitions(config)
    store = TagStore(os.getenv("GATEWAY_TAG_MAP", "data/tag-map.json"), tags)
    store.load()
    opc = OPCUAClient(**config['opcua'])
    db = PostgresClient(**config['postgres'])
    detector = ChangeDetector()
    sync = SyncEngine(
        opc, db,
        config['table']['name'],
        config['table']['target_id'],
        mapping
    )

    # Tag mapping API for the chat UI; saving sets `reload`
    reload = threading.Event()
    api.serve(int(os.getenv("GATEWAY_API_PORT", "8085")),
              opc=opc, db=db, store=store, tags=tags, reload=reload)

    # OPC UA connection
    opc.connect(logger=logger, retry_interval=5)

    # DB connection
    db.connect(logger=logger, retry_interval=5)

    # Bind the OPC UA nodes from the stored mapping
    bind_nodes(opc, store)
    last_bind = time.monotonic()

    try:
        while True:

            # Re-bind when the mapping is saved from the chat UI. With no runtime
            # selected, also re-detect while nothing reads.
            idle = set(opc.node_ids) <= opc.unresolved
            redetect = not store.runtime and idle and time.monotonic() - last_bind > REDETECT_SECONDS
            if reload.is_set() or redetect:
                reload.clear()
                bind_nodes(opc, store)
                last_bind = time.monotonic()

            # OPC UA read
            try:
                current_opc = opc.read_all()
            except Exception as e:
                logger.error(f"OPC UA error: {e}. Reconnecting...")
                opc.connect(logger=logger, retry_interval=5)
                bind_nodes(opc, store)
                continue

            # DB read
            try:
                db_record = db.get_record(config['table']['target_id'])
            except Exception as e:
                logger.error(f"DB error: {e}. Reconnecting...")
                db.connect(logger=logger, retry_interval=5)
                continue

            # Detect OPC UA changes and sync to DB
            opc_changes = detector.detect_opc_change(current_opc, detector.last_db)
            sync.sync_opc_to_db(opc_changes)

            # Detect DB changes and sync to OPC UA
            db_changes = detector.detect_db_change(db_record, detector.last_opc)
            sync.sync_db_to_opc(db_changes)

            # Update last known states
            detector.last_opc = current_opc.copy()
            detector.last_db = {k: db_record.get(mapping.get(k, k)) for k in current_opc.keys()}
            detector.last_source = db_record.get('source', 'unknown')

            # Sleep before next cycle
            time.sleep(config['sync']['interval_seconds'])

    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
    finally:
        opc.disconnect()
        db.disconnect()

if __name__ == "__main__":
    main()
