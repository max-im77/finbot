"""Курсы валют: open.er-api.com — бесплатно, без ключа, ~160 валют."""
from __future__ import annotations

import time

import httpx

URL = "https://open.er-api.com/v6/latest/USD"


class Rates:
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._rates: dict[str, float] = {}
        self._fetched = 0.0
        self.updated: str = ""

    async def get(self) -> dict[str, float]:
        if self._rates and time.time() - self._fetched < self.ttl:
            return self._rates
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(URL)
                r.raise_for_status()
                data = r.json()
            self._rates = data["rates"]
            self.updated = data.get("time_last_update_utc", "")
            self._fetched = time.time()
        except Exception:
            if not self._rates:  # кэша нет — пробрасываем ошибку
                raise
        return self._rates

    async def convert(self, amount: float, src: str, dst: str) -> float:
        rates = await self.get()
        return amount / rates[src] * rates[dst]
