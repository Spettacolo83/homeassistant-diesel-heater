"""Tests for Vevor Heater __init__.py.

Tests the setup, unload, migration, and service registration logic.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater import (
    _migrate_entity_unique_ids,
    _safe_update_unique_id,
    _UNIQUE_ID_MIGRATIONS,
    _UNIQUE_IDS_TO_REMOVE,
)


# ---------------------------------------------------------------------------
# _safe_update_unique_id tests
# ---------------------------------------------------------------------------

class TestSafeUpdateUniqueId:
    """Tests for _safe_update_unique_id helper."""

    def test_update_success_no_conflict(self):
        """Test successful update when no conflict exists."""
        registry = MagicMock()
        registry.entities = {}

        result = _safe_update_unique_id(
            registry,
            "sensor.test_entity",
            "old_uid",
            "new_uid",
        )

        assert result is True
        registry.async_update_entity.assert_called_once_with(
            "sensor.test_entity", new_unique_id="new_uid"
        )

    def test_update_removes_duplicate_on_conflict(self):
        """Test that duplicate entity is removed when target uid exists."""
        registry = MagicMock()
        existing_entity = MagicMock()
        existing_entity.unique_id = "new_uid"
        existing_entity.entity_id = "sensor.existing_entity"
        registry.entities = {"sensor.existing_entity": existing_entity}

        result = _safe_update_unique_id(
            registry,
            "sensor.duplicate_entity",
            "corrupted_uid",
            "new_uid",
        )

        assert result is True
        registry.async_remove.assert_called_once_with("sensor.duplicate_entity")
        registry.async_update_entity.assert_not_called()

    def test_update_handles_value_error(self):
        """Test graceful handling of unexpected ValueError."""
        registry = MagicMock()
        registry.entities = {}
        registry.async_update_entity.side_effect = ValueError("test error")

        result = _safe_update_unique_id(
            registry,
            "sensor.test_entity",
            "old_uid",
            "new_uid",
        )

        assert result is False


# ---------------------------------------------------------------------------
# _migrate_entity_unique_ids tests
# ---------------------------------------------------------------------------

class TestMigrateEntityUniqueIds:
    """Tests for entity unique_id migration."""

    def _make_entity(self, unique_id: str, entity_id: str = None) -> MagicMock:
        """Create a mock entity registry entry."""
        entity = MagicMock()
        entity.unique_id = unique_id
        entity.entity_id = entity_id or f"sensor.test_{unique_id.split('_')[-1]}"
        return entity

    def test_migration_skips_already_migrated(self):
        """Test that already-migrated entities are not re-migrated."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        registry = MagicMock()
        entity = self._make_entity(
            "DC:32:62:40:6A:00_est_daily_fuel_consumed",
            "sensor.test_est_daily"
        )
        registry.entities = {entity.entity_id: entity}

        with patch(
            "custom_components.vevor_heater.er.async_get", return_value=registry
        ), patch(
            "custom_components.vevor_heater.er.async_entries_for_config_entry",
            return_value=[entity],
        ):
            _migrate_entity_unique_ids(hass, entry)

        # Should not try to update since it already ends with new suffix
        registry.async_update_entity.assert_not_called()

    def test_migration_fixes_corrupted_unique_id(self):
        """Test that corrupted unique_ids with repeated _est_ are fixed."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        registry = MagicMock()
        # Simulates corrupted unique_id with multiple _est_ prefixes
        corrupted_uid = "DC:32:62:40:6A:00_est_est_daily_fuel_consumed"
        expected_uid = "DC:32:62:40:6A:00_est_daily_fuel_consumed"
        entity = self._make_entity(corrupted_uid, "sensor.test_corrupted")
        registry.entities = {entity.entity_id: entity}

        with patch(
            "custom_components.vevor_heater.er.async_get", return_value=registry
        ), patch(
            "custom_components.vevor_heater.er.async_entries_for_config_entry",
            return_value=[entity],
        ):
            _migrate_entity_unique_ids(hass, entry)

        # Should fix the corrupted unique_id
        registry.async_update_entity.assert_called()

    def test_migration_removes_deprecated_backlight(self):
        """Test that deprecated backlight number entity is removed."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        registry = MagicMock()
        entity = self._make_entity(
            "DC:32:62:40:6A:00_backlight",
            "number.test_backlight"
        )
        registry.entities = {entity.entity_id: entity}

        with patch(
            "custom_components.vevor_heater.er.async_get", return_value=registry
        ), patch(
            "custom_components.vevor_heater.er.async_entries_for_config_entry",
            return_value=[entity],
        ):
            _migrate_entity_unique_ids(hass, entry)

        # Should remove the deprecated entity
        registry.async_remove.assert_called_once_with("number.test_backlight")

    def test_migration_renames_old_suffix(self):
        """Test that old suffixes are renamed to new suffixes."""
        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry"

        registry = MagicMock()
        # Old suffix without _est_ prefix
        entity = self._make_entity(
            "DC:32:62:40:6A:00_daily_fuel_consumed",
            "sensor.test_daily_fuel"
        )
        registry.entities = {entity.entity_id: entity}

        with patch(
            "custom_components.vevor_heater.er.async_get", return_value=registry
        ), patch(
            "custom_components.vevor_heater.er.async_entries_for_config_entry",
            return_value=[entity],
        ):
            _migrate_entity_unique_ids(hass, entry)

        # Should rename to new suffix with _est_ prefix
        registry.async_update_entity.assert_called()


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestMigrationConstants:
    """Test migration constant definitions."""

    def test_unique_id_migrations_defined(self):
        """Test that migration mappings are defined."""
        assert "_hourly_fuel_consumption" in _UNIQUE_ID_MIGRATIONS
        assert "_daily_fuel_consumed" in _UNIQUE_ID_MIGRATIONS
        assert "_total_fuel_consumed" in _UNIQUE_ID_MIGRATIONS
        assert "_daily_fuel_history" in _UNIQUE_ID_MIGRATIONS
        assert "_reset_fuel_level" in _UNIQUE_ID_MIGRATIONS

    def test_unique_ids_to_remove_defined(self):
        """Test that removal list is defined."""
        assert "_backlight" in _UNIQUE_IDS_TO_REMOVE

    def test_all_new_suffixes_have_est_prefix(self):
        """Test that all new suffixes use _est_ naming."""
        for old, new in _UNIQUE_ID_MIGRATIONS.items():
            if "fuel" in old:
                assert "_est_" in new, f"Expected _est_ in {new}"
