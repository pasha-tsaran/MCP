"""Contract tests for shop cards, variant matching and public access limits."""
import pytest
import httpx

from mcp_server.shop_sources import parse_card, model_matches
from mcp_server.product_matching import compare_specs, matches_value
from mcp_server.price_http import PublicHTTP, SourceError


def test_kns_uses_main_card_not_recommended_product_price():
    data='''<div itemscope itemtype="http://schema.org/Product">
    <h1>Sony WF-1000XM5 Black</h1><meta itemprop="description" content="Bluetooth, цвет черный">
    <div class="goods-column-price"><div class="price-info"><span class="price-val">24 394</span><span class="price-valute">руб.</span></div>В наличии</div>
    <div itemscope itemtype="http://schema.org/Product"><meta itemprop="price" content="4335">
    <meta itemprop="priceCurrency" content="RUB"><link itemprop="availability" href="https://schema.org/InStock">
    <span class="goods-price1">4 335</span></div></div>'''.encode()
    offer=parse_card(data,'https://www.kns.ru/product/test/','KNS',0)
    assert offer['price_kopecks']==2439400
    assert offer['specs']['цвет']=='Bluetooth, цвет черный'
    assert parse_card(data.replace('В наличии'.encode(),'Нет в наличии'.encode()),'https://www.kns.ru/product/test/','KNS',0) is None


def test_nix_product_card_parses_specs_and_stock():
    page='''<div itemtype="http://schema.org/Product"><h1>Sony WF-1000XM5 Black</h1>
    <meta itemprop="price" content="18423"><meta itemprop="priceCurrency" content="RUB">
    <link itemprop="availability" href="https://schema.org/InStock">
    <table><tr><td>Цвет</td><td>Черный</td></tr><tr><td>Bluetooth</td><td>5.3</td></tr></table></div>'''.encode('cp1251')
    offer=parse_card(page,'https://www.nix.ru/test','НИКС',0)
    assert offer['specs']['Цвет']=='Черный'
    assert offer['price_kopecks']==1842300
    assert parse_card(page.replace(b'InStock',b'OutOfStock'),'https://www.nix.ru/test','НИКС',0) is None


def test_variant_and_capacity_must_match():
    p={'model':'iPhone 13 128 GB','brand':'Apple','category':'телефоны','specs':{'память':'128 ГБ','оперативная память':'4 ГБ'}}
    assert model_matches(p,'Apple iPhone 13 128GB Black')
    assert not model_matches(p,'Apple iPhone 13 Pro 128GB Black')
    offer={'name':'Apple iPhone 13 128GB Black','specs':{'Встроенная память':'256 GB','Оперативная память':'4 GB'}}
    assert compare_specs(p,offer)[2]==['память']
    offer['specs']['Встроенная память']='128 GB'
    assert not compare_specs(p,offer)[1:][0]
    assert not compare_specs(p,offer)[2]
    assert not matches_value('8 ГБ','128 GB')
    assert matches_value('16 ГБ','16384 MB')
    assert matches_value('RTX 4050 6 ГБ','NVIDIA GeForce RTX 4050 6GB')
    assert matches_value('12 + 12 МП','12 МП + 12 МП')
    assert not matches_value('12 + 12 МП','12 МП')


def test_missing_and_conflicting_specs_are_never_confirmed():
    p={'model':'WF-1000XM5','brand':'Sony','category':'наушники','specs':{'цвет':'Черный','связь':'Bluetooth'}}
    _,missing,conflict=compare_specs(p,{'name':'Sony WF-1000XM5 Black','specs':{'цвет':'Серебристый'}})
    assert missing==['связь'] and conflict==['цвет']


@pytest.mark.asyncio
async def test_robots_denial_prevents_product_request(tmp_path,monkeypatch):
    from mcp_server import price_http
    monkeypatch.setattr(price_http,'CACHE',tmp_path)
    calls=[]
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200,text='User-agent: *\nDisallow: /product/')
    async with PublicHTTP() as reader:
        await reader.client.aclose()
        reader.client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with pytest.raises(SourceError,match='robots'):
            await reader.get('https://www.kns.ru/product/test/')
    assert calls==['https://www.kns.ru/robots.txt']


@pytest.mark.asyncio
async def test_cache_and_forbidden_host(tmp_path,monkeypatch):
    from mcp_server import price_http
    monkeypatch.setattr(price_http,'CACHE',tmp_path)
    calls=[]
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200,text='User-agent: *\nAllow: /' if request.url.path=='/robots.txt' else 'card')
    async with PublicHTTP() as reader:
        await reader.client.aclose()
        reader.client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        first=await reader.get('https://www.kns.ru/product/test/')
        assert (await reader.get('https://www.kns.ru/product/test/'))==first
        with pytest.raises(SourceError): await reader.get('https://evil.example/test')
    assert len(calls)==2


@pytest.mark.asyncio
async def test_one_shop_failure_preserves_other_offer(tmp_path,monkeypatch):
    import json
    from mcp_server import competitors
    path=tmp_path/'sources.json'
    path.write_text(json.dumps({'sources':[{'type':'kns'},{'type':'nix'}]}),encoding='utf-8')
    monkeypatch.setattr(competitors,'CONFIG',path)
    async def fetch(source,product,matcher):
        if source.name=='НИКС':
            raise httpx.ConnectError('offline')
        return {'offers':[{'shop':'KNS','price_rub':100,'unknown':[]}], 'shop':'KNS', 'status':'ok', 'reason':'ok'}
    monkeypatch.setattr(competitors,'fetch_shop',fetch)
    result=await competitors.compare({})
    assert len(result['offers'])==1 and result['offers'][0]['shop']=='KNS'
    assert len(result['errors'])==1 and 'НИКС' in result['errors'][0]
