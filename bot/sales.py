"""Conversation state and replies with catalogue-controlled product facts."""
from __future__ import annotations
import html
import json
import re
import time
from textwrap import shorten
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, Field
from .views import h, money, compare_text


class ReplyPlan(BaseModel):
    mode: Literal['chat', 'recommend', 'details', 'compare', 'competitors']
    message: str = Field(max_length=450)
    product_ids: list[int] = Field(max_length=3)
    question: str = Field(max_length=180)


@dataclass
class SalesSession:
    history: list[dict] = field(default_factory=list)
    recent: list[dict] = field(default_factory=list)
    selected_id: int | None = None
    filters: dict = field(default_factory=dict)
    category: str = ''
    budget_max: int | None = None
    budget_min: int = 0
    requirements: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    awaiting_budget: bool = False
    catalogue_page: dict | None = None
    updated: float = field(default_factory=time.monotonic)

    def context(self):
        references=[{k:p[k] for k in ('id','name','category','price_kopecks')} for p in self.recent]
        return json.dumps({'last_shown_in_order': references, 'selected_product_id': self.selected_id,
                           'last_search_filters': self.filters,
                           'user_confirmed_budget': self.budget_max,
                           'user_confirmed_requirements': self.requirements,
                           'catalogue_page':self.catalogue_page}, ensure_ascii=False)

    def record(self, text, rendered):
        plain = html.unescape(re.sub(r'<[^>]+>', '', rendered))
        self.history = (self.history + [{'role': 'user', 'content': text[:2000]},
                                       {'role': 'assistant', 'content': plain[:3500]}])[-20:]
        self.updated = time.monotonic()


def safe_copy(text, products, filters):
    prices = {Decimal(p['price_kopecks']) / 100 for p in products.values()}
    prices.update(Decimal(str(filters[k])) for k in ('max_price_rub', 'min_price_rub') if filters.get(k))
    for match in re.finditer(r'(\d[\d \u00a0]*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:лей|ля|ль)?\b)', text, re.I):
        try: amount = Decimal(match[1].replace(' ', '').replace('\u00a0', '').replace(',', '.'))
        except InvalidOperation: return ''
        if amount not in prices: return ''
    if re.search(r'заказ (?:уже )?оформлен|я (?:зарезервировал|оформил)|доставим (?:завтра|сегодня)', text, re.I):
        return ''
    return text.strip()


def render_reply(plan, products, rows, session, comparison=None, lookup_verified=False):
    lead = safe_copy(plan.message, products, session.filters)
    question = safe_copy(plan.question, products, session.filters)
    if question and any(question.casefold() in m['content'].casefold() for m in session.history[-4:] if m['role']=='assistant'):
        question=''
    if re.search(r'оформить заказ|оплатить|забронировать',question,re.I): question=''
    if question:
        lead=re.sub(r'[^.!?]*\?', '', lead).strip()
    selected = [products[i] for i in dict.fromkeys(plan.product_ids) if i in products][:3]
    if plan.mode in {'recommend', 'details', 'compare'} and not selected:
        selected = list(products.values())[:3]
    if plan.mode == 'details': selected = selected[:1]
    if selected and plan.mode=='details':
        lead='Вот характеристики выбранной модели.'
    elif selected and plan.mode=='recommend':
        sentences=re.split(r'(?<=[!?])\s+|(?<=\.)\s+(?=[А-ЯA-Z])',lead)
        lead=' '.join(s for s in sentences if not re.search(r'₽|руб(?:лей|ля|ль)\b',s,re.I)
                      and len(re.findall(r'\d+\s*(?:ГБ|ТБ|GB|SSD|IPS|OLED)',s,re.I))<2).strip()
        if not lead:
            exact=all(not rows.get(p['id'],{}).get('deviations') for p in selected)
            lead=('Это самый доступный вариант с сохранением ваших требований.'
                  if len(selected)==1 and session.filters.get('sort')=='price_asc' and exact
                  else 'Посмотрите эти варианты из каталога.' if exact else 'Нашёл ближайшие варианты. Отличия указаны ниже.')
    if comparison is not None:
        return (h(lead) + '\n\n' if lead else '') + compare_text(comparison), [comparison['product']]
    lines = [h(lead)] if lead else []
    if selected and plan.mode != 'chat':
        context=' '.join(session.evidence[-3:]).casefold()
        focus=[]
        if re.search(r'экран|фильм|oled|ips',context): focus.append('экран')
        if re.search(r'игр|видеокарт|rtx',context): focus.append('видеокарта')
        if re.search(r'оператив|озу|ram',context): focus.append('оперативная память')
        for number, p in enumerate(selected, 1):
            lines.append(f"\n<b>{number}. {h(p['name'][:120])}</b> — <b>{money(p['price_kopecks'])}</b>")
            specs=sorted(p['specs'].items(),key=lambda item:focus.index(item[0]) if item[0] in focus else len(focus))
            for key, value in specs[:(12 if plan.mode == 'details' else 4)]:
                lines.append(f"• {h(key[:45])}: {h(value[:100])}")
            row = rows.get(p['id'], {})
            differences = row.get('deviations', row.get('differences', []))
            if differences:
                label='Отличия от первого варианта: ' if row.get('comparison_to') else 'Отличия от запроса: '
                differences=sorted(differences,key=lambda value:next((i for i,k in enumerate(focus) if value.startswith(k+':')),len(focus)))
                lines.append(label + h(shorten('; '.join(differences),width=220,placeholder='…')))
            if row.get('unknown'): lines.append('Нет данных: ' + h(', '.join(row['unknown'])[:120]))
        if any(p.get('is_demo') for p in selected):
            lines.append('\nЦены нашего учебного каталога демонстрационные.')
    elif plan.mode != 'chat' and not selected:
        lines.append('По указанным условиям совпадений не найдено. Можно изменить бюджет или требования.'
                     if lookup_verified else 'Для подбора нужно уточнить категорию, бюджет или модель.')
    if question: lines.append('\n' + h(question))
    if not lines: lines = ['Помогу выбрать технику. Для каких задач подбираете и какой бюджет?']
    return '\n'.join(lines), selected if plan.mode != 'chat' else []
