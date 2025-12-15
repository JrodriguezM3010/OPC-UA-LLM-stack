import logging
from config_loader import load_config

logger = logging.getLogger(__name__)

class ChangeDetector:
    def __init__(self):
        self.last_opc = {}
        self.last_db = {}
        self.last_source = 'unknown'
        config = load_config()
        self.opc_to_db = config['mapping']['opc_to_db']
        self.commands_to_db = config['mapping'].get('commands_to_db', {})
        # Invert mappings for DB to OPC
        self.db_to_opc = {v: k for k, v in self.opc_to_db.items()}
        self.db_to_commands = {v: k for k, v in self.commands_to_db.items()}

    def detect_opc_change(self, current_opc, last_db):
        changes = {}
        for k, v in current_opc.items():
            if self.last_opc.get(k) != v and last_db.get(k) != v:
                changes[k] = {'value': v, 'source': 'external'}
                logger.info(f"Change detected from external: {k} = {v}")
        return changes

    def detect_db_change(self, db_record, last_opc, source_field='source'):
        if db_record.get(source_field) == 'ai':
            changes = {}

            # Detect changes in commands
            for db_field, node_name in self.db_to_commands.items():
                db_val = db_record.get(db_field)
                opc_val = last_opc.get(node_name)
                if db_val is not None and db_val != opc_val:
                    changes[node_name] = {'value': db_val, 'source': 'ai'}
                    logger.info(f"Change detected from AI (command): {node_name} = {db_val}")
            return changes
        
        return {}