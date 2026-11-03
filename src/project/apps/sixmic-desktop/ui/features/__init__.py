"""Pure-Python echo-features-1 feature wiring package (no PySide6 imports).

Public surface consumed by the Lead-owned AppViewModel facade:

* :class:``FeatureRuntime`` -- UI state machine, 8-slot scheduler, polling,
  reference lifecycle and the documented flows;
* :func:``load_spec`` / :class:``FeatureCatalog`` -- read-only view spec and
  device catalog validation;
* :func:``decode_result`` -- schema-driven, bounded QML chart payloads;
* :mod:``flows`` -- fixed-hidden workflow definitions.
"""
from __future__ import annotations

from .catalog import (EXPECTED_FEATURE_COUNT, INTERFACE_VERSION, CatalogError,
                      CatalogReport, FeatureCatalog, load_spec, reason,
                      validate_feature_list_pages)
from .decoder import (DecodeError, ResultPageAssembler, decode_result,
                      peak_envelope, u32_words, validate_result_pages)
from .runtime import FeatureRuntime

__all__ = [
    "FeatureRuntime",
    "FeatureCatalog",
    "CatalogReport",
    "CatalogError",
    "load_spec",
    "reason",
    "decode_result",
    "DecodeError",
    "ResultPageAssembler",
    "validate_result_pages",
    "peak_envelope",
    "u32_words",
    "EXPECTED_FEATURE_COUNT",
    "INTERFACE_VERSION",
]
