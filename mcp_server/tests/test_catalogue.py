import json
import pytest
from mcp_server import db,search,competitors
from bot.bot import parse_form


@pytest.fixture(autouse=True)
def isolated_db(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',tmp_path/'test.db')
    db.initialize()


def test_admin_claim_crud_and_audit():
    assert db.claim_admin(100)
    assert not db.claim_admin(200)
    data={'name':'Товар','category':'телефоны','brand':'Бренд','model':'Model 123','price_kopecks':10000,'specs':{'память':'128 ГБ'}}
    with pytest.raises(PermissionError): db.save_product(200,data)
    created=db.save_product(100,data)
    data['price_kopecks']=20000
    assert db.save_product(100,data,created['id'])['price_kopecks']==20000
    with pytest.raises(PermissionError): db.delete_product(200,created['id'])
    assert db.delete_product(100,created['id'])
    with db.connect() as con: assert con.execute('select count(*) from audit').fetchone()[0]==3


def test_russian_search_and_approximation():
    assert db.list_products(query='НОУТБУК')['total']>=4
    result=search.search('ноутбук',max_price_rub=70000,requirements={'оперативная память':'16 ГБ'})
    assert result['items']
    assert not result['items'][0]['deviations']
    assert all(not x['deviations'] for x in result['items'])
    alternatives=search.search('ноутбук',max_price_rub=10000,requirements={'оперативная память':'>=32 ГБ'})
    assert alternatives['relaxed'] and all(x['deviations'] for x in alternatives['items'])


def test_form_parses_prices_and_edit():
    data=parse_form('Название: X\nКатегория: телефоны\nБренд: Y\nМодель: Z\nЦена: 123,45\nХарактеристики: память=128 ГБ')
    assert data['price_kopecks']==12345
    assert parse_form('Цена: 200',data)['name']=='X'
    with pytest.raises(ValueError): parse_form('Цена: -2',data)


def test_competitor_matches_model_and_reports_missing():
    product={'model':'iPhone 13 128 GB','specs':{'память':'128 ГБ','экран':'OLED'}}
    xml='<yml_catalog><shop><offers><offer available="true"><name>iPhone 13 128 GB</name><price>69000</price><currencyId>RUR</currencyId><url>https://example.com/1</url><param name="память">128 ГБ</param></offer><offer><name>iPhone 13 256 GB</name><price>60000</price><currencyId>RUB</currencyId></offer></offers></shop></yml_catalog>'.encode('utf-8')
    offers=competitors.parse_feed(xml,{'name':'Магазин'},product)
    assert len(offers)==1
    assert offers[0]['matched']==['память']
    assert offers[0]['unknown']==['экран']


@pytest.mark.asyncio
async def test_real_mcp_transport(tmp_path,monkeypatch):
    from bot.mcp_client import open_mcp
    monkeypatch.setenv('CRM_DB_PATH',str(tmp_path/'mcp.db'))
    async with open_mcp() as client:
        names={x.name for x in await client.tools()}
        assert {'claim_admin','search_products','save_product','compare_competitors'} <= names
        assert (await client.call('claim_admin',{'user_id':111}))['is_admin']
        assert not (await client.call('claim_admin',{'user_id':222}))['is_admin']
        assert (await client.call('list_products',{'category':'ноутбуки'}))['total']>=4
        with pytest.raises(ValueError):
            await client.call('delete_product',{'user_id':222,'product_id':1})


@pytest.mark.asyncio
async def test_three_competitors_and_table(tmp_path,monkeypatch):
    import httpx
    from bot.views import compare_text
    path=tmp_path/'sources.json'
    path.write_text(json.dumps({'sources':[{'name':f'Магазин {i}','url':f'https://shop{i}.example/feed'} for i in range(3)]}),encoding='utf-8')
    monkeypatch.setattr(competitors,'CONFIG',path)
    xml='''<yml_catalog><shop><offers><offer><name>iPhone 13 128 GB</name><price>69000</price><currencyId>RUB</currencyId><url>https://shop.example/item</url><param name="память">128 ГБ</param></offer></offers></shop></yml_catalog>'''.encode()
    transport=httpx.MockTransport(lambda request: httpx.Response(200,content=xml))
    original=httpx.AsyncClient
    monkeypatch.setattr(competitors.httpx,'AsyncClient',lambda **kwargs: original(transport=transport))
    p={'name':'iPhone 13','model':'iPhone 13 128 GB','price_kopecks':7000000,'specs':{'память':'128 ГБ'}}
    data=await competitors.compare(p)
    assert len(data['offers'])==3
    text=compare_text({'product':p,**data})
    assert text.index('Магазин 1') < text.index('Источники:') < text.index('<a href=')
