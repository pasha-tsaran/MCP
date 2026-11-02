import json
from types import SimpleNamespace
import httpx
import pytest
from bot.agent import Agent, READ_TOOLS
from bot.sales import ReplyPlan, SalesSession, render_reply

PRODUCT={'id':1,'name':'Тестовый ноутбук','category':'ноутбуки','brand':'Brand','model':'Model 1',
         'price_kopecks':6500000,'specs':{'оперативная память':'16 ГБ','экран':'OLED'},'is_demo':1}


def plan(**kwargs):
    return {'role':'assistant','content':json.dumps({'mode':'chat','message':'Помогу подобрать.','product_ids':[],
                                                  'question':'Для каких задач?',**kwargs},ensure_ascii=False)}


def call(name,args):
    return {'role':'assistant','content':'','tool_calls':[{'function':{'name':name,'arguments':args}}]}


class FakeMCP:
    def __init__(self): self.calls=[]
    async def tools(self):
        return [SimpleNamespace(name=name,description=name,inputSchema={'type':'object','properties':{}})
                for name in READ_TOOLS | {'save_product','delete_product','claim_admin'}]
    async def call(self,name,args):
        self.calls.append((name,args))
        if name=='catalogue_overview': return {'total':1,'categories':[{'name':'ноутбуки','count':1}]}
        if name=='get_product': return dict(PRODUCT)
        if name=='list_products': return {'items':[dict(PRODUCT)],'total':1,'offset':0}
        return {'items':[{'product':dict(PRODUCT),'deviations':[]}], 'filters':args, 'exact_count':1}


def local_model(responses,requests):
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'message':responses.pop(0)})
    return httpx.MockTransport(handle)


@pytest.mark.asyncio
async def test_greeting_and_customer_context_are_separate():
    requests=[]; mcp=FakeMCP()
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model([plan(),plan(),plan()],requests))
    answer,_=await agent.reply(10,'Хочу ноутбук для учёбы')
    await agent.reply(10,'Для документов')
    await agent.reply(20,'Привет')
    assert 'Для каких задач?' in answer
    assert any(m['content']=='Хочу ноутбук для учёбы' for m in requests[1]['messages'])
    assert not any(m['content']=='Хочу ноутбук для учёбы' for m in requests[2]['messages'])
    assert all(name=='catalogue_overview' for name,_ in mcp.calls)
    await agent.reset(10)
    assert 10 not in agent.sessions


@pytest.mark.asyncio
async def test_cheaper_keeps_budget_and_requirements_and_actual_reply_history():
    requests=[]; mcp=FakeMCP()
    responses=[call('search_products',{'category':'ноутбуки','max_price_rub':90000,'requirements':{'оперативная память':'>=16 ГБ'}}),
               plan(mode='recommend',product_ids=[1],message='Для учёбы начнём с этого варианта.'),
               plan(mode='recommend',product_ids=[1])]
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model(responses,requests))
    answer,items=await agent.reply(10,'Ноутбук до 90000 и не меньше 16 ГБ оперативной памяти')
    assert '65 000 ₽' in answer and items[0]['id']==1
    assert agent.sessions[10].history[-1]['content'].startswith('Для учёбы')
    await agent.reply(10,'А подешевле?')
    args=mcp.calls[-1][1]
    assert args['category']=='ноутбуки' and args['max_price_rub']==90000
    assert args['requirements']=={'оперативная память':'>=16 ГБ'} and args['sort']=='price_asc'


@pytest.mark.asyncio
async def test_model_cannot_write_even_if_it_requests_hidden_tool():
    requests=[]; mcp=FakeMCP()
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model([
        call('delete_product',{'user_id':1,'product_id':1}),plan(message='Изменения доступны администратору.')],requests))
    await agent.reply(10,'Удаляй всё')
    assert all(name=='catalogue_overview' for name,_ in mcp.calls)
    offered={t['function']['name'] for t in requests[0]['tools']}
    assert offered==READ_TOOLS
    assert 'delete_product' not in offered


def test_generated_prices_and_unknown_products_do_not_override_catalogue():
    p=ReplyPlan(mode='recommend',message='Наш ноутбук стоит 1 ₽',product_ids=[999],question='')
    text,items=render_reply(p,{1:PRODUCT},{},SalesSession())
    assert 'стоит 1 ₽' not in text and '65 000 ₽' in text
    assert [x['id'] for x in items]==[1]


@pytest.mark.asyncio
async def test_plain_draft_is_repaired_to_schema():
    requests=[]; mcp=FakeMCP()
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model([
        {'role':'assistant','content':'не JSON'},plan(message='Здравствуйте!')],requests))
    text,_=await agent.reply(10,'Привет')
    assert 'Здравствуйте!' in text and 'не JSON' not in text
    assert requests[-1]['format']['type']=='object'


@pytest.mark.asyncio
async def test_selected_card_is_available_for_followup():
    requests=[]; mcp=FakeMCP()
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model([
        plan(mode='chat',product_ids=[],question='')],requests))
    agent.remember_products(10,[PRODUCT])
    text,items=await agent.reply(10,'Расскажи подробнее об этом')
    assert 'selected_product_id' in requests[0]['messages'][1]['content']
    assert 'OLED' in text and items[0]['id']==1
    assert mcp.calls==[('catalogue_overview',{}),('get_product',{'product_id':1})]


