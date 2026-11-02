"""SQLite catalogue; all money is stored as integer kopecks."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("CRM_DB_PATH", "mcp_server/products.db"))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.create_function('CASEFOLD',1,lambda value:str(value or '').casefold(),deterministic=True)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    return con


# These are illustrative catalogue records, not verified product listings or market prices.
SEED = [
    ("Ноутбук ASUS VivoBook 15", "ноутбуки", "ASUS", "VivoBook 15", 62990, {"процессор":"Intel Core i5-1235U", "оперативная память":"16 ГБ DDR4", "накопитель":"SSD 512 ГБ", "видеокарта":"Intel Iris Xe", "экран":"15.6 IPS 1920x1080"}),
    ("Ноутбук Lenovo IdeaPad Slim 5", "ноутбуки", "Lenovo", "IdeaPad Slim 5", 89990, {"процессор":"AMD Ryzen 7 7730U", "оперативная память":"16 ГБ DDR4", "накопитель":"SSD 1 ТБ", "видеокарта":"AMD Radeon Graphics", "экран":"14 OLED 1920x1200"}),
    ("Ноутбук Acer Nitro 5", "ноутбуки", "Acer", "Nitro 5", 109990, {"процессор":"Intel Core i5-12450H", "оперативная память":"16 ГБ DDR4", "накопитель":"SSD 512 ГБ", "видеокарта":"NVIDIA GeForce RTX 4050 6 ГБ", "экран":"15.6 IPS 1920x1080 144 Гц"}),
    ("Ноутбук Apple MacBook Air M2", "ноутбуки", "Apple", "MacBook Air M2", 119990, {"процессор":"Apple M2", "оперативная память":"8 ГБ unified", "накопитель":"SSD 256 ГБ", "видеокарта":"Apple GPU 8 ядер", "экран":"13.6 IPS 2560x1664"}),
    ("Apple iPhone 13 128 ГБ", "телефоны", "Apple", "iPhone 13 128 GB", 69990, {"память":"128 ГБ", "оперативная память":"4 ГБ", "экран":"6.1 OLED 2532x1170", "процессор":"Apple A15 Bionic", "камеры":"12 + 12 МП"}),
    ("Samsung Galaxy S23 256 ГБ", "телефоны", "Samsung", "Galaxy S23 256 GB", 64990, {"память":"256 ГБ", "оперативная память":"8 ГБ", "экран":"6.1 AMOLED 2340x1080", "процессор":"Snapdragon 8 Gen 2", "камеры":"50 + 12 + 10 МП"}),
    ("Xiaomi Redmi Note 13 256 ГБ", "телефоны", "Xiaomi", "Redmi Note 13 256 GB", 22990, {"память":"256 ГБ", "оперативная память":"8 ГБ", "экран":"6.67 AMOLED 2400x1080", "процессор":"Snapdragon 685", "аккумулятор":"5000 мАч"}),
    ("ПК игровой Ryzen 5 RTX 4060", "компьютеры", "CRM Demo", "Gaming R5 4060", 99990, {"процессор":"AMD Ryzen 5 5600", "оперативная память":"32 ГБ DDR4", "накопитель":"SSD 1 ТБ", "видеокарта":"NVIDIA GeForce RTX 4060 8 ГБ", "материнская плата":"B550", "блок питания":"650 Вт", "корпус":"Mid Tower"}),
    ("ПК офисный Core i5", "компьютеры", "CRM Demo", "Office i5", 49990, {"процессор":"Intel Core i5-12400", "оперативная память":"16 ГБ DDR4", "накопитель":"SSD 512 ГБ", "видеокарта":"Intel UHD Graphics 730", "материнская плата":"B660", "блок питания":"450 Вт", "корпус":"Mini Tower"}),
    ("Планшет Apple iPad 10 64 ГБ", "планшеты", "Apple", "iPad 10 64 GB", 42990, {"память":"64 ГБ", "оперативная память":"4 ГБ", "экран":"10.9 IPS 2360x1640", "процессор":"Apple A14 Bionic", "связь":"Wi-Fi"}),
    ("Планшет Samsung Galaxy Tab S9 FE", "планшеты", "Samsung", "Galaxy Tab S9 FE", 44990, {"память":"128 ГБ", "оперативная память":"6 ГБ", "экран":"10.9 IPS 2304x1440", "процессор":"Exynos 1380", "связь":"Wi-Fi"}),
    ("Часы Apple Watch SE 40 мм", "умные часы", "Apple", "Watch SE 40mm", 24990, {"экран":"OLED 40 мм", "связь":"Bluetooth Wi-Fi", "датчики":"пульс, акселерометр", "защита":"5 ATM"}),
    ("Часы Samsung Galaxy Watch6 40 мм", "умные часы", "Samsung", "Galaxy Watch6 40mm", 19990, {"экран":"1.3 AMOLED", "связь":"Bluetooth Wi-Fi", "датчики":"пульс, SpO2", "защита":"5 ATM"}),
    ("Колонка JBL Charge 5", "колонки", "JBL", "Charge 5", 17990, {"мощность":"40 Вт", "связь":"Bluetooth", "защита":"IP67", "аккумулятор":"7500 мАч"}),
    ("Телевизор LG OLED C3 55", "телевизоры", "LG", "OLED55C3", 129990, {"экран":"55 OLED 3840x2160", "частота":"120 Гц", "система":"webOS", "порты":"HDMI USB"}),
    ("Монитор Samsung Odyssey G5 27", "мониторы", "Samsung", "Odyssey G5 27", 28990, {"экран":"27 VA 2560x1440", "частота":"144 Гц", "порты":"HDMI DisplayPort"}),
    ("Наушники Sony WH-1000XM5", "наушники", "Sony", "WH-1000XM5", 34990, {"тип":"накладные беспроводные", "связь":"Bluetooth", "шумоподавление":"активное", "автономность":"до 30 часов"}),
    ("Наушники Sony WF-1000XM5 Black", "наушники", "Sony", "WF-1000XM5", 24990, {"связь":"Bluetooth", "цвет":"Черный"}),
]


def initialize():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
          brand TEXT NOT NULL, model TEXT NOT NULL, price_kopecks INTEGER NOT NULL CHECK(price_kopecks >= 0),
          specs TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 1, is_demo INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, actor INTEGER NOT NULL,
          action TEXT NOT NULL, product_id INTEGER, details TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        if not con.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            con.executemany("INSERT INTO products(name,category,brand,model,price_kopecks,specs,is_demo) VALUES(?,?,?,?,?,?,1)",
                [(n,c,b,m,p*100,json.dumps(s,ensure_ascii=False)) for n,c,b,m,p,s in SEED])
            con.execute("INSERT INTO settings VALUES('seeded','1')")


def claim_admin(user_id: int) -> bool:
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('admin_id',?)", (str(user_id),))
        return con.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone()[0] == str(user_id)


def is_admin(user_id: int) -> bool:
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone()
        return bool(row and row[0] == str(user_id))


def require_admin(con, actor):
    row = con.execute("SELECT value FROM settings WHERE key='admin_id'").fetchone()
    if not row or row[0] != str(actor):
        raise PermissionError("Недостаточно прав администратора")


def product(row):
    if not row: return None
    result = dict(row)
    result['specs'] = json.loads(result['specs'])
    return result


def get_product(product_id):
    with connect() as con:
        return product(con.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())


def list_products(category='', query='', limit=30, offset=0):
    limit = min(max(int(limit),1),50)
    with connect() as con:
        clauses = ["available=1"]
        args = []
        if category:
            clauses.append("CASEFOLD(category)=CASEFOLD(?)"); args.append(category)
        where = ' AND '.join(clauses)
        if query.strip():
            # SQLite's built-in LOWER does not handle Cyrillic; Python casefold does.
            rows = con.execute('SELECT * FROM products WHERE '+where+' ORDER BY id', args).fetchall()
            terms = query.casefold().split()[:8]
            items = [product(r) for r in rows]
            items = [p for p in items if all(t in json.dumps(p,ensure_ascii=False).casefold() for t in terms)]
            offset=max(0,int(offset))
            return {'items':items[offset:offset+limit], 'total':len(items), 'offset':offset}
        total = con.execute('SELECT COUNT(*) FROM products WHERE '+where, args).fetchone()[0]
        rows = con.execute('SELECT * FROM products WHERE '+where+' ORDER BY id LIMIT ? OFFSET ?', args+[limit,max(0,int(offset))]).fetchall()
        return {'items':[product(r) for r in rows], 'total':total, 'offset':offset}


def categories():
    with connect() as con:
        return [r[0] for r in con.execute('SELECT DISTINCT CASEFOLD(category) AS category FROM products WHERE available=1 ORDER BY category')]


def catalogue_overview():
    with connect() as con:
        rows=con.execute('SELECT CASEFOLD(category) AS category,COUNT(*) AS count,MIN(price_kopecks) AS min_price_kopecks,MAX(price_kopecks) AS max_price_kopecks FROM products WHERE available=1 GROUP BY CASEFOLD(category) ORDER BY category').fetchall()
        categories=[{'name':r['category'],'count':r['count'],'min_price_kopecks':r['min_price_kopecks'],'max_price_kopecks':r['max_price_kopecks']} for r in rows]
        return {'total':sum(c['count'] for c in categories),'categories':categories}


def save_product(actor, data, product_id=None):
    required = ('name','category','brand','model','price_kopecks','specs')
    if any(k not in data for k in required): raise ValueError('Не заполнены обязательные поля')
    if any(not isinstance(data[k],str) or not data[k].strip() or len(data[k])>200 for k in required[:4]):
        raise ValueError('Название, категория, бренд и модель должны быть непустыми строками до 200 символов')
    if isinstance(data['price_kopecks'], bool) or not isinstance(data['price_kopecks'],int) or not 0 <= data['price_kopecks'] <= 10**12:
        raise ValueError('Некорректная цена')
    specs = data['specs']
    if not isinstance(specs,dict) or len(specs)>50 or any(not isinstance(k,str) or not isinstance(v,str) or not k.strip() or len(k)>100 or len(v)>500 for k,v in specs.items()):
        raise ValueError('Характеристики должны быть словарём строк')
    values = [data[k].strip() for k in required[:4]]+[data['price_kopecks'],json.dumps(specs,ensure_ascii=False)]
    values[1]=values[1].casefold()
    with connect() as con:
        require_admin(con,actor)
        if product_id:
            if not con.execute('SELECT 1 FROM products WHERE id=?',(product_id,)).fetchone(): raise ValueError('Товар не найден')
            con.execute('UPDATE products SET name=?,category=?,brand=?,model=?,price_kopecks=?,specs=?,is_demo=0 WHERE id=?',values+[product_id])
            action='update'
        else:
            product_id=con.execute('INSERT INTO products(name,category,brand,model,price_kopecks,specs) VALUES(?,?,?,?,?,?)',values).lastrowid
            action='add'
        con.execute('INSERT INTO audit(actor,action,product_id,details) VALUES(?,?,?,?)',(actor,action,product_id,json.dumps(data,ensure_ascii=False)))
    return get_product(product_id)


def delete_product(actor, product_id):
    with connect() as con:
        require_admin(con,actor)
        old=con.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
        if not old: raise ValueError('Товар не найден')
        con.execute('DELETE FROM products WHERE id=?',(product_id,))
        con.execute('INSERT INTO audit(actor,action,product_id,details) VALUES(?,?,?,?)',(actor,'delete',product_id,json.dumps(dict(old),ensure_ascii=False)))
    return True
