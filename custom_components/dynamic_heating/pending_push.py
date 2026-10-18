"""Pushes whose notify service is not there yet, e.g. right after a restart.

The mobile app registers ``notify.mobile_app_*`` only once it is set up; a
push sent before that would be lost. It waits here instead and goes out as
soon as the service is registered, or is dropped after ``PENDING_MAX_AGE``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_SERVICE_REGISTERED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PENDING_MAX_AGE = timedelta(minutes=10)
# A service that never comes (a typo) must not let the queue grow forever.
PENDING_MAX_ITEMS = 20
_DATA_KEY = f"{DOMAIN}_pending_pushes"


class PendingPushes:
    """Hold pushes until their notify service exists."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._items: list[tuple[datetime, str, str, str, dict[str, Any]]] = []
        self._unsub: Any = None

    def __len__(self) -> int:
        return len(self._items)

    def add(
        self, owner: str, domain: str, service: str, data: dict[str, Any]
    ) -> None:
        del self._items[: max(0, len(self._items) - PENDING_MAX_ITEMS + 1)]
        self._items.append(
            (dt_util.utcnow() + PENDING_MAX_AGE, owner, domain, service, data)
        )
        if self._unsub is None:
            self._unsub = self.hass.bus.async_listen(
                EVENT_SERVICE_REGISTERED, self._async_registered
            )

    @callback
    def _async_registered(self, event: Event) -> None:
        domain = event.data.get(ATTR_DOMAIN)
        service = event.data.get(ATTR_SERVICE)
        now = dt_util.utcnow()
        keep = []
        for item in self._items:
            deadline, _, item_domain, item_service, data = item
            if deadline < now:
                _LOGGER.info(
                    "Push dropped, %s.%s never appeared: %s",
                    item_domain,
                    item_service,
                    data.get("message"),
                )
            elif item_domain == domain and item_service == service:
                self.hass.async_create_task(self._async_send(domain, service, data))
            else:
                keep.append(item)
        self._items = keep
        self._stop_if_empty()

    @callback
    def discard(self, owner: str) -> None:
        """Drop an entry's pushes: it unloads, maybe with another service."""
        self._items = [item for item in self._items if item[1] != owner]
        self._stop_if_empty()

    def _stop_if_empty(self) -> None:
        if not self._items and self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _async_send(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Held push to %s.%s failed: %s", domain, service, err)


def pending_pushes(hass: HomeAssistant) -> PendingPushes:
    """The one queue of this Home Assistant."""
    queue = hass.data.get(_DATA_KEY)
    if queue is None:
        queue = hass.data[_DATA_KEY] = PendingPushes(hass)
    return queue


def hold_if_missing(
    hass: HomeAssistant, owner: str, domain: str, service: str, data: dict[str, Any]
) -> bool:
    """Queue a push to a notify service that is not registered yet.

    True when it was queued; the caller then counts it as sent.
    """
    if domain != "notify" or hass.services.has_service(domain, service):
        return False
    _LOGGER.debug("%s.%s not there yet, push held", domain, service)
    pending_pushes(hass).add(owner, domain, service, data)
    return True
