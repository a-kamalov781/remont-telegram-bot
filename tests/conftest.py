"""Роутеры — модульные синглтоны, а aiogram не даёт подключить роутер к двум Dispatcher."""
from __future__ import annotations

import pytest

from bot.handlers import admin, client, demo


@pytest.fixture(autouse=True)
def detach_routers():
    yield
    for module in (admin, demo, client):
        module.router._parent_router = None
