from opcua import Client, ua
import logging
import time

logger = logging.getLogger(__name__)

# Every vPLC tag is a string NodeId in namespace 1, led by the runtime's name:
#   ns=1;s=<runtime>.Tags.config.<...>.TankLevel_PV
NS = 1

# Built-in OPC UA data types the DB columns can hold
_BOOL = {ua.ObjectIds.Boolean}
_NUMBER = {
    ua.ObjectIds.SByte, ua.ObjectIds.Byte,
    ua.ObjectIds.Int16, ua.ObjectIds.UInt16,
    ua.ObjectIds.Int32, ua.ObjectIds.UInt32,
    ua.ObjectIds.Int64, ua.ObjectIds.UInt64,
    ua.ObjectIds.Float, ua.ObjectIds.Double,
}
_CURRENT_WRITE = 0x02  # AccessLevel bit


def node_id(runtime, path):
    return f"ns={NS};s={runtime}.{path}"


def _good(dv):
    return dv.StatusCode is None or dv.StatusCode.is_good()


def _kind(data_type):
    """'bool' or 'number' for a DataType attribute, None for anything else."""
    if not isinstance(data_type, ua.NodeId) or data_type.NamespaceIndex != 0:
        return None
    if data_type.Identifier in _BOOL:
        return "bool"
    if data_type.Identifier in _NUMBER:
        return "number"
    return None


class OPCUAClient:
    def __init__(self, url, user=None, password=None):
        self.url = url
        self.user = (user or "").strip() or None
        self.password = (password or "").strip() or None
        self.client = Client(url)
        self.connected = False
        self.runtime = ""        # runtime the tags are bound to
        self.node_ids = {}       # tag -> NodeId string
        self.unresolved = set()  # mapped tags the server rejects

    @property
    def anonymous(self):
        return self.user is None

    def connect(self, logger=None, retry_interval=5):
        self.connected = False
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
                self.connected = True
                if logger:
                    mode = "anonymous" if self.anonymous else f"user '{self.user}'"
                    logger.info(f"OPC UA Connected ({mode})")
                break
            except Exception as e:
                if logger:
                    logger.error(f"OPC UA connection error: {e}. Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)

    def load_nodes(self, runtime, node_ids):
        self.runtime = runtime
        self.node_ids = dict(node_ids)
        self.unresolved = set()
        if not runtime:
            logger.warning("No runtime found; select one under Tag mapping in the chat UI")
        elif not node_ids:
            logger.warning(f"Bound to runtime '{runtime}', but no tags are mapped yet; map them under Tag mapping in the chat UI")
        else:
            logger.info(f"Nodes loaded from runtime '{runtime}': {list(self.node_ids.keys())}")

    def read_all(self):
        """Values of the tags that read good. A tag the server rejects is left
        out and logged once, so one bad mapping does not stop the others."""
        if not self.node_ids:
            return {}
        keys = list(self.node_ids)
        try:
            results = self._read(self.client, [ua.NodeId.from_string(self.node_ids[k]) for k in keys],
                                 ua.AttributeIds.Value)
        except Exception:
            self.connected = False
            raise

        values, bad = {}, {}
        for k, dv in zip(keys, results):
            if _good(dv):
                values[k] = dv.Value.Value
            else:
                bad[k] = dv.StatusCode.name
        for k in bad.keys() - self.unresolved:
            logger.error(f"Failed to read tag '{k}' ({self.node_ids[k]}): {bad[k]}")
        for k in self.unresolved - bad.keys():
            logger.info(f"Tag '{k}' reads again")
        self.unresolved = set(bad)
        return values

    def write(self, node_name, value):
        if node_name not in self.node_ids:
            logger.warning(f"Tag '{node_name}' is not mapped to an OPC UA node; skipping write")
            return
        node = self.client.get_node(self.node_ids[node_name])
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

    # ---- address space, for the Tag mapping panel ----

    def runtimes(self):
        """Names of the runtimes on the server."""
        objects = self.client.get_objects_node()
        children = objects.get_children()
        for child in children:
            if child.get_browse_name().Name == "Devices":
                return sorted(c.get_browse_name().Name for c in child.get_children())
        # No Devices folder: some servers hang the runtime straight off Objects
        return sorted(c.get_browse_name().Name for c in children if c.nodeid.NamespaceIndex != 0)

    def browse(self, runtime):
        """Every bool or numeric variable under `runtime`, as {path: kind}."""
        client = self.client
        found = []
        self._walk(client, client.get_node(f"ns={NS};s={runtime}"), 0, found)

        prefix = runtime + "."
        found = [n for n in found
                 if n.NamespaceIndex == NS and isinstance(n.Identifier, str) and n.Identifier.startswith(prefix)]
        types = self._read(client, found, ua.AttributeIds.DataType)
        nodes = {}
        for n, dv in zip(found, types):
            kind = _kind(dv.Value.Value) if _good(dv) else None
            if kind:
                nodes[n.Identifier[len(prefix):]] = kind
        return nodes

    def inspect(self, runtime, paths):
        """For each tag -> path: the node's kind and whether it is writable,
        or None when the server does not have it."""
        client = self.client
        keys = list(paths)
        ids = [ua.NodeId.from_string(node_id(runtime, paths[k])) for k in keys]
        types = self._read(client, ids, ua.AttributeIds.DataType)
        access = self._read(client, ids, ua.AttributeIds.UserAccessLevel)
        found = {}
        for k, t, a in zip(keys, types, access):
            if not _good(t):
                found[k] = None
                continue
            found[k] = {
                "kind": _kind(t.Value.Value),
                "writable": _good(a) and bool(a.Value.Value & _CURRENT_WRITE),
            }
        return found

    def detect_runtime(self, paths):
        """The runtime to bind when none is selected: the only one on the
        server, else the first where every mapped path exists."""
        names = self.runtimes()
        if len(names) == 1:
            return names[0]
        for name in names if paths else []:
            if all(self.inspect(name, paths).values()):
                return name
        return ""

    def _walk(self, client, node, depth, out, max_depth=12):
        if depth > max_depth:
            return
        try:
            refs = node.get_children_descriptions()
        except Exception:
            return  # An unreadable branch is not fatal
        for ref in refs:
            if ref.NodeClass == ua.NodeClass.Variable:
                out.append(ref.NodeId)
            if ref.NodeClass in (ua.NodeClass.Object, ua.NodeClass.Variable):
                self._walk(client, client.get_node(ref.NodeId), depth + 1, out, max_depth)

    @staticmethod
    def _read(client, node_ids, attribute, chunk=500):
        """One attribute of many nodes in few round trips: a DataValue per
        node, bad ones included rather than raised."""
        results = []
        for i in range(0, len(node_ids), chunk):
            params = ua.ReadParameters()
            for nid in node_ids[i:i + chunk]:
                rv = ua.ReadValueId()
                rv.NodeId = nid
                rv.AttributeId = attribute
                params.NodesToRead.append(rv)
            results.extend(client.uaclient.read(params))
        return results

    def disconnect(self):
        self.client.disconnect()
        logger.info("OPC UA disconnected")
