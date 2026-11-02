"""Actual MCP server. The bot launches it locally over stdio."""
import asyncio
import json
from typing import Literal
from mcp.server.fastmcp import FastMCP
from . import db, search, competitors

server=FastMCP('electronics-crm')
db.initialize()


@server.tool()
def claim_admin(user_id:int) -> dict:
    """Register the first private-chat /start user as administrator, atomically."""
    return {'is_admin':db.claim_admin(user_id)}


@server.tool()
def check_admin(user_id:int) -> dict:
    return {'is_admin':db.is_admin(user_id)}


@server.tool()
def categories() -> list[str]:
    """List product categories."""
    return db.categories()


@server.tool()
def catalogue_overview() -> dict:
    """Актуальные категории, количество товаров в наличии и диапазоны цен. Источник фактов о наличии, не зависит от фильтров подбора."""
    return db.catalogue_overview()


@server.tool()
def list_products(category:str='', query:str='', limit:int=10, offset:int=0) -> dict:
    """List catalogue products with pagination. Use exact category or a model substring."""
    return db.list_products(search.category_name(category),query,limit,offset)


@server.tool()
def get_product(product_id:int) -> dict:
    """Read a product card by ID."""
    return db.get_product(product_id) or {'error':'Товар не найден'}


@server.tool()
def search_products(category:str='', query:str='', max_price_rub:int=0, requirements:dict[str,str]|None=None,
                    min_price_rub:int=0, sort:Literal['relevance','price_asc','price_desc']='relevance',
                    allow_alternatives:bool=True, limit:int=5) -> dict:
    """Подобрать технику. requirements: русское имя характеристики → значение, например ОЗУ: >=16 ГБ. query — только модель/бренд. sort=price_asc для более дешёвых вариантов. Точные совпадения приоритетны; альтернативы с отличиями только при отсутствии точных."""
    return search.search(category,query,max_price_rub,requirements,min_price_rub,sort,allow_alternatives,limit)


@server.tool()
def compare_products(product_ids:list[int]) -> dict:
    """Сравнить до трёх товаров нашего каталога по их ID: цены, характеристики, отличия от первого."""
    return search.compare_products(product_ids)


@server.tool()
def similar_products(product_id:int) -> dict:
    """Find products with similar specifications by catalogue product ID."""
    return search.similar(product_id)


@server.tool()
async def compare_competitors(product_id:int) -> dict:
    """Compare current prices from configured feeds for one catalogue product."""
    p=db.get_product(product_id)
    if not p: return {'error':'Товар не найден'}
    return {'product':p, **(await competitors.compare(p))}


@server.tool()
def save_product(user_id:int, data:dict, product_id:int=0) -> dict:
    """Administrator-only: create or update a product with validated fields."""
    return db.save_product(user_id,data,product_id or None)


@server.tool()
def delete_product(user_id:int, product_id:int) -> dict:
    """Administrator-only: delete a product after confirmation in the bot."""
    return {'deleted':db.delete_product(user_id,product_id)}


if __name__ == '__main__':
    server.run(transport='stdio')
