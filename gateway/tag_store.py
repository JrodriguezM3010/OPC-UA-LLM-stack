"""
Where each tag reads from on the vPLC: the runtime, and one node per tag.
Paths are stored below the runtime (the full NodeId is ns=1;s=<runtime>.<path>),
"""

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class TagStore:
    def __init__(self, path, tag_keys):
        self.path = Path(path)
        self.tag_keys = set(tag_keys)
        self.runtime = ""   # empty = detect from the server
        self.paths = {}     # tag key -> node path below the runtime
        self._lock = threading.Lock()

    def load(self):
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            logger.warning(f"No tag mapping at {self.path} yet; map the tags from the chat UI")
            return
        except (OSError, ValueError) as e:
            logger.warning(f"Ignoring unreadable tag mapping {self.path}: {e}")
            return
        if not isinstance(raw, dict):
            logger.warning(f"Ignoring tag mapping {self.path}: not an object")
            return

        runtime = raw.get("runtime")
        self.runtime = runtime.strip() if isinstance(runtime, str) else ""
        paths = raw.get("paths")
        for key, path in (paths.items() if isinstance(paths, dict) else []):
            if key not in self.tag_keys:
                logger.warning(f"Dropping mapping for unknown tag '{key}'")
            elif isinstance(path, str) and path.strip():
                self.paths[key] = path.strip()
        logger.info(f"Tag mapping loaded: runtime '{self.runtime or 'auto'}', {len(self.paths)} tag(s) mapped")

    def snapshot(self):
        with self._lock:
            return self.runtime, dict(self.paths)

    def save(self, runtime, paths):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so a crash cannot truncate the file
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps({"runtime": runtime, "paths": paths}, indent=2, sort_keys=True) + "\n")
            tmp.replace(self.path)
            self.runtime = runtime
            self.paths = dict(paths)
        logger.info(f"Tag mapping saved: runtime '{runtime or 'auto'}', {len(paths)} tag(s) mapped")
