"""Deterministic matching and ranking, independent of the language model."""
import re
from difflib import SequenceMatcher
from . import db
from .product_matching import matches_value


ALIASES = {'ноутбук':'ноутбуки', 'ноутбуки':'ноутбуки', 'телефон':'телефоны', 'смартфон':'телефоны', 'смартфоны':'телефоны', 'телефоны':'телефоны', 'пк':'компьютеры', 'компьютер':'компьютеры', 'компьютеры':'компьютеры', 'планшет':'планшеты', 'планшеты':'планшеты', 'часы':'умные часы', 'умные часы':'умные часы', 'колонка':'колонки', 'колонки':'колонки', 'телевизор':'телевизоры', 'телевизоры':'телевизоры', 'монитор':'мониторы', 'мониторы':'мониторы', 'наушники':'наушники'}


def category_name(value):
    return ALIASES.get(value.strip().lower(), value.strip().lower())


def all_products(category=''):
    items=[]; offset=0
    while True:
        page=db.list_products(category=category_name(category),limit=50,offset=offset)
        items.extend(page['items']); offset+=len(page['items'])
        if offset>=page['total'] or not page['items']: return items


def spec_value(specs,key):
    aliases={'озу':'оперативная память','ram':'оперативная память','ssd':'накопитель','дисплей':'экран','cpu':'процессор','gpu':'видеокарта'}
    key=aliases.get(key.casefold(),key.casefold())
    for name,value in specs.items():
        if key==name.casefold(): return value
    return next((v for k,v in specs.items() if key in k.casefold() and not (key=='память' and 'оператив' in k.casefold())),None)


def requirement_matches(expected,actual):
    match=re.match(r'^\s*(>=|<=|>|<)\s*(\d+(?:[.,]\d+)?)\s*(ГБ|ТБ|МБ|GB|TB|MB)?',expected,re.I)
    if not match: return matches_value(expected,actual)
    target=float(match[2].replace(',','.'))
    found=re.search(r'(\d+(?:[.,]\d+)?)\s*(ГБ|ТБ|МБ|GB|TB|MB)?',actual,re.I)
    if not found: return False
    value=float(found[1].replace(',','.'))
    factors={'гб':1,'gb':1,'тб':1024,'tb':1024,'мб':1/1024,'mb':1/1024}
    target*=factors.get((match[3] or '').casefold(),1)
    value*=factors.get((found[2] or '').casefold(),1)
    return {'>=':value>=target,'<=':value<=target,'>':value>target,'<':value<target}[match[1]]


def search(category='', query='', max_price_rub=0, requirements=None, min_price_rub=0,
           sort='relevance', allow_alternatives=True, limit=5):
    """Return exact matches; relax conditions only if there are no exact matches."""
    if min_price_rub<0 or max_price_rub<0: raise ValueError('Бюджет должен быть неотрицательным')
    if max_price_rub and min_price_rub>max_price_rub: raise ValueError('Минимальный бюджет больше максимального')
    requirements=requirements or {}
    items=all_products(category)
    if query:
        terms=query.casefold().split()
        items=[p for p in items if all(t in (p['name']+' '+p['model']+' '+p['brand']).casefold() for t in terms)]
    results=[]
    for p in items:
        deviations=[]; matches=[]; unknown=[]
        price=p['price_kopecks']/100
        if max_price_rub and price>max_price_rub:
            deviations.append(f"дороже бюджета на {price-max_price_rub:,.0f} ₽")
        if min_price_rub and price<min_price_rub:
            deviations.append(f"дешевле нижней границы на {min_price_rub-price:,.0f} ₽")
        for key,value in requirements.items():
            actual=spec_value(p['specs'],key)
            if actual is None:
                unknown.append(key); deviations.append(f'{key}: нет данных (запрос: {value})')
            elif not requirement_matches(str(value),actual):
                deviations.append(f'{key}: {actual} (запрос: {value})')
            else: matches.append(f'{key}: {actual}')
        results.append({'product':p,'matches':matches,'deviations':deviations,'unknown':unknown})
    exact=[r for r in results if not r['deviations']]
    chosen=exact if exact else results if allow_alternatives else []
    price_sign=-1 if sort=='price_desc' else 1
    chosen.sort(key=lambda x:(len(x['deviations']),price_sign*x['product']['price_kopecks']))
    return {'items':chosen[:min(max(int(limit),1),10)],'total':len(chosen), 'exact_count':len(exact),
            'relaxed':bool(chosen and not exact),
            'filters':{'category':category_name(category),'query':query,'max_price_rub':max_price_rub,
                       'min_price_rub':min_price_rub,'requirements':requirements,'sort':sort},
            'note':'Есть точные совпадения.' if exact else 'Точных совпадений нет. Каждый компромисс указан явно.'}


def compare_products(product_ids):
    ids=list(dict.fromkeys(product_ids))[:3]
    items=[p for i in ids if (p:=db.get_product(i)) is not None]
    if not items: return {'items':[],'error':'Товары не найдены'}
    first=items[0]
    rows=[]
    for p in items:
        differences=[f"{k}: {v} (у первого: {first['specs'].get(k,'нет данных')})" for k,v in p['specs'].items() if first['specs'].get(k)!=v]
        rows.append({'product':p,'differences':differences,'comparison_to':first['id'],
                     'unknown':[k for k in first['specs'] if k not in p['specs']]})
    return {'items':rows,'reference':first,'missing_ids':[i for i in ids if not any(p['id']==i for p in items)]}


def similar(product_id):
    target=db.get_product(product_id)
    if not target: raise ValueError('Товар не найден')
    candidates=db.list_products(category=target['category'],limit=50)['items']
    results=[]
    for p in candidates:
        if p['id']==target['id']: continue
        common=target['specs'].keys() & p['specs'].keys()
        if not common: continue
        similarities=[SequenceMatcher(None,target['specs'][k].casefold(),p['specs'][k].casefold()).ratio() for k in common]
        differences=[f"{k}: {p['specs'][k]} (исходный: {target['specs'][k]})" for k in common if p['specs'][k].casefold()!=target['specs'][k].casefold()]
        unknown=[k for k in target['specs'] if k not in p['specs']]
        results.append({'product':p,'similarity':round(sum(similarities)/len(target['specs'])*100), 'differences':differences, 'unknown':unknown})
    results.sort(key=lambda x:(-x['similarity'],x['product']['price_kopecks']))
    return {'reference':target,'items':results[:5], 'note':'Оценка ориентировочная: сравнение текстовых характеристик, а не тест производительности.'}
