"""Download public guide bodies and their directly embedded assets. No login."""
import hashlib
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

ROOT = Path('materials/api_export')
ROOT.mkdir(parents=True, exist_ok=True)

def fetch(url, path):
    p = subprocess.run(['curl.exe', '-L', '--max-time', '30', '--max-filesize', '30000000', '-sS', '-w', '%{http_code}', url, '-o', str(path)], capture_output=True)
    return p.returncode == 0 and p.stdout.decode().strip() == '200', p.stderr.decode(errors='replace')

records = json.loads(Path('materials/inventory.json').read_text(encoding='utf-8'))
articles, assets = [], {}
for record in records:
    key = record['id']
    path = ROOT / (key + '.json')
    ok, error = fetch('https://note.com/api/v3/notes/' + key, path)
    article = dict(id=key, source=record['url'], status='failed', error=error)
    if ok:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))['data']
            body = data.get('body') or ''
            soup = BeautifulSoup(body, 'html.parser')
            article.update(status='body_saved' if body else 'empty_body', title=data.get('name'), characters=len(soup.get_text()))
            (ROOT/(key+'.html')).write_text(body, encoding='utf-8')
            (ROOT/(key+'.txt')).write_text(soup.get_text('\n',strip=True), encoding='utf-8')
            for node in soup.select('img[src], figure[embedded-service="attachment"] a[href]'):
                kind = 'image' if node.name == 'img' else 'attachment'
                url = node.get('src') or node.get('href')
                if urlparse(url).scheme != 'https':
                    continue
                label = node.get('alt','') if kind == 'image' else node.get_text(' ',strip=True)
                if kind == 'image' and node.parent:
                    caption = node.parent.select_one('figcaption')
                    if caption: label = caption.get_text(' ',strip=True)
                item = assets.setdefault(url,dict(url=url,kind=kind,label=label,articles=[],status='pending',content_status='未读取'))
                item['articles'].append(key)
        except (ValueError, KeyError) as e:
            article['error'] = str(e)
    articles.append(article)
    print(key, article['status'], flush=True)
    time.sleep(0.3)

def save_manifest():
    (ROOT/'manifest.json').write_text(json.dumps(dict(articles=articles,assets=list(assets.values())),ensure_ascii=False,indent=2),encoding='utf-8')

save_manifest()
for url, item in assets.items():
    suffix = Path(urlparse(url).path).suffix.lower()
    if item['kind']=='attachment':
        suffix = next((e for e in ['.pdf','.docx','.doc','.xlsx','.xls'] if e in item['label'].lower()), '.bin')
    if suffix not in ['.png','.jpg','.jpeg','.webp','.gif','.pdf','.docx','.doc','.xlsx','.xls']: suffix='.bin'
    relative = 'assets/' + hashlib.sha256(url.encode()).hexdigest()[:20] + suffix
    path = ROOT / relative
    path.parent.mkdir(exist_ok=True)
    ok, error = fetch(url,path)
    item.update(status='downloaded' if ok else 'failed',path=relative,error=error)
    if ok:
        item['bytes'] = path.stat().st_size
        if suffix=='.pdf' and not path.read_bytes().startswith(b'%PDF'):
            item['status']='invalid_pdf_response'
    save_manifest()
    print(item['kind'],item['status'],relative,flush=True)
    time.sleep(0.2)
print('DONE',len(articles),'articles',len(assets),'assets',flush=True)
