"""Catalogue and stock answers come from MCP, independently of LLM generation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from textwrap import shorten
from .preferences import detect_category
from .views import h, money

PAGE_SIZE = 20
CATEGORY_WORDS = {'ноутбук','ноутбуки','телефон','телефоны','смартфон','смартфоны',
                  'компьютер','компьютеры','пк','планшет','планшеты','колонка','колонки',
                  'часы','умные часы','телевизор','телевизоры','монитор','мониторы','наушники'}


class CatalogueUnavailable(ValueError):
    """A failed source read must never be interpreted as an empty stock list."""


@dataclass
class CatalogueRequest:
    category: str = ''
    offset: int = 0
    table: bool = False


def catalogue_request(text, session):
    lower=text.casefold().strip(' \n\t.!?')
    page=session.catalogue_page
    if page and re.fullmatch(r'(?:дальше|далее|ещ[её]|следующ\w*(?: страниц\w*)?)',lower):
        return CatalogueRequest(page['category'], page['offset']+PAGE_SIZE, page['table'])
    if page and re.fullmatch(r'(?:назад|предыдущ\w*(?: страниц\w*)?)',lower):
        return CatalogueRequest(page['category'], max(0,page['offset']-PAGE_SIZE), page['table'])
    category=detect_category(text) or ''
    explicit=bool(re.search(r'каталог|ассортимент|таблиц|список',lower))
    # Filtered selection remains a consultation; a bare stock query ignores old filters.
    constrained=bool(re.search(r'\d|бюджет|дешев|дороже|похож|аналог|характеристик|посовет|подбер|подоб|сравн|экран|камер|памят|оператив|bluetooth|oled|ips|nfc|wi-fi|функци|этого|этой|добав|удал|измен|переимен|для (?:игр|уч[её]бы|работ)',lower))
    if constrained: return None
    if explicit:
        return CatalogueRequest(category,table=bool(re.search(r'таблиц',lower)))
    if lower in CATEGORY_WORDS:
        return CatalogueRequest(category)
    presence=bool(re.search(r'\bесть\b|\bиме[ею]тся\b|\bбывают\b|\bпрода[её]те\b|налич\w*|\bторгуете\b|\bпокажи\b|\bпришли\b|\bпокажите\b|\bцен[аы]\b|сколько стоят',lower))
    if category and presence:
        return CatalogueRequest(category)
    if re.search(r'что\s+(?:у\s+(?:вас|тебя)\s+)?(?:есть|прода[её](?:те|шь))|какие\s+(?:есть\s+)?(?:товары|устройства|категории)',lower):
        return CatalogueRequest()
    return None


def availability_claim(text):
    """Free model prose must not be an unverified stock or assortment statement."""
    return bool(re.search(
        r'(?:в (?:нашем )?(?:каталоге|ассортименте|магазине)|у нас).{0,65}(?:нет|есть|отсутств|представ|имеется|имеются)'
        r'|(?:нет|отсутству\w*)\s+(?:(?:подходящ|никак|сейчас|пока)\w*\s+)*(?:телефон|смартфон|ноутбук|товар|модел)'
        r'|(?:телефон|смартфон|ноутбук|товар|модел)\w*.{0,80}(?:\bнет\b|отсутств|не (?:вижу|наш[её]л|представлен|имеется|имеются|осталось|прода[её]м))'
        r'|не (?:вижу|наш[её]л|прода[её]м).{0,40}(?:телефон|смартфон|ноутбук|товар|модел)',text,re.I))


def verified_catalogue_read(name,result):
    if not isinstance(result,dict): return False
    if name in {'list_products','search_products','similar_products','compare_products'}:
        return isinstance(result.get('items'),list) and not result.get('error')
    return name=='get_product' and 'id' in result


async def read_page(mcp,args):
    try: data=await mcp.call('list_products',args)
    except Exception as exc: raise CatalogueUnavailable('Не удалось прочитать каталог') from exc
    if not isinstance(data,dict) or not isinstance(data.get('items'),list) or not isinstance(data.get('total'),int):
        raise CatalogueUnavailable('Не удалось прочитать каталог')
    return data


async def catalogue_reply(mcp, request, session, text):
    args={'category':request.category,'limit':PAGE_SIZE,'offset':request.offset}
    data=await read_page(mcp,args)
    items=data['items']; total=data['total']
    if total and not items and request.offset>=total:
        request.offset=((total-1)//PAGE_SIZE)*PAGE_SIZE
        data=await read_page(mcp,{**args,'offset':request.offset})
        items=data['items'];total=data['total']
    title=f'Раздел «{h(request.category)}»' if request.category else 'Каталог всех устройств'
    lines=[f'<b>{title}</b>',f'Товаров в наличии: {total}.']
    if items:
        if total>PAGE_SIZE: lines.append(f'Показаны {request.offset+1}–{request.offset+len(items)} из {total}.')
        if request.table:
            rows=[f"{'№':<4} {'Товар':<46} {'Цена':>12}"]
            rows.extend(f"{p['id']:<4} {shorten(p['name'],width=46,placeholder='…'):<46} {money(p['price_kopecks']):>12}" for p in items)
            lines.append('<pre>'+h('\n'.join(rows))+'</pre>')
        else:
            last_category=None
            for p in items:
                if not request.category and p['category']!=last_category:
                    lines.append('\n<b>'+h(shorten(p['category'].capitalize(),width=60,placeholder='…'))+'</b>')
                    last_category=p['category']
                lines.append(f"{p['id']}. {h(shorten(p['name'],width=95,placeholder='…'))} — <b>{money(p['price_kopecks'])}</b>")
        if request.offset+len(items)<total: lines.append('\nНапишите «дальше», чтобы получить следующую страницу.')
        if request.offset: lines.append('Напишите «назад», чтобы вернуться на предыдущую страницу.')
        if any(p.get('is_demo') for p in items): lines.append('\nЦены учебного каталога демонстрационные.')
        lines.append('\nМогу рассказать подробнее о любой модели из списка.')
    else:
        lines.append('В этом разделе сейчас нет активных товаров.' if request.category else 'В каталоге сейчас нет активных товаров.')
    session.catalogue_page={'category':request.category,'offset':request.offset,'table':request.table}
    session.recent=items
    session.selected_id=items[0]['id'] if len(items)==1 else None
    session.filters={'category':request.category}
    if not request.category:
        session.category='';session.budget_max=None;session.budget_min=0;session.requirements={}
    answer='\n'.join(lines)
    session.record(text,answer)
    return answer,items