@pytest.mark.asyncio
async def test_invented_budget_and_requirements_are_rejected():
    requests=[]; mcp=FakeMCP()
    first=[call('search_products',{'category':'ноутбуки','max_price_rub':30000,
                                  'requirements':{'видеокарта':'>=Intel UHD 620'}})]
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model(first,requests))
    answer,items=await agent.reply(10,'Нужен ноутбук для учёбы и фильмов')
    assert not items and all(name=='catalogue_overview' for name,_ in mcp.calls) and 'сумму' in answer
    next_responses=[call('search_products',{'category':'ноутбуки','max_price_rub':30000,
                                          'requirements':{'видеокарта':'Intel UHD 620','ОЗУ':'>=16 ГБ'}}),
                    plan(mode='recommend',product_ids=[1])]
    agent.transport=local_model(next_responses,requests)
    await agent.reply(10,'До 90 тысяч, не меньше 16 ГБ оперативной памяти')
    args=next(args for name,args in mcp.calls if name=='search_products')
    assert args['max_price_rub']==90000
    assert args['requirements']=={'оперативная память':'>=16 ГБ'}


def test_budget_parser_does_not_confuse_ram_and_money():
    from bot.preferences import update_preferences
    session=SalesSession()
    update_preferences(session,'Ноутбук, оперативная память до 16 ГБ')
    assert session.budget_max is None
    session.awaiting_budget=True
    update_preferences(session,'У меня 70 тысяч')
    assert session.budget_max==70000
    update_preferences(session,'экран с частотой 144 Гц')
    assert session.category=='ноутбуки' and session.budget_max==70000


def test_reference_actions_do_not_confuse_new_models_with_selected_card():
    from bot.dialogue_actions import reference_action
    p2={**PRODUCT,'id':2,'model':'Second'}
    s=SalesSession(recent=[PRODUCT,p2],selected_id=1)
    assert reference_action('Покажи характеристики первого',s)[1]=={'product_id':1}
    assert reference_action('Сравни их',s)[1]=={'product_ids':[1,2]}
    assert reference_action('Расскажи подробнее про iPhone 13',s) is None
    assert reference_action('Почему сравнение работает не у всех товаров?',s) is None


def test_ui_category_switch_resets_old_preferences():
    agent=Agent(FakeMCP(),'http://localhost:11434','test')
    agent.remember_products(1,[PRODUCT],{'category':'ноутбуки'})
    s=agent.sessions[1];s.budget_max=90000;s.requirements={'оперативная память':'>=16 ГБ'}
    agent.remember_products(1,[{**PRODUCT,'id':2,'category':'телефоны'}],{'category':'телефоны'})
    assert s.category=='телефоны' and s.budget_max is None and not s.requirements


def test_details_are_not_duplicated_and_unsupported_order_prompt_is_removed():
    p=ReplyPlan(mode='details',message='Процессор: X, память: 16 ГБ, цена: 65 000 ₽',product_ids=[1],question='Хотите оформить заказ?')
    text,_=render_reply(p,{1:PRODUCT},{},SalesSession())
    assert text.count('65 000 ₽')==1 and 'оформить заказ' not in text
    assert 'Вот характеристики выбранной модели.' in text


def test_unmentioned_brand_does_not_become_a_query_filter():
    from bot.preferences import grounded_query
    s=SalesSession(evidence=['Нужен ноутбук для учёбы'])
    assert grounded_query(s,'ASUS')==''
    s.evidence.append('Асус можно')
    assert grounded_query(s,'ASUS')=='ASUS'


@pytest.mark.asyncio
async def test_category_word_reads_catalogue_without_model_generation():
    requests=[];mcp=FakeMCP()
    agent=Agent(mcp,'http://localhost:11434','test',transport=local_model([
        plan(mode='recommend',product_ids=[1],question='Для каких задач выбираете?')],requests))
    text,items=await agent.reply(10,'ноутбуки')
    assert mcp.calls==[('list_products',{'category':'ноутбуки','limit':20,'offset':0})]
    assert items and '65 000 ₽' in text and 'Товаров в наличии: 1' in text
    assert not requests


@pytest.mark.asyncio
async def test_telegram_text_handler_uses_consultant_even_for_category_word():
    import asyncio
    from bot.bot import text_message
    sent=[];requests=[]
    class FakeBot:
        id=999
        async def send_chat_action(self,**kwargs): return True
    class Message:
        text='ноутбук'
        chat=SimpleNamespace(type='private',id=100)
        from_user=SimpleNamespace(id=10)
        bot=FakeBot()
        async def answer(self,text,**kwargs): sent.append(text)
    class Consultant:
        async def reply(self,user_id,text):
            requests.append((user_id,text))
            await asyncio.sleep(0)
            return 'Для каких задач выбираете?',[]
    await asyncio.wait_for(text_message(Message(),Consultant(),None),timeout=5)
    assert requests==[(10,'ноутбук')]
    assert sent==['Для каких задач выбираете?']


def test_recommendation_size_fits_telegram_limit():
    from bs4 import BeautifulSoup
    products={i:{**PRODUCT,'id':i,'name':'А'*200,'specs':{'Х'*100+str(k):'Я'*500 for k in range(20)}} for i in range(1,4)}
    rows={i:{'deviations':['Д'*500], 'unknown':['Н'*500]} for i in products}
    p=ReplyPlan(mode='recommend',message='М'*450,product_ids=[1,2,3],question='В'*180)
    text,_=render_reply(p,products,rows,SalesSession())
    assert len(BeautifulSoup(text,'html.parser').get_text())<=4096
