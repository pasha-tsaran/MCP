"""Adapters for the publicly accessible KNS and NIX catalogues.

Discovery never uses private APIs or forbidden search endpoints. Prices and
configuration are re-read from the actual product card, not inferred from a name.
"""
from __future__ import annotations

import asyncio
import json
import re
import httpx
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup
from defusedxml import ElementTree

from .price_http import PublicHTTP, SourceError, CACHE


def soup(data, encoding=None):
    return BeautifulSoup(data.decode(encoding or 'utf-8', errors='replace'), 'lxml')


def compact(value):
    text = str(value).casefold().replace('ё', 'е').replace('гб', 'gb').replace('тб', 'tb')
    return re.sub(r'[^a-zа-я0-9]', '', text)


def discovery_key(product):
    # Storage is checked as a separate configuration field on the product page.
    model = re.sub(r'\b\d+\s*(?:gb|гб|tb|тб)\b', '', product['model'], flags=re.I)
    return compact(model)


def model_matches(product, name):
    model = discovery_key(product)
    candidate = compact(name)
    if len(model) < 5 or model not in candidate:
        return False
    if product.get('brand') and compact(product['brand']) not in candidate:
        return False
    # Do not merge Pro/Plus/Max/Ultra/FE/Lite with a base model.
    tail = candidate.split(model, 1)[1]
    if re.match(r'^(?:pro|max|plus|ultra|lite|fe|mini|\d)', tail):
        # Memory digits may immediately follow the model (iPhone 13 128GB).
        if not re.match(r'^\d+(?:gb|tb)', tail):
            return False
    if any(word in name.casefold() for word in ('чехол', 'для экрана', 'защитное стекло', 'уценка', 'восстановлен', 'витринный')):
        return False
    return True


def number_price(value):
    try:
        value = re.sub(r'[^\d,.]', '', str(value)).replace(',', '.')
        price = Decimal(value)
        if price.is_finite() and 0 < price < 100_000_000:
            return int((price * 100).quantize(Decimal('1')))
    except InvalidOperation:
        pass
    return None


def meta_value(root, prop):
    tag = root.select_one(f'[itemprop="{prop}"]')
    return (tag.get('content') or tag.get('href') or tag.get_text(' ', strip=True)) if tag else ''


def parse_card(data, url, shop, fetched_at):
    root = soup(data, 'cp1251' if shop == 'НИКС' else 'utf-8')
    product = root.select_one('[itemtype$="/Product"]')
    if product is None:
        raise SourceError('Структура карточки товара изменилась')
    title = root.select_one('h1')
    name = title.get_text(' ', strip=True) if title else meta_value(product, 'name')
    price = number_price(meta_value(product, 'price'))
    available = meta_value(product, 'availability')
    currency = meta_value(product, 'priceCurrency')
    if shop == 'KNS':
        # Recommendations are nested inside Product. Never take their prices or stock.
        main = product.select_one('.goods-column-price')
        visible = main.select_one('.price-info .price-val') if main else None
        price = number_price(visible.get_text(' ', strip=True)) if visible else None
        stock_text = main.get_text(' ', strip=True).casefold() if main else ''
        available = '/InStock' if 'в наличии' in stock_text and 'нет в наличии' not in stock_text else ''
        currency_tag = main.select_one('.price-valute') if main else None
        currency = 'RUB' if currency_tag and 'руб' in currency_tag.get_text().casefold() else ''
    if not price or currency != 'RUB' or not available.endswith('/InStock'):
        return None
    specs = {}
    for row in root.select('tr'):
        cells = row.find_all(['td', 'th'], recursive=False)
        if len(cells) == 2:
            key = cells[0].get_text(' ', strip=True).rstrip(':')
            val = cells[1].get_text(' ', strip=True)
            if key and val and len(key) < 130 and len(val) < 1500:
                specs[key] = val
    for prop in root.select('[itemtype$="/PropertyValue"]'):
        key, val = meta_value(prop, 'name'), meta_value(prop, 'value')
        if key and val:
            specs[key] = val
    description = meta_value(product, 'description')
    if shop == 'KNS':
        # Only assertions actually present in the public description are used.
        patterns = {'связь': ('bluetooth', 'wi-fi'), 'цвет': ('цвет ',),
                    'экран': ('ips', 'oled', 'amoled', '1920', '2560', '3840', 'full hd'),
                    'процессор': ('intel core', 'amd ryzen', 'snapdragon', 'apple m'),
                    'накопитель': ('ssd', 'hdd'), 'видеокарта': ('graphics', 'geforce', 'radeon')}
        for key, terms in patterns.items():
            if any(t in description.casefold() for t in terms):
                specs[key] = description
        # Computer descriptions use Mb for RAM; separate it from SSD capacity.
        ram = re.search(r'(\d+)\s*Mb\b', description)
        if ram:
            specs['оперативная память'] = f'{int(ram[1]) / 1024:g} ГБ'
        for chunk in description.split(','):
            if re.search(r'\b\d+\s*(?:Gb|ГБ)\b', chunk, re.I) and not re.search(r'SSD|HDD', chunk, re.I):
                specs.setdefault('память', chunk.strip())
    return {'shop': shop, 'name': name, 'url': url, 'price_kopecks': price,
            'price_rub': price / 100, 'specs': specs, 'description': description,
            'checked_at': datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(timespec='seconds'),
            'price_note': 'Публичная цена карточки; условия оплаты и доставки уточняются у магазина.'}


