"""Telegram UI: public browsing, private administrator operations."""
from __future__ import annotations
import asyncio
import logging
import os
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.chat_action import ChatActionSender
from dotenv import load_dotenv

from .mcp_client import open_mcp
from .agent import Agent
from .catalogue import CatalogueUnavailable
from . import views

ROOT=Path(__file__).resolve().parent.parent
load_dotenv(ROOT/'.env')
dp=Dispatcher()


class Edit(StatesGroup):
    data=State()
    confirm=State()


def private(message): return message.chat.type=='private'


async def admin(mcp,user_id): return (await mcp.call('check_admin',{'user_id':user_id}))['is_admin']


@dp.message(CommandStart())
async def start(message:Message,mcp,agent:Agent,state:FSMContext):
    if not private(message):
        await message.answer('Откройте личный чат с ботом и нажмите /start.'); return
    result=await mcp.call('claim_admin',{'user_id':message.from_user.id})
    is_admin=result['is_admin']
    await state.clear()
    await agent.reset(message.from_user.id)
    await message.answer('Здравствуйте! Помогу выбрать технику под ваши задачи и бюджет. Что подбираете и для чего будете использовать?\n\n'+('Вы администратор каталога.' if is_admin else 'Можно общаться обычными сообщениями.'),reply_markup=views.menu(is_admin))


@dp.message(Command('reset'))
async def reset_dialogue(message:Message,agent:Agent,state:FSMContext):
    if not private(message): return
    await state.clear()
    await agent.reset(message.from_user.id)
    await message.answer('Начнём подбор заново. Какую технику ищете и для каких задач?')


@dp.message(Command('cancel'))
async def cancel_message(message:Message,state:FSMContext,mcp):
    await state.clear()
    await message.answer('Действие отменено.',reply_markup=views.menu(await admin(mcp,message.from_user.id)))


@dp.message(F.text=='📂 Каталог')
async def catalogue(message:Message,mcp):
    if not private(message): return
    cats=await mcp.call('categories')
    await message.answer('Выберите категорию:',reply_markup=views.category_keyboard(cats))


@dp.message(F.text=='🔎 Поиск')
async def search_help(message:Message):
    if private(message): await message.answer('Напишите, например: «Ноутбук до 90000 рублей с 16 ГБ оперативной памяти» или «Найди похожее на iPhone 13».')


@dp.message(F.text=='⚙️ Управление товарами')
async def manage(message:Message,mcp):
    if not private(message) or not await admin(mcp,message.from_user.id):
        await message.answer('Доступно только администратору в личном чате.'); return
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='➕ Добавить товар',callback_data='add')],
       [InlineKeyboardButton(text='📂 Найти товар для изменения или удаления',callback_data='manage_catalog')]])
    await message.answer('Выберите действие. Изменение и удаление доступны в карточке товара.',reply_markup=kb)


@dp.callback_query(F.data=='manage_catalog')
async def manage_catalog(callback:CallbackQuery,mcp):
    if not private(callback.message) or not await admin(mcp,callback.from_user.id): await callback.answer('Нет доступа',show_alert=True); return
    cats=await mcp.call('categories')
    await callback.message.answer('Выберите категорию:',reply_markup=views.category_keyboard(cats)); await callback.answer()


@dp.callback_query(F.data.startswith('cat:'))
async def category(callback:CallbackQuery,mcp,agent:Agent):
    cats=await mcp.call('categories')
    try: i=int(callback.data.split(':')[1]); cat=cats[i]
    except (ValueError,IndexError): await callback.answer('Категория изменилась. Откройте каталог снова.'); return
    data=await mcp.call('list_products',{'category':cat,'limit':8,'offset':0})
    agent.remember_products(callback.from_user.id,data['items'],{'category':cat})
    await callback.message.answer(f'<b>{views.h(cat.title())}</b>: {data["total"]}',reply_markup=views.products_keyboard(data['items'],str(i),0,data['total'])); await callback.answer()


@dp.callback_query(F.data.startswith('page:'))
async def page(callback:CallbackQuery,mcp,agent:Agent):
    try:
        _,index,offset=callback.data.split(':'); cats=await mcp.call('categories'); cat=cats[int(index)]; offset=max(0,int(offset))
    except (ValueError,IndexError): await callback.answer('Откройте каталог снова.'); return
    data=await mcp.call('list_products',{'category':cat,'limit':8,'offset':offset})
    agent.remember_products(callback.from_user.id,data['items'],{'category':cat})
    await callback.message.edit_text(f'<b>{views.h(cat.title())}</b>: {data["total"]}',reply_markup=views.products_keyboard(data['items'],index,offset,data['total'])); await callback.answer()


