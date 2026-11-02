"""Bounded public HTTP reads with robots checks, host allowlist and disk caching."""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from protego import Protego

USER_AGENT = 'CRM-Catalog/1.0'
CACHE = Path(__file__).with_name('.price_cache')
ALLOWED_HOSTS = {'www.kns.ru', 'www.nix.ru'}
_locks: dict[str, asyncio.Lock] = {}
_last_request: dict[str, float] = {}


class SourceError(ValueError):
    """A source could not be read without violating its limits."""


class PublicHTTP:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                        headers={'User-Agent': USER_AGENT})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def _read(self, url, ttl, max_bytes):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None, 443):
            raise SourceError('Адрес источника не входит в разрешённый список')
        key = hashlib.sha256(url.encode()).hexdigest()
        path = CACHE / key
        lock = _locks.setdefault(parsed.hostname, asyncio.Lock())
        async with lock:
            if path.exists() and time.time() - path.stat().st_mtime < ttl:
                return path.read_bytes(), path.stat().st_mtime
            delay = max(0, 1.1 - (time.monotonic() - _last_request.get(parsed.hostname, 0)))
            if delay:
                await asyncio.sleep(delay)
            _last_request[parsed.hostname] = time.monotonic()
            async with self.client.stream('GET', url) as response:
                response.raise_for_status()  # No redirect, CAPTCHA or authentication workaround.
                chunks = []; size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise SourceError('Превышен допустимый размер ответа')
                    chunks.append(chunk)
            data = b''.join(chunks)
            CACHE.mkdir(exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(path)
            return data, path.stat().st_mtime

    async def get(self, url, ttl=900, max_bytes=20 * 1024 * 1024):
        parsed = urlparse(url)
        robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
        robots, _ = await self._read(robots_url, 86400, 512 * 1024)
        rules = Protego.parse(robots.decode('utf-8-sig', errors='replace'))
        if not rules.can_fetch(url, USER_AGENT):
            raise SourceError('robots.txt запрещает автоматическое чтение этой страницы')
        delay = rules.crawl_delay(USER_AGENT)
        if delay and delay > 1.1:
            if delay > 60:
                raise SourceError('Требуемый интервал запросов слишком велик для интерактивного сравнения')
            await asyncio.sleep(float(delay))
        return await self._read(url, ttl, max_bytes)
