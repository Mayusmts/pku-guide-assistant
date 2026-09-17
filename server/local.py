# -*- coding: utf-8 -*-
"""ローカルで質問応答を試す一体型サーバ（Python 標準ライブラリのみ）。

ページと代理を同じサーバから出す。これで三つが一度に片付く。

  * API キーがブラウザに出ない（このプロセスだけが持つ）
  * 同一生成元なので CORS も Artifact の CSP も関係ない
  * Node を入れなくても動く

使い方（Windows PowerShell）:

    $env:DASHSCOPE_API_KEY  = "sk-..."
    $env:DASHSCOPE_BASE_URL = "https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    python server/local.py

    → http://127.0.0.1:8787/ を開く

キーは環境変数から読むだけで、どこにも書き出さない。誰かに渡す前提の
サーバではないので、待ち受けは 127.0.0.1 に固定してある（社内やLANに
出したい場合だけ --host を変える）。

本番（みんなに使わせる）では server/index.mjs をアリババクラウド関数計算に
置く。指示文 rules.txt と資料 docs.json は両方で同じものを使う。
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, 'app')

MAX_DOC_CHARS = 12000
MAX_QUESTION = 400
MAX_IDS = 20
MAX_BODY = 65536

PROFILE_FIELDS = {
    'visa': ('ビザ', {
        'X1': 'X1（180日以上・2学期以上）',
        'X2': 'X2（180日未満・1学期）',
    }),
    'housing': ('住まい', {
        'dorm': '大学の留学生寮', 'rent': '学外の賃貸物件',
        'hotel': 'ホテル', 'family': '親戚・友人知人宅',
    }),
    'program': ('プログラム', {
        'gogaku': '語学進修生（対外漢語）', 'shinshu': 'その他の進修生',
        'exchange': '交換留学', 'honka': '本科（学部）',
        'grad': '大学院（修士・博士）', 'yoka': '予科',
    }),
}


def load(name):
    with io.open(os.path.join(HERE, name), encoding='utf-8') as f:
        return f.read()


DOCS = json.loads(load('docs.json'))
RULES = load('rules.txt').strip()

API_KEY = os.environ.get('DASHSCOPE_API_KEY', '')
BASE_URL = os.environ.get('DASHSCOPE_BASE_URL', '').rstrip('/')
MODEL = os.environ.get('MODEL', 'qwen3.7-plus')


def profile_text(p):
    out = []
    for key, (label, table) in PROFILE_FIELDS.items():
        v = p.get(key) if isinstance(p, dict) else None
        out.append('- %s: %s' % (label, table.get(v, 'まだ分からない（未選択）')))
    return '\n'.join(out)


def build_prompt(question, profile, ids):
    """資料は id から引く。画面側は本文を送れないので差し替えられない。"""
    picked, chars, dropped = [], 0, 0
    for i in ids:
        d = DOCS.get(i)
        if not d:
            continue
        head = d['label'] + ('（資料の更新日 %s）' % d['updated'] if d.get('updated') else '')
        piece = head + '\n' + d['body']
        if chars + len(piece) > MAX_DOC_CHARS and picked:
            dropped += 1
            continue
        chars += len(piece)
        picked.append('[S%d] %s' % (len(picked) + 1, piece))
    note = '\n（分量の都合で %d 件は省略しています）' % dropped if dropped else ''
    return '%s\n\n# 利用者の条件\n%s\n\n# 資料\n%s%s\n\n# 質問\n%s' % (
        RULES, profile_text(profile), '\n\n'.join(picked), note, question)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'yanyuan-nav-local'

    def log_message(self, fmt, *args):
        sys.stderr.write('  %s\n' % (fmt % args))

    # ---- 返し方 ----
    def _json(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _drain(self, n=None):
        """残っている本体を捨てる。読み残したまま応答すると、
        keep-alive の接続が壊れて相手側では接続リセットになる。"""
        if n is None:
            n = int(self.headers.get('Content-Length') or 0)
        left = min(n, 1 << 20)
        while left > 0:
            got = self.rfile.read(min(left, 65536))
            if not got:
                break
            left -= len(got)

    def _file(self, path, ctype, transform=None):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError:
            self._json(404, {'error': 'not_found'})
            return
        if transform:
            raw = transform(raw.decode('utf-8')).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    # ---- GET: ページと画像 ----
    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            # 生成物は AI_ENDPOINT が空。ここで同一生成元の /ask を差し込む。
            self._file(
                os.path.join(APP, 'index.html'), 'text/html; charset=utf-8',
                lambda s: s.replace('var AI_ENDPOINT = "";',
                                    'var AI_ENDPOINT = "/ask";', 1))
            return
        if path == '/health':
            self._json(200, {
                'ok': True, 'docs': len(DOCS), 'model': MODEL,
                'configured': bool(API_KEY and BASE_URL),
            })
            return
        m = re.match(r'^/img/([A-Za-z0-9._-]+)$', path)
        if m:
            self._file(os.path.join(APP, 'img', m.group(1)), 'image/webp')
            return
        self._json(404, {'error': 'not_found'})

    # ---- POST /ask: 資料を添えて模型に投げ、SSE で流し返す ----
    def do_POST(self):
        if self.path.split('?')[0] != '/ask':
            self._drain()
            self._json(404, {'error': 'not_found'})
            return

        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            self._drain(n)
            self.close_connection = True
            self._json(413, {'error': 'too_long'})
            return

        # 先に本体を読み切る。これ以降はどこで返しても接続が壊れない。
        try:
            body = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
        except Exception:
            self._json(400, {'error': 'bad_request'})
            return
        if not isinstance(body, dict):
            self._json(400, {'error': 'bad_request'})
            return

        question = (body.get('question') or '').strip()
        if not question:
            self._json(400, {'error': 'bad_request'})
            return
        if len(question) > MAX_QUESTION:
            self._json(413, {'error': 'too_long'})
            return

        ids = [x for x in (body.get('sectionIds') or [])
               if isinstance(x, str)][:MAX_IDS]
        known = [i for i in ids if i in DOCS]
        if not known:
            self._json(400, {'error': 'no_sections'})
            return

        # 入力の検証が通ってから設定を見る。入力の誤りは設定と無関係に 400。
        if not (API_KEY and BASE_URL):
            self._json(500, {'error': 'unauthorized'})
            return

        prompt = build_prompt(question, body.get('profile') or {}, known)
        history = body.get('history')
        history = history[-6:] if isinstance(history, list) else []
        messages = [
            {'role': m['role'], 'content': m['content'][:2400]}
            for m in history
            if isinstance(m, dict) and m.get('role') in ('user', 'assistant')
            and isinstance(m.get('content'), str)
        ]
        messages.append({'role': 'user', 'content': prompt})
        req = urllib.request.Request(
            BASE_URL + '/chat/completions',
            data=json.dumps({
                'model': MODEL,
                'stream': True,
                'temperature': 0.2,
                'max_tokens': 1200,
                'messages': messages,
            }).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + API_KEY,
            },
            method='POST')

        try:
            up = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', 'replace')[:400]
            except Exception:
                pass
            code = ('rate_limited' if e.code == 429
                    else 'unauthorized' if e.code in (401, 403)
                    else 'upstream')
            # 原因が分からないと直せないので、手元では素の応答も出す
            sys.stderr.write('  上流エラー %s: %s\n' % (e.code, detail))
            self._json(e.code if e.code in (401, 403, 429) else 502, {'error': code})
            return
        except Exception as e:
            sys.stderr.write('  上流に届かない: %r\n' % (e,))
            self._json(502, {'error': 'upstream'})
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-transform')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()

        def chunk(payload):
            """HTTP/1.1 のチャンク形式で一片返す。"""
            data = payload.encode('utf-8')
            self.wfile.write(('%X\r\n' % len(data)).encode('ascii'))
            self.wfile.write(data)
            self.wfile.write(b'\r\n')
            self.wfile.flush()

        try:
            for raw in up:
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if not payload or payload == '[DONE]':
                    continue
                try:
                    j = json.loads(payload)
                except Exception:
                    continue
                try:
                    piece = j['choices'][0]['delta'].get('content')
                except (KeyError, IndexError, TypeError):
                    piece = None
                if piece:
                    chunk('data: %s\n\n' % json.dumps({'delta': piece},
                                                      ensure_ascii=False))
            chunk('data: [DONE]\n\n')
        except Exception as e:
            sys.stderr.write('  途中で切れた: %r\n' % (e,))
            try:
                chunk('data: %s\n\n' % json.dumps({'error': 'upstream'}))
            except Exception:
                pass
        finally:
            try:
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description='燕園手続きナビ ローカルサーバ')
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--host', default='127.0.0.1',
                    help='既定は自分の端末だけ。LAN に出す場合のみ変える')
    args = ap.parse_args()

    if not os.path.exists(os.path.join(APP, 'index.html')):
        raise SystemExit('app/index.html がありません。先に python build_app.py')

    print('資料      : %d 件' % len(DOCS))
    print('模型      : %s' % MODEL)
    if API_KEY and BASE_URL:
        print('接続先    : %s' % BASE_URL)
        print('APIキー   : 設定済み（下4桁 …%s）' % API_KEY[-4:])
    else:
        missing = []
        if not API_KEY:
            missing.append('DASHSCOPE_API_KEY')
        if not BASE_URL:
            missing.append('DASHSCOPE_BASE_URL')
        print('APIキー   : 未設定（%s）' % '、'.join(missing))
        print('            → 検索は使えますが「AI がまとめた答え」は出ません')
    print()
    print('  http://%s:%d/ を開いてください（Ctrl+C で終了）' % (args.host, args.port))
    print()

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
