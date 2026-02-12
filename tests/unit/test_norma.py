# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the workload abstraction module (src/norma.py).

These tests use plain pytest with no ops dependency, validating that
the workload module is independently testable per Constitution Principle II.
"""

import os

import norma


class TestConstants:
    """Verify all expected constants are defined."""

    def test_ledger_file(self):
        assert norma.LEDGER_FILE == "/tmp/norma-event-ledger.json"

    def test_container_name(self):
        assert norma.CONTAINER_NAME == "norma"

    def test_secondary_container(self):
        assert norma.SECONDARY_CONTAINER == "norma-secondary"

    def test_default_port(self):
        assert norma.DEFAULT_PORT == 8080

    def test_secondary_port(self):
        assert norma.SECONDARY_PORT == 8081

    def test_health_flag_file(self):
        assert norma.HEALTH_FLAG_FILE == "/tmp/norma-unhealthy"

    def test_storage_path(self):
        assert norma.STORAGE_PATH == "/var/lib/norma"

    def test_marker_file(self):
        assert norma.MARKER_FILE == "calibration-marker.json"

    def test_binary_path(self):
        assert norma.BINARY_PATH == "/bin/norma"


class TestValidateConfig:
    """Test configuration validation logic."""

    def test_valid_defaults(self):
        config = {
            "calibration_string": "default",
            "calibration_int": 8080,
            "calibration_float": 1.0,
            "calibration_bool": True,
        }
        valid, msg = norma.validate_config(config)
        assert valid is True
        assert msg == ""

    def test_empty_string_invalid(self):
        config = {
            "calibration_string": "",
            "calibration_int": 8080,
            "calibration_float": 1.0,
        }
        valid, msg = norma.validate_config(config)
        assert valid is False
        assert "calibration-string" in msg

    def test_port_zero_invalid(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 0,
            "calibration_float": 1.0,
        }
        valid, msg = norma.validate_config(config)
        assert valid is False
        assert "calibration-int" in msg

    def test_port_too_high_invalid(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 99999,
            "calibration_float": 1.0,
        }
        valid, msg = norma.validate_config(config)
        assert valid is False
        assert "65535" in msg

    def test_negative_float_invalid(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 8080,
            "calibration_float": -1.0,
        }
        valid, msg = norma.validate_config(config)
        assert valid is False
        assert "calibration-float" in msg

    def test_zero_float_invalid(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 8080,
            "calibration_float": 0.0,
        }
        valid, _msg = norma.validate_config(config)
        assert valid is False

    def test_valid_custom_values(self):
        config = {
            "calibration_string": "custom",
            "calibration_int": 9090,
            "calibration_float": 3.14,
            "calibration_bool": False,
        }
        valid, _msg = norma.validate_config(config)
        assert valid is True

    def test_port_boundary_one(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 1,
            "calibration_float": 1.0,
        }
        valid, _ = norma.validate_config(config)
        assert valid is True

    def test_port_boundary_max(self):
        config = {
            "calibration_string": "test",
            "calibration_int": 65535,
            "calibration_float": 1.0,
        }
        valid, _ = norma.validate_config(config)
        assert valid is True


class TestBuildPebbleLayer:
    """Test Pebble layer construction for primary container."""

    def test_basic_structure(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        assert "services" in layer
        assert "checks" in layer
        assert "norma" in layer["services"]

    def test_service_config(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        svc = layer["services"]["norma"]
        assert svc["override"] == "replace"
        assert svc["startup"] == "enabled"
        assert svc["command"] == norma.BINARY_PATH
        assert "user" not in svc  # Run as container default user (OCI image USER)
        assert svc["environment"]["PORT"] == "8080"
        assert svc["environment"]["VERSION"] == "1.0.0"

    def test_custom_port(self):
        layer = norma.build_pebble_layer("norma", 9090, "2.0.0")
        svc = layer["services"]["norma"]
        assert svc["environment"]["PORT"] == "9090"

    def test_health_check_http(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        check = layer["checks"]["health"]
        assert check["level"] == "ready"
        assert "8080" in check["http"]["url"]

    def test_health_check_exec(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        check = layer["checks"]["alive"]
        assert check["level"] == "alive"
        assert norma.BINARY_PATH in check["exec"]["command"]

    def test_health_check_tcp(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        check = layer["checks"]["tcp-alive"]
        assert check["level"] == "alive"
        assert check["tcp"]["port"] == 8080

    def test_three_checks_present(self):
        layer = norma.build_pebble_layer("norma", 8080, "1.0.0")
        assert len(layer["checks"]) == 3


class TestBuildSecondaryLayer:
    """Test Pebble layer construction for secondary container."""

    def test_secondary_service(self):
        layer = norma.build_secondary_layer("1.0.0")
        assert "norma-secondary" in layer["services"]

    def test_secondary_port(self):
        layer = norma.build_secondary_layer("1.0.0")
        svc = layer["services"]["norma-secondary"]
        assert svc["environment"]["PORT"] == str(norma.SECONDARY_PORT)

    def test_secondary_health_check(self):
        layer = norma.build_secondary_layer("1.0.0")
        assert "health-secondary" in layer["checks"]
        check = layer["checks"]["health-secondary"]
        assert str(norma.SECONDARY_PORT) in check["http"]["url"]


class TestEventLedgerPersistence:
    """Test event ledger file-based persistence."""

    def setup_method(self):
        self._orig = norma.LEDGER_FILE

    def teardown_method(self):
        norma.LEDGER_FILE = self._orig
        # Clean up temp file if created
        if os.path.exists(norma.LEDGER_FILE):
            os.remove(norma.LEDGER_FILE)

    def _use_tmp(self, tmp_path):
        norma.LEDGER_FILE = str(tmp_path / "ledger.json")

    def test_read_empty_when_no_file(self, tmp_path):
        self._use_tmp(tmp_path)
        assert norma.read_event_ledger() == []

    def test_write_then_read_roundtrip(self, tmp_path):
        self._use_tmp(tmp_path)
        entries = [{"event_name": "install", "timestamp": "t1", "unit_name": "u/0", "extra": {}}]
        norma.write_event_ledger(entries)
        assert norma.read_event_ledger() == entries

    def test_append_persists(self, tmp_path):
        self._use_tmp(tmp_path)
        norma.write_event_ledger([{"event_name": "install"}])
        ledger = norma.read_event_ledger()
        ledger.append({"event_name": "config-changed"})
        norma.write_event_ledger(ledger)
        result = norma.read_event_ledger()
        assert len(result) == 2
        assert result[0]["event_name"] == "install"
        assert result[1]["event_name"] == "config-changed"

    def test_read_returns_empty_on_corrupt_json(self, tmp_path):
        self._use_tmp(tmp_path)
        with open(norma.LEDGER_FILE, "w") as f:
            f.write("not json{{{")
        assert norma.read_event_ledger() == []
