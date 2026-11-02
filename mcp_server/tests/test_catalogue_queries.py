"""Regression cases from Telegram: stock, full catalogue and assortment tables."""
import json
from types import SimpleNamespace
import httpx
import pytest
from bot.agent import Agent, READ_TOOLS
from bot.catalogue import catalogue_request
from bot.sales import SalesSession
from mcp_server import db, search


@pytest.fixture(autouse=True)
def catalogue_db(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'catalogue.db')
    db.initialize()


class DatabaseMCP:
    def __init__(self): self.calls=[]
    async def tools(self):
        return [SimpleNamespace(name=n,description=n,inputSchema={'type':'object','properties':{}}) for n in READ_TOOLS]
    async def call(self,name,args):
        self.calls.append((name,args))
        if name=='catalogue_overview': return db.catalogue_overview()
        if name=='list_products': return db.list_products(**args)
        if name=='search_products': return search.search(**args)
        if name=='get_product': return db.get_product(args['product_id'])
        raise AssertionError('Unexpected tool: '+name)


def no_model(request):
    raise AssertionError('Catalogue must work without calling Ollama')


@pytest.mark.asyncio
@pytest.mark.parametrize('text,category,table',[
    ('телефоны есть?','телефоны',False),
    ('Есть ли смартфоны?','телефоны',False),
    ('Какие телефоны в наличии?','телефоны',False),
    ('что есть?','',False),
    ('Что у вас есть?','',False),
    ('пришли каталог всех устройств в ассортименте','',False),
    ('пришли таблицу ассортимента','',True),
    ('Пришлите таблицу','',True),
])
async def test_real_catalogue_is_returned_despite_stale_laptop_context(text,category,table):
    mcp=DatabaseMCP();agent=Agent(mcp,'http://localhost:11434','test',transport=httpx.MockTransport(no_model))
    s=agent._session(10)
    s.category='ноутбуки';s.budget_max=5000;s.requirements={'экран':'OLED'}
    s.history=[{'role':'assistant','content':'Пока в каталоге нет телефонов, могу подобрать ноутбук.'}]
    answer,products=await agent.reply(10,text)
    expected=db.list_products(category=category,limit=50)['items']
    assert {p['id'] for p in products}=={p['id'] for p in expected}
    assert f'Товаров в наличии: {len(expected)}' in answer
    for p in expected: assert p['name'] in answer
    assert 'нет телефонов' not in answer.casefold()
    assert ('<pre>' in answer)==table
    assert mcp.calls==[('list_products',{'category':category,'limit':20,'offset':0})]


@pytest.mark.asyncio
@pytest.mark.parametrize('claim',['Пока в каталоге нет телефонов, но могу подобрать ноутбуки.',
                                 'Смартфонов я, к сожалению, сейчас не вижу.'])
async def test_model_absence_claim_is_overridden_with_live_stock(claim):
    mcp=DatabaseMCP()
    def lying_model(request):
        body=json.loads(request.content)
        assert any('Свежий состав каталога' in m['content'] for m in body['messages'] if m['role']=='system')
        return httpx.Response(200,json={'message':{'role':'assistant','content':json.dumps({
            'mode':'chat','message':claim,
            'product_ids':[],'question':'Что ещё интересует?'},ensure_ascii=False)}})
    agent=Agent(mcp,'http://localhost:11434','test',transport=httpx.MockTransport(lying_model))
    answer,products=await agent.reply(10,'Помоги выбрать мобильник')
    assert len(products)==3 and all(p['category']=='телефоны' for p in products)
    assert 'нет телефонов' not in answer.casefold() and 'iPhone 13' in answer


@pytest.mark.asyncio
async def test_verified_empty_filtered_search_is_not_global_absence():
    mcp=DatabaseMCP(); responses=[
        {'role':'assistant','content':'','tool_calls':[{'function':{'name':'search_products','arguments':{
            'category':'телефоны','max_price_rub':5000,'allow_alternatives':False}}}]},
        {'role':'assistant','content':json.dumps({'mode':'chat','message':'В каталоге нет телефонов.',
                                               'product_ids':[],'question':''},ensure_ascii=False)}]
    agent=Agent(mcp,'http://localhost:11434','test',transport=httpx.MockTransport(
        lambda request:httpx.Response(200,json={'message':responses.pop(0)})))
    answer,products=await agent.reply(10,'Подбери телефон строго до 5000 рублей')
    assert not products and 'По указанным условиям' in answer
    assert 'нет телефонов' not in answer.casefold()
    assert db.catalogue_overview()['total']==18


@pytest.mark.asyncio
async def test_catalogue_pagination_has_no_missing_or_duplicate_products():
    with db.connect() as con:
        con.executemany('INSERT INTO products(name,category,brand,model,price_kopecks,specs) VALUES(?,?,?,?,?,?)',
                        [(f'Дополнительный товар {i}','другое','Brand',f'SKU-{i}',10000,'{}') for i in range(47)])
    mcp=DatabaseMCP();agent=Agent(mcp,'http://localhost:11434','test',transport=httpx.MockTransport(no_model))
    seen=set(); text='Пришли таблицу ассортимента'
    for _ in range(4):
        answer,items=await agent.reply(10,text)
        ids={p['id'] for p in items}
        assert not (seen&ids)
        seen|=ids
        assert len(items)<=20 and 'из 65' in answer
        text='дальше'
    assert len(seen)==65
    _,previous=await agent.reply(10,'назад')
    assert len(previous)==20


@pytest.mark.asyncio
async def test_read_failure_is_not_reported_as_empty_inventory():
    class BrokenMCP(DatabaseMCP):
        async def call(self,name,args): return {'error':'Unavailable'}
    agent=Agent(BrokenMCP(),'http://localhost:11434','test',transport=httpx.MockTransport(no_model))
    with pytest.raises(ValueError,match='прочитать каталог'):
        await agent.reply(10,'Телефоны есть?')


def test_filtered_recommendation_is_not_unfiltered_catalogue():
    assert catalogue_request('Есть телефоны до 30000 рублей?',SalesSession()) is None
    assert catalogue_request('Что есть для учёбы?',SalesSession()) is None
    assert catalogue_request('Есть телефоны с OLED?',SalesSession()) is None
    assert catalogue_request('У этого телефона есть камера?',SalesSession()) is None


def test_cyrillic_category_case_does_not_hide_products():
    with db.connect() as con:
        con.execute('INSERT INTO products(name,category,brand,model,price_kopecks,specs) VALUES(?,?,?,?,?,?)',
                    ('Другой телефон','Телефоны','Brand','Phone2',100000,'{}'))
    assert db.list_products(category='телефоны')['total']==4
    assert db.categories().count('телефоны')==1
    category=next(c for c in db.catalogue_overview()['categories'] if c['name']=='телефоны')
    assert category['count']==4


@pytest.mark.asyncio
async def test_telegram_reports_catalogue_failure_instead_of_absence():
    from bot.bot import text_message
    from bot.catalogue import CatalogueUnavailable
    sent=[]
    class Bot:
        id=999
        async def send_chat_action(self,**kwargs): return True
    class Message:
        text='телефоны есть?';chat=SimpleNamespace(type='private',id=10)
        from_user=SimpleNamespace(id=10);bot=Bot()
        async def answer(self,text,**kwargs): sent.append(text)
    class BrokenAgent:
        async def reply(self,*args): raise CatalogueUnavailable('Read failed')
    import asyncio
    await asyncio.wait_for(text_message(Message(),BrokenAgent(),None),timeout=5)
    assert sent==['Сейчас не удалось прочитать каталог. Попробуйте немного позже.']
