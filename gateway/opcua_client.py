from opcua import Client, ua
import logging
import time

logger = logging.getLogger(__name__)

class OPCUAClient:
    def __init__(self, url, user=None, password=None):
        self.url = url
        self.user = (user or "").strip() or None
        self.password = (password or "").strip() or None
        self.client = Client(url)
        self.nodes = {}

    @property
    def anonymous(self):
        return self.user is None

    def connect(self, logger=None, retry_interval=5):
        while True:
            try:
                # Always disconnect before connecting to avoid too many sessions
                try:
                    self.client.disconnect()
                except Exception:
                    pass  # Ignore errors if not connected

                self.client = Client(self.url)
                if not self.anonymous:
                    self.client.set_user(self.user)
                    if self.password is not None:
                        self.client.set_password(self.password)
                self.client.connect()
                if logger:
                    mode = "anonymous" if self.anonymous else f"user '{self.user}'"
                    logger.info(f"OPC UA Connected ({mode})")
                break
            except Exception as e:
                if logger:
                    logger.error(f"OPC UA connection error: {e}. Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)

    def load_nodes(self, node_map):
        self.nodes = {k: self.client.get_node(nid) for k, nid in node_map.items()}
        logger.info(f"Nodes loaded: {list(self.nodes.keys())}")

    def read_all(self):
        result = {}
        for k, n in self.nodes.items():
            try:
                result[k] = n.get_value()
            except Exception as e:
                logger.error(f"Failed to read node '{k}' ({n.nodeid}): {e}")
                raise
        return result

    def write(self, node_name, value):
        if node_name not in self.nodes:
            logger.warning(f"Node not found: {node_name}")
            return
        node = self.nodes[node_name]
        try:
            variant_type = node.get_data_type_as_variant_type()
            # Map basic types
            if variant_type.name in ['Int16', 'Int32', 'UInt16', 'UInt32']:
                value = int(value)
            elif variant_type.name in ['Float', 'Double']:
                value = float(value)
            elif variant_type.name == 'Boolean':
                value = bool(value)
            # Use ua.Variant to ensure type correctness
            value_variant = ua.Variant(value, variant_type)
            node.set_value(value_variant)
            logger.info(f"Wrote to OPC UA → {node_name} = {value} (type: {variant_type.name})")
        except Exception as e:
            logger.error(f"Error writing to OPC UA: {e}")

    def disconnect(self):
        self.client.disconnect()
        logger.info("OPC UA disconnected")