@dp.callback_query(F.data.startswith('p:'))
async def card(callback:CallbackQuery,mcp,agent:Agent):
    try: pid=int(callback.data.split(':')[1])
    except ValueError: await callback.answer('Неверный товар'); return
    p=await mcp.call('get_product',{'product_id':pid})
    if 'error' in p: await callback.answer('Товар не найден',show_alert=True); return
    agent.remember_products(callback.from_user.id,[p])
    is_admin=private(callback.message) and await admin(mcp,callback.from_user.id)
    await callback.message.answer(views.product_card(p),reply_markup=views.card_keyboard(pid,is_admin)); await callback.answer()


@dp.callback_query(F.data.startswith('compare:'))
async def compare(callback:CallbackQuery,mcp,agent:Agent=None):
    await callback.answer('Проверяю источники цен…')
    try:
        data=await mcp.call('compare_competitors',{'product_id':int(callback.data.split(':')[1])})
        if 'error' in data: await callback.message.answer('Товар не найден.'); return
        if agent: agent.remember_products(callback.from_user.id,[data['product']])
        await callback.message.answer(views.compare_text(data),disable_web_page_preview=True)
    except Exception:
        logging.exception('Comparison failed'); await callback.message.answer('Не удалось получить цены. Попробуйте позже.')


@dp.callback_query(F.data.startswith('similar:'))
async def similar(callback:CallbackQuery,mcp,agent:Agent):
    data=await mcp.call('similar_products',{'product_id':int(callback.data.split(':')[1])})
    items=data.get('items',[])
    agent.remember_products(callback.from_user.id,[x['product'] for x in items])
    lines=['<b>Похожие товары</b>',views.h(data.get('note',''))]
    for x in items:
        lines.append(f"\n{views.h(x['product']['name'])} — {views.money(x['product']['price_kopecks'])}")
        if x['differences']: lines.append('Отличия: '+views.h('; '.join(x['differences'])))
        if x['unknown']: lines.append('Неизвестно: '+views.h(', '.join(x['unknown'])))
    if not items: lines.append('Близкие товары не найдены.')
    await callback.message.answer('\n'.join(lines),reply_markup=views.products_keyboard([x['product'] for x in items])); await callback.answer()


FORM='''Отправьте карточку одним сообщением, по строкам:
Название: ...
Категория: ...
Бренд: ...
Модель: ...
Цена: 69990.00
Характеристики: память=128 ГБ; экран=6.1 OLED; процессор=A15

Для изменения пришлите только нужные поля. Характеристики заменяются целиком. Отмена: /cancel.'''


def parse_form(text,old=None):
    aliases={'название':'name','категория':'category','бренд':'brand','модель':'model','цена':'price_kopecks','характеристики':'specs'}
    data={k:old[k] for k in ('name','category','brand','model','price_kopecks','specs')} if old else {}
    seen=set()
    for line in text.splitlines():
        if not line.strip(): continue
        key,sep,value=line.partition(':'); key=key.strip().lower(); value=value.strip()
        if not sep or key not in aliases or not value or key in seen: raise ValueError('Проверьте названия полей и значения; каждое поле указывается один раз.')
        seen.add(key); field=aliases[key]
        if field=='price_kopecks':
            try:
                n=Decimal(value.replace(' ','').replace(',','.'))
                if not n.is_finite() or n<0 or n>Decimal('10000000000') or n.as_tuple().exponent < -2: raise ValueError('Некорректная цена')
                data[field]=int(n*100)
            except InvalidOperation: raise ValueError('Некорректная цена')
        elif field=='specs':
            specs={}
            for pair in value.split(';'):
                k,s,v=pair.partition('=')
                if not s or not k.strip() or not v.strip(): raise ValueError('Характеристики: ключ=значение; ключ=значение')
                specs[k.strip()]=v.strip()
            data[field]=specs
        else: data[field]=value
    if set(data)!={'name','category','brand','model','price_kopecks','specs'}: raise ValueError('Для нового товара укажите все шесть полей.')
    return data


@dp.callback_query(F.data=='add')
async def add(callback:CallbackQuery,state:FSMContext,mcp):
    if not private(callback.message) or not await admin(mcp,callback.from_user.id): await callback.answer('Нет доступа',show_alert=True); return
    await state.clear(); await state.set_state(Edit.data); await state.update_data(product_id=0)
    await callback.message.answer(FORM); await callback.answer()


@dp.callback_query(F.data.startswith('edit:'))
async def edit(callback:CallbackQuery,state:FSMContext,mcp):
    if not private(callback.message) or not await admin(mcp,callback.from_user.id): await callback.answer('Нет доступа',show_alert=True); return
    pid=int(callback.data.split(':')[1]); p=await mcp.call('get_product',{'product_id':pid})
    if 'error' in p: await callback.answer('Товар не найден',show_alert=True); return
    await state.clear(); await state.set_state(Edit.data); await state.update_data(product_id=pid,old=p)
    await callback.message.answer('Изменение товара: '+views.h(p['name'])+'\n\n'+FORM); await callback.answer()


