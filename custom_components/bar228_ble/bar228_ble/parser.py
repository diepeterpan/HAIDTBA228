"""Parser for BAR228 BLE devices"""

from __future__ import annotations

import asyncio
import dataclasses
import struct
from collections import namedtuple
from datetime import datetime
import logging

# from logging import Logger
from math import exp
from typing import Any, Callable, Tuple, TypeVar, cast

from bleak import BleakClient, BleakError
from bleak.backends.device import BLEDevice
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import establish_connection

WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])


class BleakCharacteristicMissing(BleakError):
    """Raised when a characteristic is missing from a service."""


class BleakServiceMissing(BleakError):
    """Raised when a service is missing."""


BAR228_CHARACTERISTIC_UUID_READ = "905e8e30-81e9-4796-9b75-b95cf5e30c0b"

BAR228_CHARACTERISTIC_UUID_WRITE1 = "905e8e01-81e9-4796-9b75-b95cf5e30c0b"  # i
BAR228_CHARACTERISTIC_UUID_WRITE2 = "905e8e02-81e9-4796-9b75-b95cf5e30c0b"  # i
BAR228_CHARACTERISTIC_UUID_WRITE3 = "905e8e03-81e9-4796-9b75-b95cf5e30c0b"  # i
BAR228_CHARACTERISTIC_UUID_WRITE4 = "905e8e30-81e9-4796-9b75-b95cf5e30c0b"  # i
BAR228_CHARACTERISTIC_UUID_WRITE5 = "905e8e34-81e9-4796-9b75-b95cf5e30c0b"  # n
BAR228_CHARACTERISTIC_UUID_WRITE6 = "905e8e40-81e9-4796-9b75-b95cf5e30c0b"  # r/w

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class BAR228Device:
    """Response data with information about the BAR228 device"""

    hw_version: str = ""
    sw_version: str = ""
    name: str = ""
    identifier: str = ""
    address: str = ""
    sensors: dict[str, str | float | None] = dataclasses.field(
        default_factory=lambda: {}
    )


# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=broad-exception-caught
class BAR228BluetoothDeviceData:
    """Data for BAR228 BLE sensors."""

    _event: asyncio.Event | None
    _command_data: bytearray | None
    _bardevice: BAR228Device | None
    _bleclient: BleakClient | None

    def __init__(
        self,
        logger: Logger,
        elevation: int | None = None,
        is_metric: bool = True,
        voltage: tuple[float, float] = (2.4, 3.2),
    ):
        super().__init__()
        self.logger = logger
        self.is_metric = is_metric
        self.elevation = elevation
        self.voltage = voltage
        self._command_data = None
        self._bardevice = None
        self._bleclient = None
        self._event = None

    def notification_handler(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """Helper for command events"""
        self._command_data = data
        self.logger.debug("notification_handler - data received")
        self.logger.debug(f"notification_handler - sender {sender} : data {data}")
        self.logger.debug(f"notification_handler - sender.handle {sender.handle}")

        if sender.handle >= 0x0013:
            self.logger.debug("notification_handler - begin process data")
            self._bardevice.sensors["temperature"] = (
                struct.unpack("<H", self._command_data[3:5])[0]
            ) / 10
            self._bardevice.sensors["humidity"] = struct.unpack(
                "@B", self._command_data[6:7]
            )[0]
            self._bardevice.sensors["pressure"] = (
                struct.unpack("<H", self._command_data[8:10])[0]
            ) / 10
            self._bardevice.sensors["last"] = datetime.now().astimezone()
            self.logger.debug("notification_handler - end processed data")

        if self._event is None:
            return
        self._event.set()

    def disconnect_on_missing_services(func: WrapFuncType) -> WrapFuncType:
        """Define a wrapper to disconnect on missing services and characteristics.

        This must be placed after the retry_bluetooth_connection_error
        decorator.
        """

        async def _async_disconnect_on_missing_services_wrap(
            self, *args: Any, **kwargs: Any
        ) -> None:
            try:
                return await func(self, *args, **kwargs)
            except (BleakServiceMissing, BleakCharacteristicMissing) as ex:
                logger.warning(
                    "%s: Missing service or characteristic, disconnecting to force refetch of GATT services: %s",
                    self.name,
                    ex,
                )
                if self.client:
                    await self.client.clear_cache()
                    await self.client.disconnect()
                raise

        return cast(WrapFuncType, _async_disconnect_on_missing_services_wrap)

    @disconnect_on_missing_services
    async def _get_bar228(
        self, client: BleakClient, device: BAR228Device
    ) -> BAR228Device:

        self._event = asyncio.Event()

        try:
            await client.start_notify(
                BAR228_CHARACTERISTIC_UUID_WRITE1, self.notification_handler
            )
        except Exception:
            self.logger.debug(
                f"_get_bar228 start_notify failed on {BAR228_CHARACTERISTIC_UUID_WRITE1}"
            )
        try:
            await client.start_notify(
                BAR228_CHARACTERISTIC_UUID_WRITE2, self.notification_handler
            )
        except Exception:
            self.logger.debug(
                f"_get_bar228 start_notify failed on {BAR228_CHARACTERISTIC_UUID_WRITE2}"
            )
        try:
            await client.start_notify(
                BAR228_CHARACTERISTIC_UUID_WRITE3, self.notification_handler
            )
        except Exception:
            self.logger.debug(
                f"_get_bar228 start_notify failed on {BAR228_CHARACTERISTIC_UUID_WRITE3}"
            )
        try:
            await client.start_notify(
                BAR228_CHARACTERISTIC_UUID_WRITE4, self.notification_handler
            )
        except Exception:
            self.logger.debug(
                f"_get_bar228 start_notify failed on {BAR228_CHARACTERISTIC_UUID_WRITE4}"
            )
        try:
            await client.start_notify(
                BAR228_CHARACTERISTIC_UUID_WRITE5, self.notification_handler
            )
        except Exception:
            self.logger.debug(
                f"_get_bar228 start_notify failed on {BAR228_CHARACTERISTIC_UUID_WRITE5}"
            )

        self.logger.debug("_get_bar228 completed")

        return device

    async def update_device(self, ble_device: BLEDevice) -> BAR228Device:
        """Connects to the device through BLE and retrieves relevant data"""
        self.logger.debug("update_device - begin")

        if self._bardevice is not None:
            self.logger.debug("update_device - returning existing _bardevice")
        else:
            self._bardevice = BAR228Device()
            self._bardevice.name = ble_device.name
            self._bardevice.address = ble_device.address
            self._bardevice.sensors["temperature"] = None
            self._bardevice.sensors["humidity"] = None
            self._bardevice.sensors["pressure"] = None
            self._bardevice.sensors["last"] = None
            self._command_data = None
            self.logger.debug("update_device - returning new _bardevice")

        if self._bleclient is not None:
            self.logger.debug("update_device - existing _bleclient begin")
            if not self._bleclient.is_connected:
                self.logger.debug("existing _bleclient not connected")
                await self._bleclient.connect()
                self._bardevice = await self._get_bar228(
                    self._bleclient, self._bardevice
                )
                self.logger.debug("update_device - existing _bleclient re-connected")
            self.logger.debug("update_device - existing _bleclient end")
        else:
            self.logger.debug("update_device - new _bleclient begin")
            self._bleclient = await establish_connection(
                BleakClient, ble_device, ble_device.address
            )
            if ble_device.name.startswith("IDTBA228"):
                self._bardevice = await self._get_bar228(
                    self._bleclient, self._bardevice
                )
            self.logger.debug("update_device - new _bleclient end")

        self.logger.debug("update_device - end")

        return self._bardevice
