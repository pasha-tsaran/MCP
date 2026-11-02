"""Ground hard search constraints in customer messages, not model guesses."""
import re

CATEGORIES = {'ноутбук':'ноутбуки','macbook':'ноутбуки','телефон':'телефоны','смартфон':'телефоны',
              'iphone':'телефоны','айфон':'телефоны','мобильник':'телефоны','компьютер':'компьютеры','пк':'компьютеры','планшет':'планшеты','ipad':'планшеты',
              'наушник':'наушники','телевизор':'телевизоры','монитор':'мониторы','колонк':'колонки','часы':'умные часы'}
KEYS = {'оперативная память':('оператив','озу','ram'),'память':('памят','накопител','хранилищ'),
        'экран':('экран','диспле','матриц','oled','ips','amoled'),
        'накопитель':('накопител','ssd','hdd','диск'),'процессор':('процессор','intel','ryzen','cpu'),
        'видеокарта':('видеокарт','график','gpu','rtx','radeon'),'цвет':('цвет','чёрн','черн','бел','серебрист'),
        'связь':('bluetooth','wi-fi','связ'),'шумоподавление':('шумоподавлен',)}


def normalized(text):
    text=text.casefold().replace('ё','е')
    for word in ('гигабайт','гигов','гига','гб'): text=text.replace(word,'gb')
    return re.sub(r'[^a-zа-я0-9]','',text)


def detect_category(text):
    lower=text.casefold()
    found=[]
    for stem,category in CATEGORIES.items():
        ending=r'(?:ы|а|ов|у|ом|е)?\b' if stem in {'компьютер','телефон','смартфон','планшет'} else ''
        match=re.search(r'\b'+re.escape(stem)+ending,lower)
        if match: found.append((match.start(),category))
    return min(found,key=lambda item:item[0])[1] if found else None


def update_preferences(session,text):
    category=detect_category(text)
    if category and category!=session.category:
        if not re.search(r'тот же бюджет|те же деньги',text,re.I):
            session.budget_max=None; session.budget_min=0
        session.category=category; session.requirements={}; session.evidence=[]
    session.evidence=(session.evidence+[text])[-12:]
    if re.search(r'бюджет (?:не ограничен|любой|не важен|не знаю)|любой бюджет|не знаю (?:пока )?бюджет|цена не важна|без ограничений по цене',text,re.I):
        session.budget_max=0; session.budget_min=0
    pattern=r'(?P<cue>до|от|бюджет[а-я]*|примерно)\s*[:—-]?\s*(?P<n>\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)\s*(?P<scale>тыс\w*|[кk]\b|млн\b)?'
    found=False
    for match in re.finditer(pattern,text,re.I):
        after=text[match.end():].lstrip()
        if re.match(r'(?:ГБ|GB|ТБ|TB|МБ|MB|Гц|Hz|Вт|МП|дюйм)',after,re.I): continue
        amount=float(match['n'].replace(' ','').replace('\u00a0','').replace(',','.'))
        scale=(match['scale'] or '').casefold()
        amount*=1_000_000 if scale=='млн' else 1000 if scale else 1
        if amount<1000 and not scale and not re.match(r'руб|₽',after,re.I): continue
        if not 0<=amount<=10_000_000_000: continue
        if match['cue'].casefold()=='от': session.budget_min=int(amount)
        else: session.budget_max=int(amount); found=True
    if not found and session.awaiting_budget:
        bare=re.fullmatch(r'\s*(\d+(?:[ \u00a0]\d{3})*)\s*(тыс\w*|[кk]|руб\w*|₽)?[.!]?\s*',text,re.I)
        if not bare: bare=re.search(r'(\d+(?:[ \u00a0]\d{3})*)\s*(тыс\w*|[кk]\b|руб\w*|₽)',text,re.I)
        if bare:
            amount=int(bare[1].replace(' ','').replace('\u00a0',''))
            if (bare[2] or '').casefold().startswith(('тыс','к','k')): amount*=1000
            if 1000<=amount<=10_000_000_000: session.budget_max=amount
    if session.budget_max is not None: session.awaiting_budget=False


def grounded_search_args(session,args):
    evidence=' '.join(session.evidence)
    proof=normalized(evidence)
    aliases={'озу':'оперативная память','ram':'оперативная память','ssd':'накопитель','cpu':'процессор','gpu':'видеокарта','дисплей':'экран'}
    for raw_key,value in (args.get('requirements') or {}).items():
        key=aliases.get(raw_key.casefold(),raw_key.casefold())
        if key not in KEYS: continue
        plain=re.sub(r'^[<>=\s]+','',str(value))
        if not normalized(plain) or normalized(plain) not in proof: continue
        if not any(term in evidence.casefold() for term in KEYS[key]): continue
        if re.match(r'^\s*[<>]',str(value)) and not re.search(r'не (?:меньше|менее|больше|более)|минимум|максимум|[<>]=?',evidence,re.I):
            value=plain
        session.requirements[key]=str(value)
    return {'category':session.category or args.get('category',''), 'query':grounded_query(session,args.get('query','')),
            'max_price_rub':session.budget_max or 0, 'min_price_rub':session.budget_min,
            'requirements':dict(session.requirements),
            'sort':args.get('sort','relevance'), 'allow_alternatives':args.get('allow_alternatives',True),
            'limit':min(int(args.get('limit',5)),5)}


def grounded_query(session,query):
    if not query: return ''
    evidence=' '.join(session.evidence).casefold()
    for word,brand in {'айфон':'iphone','самсунг':'samsung','леново':'lenovo','асус':'asus','сяоми':'xiaomi'}.items():
        evidence=evidence.replace(word,brand)
    return query if normalized(query) in normalized(evidence) else ''
