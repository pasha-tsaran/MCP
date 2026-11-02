"""Read explicitly configured partner YML feeds. Never fabricate offers."""
from __future__ import annotations
import json
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from .shop_sources import KNS, NIX, fetch_shop
from .product_matching import compare_specs

CONFIG = Path(__file__).with_name('sources.json')
MAX_BYTES = 15 * 1024 * 1024


def normalize(s):
    return re.sub(r'[^a-zа-яё0-9]+', '', str(s).casefold())


def parse_feed(data, source, product):
    root=ElementTree.fromstring(data)
    offers=[]
    target=normalize(product['model'])
    if len(target)<5: return []
    for node in root.findall('.//offer'):
        if node.get('available','true').lower() == 'false': continue
        text=lambda name: (node.findtext(name) or '').strip()
        model = text('model')
        name = text('name') or (text('vendor')+' '+model).strip()
        # Exact model/name identity only; no guessing on similar model names.
        if target not in {normalize(model), normalize(name), normalize(text('vendor')+' '+model)}: continue
        currency=text('currencyId').upper()
        if currency not in ('RUR','RUB'): continue
        try:
            price=float(text('price').replace(',','.'))
            if not 0 < price < 100_000_000: continue
        except ValueError: continue
        params={p.get('name','').casefold(): (p.text or '').strip() for p in node.findall('param')}
        matched=[]; unknown=[]; conflict=[]
        for key,value in product['specs'].items():
            actual=params.get(key.casefold())
            if not actual: unknown.append(key)
            elif normalize(actual)==normalize(value): matched.append(key)
            else: conflict.append(f'{key}: {actual} / {value}')
        if conflict: continue
        url=text('url')
        if urlparse(url).scheme not in ('http','https'): url=''
        offers.append({'shop':source['name'],'name':name,'price_rub':price,'url':url,
                       'matched':matched,'unknown':unknown,
                       'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds')})
    return offers


async def compare(product):
    if not CONFIG.exists(): return {'offers':[], 'errors':['Источники цен не настроены.']}
    try:
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'offers':[], 'errors':['Не удалось прочитать настройки источников.']}
    offers=[]; errors=[]; statuses=[]
    providers={'kns':KNS, 'nix':NIX}
    async def public_source(source):
        provider=providers[source['type']]()
        try:
            result=await asyncio.wait_for(fetch_shop(provider, product, compare_specs), timeout=180)
            offers.extend(result.pop('offers'))
            statuses.append(result)
        except (httpx.HTTPError, ValueError, TimeoutError, OSError, ElementTree.ParseError, DefusedXmlException) as exc:
            errors.append(f'{provider.name}: источник временно недоступен ({type(exc).__name__})')
            statuses.append({'shop':provider.name, 'status':'error', 'reason':'Источник временно недоступен'})
    public=[s for s in config.get('sources',[])[:10] if s.get('type') in providers]
    await asyncio.gather(*(public_source(s) for s in public))
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        for source in config.get('sources',[])[:10]:
            if source.get('type') in providers: continue
            name=source.get('name','Источник'); url=source.get('url','')
            if urlparse(url).scheme!='https':
                errors.append(f'{name}: допустим только HTTPS'); continue
            try:
                async with client.stream('GET',url,headers={'User-Agent':'CRM-Catalog/1.0'}) as response:
                    response.raise_for_status()
                    chunks=[]; size=0
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>MAX_BYTES: raise ValueError('фид больше 15 МБ')
                        chunks.append(chunk)
                offers.extend(o for o in parse_feed(b''.join(chunks),source,product) if not o['unknown'])
            except (httpx.HTTPError, ValueError, ElementTree.ParseError, DefusedXmlException) as exc:
                errors.append(f'{name}: источник недоступен или имеет неверный формат ({type(exc).__name__})')
    # One cheapest offer per shop.
    best={}
    for offer in offers:
        if offer['shop'] not in best or offer['price_rub']<best[offer['shop']]['price_rub']:
            best[offer['shop']]=offer
    return {'offers':sorted(best.values(),key=lambda x:x['price_rub'])[:3], 'errors':errors,
            'sources':statuses, 'region':'Москва',
            'note':'Публичные рублёвые цены без доставки. Только совпадающие модели и подтверждённые характеристики; цены карточек кэшируются до 15 минут.'}