class KNS:
    name = 'KNS'

    async def discover(self, http, product):
        key = discovery_key(product)
        saved = CACHE / 'kns_product_urls.json'
        if saved.exists() and time.time() - saved.stat().st_mtime < 86400:
            urls = json.loads(saved.read_text(encoding='utf-8'))
            return [u for u in urls if key in compact(unquote(u))][:8]
        index, _ = await http.get('https://www.kns.ru/sitemap.xml', ttl=86400)
        candidates = []
        all_urls = []
        for node in ElementTree.fromstring(index).iter():
            if node.tag.endswith('}loc') and node.text:
                url = node.text.strip()
                if urlparse(url).hostname != 'www.kns.ru':
                    continue
                data, _ = await http.get(url, ttl=86400)
                for entry in ElementTree.fromstring(data).iter():
                    if not entry.tag.endswith('}loc') or not entry.text:
                        continue
                    link = entry.text.strip()
                    if urlparse(link).hostname == 'www.kns.ru' and '/product/' in link:
                        all_urls.append(link)
                        if key in compact(unquote(link)):
                            candidates.append(link)
        CACHE.mkdir(exist_ok=True)
        temporary = saved.with_suffix('.tmp')
        temporary.write_text(json.dumps(list(dict.fromkeys(all_urls)), ensure_ascii=False), encoding='utf-8')
        temporary.replace(saved)
        return list(dict.fromkeys(candidates))[:8]


class NIX:
    name = 'НИКС'

    async def discover(self, http, product):
        data, _ = await http.get('https://www.nix.ru/price/index.html', ttl=86400)
        root = soup(data, 'cp1251')
        brand = product.get('brand', '').casefold()
        category = product.get('category', '').casefold()
        words = {'ноутбуки':'ноутбуки', 'телефоны':'смартфоны', 'планшеты':'планшеты',
                 'наушники':'наушники', 'мониторы':'мониторы', 'телевизоры':'телевизоры',
                 'колонки':'колонки', 'умные часы':'часы', 'компьютеры':'компьютеры'}
        word = words.get(category, category)
        links = []
        for a in root.select('a[href*="/price/price_list.html?section="]'):
            title = a.get_text(' ', strip=True).casefold()
            if word in title and brand and brand in title and '&' not in a['href']:
                links.append(urljoin('https://www.nix.ru', a['href']))
        candidates = []
        for link in list(dict.fromkeys(links))[:2]:
            data, _ = await http.get(link, ttl=3600)
            listing = soup(data, 'cp1251')
            for a in listing.select('.search-result-name a[href*="/autocatalog/"]'):
                if model_matches(product, a.get_text(' ', strip=True)):
                    candidates.append(urljoin('https://www.nix.ru', a['href']))
        return list(dict.fromkeys(candidates))[:8]


async def fetch_shop(source, product, matcher):
    async with PublicHTTP() as http:
        urls = await source.discover(http, product)
        offers = []
        missing = set(); conflicting = set(); unavailable = 0
        for url in urls:
            try:
                data, timestamp = await http.get(url)
                offer = parse_card(data, url, source.name, timestamp)
                if offer:
                    matched, unknown, conflicts = matcher(product, offer)
                    missing.update(unknown); conflicting.update(conflicts)
                    if not conflicts and not unknown:
                        public = {k: v for k, v in offer.items() if k not in {'specs', 'description'}}
                        offers.append({**public, 'matched': matched, 'unknown': []})
            except (ValueError, httpx.HTTPError):
                # A single discontinued card must not discard other valid candidates.
                unavailable += 1
        offers = sorted(offers, key=lambda o: o['price_kopecks'])[:1]
        reason = 'Совпадение модели и указанных характеристик подтверждено' if offers else 'Подходящих предложений в доступной части каталога нет'
        if not offers and missing:
            reason += '; не подтверждены: ' + ', '.join(sorted(missing))
        if not offers and conflicting:
            reason += '; отличаются: ' + ', '.join(sorted(conflicting))
        if unavailable:
            reason += f'; недоступных карточек: {unavailable}'
        return {'offers': offers, 'shop': source.name, 'reason': reason,
                'status': 'ok' if offers else 'no_match'}
