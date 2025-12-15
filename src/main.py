import time
import logging
import logging.config
import yaml
from config_loader import load_config
from opcua_client import OPCUAClient
from postgres_client import PostgresClient
from change_detector import ChangeDetector
from sync_engine import SyncEngine

# load logging configuration
with open('config/logging.yaml', 'r') as f:
    logging_config = yaml.safe_load(f)
logging.config.dictConfig(logging_config)
logger = logging.getLogger(__name__)

def main():
    config = load_config()
    mapping = config['mapping']['opc_to_db']
    opc = OPCUAClient(**config['opcua'])
    all_nodes = {**config['nodes']['variables'], **config['nodes']['commands']}
    db = PostgresClient(**config['postgres'])
    detector = ChangeDetector()
    sync = SyncEngine(
        opc, db,
        config['table']['name'],
        config['table']['target_id'],
        mapping  
    )

    # OPC UA connection
    opc.connect(logger=logger, retry_interval=5)

    # DB connection
    db.connect(logger=logger, retry_interval=5)

    # Load OPC UA nodes
    opc.load_nodes(all_nodes)

    try:
        while True:
            
            # OPC UA read
            try:
                current_opc = opc.read_all()
            except Exception as e:
                logger.error(f"OPC UA error: {e}. Reconnecting...")
                opc.connect(logger=logger, retry_interval=5)

            # DB read
            try:
                db_record = db.get_record(config['table']['target_id'])
            except Exception as e:
                logger.error(f"DB error: {e}. Reconnecting...")
                db.connect(logger=logger, retry_interval=5)

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