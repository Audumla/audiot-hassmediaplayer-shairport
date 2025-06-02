---

## `media_player.py`
```python
"""MQTT-driven MediaPlayer entity for Shairport Sync.

This module provides a Home Assistant `MediaPlayerEntity` that represents a
single Shairport Sync instance.  It subscribes to Shairport Sync’s MQTT topic
hierarchy (`<base>/<ssnc>/<event>` and `<base>/<ssnc>/<core>/<field>`) and
translates messages into HA state updates.  All core playback commands are
supported; continuous volume is mapped from –30 dB…0 dB → 0 … 1.

**Planned / placeholder enhancements**
-------------------------------------------------
* MEDIA_SEEK — receive `/seek` commands & position updates.
* Progress bar — subscribe to `/position` & `/duration` for live progress.
* MQTT error resilience — re‑subscribe on broker reconnect (TODO).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.components.media_player import (
    PLATFORM_SCHEMA,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.mqtt import async_publish, async_subscribe
from homeassistant.components.mqtt.const import CONF_TOPIC
from homeassistant.components.mqtt.util import valid_publish_topic
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import utcnow

from .const import (
    DOMAIN,
    Command,
    TopLevelTopic,
    Configuration,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration (YAML) schema
# -----------------------------------------------------------------------------

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(Configuration.NAME): cv.string,
        vol.Required(Configuration.TOPIC): valid_publish_topic,
        vol.Optional(Configuration.DESCRIPTION, default=""): cv.string,
    },
    extra=vol.REMOVE_EXTRA,
)

# -----------------------------------------------------------------------------
# Feature flags
# -----------------------------------------------------------------------------
SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_SET
    # ─────────────────────────────── future ────────────────────────────────
    # MediaPlayerEntityFeature.SEEK  # when seek implemented
)

# Shairport volume range (hardware‑agnostic software profile)
_MIN_DB = -30.0
_MAX_DB = 0.0
_DB_RANGE = _MAX_DB - _MIN_DB

# -----------------------------------------------------------------------------
# Setup helpers
# -----------------------------------------------------------------------------

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Legacy YAML setup (still supported)."""
    async_add_entities(
        [
            ShairportSyncMediaPlayer(
                hass,
                name=config[Configuration.NAME],
                base_topic=config[Configuration.TOPIC],
                description=config.get(Configuration.DESCRIPTION, ""),
            )
        ]
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """UI‑flow setup."""
    data = config_entry.data
    async_add_entities(
        [
            ShairportSyncMediaPlayer(
                hass,
                name=data[Configuration.NAME],
                base_topic=data[Configuration.TOPIC],
                description=data.get(Configuration.DESCRIPTION, ""),
            )
        ]
    )


# -----------------------------------------------------------------------------
# Entity implementation
# -----------------------------------------------------------------------------

class ShairportSyncMediaPlayer(MediaPlayerEntity):
    """Home Assistant entity wrapping a Shairport Sync AirPlay endpoint."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = SUPPORTED_FEATURES

    # ─────────────────────────────── init ────────────────────────────────
    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        base_topic: str,
        description: str,
    ) -> None:
        self.hass = hass
        self._name = name
        self._base_topic = base_topic.rstrip("/")  # ensure no trailing slash
        self._description = description

        # State attributes
        self._state: MediaPlayerState = MediaPlayerState.IDLE
        self._title: str | None = None
        self._artist: str | None = None
        self._album: str | None = None
        self._media_image: bytes | None = None
        self._volume_db: float | None = None

        # Progress tracking placeholders (future)
        self._duration: float | None = None  # seconds
        self._position: float | None = None  # seconds
        self._last_position_update: float | None = None  # UTC timestamp

        self._subscriptions: list[callback] = []

        # Remote‑command topic
        self._remote_topic = f"{self._base_topic}/{TopLevelTopic.SSNC}/{TopLevelTopic.REMOTE}"

    # ------------------------------------------------------------------
    # HA lifecycle
    # ------------------------------------------------------------------
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._subscribe_topics()

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._subscriptions:
            unsub()

    # ------------------------------------------------------------------
    # Subscription helpers
    # ------------------------------------------------------------------
    async def _subscribe_topics(self) -> None:
        """Subscribe to ssnc/* and ssnc/core/* topics."""
        ssnc_prefix = f"{self._base_topic}/{TopLevelTopic.SSNC}"
        core_prefix = f"{ssnc_prefix}/{TopLevelTopic.CORE}"

        # ───────────────────── event/state callbacks ─────────────────────
        @callback
        def _set_state(new: MediaPlayerState):
            self._state = new
            if new == MediaPlayerState.IDLE:
                self._title = self._artist = self._album = None
                self._media_image = None
                self._volume_db = None
            self.async_write_ha_state()

        @callback
        def _cb_play(_):
            _set_state(MediaPlayerState.PLAYING)

        @callback
        def _cb_pause(_):
            _set_state(MediaPlayerState.PAUSED)

        @callback
        def _cb_stop(_):
            _set_state(MediaPlayerState.IDLE)

        def _meta_updater(attr: str):
            @callback
            def _upd(msg):
                setattr(self, f"_{attr}", msg.payload)
                self.async_write_ha_state()
            return _upd

        @callback
        def _cb_art(msg):
            self._media_image = msg.payload
            self.async_write_ha_state()

        @callback
        def _cb_vol(msg):
            try:
                db = float(msg.payload.split(",")[0])
            except (ValueError, IndexError):
                return
            self._volume_db = max(min(db, _MAX_DB), _MIN_DB)
            self.async_write_ha_state()

        # Placeholders for progress callbacks
        @callback
        def _cb_position(msg):  # TODO
            pass

        @callback
        def _cb_duration(msg):  # TODO
            pass

        # Map of topics → (callback, encoding)
        topic_map: dict[str, tuple[callback, str | None]] = {
            # ssnc events
            f"{ssnc_prefix}/{TopLevelTopic.PLAY_START}": (_cb_play, "utf-8"),
            f"{ssnc_prefix}/{TopLevelTopic.PLAY_RESUME}": (_cb_play, "utf-8"),
            f"{ssnc_prefix}/{TopLevelTopic.PLAY_END}": (_cb_pause, "utf-8"),
            f"{ssnc_prefix}/{TopLevelTopic.PLAY_FLUSH}": (_cb_pause, "utf-8"),
            f"{ssnc_prefix}/{TopLevelTopic.ACTIVE_END}": (_cb_stop, "utf-8"),
            f"{ssnc_prefix}/{TopLevelTopic.COVER}": (_cb_art, None),
            f"{ssnc_prefix}/{TopLevelTopic.VOLUME}": (_cb_vol, "utf-8"),
            # core metadata
            f"{core_prefix}/{TopLevelTopic.ARTIST}": (_meta_updater("artist"), "utf-8"),
            f"{core_prefix}/{TopLevelTopic.ALBUM}": (_meta_updater("album"), "utf-8"),
            f"{core_prefix}/{TopLevelTopic.TITLE}": (_meta_updater("title"), "utf-8"),
            # Future progress topics (optional in Shairport)
            f"{core_prefix}/{TopLevelTopic.POSITION}": (_cb_position, "utf-8"),
            f"{core_prefix}/{TopLevelTopic.DURATION}": (_cb_duration, "utf-8"),
        }

        for topic, (cb, enc) in topic_map.items():
            unsub = await async_subscribe(self.hass, topic, cb, encoding=enc)
            self._subscriptions.append(unsub)

    # ------------------------------------------------------------------
    # MediaPlayerEntity properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @property
    def state(self) -> MediaPlayerState | None:  # type: ignore[override]
        return self._state

    @property
    def media_content_type(self) -> MediaType | None:  # type: ignore[override]
        return MediaType.MUSIC

    @property
    def media_title(self) -> str | None:  # type: ignore[override]
        return self._title

    @property
    def media_artist(self) -> str | None:  # type: ignore[override]
        return self._artist

    @property
    def media_album_name(self) -> str | None:  # type: ignore[override]
        return self._album

    @property
    def media_image_hash(self) -> str | None:  # type: ignore[override]
        if self._media_image:
            return hashlib.md5(self._media_image).hexdigest()
        return None

    @property
    def volume_level(self) -> float | None:  # type: ignore[override]
        if self._volume_db is None:
            return None
        return (self._volume_db - _MIN_DB) / _DB_RANGE

    # ------------------------------------------------------------------
    # Extra attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self):  # type: ignore[override]
        attrs: dict[str, str | float | None] = {"description": self._description}
        if self._duration is not None:
            attrs["duration"] = self._duration
        if self._position is not None:
            attrs["position"] = self._position
        return attrs

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    async def _publish_cmd(self, cmd: Command | str) -> None:
        _LOGGER.debug("Sending command → %s", cmd)
        await async_publish(self.hass, self._remote_topic, str(cmd))

    async def async_media_play(self) -> None:  # type: ignore[override]
        await self._publish_cmd(Command.PLAY)

    async def async_media_pause(self) -> None:  # type: ignore[override]
        await self._publish_cmd(Command.PAUSE)

    async def async_media_stop(self) -> None:  # type: ignore[override]
        await self._publish_cmd(Command.STOP)

    async def async_media_next_track(self) -> None:  # type: ignore[override]
        await