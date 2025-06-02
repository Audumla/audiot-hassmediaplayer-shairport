"""
Provides the constants needed for the Shairport Sync MQTT media player integration.
"""
from enum import StrEnum

# Integration domain
DOMAIN = "shairport_sync"

class Configuration(StrEnum):
    """Configuration keys for YAML and UI setup."""
    NAME = "name"
    TOPIC = "topic"
    DESCRIPTION = "description"

class TopLevelTopic(StrEnum):
    """MQTT topic segments published by Shairport Sync."""
    SSNC = "ssnc"
    CORE = "core"
    REMOTE = "remote"
    PLAY_START = "play_start"
    PLAY_RESUME = "play_resume"
    PLAY_END = "play_end"
    PLAY_FLUSH = "play_flush"
    ACTIVE_END = "active_end"
    ARTIST = "artist"
    ALBUM = "album"
    TITLE = "title"
    COVER = "cover"
    VOLUME = "volume"
    # Placeholders for future enhancements
    POSITION = "position"
    DURATION = "duration"
    SEEK = "seek"

class Command(StrEnum):
    """Commands that can be sent to Shairport Sync via MQTT."""
    PLAY = "play"
    PAUSE = "pause"
    STOP = "stop"
    SKIP_NEXT = "nextitem"
    SKIP_PREVIOUS = "previtem"
    VOLUME_UP = "volumeup"
    VOLUME_DOWN = "volumedown"
    # Future enhancements
    SEEK_TO = "seek_to"
    SET_POSITION = "set_position"