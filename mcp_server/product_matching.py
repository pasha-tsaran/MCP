"""Conservative matching: every requested specification must be confirmed."""
from __future__ import annotations

import re
from collections import Counter
from .shop_sources import model_matches

KEYS = {
    'оперативная память': ('оперативн', 'ram', 'объем памяти', 'тип памяти'),
    'память': ('встроенн', 'емкость накопителя', 'объем накопителя', 'объем встроенной', 'память'),
    'накопитель': ('ssd', 'hdd', 'накопител', 'диск'),
    'процессор': ('процессор', 'cpu'),
    'видеокарта': ('видеокарт', 'графич', 'видеопроцессор', 'видеочип'),
    'экран': ('экран', 'диагональ', 'матриц', 'диспле', 'разрешение'),
    'частота': ('частота обновления', 'частота развертки'),
    'камеры': ('камера', 'камеры'),
    'аккумулятор': ('аккумулятор', 'батаре'),
    'связь': ('связ', 'bluetooth', 'wi-fi', 'беспроводн', 'интерфейс'),
    'цвет': ('цвет',),
    'защита': ('защит', 'водонепроницаем'),
    'тип': ('тип', 'конструкц'),
    'шумоподавление': ('шумоподавлен',),
    'автономность': ('время работы', 'автономн'),
    'мощность': ('мощност',),
    'порты': ('порт', 'интерфейс', 'разъем'),
    'система': ('операционная система', 'платформа'),
}


def canonical(value):
    value = str(value).casefold().replace('ё', 'е').replace('×', 'x').replace('х', 'x')
    for original, replacement in [('терабайт','tb'), ('гигабайт','gb'), ('мегабайт','mb'),
                                  ('тб','tb'), ('гб','gb'), ('мб','mb'), ('гц','hz'),
                                  ('дюйма','inch'), ('дюймов','inch'), ('дюйм','inch')]:
        value = value.replace(original, replacement)
    value = value.replace(',', '.')
    def memory(match):
        amount = float(match[1]); unit = match[2]
        amount = amount * 1024 if unit == 'tb' else amount / 1024 if unit == 'mb' else amount
        return f'{amount:g}gb'
    value = re.sub(r'(\d+(?:\.\d+)?)\s*(tb|gb|mb)\b', memory, value)
    value = re.sub(r'\b(?:гб|gb)\b', 'gb', value)
    # Preserve separation of numeric values: RTX 4050 6GB and 12+12 MP.
    value = re.sub(r'(?<=\d)[^a-zа-я0-9.]+(?=\d)', '|', value)
    return re.sub(r'[^a-zа-я0-9.|]', '', value)


def matches_value(expected, actual):
    # Split the requested compound specification into independently checked tokens.
    expected = re.sub(r'(\d+)\s*[xх×]\s*(\d+)', r'\1 \2', str(expected), flags=re.I)
    expected = re.sub(r'(\d+)\s*\+\s*(\d+)', r'\1 \2', expected)
    # Keep quantities and their units together, so 8 GB cannot match 128 GB.
    expected = re.sub(r'(\d+(?:[.,]\d+)?)\s+(ГБ|ТБ|МБ|GB|TB|MB|Гц|Hz)', r'\1\2', expected, flags=re.I)
    tokens = [canonical(x) for x in re.split(r'[\s+,;/]+', expected) if x]
    haystack = canonical(actual)
    required = Counter(t for t in tokens if t and t not in {'до', 'или', 'и'})
    return all(len(re.findall((r'(?<!\d)' if t[:1].isdigit() else '') + re.escape(t) + (r'(?!\d)' if t[-1:].isdigit() else ''), haystack)) >= count
               for t, count in required.items())


def compare_specs(product, offer):
    if not model_matches(product, offer['name']):
        return [], [], ['Модель или модификация отличается']
    required = dict(product.get('specs', {}))
    # Capacity in a model name is binding even if the administrator omitted specs.
    capacities = re.findall(r'\b(\d+\s*(?:gb|гб|tb|тб))\b', product['model'], flags=re.I)
    if capacities and 'память' not in required and product.get('category') in {'телефоны', 'планшеты'}:
        required['память'] = capacities[-1]
    matched = ['модель']; unknown = []; conflicts = []
    actual_specs = offer.get('specs', {})
    for key, expected in required.items():
        patterns = KEYS.get(key.casefold(), (key.casefold(),))
        selected = []
        for actual_key, actual_value in actual_specs.items():
            lower = actual_key.casefold()
            if key == 'память' and ('оперативн' in lower or 'ram' in lower):
                continue
            if any(pattern in lower for pattern in patterns):
                selected.append(actual_key + ': ' + actual_value)
        if not selected:
            unknown.append(key)
        elif matches_value(expected, ' | '.join(selected)):
            matched.append(key)
        else:
            conflicts.append(key)
    # No same-spec claim is made when the local product has no specifications.
    if not required:
        unknown.append('характеристики исходного товара')
    return matched, unknown, conflicts