@dp.message(Edit.data)
async def form(message:Message,state:FSMContext,mcp):
    if not private(message) or not await admin(mcp,message.from_user.id): await state.clear(); return
    context=await state.get_data()
    try: data=parse_form(message.text or '',context.get('old'))
    except ValueError as exc: await message.answer('Ошибка: '+views.h(exc.args[0])+'\nПопробуйте ещё раз или /cancel.'); return
    preview={**data,'id':context.get('product_id') or 'новый','is_demo':False}
    nonce=secrets.token_hex(6)
    await state.update_data(pending=data,nonce=nonce); await state.set_state(Edit.confirm)
    await message.answer(views.product_card(preview)+'\n\nСохранить?',reply_markup=views.confirmation('save',nonce))


@dp.callback_query(F.data.startswith('delete:'))
async def delete(callback:CallbackQuery,state:FSMContext,mcp):
    if not private(callback.message) or not await admin(mcp,callback.from_user.id): await callback.answer('Нет доступа',show_alert=True); return
    pid=int(callback.data.split(':')[1]); p=await mcp.call('get_product',{'product_id':pid})
    if 'error' in p: await callback.answer('Товар не найден',show_alert=True); return
    nonce=secrets.token_hex(6)
    await state.clear(); await state.set_state(Edit.confirm); await state.update_data(delete_id=pid,nonce=nonce)
    await callback.message.answer('Удалить товар «'+views.h(p['name'])+'»?',reply_markup=views.confirmation('delete',nonce)); await callback.answer()


@dp.callback_query(F.data=='cancel')
async def cancel_callback(callback:CallbackQuery,state:FSMContext):
    await state.clear(); await callback.message.edit_text('Действие отменено.'); await callback.answer()


@dp.callback_query(F.data.startswith('confirm:'))
async def confirm(callback:CallbackQuery,state:FSMContext,mcp):
    if not private(callback.message) or not await admin(mcp,callback.from_user.id): await callback.answer('Нет доступа',show_alert=True); return
    data=await state.get_data(); parts=callback.data.split(':')
    if len(parts)!=3 or await state.get_state()!=Edit.confirm.state or parts[2]!=data.get('nonce'):
        await callback.answer('Подтверждение устарело.',show_alert=True); return
    action=parts[1]
    try:
        if action=='save' and 'pending' in data:
            p=await mcp.call('save_product',{'user_id':callback.from_user.id,'product_id':data.get('product_id',0),'data':data['pending']})
            await callback.message.edit_text('Товар сохранён. ID: '+str(p['id']))
        elif action=='delete' and 'delete_id' in data:
            await mcp.call('delete_product',{'user_id':callback.from_user.id,'product_id':data['delete_id']})
            await callback.message.edit_text('Товар удалён.')
        else: await callback.answer('Подтверждение устарело.',show_alert=True); return
        await state.clear(); await callback.answer()
    except Exception:
        logging.exception('Save/delete failed'); await callback.answer('Ошибка сохранения. Проверьте данные.',show_alert=True)


@dp.message(F.text)
async def text_message(message:Message,agent:Agent,mcp):
    if not private(message): return
    text=message.text.strip()
    try:
        async with ChatActionSender.typing(bot=message.bot,chat_id=message.chat.id):
            answer,products=await agent.reply(message.from_user.id,text)
        await message.answer(answer,reply_markup=views.products_keyboard(products[:3]),disable_web_page_preview=True)
    except CatalogueUnavailable:
        logging.exception('Catalogue unavailable')
        await message.answer('Сейчас не удалось прочитать каталог. Попробуйте немного позже.')
    except (httpx.HTTPError,TimeoutError):
        logging.exception('Ollama unavailable'); await message.answer('Сейчас не получилось завершить подбор. Попробуйте немного позже; каталог доступен в меню.')
    except Exception:
        logging.exception('Agent failed'); await message.answer('Не удалось обработать запрос. Попробуйте уточнить его или откройте каталог.')


async def main():
    logging.basicConfig(level=logging.INFO)
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token: raise SystemExit('Укажите TELEGRAM_BOT_TOKEN в файле .env в корне MCP.')
    async with open_mcp() as mcp:
        agent=Agent(mcp,os.getenv('OLLAMA_URL','http://127.0.0.1:11434'),os.getenv('OLLAMA_MODEL','qwen3:8b'))
        bot=Bot(token,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try: await dp.start_polling(bot,mcp=mcp,agent=agent)
        finally: await bot.session.close()


if __name__=='__main__': asyncio.run(main())
