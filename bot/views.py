"""Telegram text and keyboard rendering."""
import html
from datetime import datetime, timedelta, timezone
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def money(kopecks): return f'{kopecks / 100:,.2f}'.replace(',', ' ').replace('.00','')+' ₽'
def h(value): return html.escape(str(value))


def menu(admin=False):
    rows=[[KeyboardButton(text='📂 Каталог'),KeyboardButton(text='🔎 Поиск')]]
    if admin: rows.append([KeyboardButton(text='⚙️ Управление товарами')])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)


def category_keyboard(categories):
    rows=[[InlineKeyboardButton(text=c.title(),callback_data='cat:'+str(i))] for i,c in enumerate(categories)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_keyboard(items,category='',offset=0,total=None):
    rows=[[InlineKeyboardButton(text=f"{p['name'][:40]} · {money(p['price_kopecks'])}",callback_data=f"p:{p['id']}")] for p in items]
    nav=[]
    if offset>0: nav.append(InlineKeyboardButton(text='⬅️ Назад',callback_data=f'page:{category}:{max(0,offset-8)}'))
    if total is not None and offset+8<total: nav.append(InlineKeyboardButton(text='Вперёд ➡️',callback_data=f'page:{category}:{offset+8}'))
    if nav: rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def product_card(p):
    lines=[f"<b>{h(p['name'])}</b>",f"Цена: <b>{money(p['price_kopecks'])}</b>",f"Категория: {h(p['category'])}",f"Модель: {h(p['brand'])} {h(p['model'])}",f"ID: {p['id']}"]
    if p.get('is_demo'): lines.append('⚠️ Демонстрационный товар: цена и характеристики не проверены.')
    lines += ['','<b>Характеристики:</b>']+[f"• {h(k)}: {h(v)}" for k,v in p['specs'].items()]
    return '\n'.join(lines)


def card_keyboard(pid,admin=False):
    rows=[[InlineKeyboardButton(text='📊 Сравнить с конкурентами',callback_data=f'compare:{pid}')],
          [InlineKeyboardButton(text='🔄 Похожие товары',callback_data=f'similar:{pid}')]]
    if admin: rows.append([InlineKeyboardButton(text='✏️ Изменить',callback_data=f'edit:{pid}'),InlineKeyboardButton(text='🗑 Удалить',callback_data=f'delete:{pid}')])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirmation(action,nonce):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Подтвердить',callback_data=f'confirm:{action}:{nonce}'),InlineKeyboardButton(text='❌ Отмена',callback_data='cancel')]])


def compare_text(data):
    p=data['product']; offers=data.get('offers',[])
    table=[f"{'Продавец':<12} {'Цена':>10} {'Разница':>11}",f"{'Наш магазин':<12} {money(p['price_kopecks']):>10} {'—':>11}"]
    rows=['<b>Сравнение цен</b>',h(p['name'][:200])]
    if p.get('is_demo'):
        rows.append('Наша цена демонстрационная. Цены конкурентов получены с сайтов магазинов.')
    for o in offers:
        diff=o.get('price_kopecks',round(o['price_rub']*100))-p['price_kopecks']
        sign='+' if diff>0 else '−' if diff<0 else ''
        table.append(f"{o['shop'][:12]:<12} {money(o.get('price_kopecks',round(o['price_rub']*100))):>10} {sign+money(abs(diff)):>11}")
    rows.append('<pre>'+h('\n'.join(table))+'</pre>')
    if not offers: rows.append('Предложений с подтверждёнными характеристиками и наличием не найдено.')
    configured=len(data.get('sources',[]))
    if configured: rows.append(f'Найдено магазинов: {len(offers)} из {configured}. Регион: {h(data.get("region","Москва"))}.')
    for i,o in enumerate(offers,1):
        rows.append(f"\n<b>{i}. {h(o['shop'])}</b>: {h(o['name'][:160])}")
        matched=[k+': '+str(p.get('specs',{}).get(k,p.get('model',''))) for k in o['matched']]
        rows.append('Совпали: '+h('; '.join(matched)[:350] or 'в фиде не подтверждены'))
        if o['unknown']: rows.append('Не подтверждены: '+h(', '.join(o['unknown'])[:150]))
        timestamp=datetime.fromisoformat(o['checked_at']).astimezone(timezone(timedelta(hours=3)))
        rows.append('Проверено: '+timestamp.strftime('%d.%m.%Y %H:%M МСК'))
    for source in data.get('sources',[]):
        if source.get('status')!='ok':
            rows.append('\n'+h(source['shop'])+': '+h(source['reason'][:250]))
    if data.get('note'): rows.append('\n'+h(data['note'][:250]))
    if offers:
        rows.append('\n<b>Источники:</b>')
        for i,o in enumerate(offers,1):
            if o['url']: rows.append(f"{i}. <a href=\"{h(o['url'])}\">{h(o['shop'])}</a>")
    if data.get('errors'): rows.append('\nНекоторые источники недоступны: '+h('; '.join(data['errors'])))
    return '\n'.join(rows)
