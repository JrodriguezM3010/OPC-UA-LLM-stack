import yaml
import os
from string import Template
from dotenv import load_dotenv

load_dotenv()

def load_config(path="config/config.yaml"):
    with open(path, 'r') as f:
        config = yaml.safe_load(f)

    # Replace environment variables in config
    def replace_env(obj):
        if isinstance(obj, dict):
            return {k: replace_env(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_env(i) for i in obj]
        elif isinstance(obj, str):
            try:
                return Template(obj).substitute(os.environ)
            except KeyError as e:
                raise ValueError(f"Environment variable {e} not found for configuration.")
        return obj

    config = replace_env(config)

    # Validate environment variables
    required_env = ["POSTGRES_PASSWORD"]
    for var in required_env:
        if not os.getenv(var):
            raise ValueError(f"Missing required environment variable: {var}")
    required_config = ["opcua", "table", "mapping", "sync"]
    for key in required_config:
        if key not in config:
            raise ValueError(f"Missing required field in config.yaml: {key}")
    return config

def tag_definitions(config):
    """The fixed set of tags: key -> DB column, and whether the AI writes it.
    Which OPC UA node each tag reads is mapped from the chat UI, not here."""
    mapping = config['mapping']
    tags = {k: {"column": c, "writable": False} for k, c in mapping['opc_to_db'].items()}
    tags.update({k: {"column": c, "writable": True} for k, c in mapping.get('commands_to_db', {}).items()})
    return tags