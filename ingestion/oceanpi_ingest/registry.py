"""An explicit allowlist: archive contents cannot grant a node processing access."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Node:
    node_id: str
    vessel_id: str
    node_type: str
    bucket: str
    prefix: str
    data_type: str = "nmea2000.raw"
    input_format: str = "candump"
    date_partitioned: bool = True
    approved: bool = True

    def __post_init__(self):
        for name in ("node_id", "vessel_id", "node_type"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9_/-]{0,127}", getattr(self, name)):
                raise ValueError(f"Invalid {name}")
        if not self.bucket or "/" in self.bucket:
            raise ValueError("An exact R2 bucket name is required")
        if not self.prefix or not self.prefix.endswith("/") or self.prefix.startswith("/"):
            raise ValueError("A nonempty relative prefix ending in / is required")
        if any(segment in (".", "..", "") for segment in self.prefix[:-1].split("/")):
            raise ValueError("Invalid archive prefix")
        if self.input_format not in ("candump", "canboat"):
            raise ValueError("Cloud NMEA processor requires raw input with known units")
        if type(self.approved) is not bool or type(self.date_partitioned) is not bool:
            raise ValueError("Approval and partition settings must be booleans")

    def as_dict(self):
        return asdict(self)


def load_nodes(path, default_bucket=None):
    if path:
        data = json.loads(Path(path).read_text())
        if data.get("schema_version") != 1 or not isinstance(data.get("nodes"), list):
            raise ValueError("Expected registry schema_version 1 and nodes array")
        nodes = [Node(**row) for row in data["nodes"]]
    else:
        nodes = [
            Node(
                "tabor-boy/nmea-main",
                "tabor-boy",
                "nmea2000",
                default_bucket or "",
                "raw/tabor-boy/",
            )
        ]
    ids = set()
    for index, node in enumerate(nodes):
        if node.node_id in ids:
            raise ValueError("Duplicate node ID")
        ids.add(node.node_id)
        for other in nodes[:index]:
            if node.bucket == other.bucket and (
                node.prefix.startswith(other.prefix) or other.prefix.startswith(node.prefix)
            ):
                raise ValueError("Node archive prefixes must not overlap")
    return nodes
