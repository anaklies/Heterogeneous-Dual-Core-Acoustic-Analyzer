"""SixMic3D PC backend (invisible backend, no UI design).

Protocol: sixmic-analysis v1 (see interfaces/pc_backend_v1/PROTOCOL.md).
Board device interface: MMIO protocol 3 (see interfaces/pc_backend_v1/device/MMIO_PROTOCOL3.md).
No automatic DOA, no fabricated live data, no CPU-side acoustic recomputation.
"""
from __future__ import annotations

__version__ = "0.1.0"
PROTOCOL_NAME = "sixmic-analysis"
PROTOCOL_VERSION = 1
DEVICE_PROTOCOL_VERSION = 3
BACKEND_STATUS = "backend-stage"
