"""
Config flow for the Shairport Sync MQTT media player integration.

Collects essential configuration: name, base MQTT topic, and a description field.
All enhancement features (seek/position, progress updates, MQTT error handling)
are always enabled and no longer optional.
"""
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_TOPIC

_LOGGER = logging.getLogger(__name__)

# Define the schema for the user step, including description
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): str,
        vol.Required(CONF_TOPIC): str,
        vol.Optional("description", default=user_input.get(CONF_TOPIC, "Shairport"): str,
    }
)


class ShairportSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for Shairport Sync MQTT media player.

    The user will be prompted to enter a name, the base MQTT topic, and a
    description for the entity. All advanced features are enabled by default.
    """
    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, any] | None = None
    ) -> config_entries.FlowResult:
        """
        Handle the initial step of the config flow.

        Presents a form for the user to input the required configuration.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            # Create the integration entry with provided configuration
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input,
            )

        # Show configuration form with description field included
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
