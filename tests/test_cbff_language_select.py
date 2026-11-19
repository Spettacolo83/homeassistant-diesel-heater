"""Sunster V2.1 language selector coverage.

APK: sunster-2.2.000-app-service.js character offsets 839300 and
841469-842500 (metadata mask and mapping), 821491-821700 (255 unsupported).
"""
import pytest

from custom_components.diesel_heater.select import VevorHeaterLanguageSelect

from .test_select import create_mock_coordinator

LANGUAGES = ["Off", "English", "Chinese", "Russian", "German",
             "Turkish", "Korean", "French", "Polish"]


@pytest.mark.parametrize(("code", "name"), list(enumerate(LANGUAGES)))
@pytest.mark.asyncio
async def test_cbff_mapping_and_selection(code, name):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=code, cbff_language_mask=0xFF)
    entity = VevorHeaterLanguageSelect(coordinator)
    assert entity.options == LANGUAGES
    assert entity.current_option == name
    assert entity.available
    await entity.async_select_option(name)
    coordinator.async_set_language.assert_awaited_once_with(code)


@pytest.mark.parametrize("code", range(1, 9))
def test_mask_bits_enable_only_corresponding_language(code):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=0, cbff_language_mask=1 << (code - 1))
    assert VevorHeaterLanguageSelect(coordinator).options == ["Off", LANGUAGES[code]]


@pytest.mark.parametrize("mask", [0, 0xFF00])
def test_no_known_language_bits_means_off_only(mask):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=4, cbff_language_mask=mask)
    entity = VevorHeaterLanguageSelect(coordinator)
    assert entity.options == ["Off"]
    assert entity.current_option == "German"


@pytest.mark.parametrize("current", range(9))
def test_unknown_metadata_allows_only_off_and_current(current):
    coordinator = create_mock_coordinator(6)
    coordinator.data["language"] = current
    entity = VevorHeaterLanguageSelect(coordinator)
    assert entity.options == (["Off"] if current == 0 else ["Off", LANGUAGES[current]])


@pytest.mark.parametrize("mask", [None, -1, 65536, "255", True])
def test_invalid_metadata_uses_safe_fallback(mask):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=4, cbff_language_mask=mask)
    assert VevorHeaterLanguageSelect(coordinator).options == ["Off", "German"]


@pytest.mark.parametrize("language", [None, 255, 99])
@pytest.mark.asyncio
async def test_unsupported_or_unknown_language_is_unavailable(language):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=language, cbff_language_mask=0xFF)
    entity = VevorHeaterLanguageSelect(coordinator)
    assert not entity.available
    assert entity.current_option is None
    await entity.async_select_option("Off")
    coordinator.async_set_language.assert_not_awaited()


@pytest.mark.parametrize("mask", [None, 1])
@pytest.mark.asyncio
async def test_disallowed_option_does_not_write(mask):
    coordinator = create_mock_coordinator(6)
    coordinator.data.update(language=1, cbff_language_mask=mask)
    entity = VevorHeaterLanguageSelect(coordinator)
    await entity.async_select_option("German")
    await entity.async_select_option("Silent")
    coordinator.async_set_language.assert_not_awaited()


@pytest.mark.asyncio
async def test_options_follow_metadata_and_status_updates():
    coordinator = create_mock_coordinator(6)
    coordinator.data["language"] = 3
    entity = VevorHeaterLanguageSelect(coordinator)
    assert entity.options == ["Off", "Russian"]
    coordinator.data["cbff_language_mask"] = 8
    assert entity.options == ["Off", "German"]
    await entity.async_select_option("Russian")
    coordinator.async_set_language.assert_not_awaited()
    coordinator.data["language"] = 4
    assert entity.current_option == "German"
    coordinator.data["connected"] = False
    assert not entity.available


@pytest.mark.parametrize("mode", [0, 1, 2, 3, 4, 5, 7, 8, 9])
@pytest.mark.asyncio
async def test_other_families_keep_legacy_mapping(mode):
    coordinator = create_mock_coordinator(mode)
    coordinator.data.update(language=2, cbff_language_mask=0)
    entity = VevorHeaterLanguageSelect(coordinator)
    assert entity.options == ["English", "Chinese", "German", "Silent", "Russian"]
    assert entity.current_option == "German"
    await entity.async_select_option("German")
    coordinator.async_set_language.assert_awaited_once_with(2)
