import json, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

root = Path('materials')
index = BeautifulSoup((root/'index.html').read_text(encoding='utf-8'), 'html.parser')
body = index.select_one('.note-common-styles__textnote-body')
links = dict((a['href'], a.get_text(' ', strip=True)) for a in body.select('a[href]'))
def fetch(item):
    url, label = item
    key = url.rsplit('/', 1)[-1]
    path = root / (key + '.html')
    result = subprocess.run(['curl.exe','-L','--max-time','30','-sS',url,'-o',str(path)], capture_output=True)
    record = dict(id=key, url=url, directory_title=label, error=result.stderr.decode(errors='replace'))
    if path.exists():
        soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        article = soup.select_one('.note-common-styles__textnote-body')
        record['title'] = soup.title.get_text() if soup.title else None
        record['text'] = article.get_text('\n',strip=True) if article else ''
        record['links'] = [dict(text=a.get_text(' ',strip=True),url=a.get('href')) for a in article.select('a')] if article else []
        record['metadata'] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try: record['metadata'].append(json.loads(script.string or script.get_text()))
            except ValueError: pass
        (root/(key+'.txt')).write_text(record['text'],encoding='utf-8')
    return record
with ThreadPoolExecutor(max_workers=4) as pool:
    records = list(pool.map(fetch,links.items()))
(root/'inventory.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
for r in records:
    print(r['id'], len(r.get('text','')), r.get('title'), r['error'])
