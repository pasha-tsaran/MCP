"""Resolve explicit references to shown products before asking the model to reply."""
import re


def reference_ids(text,session):
    ids=[]
    for value in re.findall(r'(?:\bID\s*|№\s*)(\d+)',text,re.I):
        ids.append(int(value))
    for word,index in [('перв',0),('втор',1),('трет',2)]:
        if re.search(r'\b'+word+r'\w*',text,re.I) and len(session.recent)>index:
            ids.append(session.recent[index]['id'])
    if not ids:
        for product in session.recent:
            if product['model'].casefold() in text.casefold(): ids.append(product['id'])
    if not ids and re.search(r'\b(?:их|эти|между ними)\b',text,re.I):
        ids=[p['id'] for p in session.recent[:3]]
    deictic=bool(re.search(r'\b(?:эт\w+|его|ее|её|него|нему|ней|нем|нём|выбранн\w*)\b',text,re.I))
    implicit=bool(re.fullmatch(r'(?:а )?(?:сколько стоит|какая цена|сравни (?:цену )?с конкурентами|покажи (?:все )?характеристики|расскажи подробнее|подробнее)[?!. ]*',text,re.I))
    if not ids and (deictic or implicit):
        if session.selected_id: ids=[session.selected_id]
        elif len(session.recent)==1: ids=[session.recent[0]['id']]
    return list(dict.fromkeys(ids))


def reference_action(text,session):
    categories={'ноутбук','ноутбуки','телефон','телефоны','смартфон','смартфоны','компьютер','компьютеры','пк',
                'планшет','планшеты','колонка','колонки','часы','умные часы','телевизор','телевизоры','монитор','мониторы','наушники'}
    if text.strip().casefold() in categories and session.category:
        if session.budget_max is not None:
            return 'search_products',{'category':session.category,'max_price_rub':session.budget_max,
                    'requirements':dict(session.requirements),'limit':3},'recommend'
        return 'list_products',{'category':session.category,'limit':3},'recommend'
    ids=reference_ids(text,session)
    if re.search(r'конкурент|других магазин|другими магазин',text,re.I) and len(ids)==1 and not re.search(r'почему|нормально|всех|некотор',text,re.I):
        return 'compare_competitors',{'product_id':ids[0]},'competitors'
    if re.search(r'сравн',text,re.I) and len(ids)>=2:
        return 'compare_products',{'product_ids':ids[:3]},'compare'
    if re.search(r'подешевле|дешевле',text,re.I) and not re.search(r'почему|чем|за сч[её]т',text,re.I) and session.category and (session.budget_max is not None or session.recent):
        ceiling=session.budget_max if session.budget_max is not None else int(min(p['price_kopecks'] for p in session.recent)/100)
        return 'search_products',{'category':session.category,'max_price_rub':ceiling,
                'min_price_rub':session.budget_min,'requirements':dict(session.requirements),
                'sort':'price_asc','allow_alternatives':True,'limit':1},'recommend'
    if ids and re.search(r'характеристик|подробн|расскажи|какой.{0,10}экран|какая.{0,10}память|сколько.{0,10}памяти',text,re.I):
        return 'get_product',{'product_id':ids[0]},'details'
    if ids and re.search(r'похож|аналог',text,re.I):
        return 'similar_products',{'product_id':ids[0]},'recommend'
    return None
