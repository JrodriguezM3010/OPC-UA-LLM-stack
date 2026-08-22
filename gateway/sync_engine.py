import logging

logger = logging.getLogger(__name__)

class SyncEngine:
    def __init__(self, opc_client, db_client, table, target_id, mapping):
        self.opc = opc_client
        self.db = db_client
        self.table = table
        self.target_id = target_id
        self.mapping = mapping  

    def sync_opc_to_db(self, changes):
        if not changes:
            return

        payload = {
            "source": "external"
        }

        for node_name, data in changes.items():
            db_column = self.mapping.get(node_name, node_name)  # fallback
            payload[db_column] = data['value']

        self.db.upsert(self.target_id, payload)

    def sync_db_to_opc(self, changes):
        if not changes:
            return
        for node, data in changes.items():
            self.opc.write(node, data['value'])
        # Avoid loop: mark as synchronized
        self.db.upsert(self.target_id, {"source": "synced"})