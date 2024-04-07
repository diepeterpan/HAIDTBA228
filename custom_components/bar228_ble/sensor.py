"""Support for bar228 ble sensors."""
from __future__ import annotations

import logging
import dataclasses

from .bar228_ble import BAR228Device

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.util.unit_system import METRIC_SYSTEM

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SENSORS_MAPPING_TEMPLATE: dict[str, SensorEntityDescription] = {
    "temperature": SensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        name="Temperature",
    ),
    "humidity": SensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        name="Humidity",
    ),
    "pressure": SensorEntityDescription(
        key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.MBAR,
        name="Pressure",
    ),
    "last": SensorEntityDescription(
        key="last",
        device_class=SensorDeviceClass.TIMESTAMP,
        native_unit_of_measurement=None,
        name="Last",
    ),
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BAR228 BLE sensors."""
    is_metric = hass.config.units is METRIC_SYSTEM

    coordinator: DataUpdateCoordinator[BAR228Device] = hass.data[DOMAIN][entry.entry_id]

    sensors_mapping = SENSORS_MAPPING_TEMPLATE.copy()
    entities = []
    _LOGGER.debug("got sensors: %s", coordinator.data.sensors)
    for sensor_type, sensor_value in coordinator.data.sensors.items():
        if sensor_type not in sensors_mapping:
            _LOGGER.debug(
                "Unknown sensor type detected: %s, %s",
                sensor_type,
                sensor_value,
            )
            continue
        entities.append(
            BAR228Sensor(coordinator, coordinator.data, sensors_mapping[sensor_type])
        )

    async_add_entities(entities)


class BAR228Sensor(CoordinatorEntity[DataUpdateCoordinator[BAR228Device]], SensorEntity):
    """BAR228 BLE sensors for the device."""

    ## Setting the Device State to None fixes Uptime String, Appears to override line: https://github.com/Makr91/rd200v2/blob/3d87d6e005f5efb7c143ff32256153c517ccade9/custom_components/rd200_ble/sensor.py#L78
    # Had to comment this line out to avoid it setting all state_class to none
    #_attr_state_class = None
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        bar228_device: BAR228Device,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Populate the bar228 entity with relevant data."""
        super().__init__(coordinator)
        self.entity_description = entity_description

        name = f"{bar228_device.name} {bar228_device.identifier}"

        self._attr_unique_id = f"{name}_{entity_description.key}"

        self._id = bar228_device.address
        self._attr_device_info = DeviceInfo(
            connections={
                (
                    CONNECTION_BLUETOOTH,
                    bar228_device.address,
                )
            },
            name=name,
            manufacturer="Oregon Scientific",
            model="BAR228",
            hw_version=bar228_device.hw_version,
            sw_version=bar228_device.sw_version,
        )

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        try:
            return self.coordinator.data.sensors[self.entity_description.key]
        except KeyError:
            return None
