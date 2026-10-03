import base64
import json
import mimetypes
import re
import secrets
import shutil
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from .core import inspect, edit, read_archive
from .config import tool_path

ROOT=Path(__file__).resolve().parent.parent
STORE=ROOT/'.runtime'
STORE.mkdir(exist_ok=True)
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()
SESSIONS={}
MAX_BODY=340*1024**2

def available(name):
    try: tool_path(name); return True
    except (ValueError, OSError): return False

class Handler(BaseHTTPRequestHandler):
    def send(self,status,data,ctype='application/json',extra=None):
        if isinstance(data,dict): data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def trusted(self):
        host=self.headers.get('Host','')
        return host in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
    def do_GET(self):
        if not self.trusted(): return self.send(403,{'error':'Hostが許可されていません。'})
        try:
            route=self.path.split('?')[0]
            if route=='/api/config': return self.send(200,{'app':'monogatari-checker','root':str(ROOT),'token':TOKEN,'ffmpeg':available('ffmpeg'),'ffprobe':available('ffprobe')})
            match=re.fullmatch(r'/api/books/([a-f0-9]{32})/(audio|cover|download)',route)
            if match:
                sid,kind=match.groups()
                session=SESSIONS.get(sid)
                if not session: return self.send(404,{'error':'検査セッションがありません。'})
                if kind=='download':
                    if not session['report']['valid']: return self.send(409,{'error':'検査エラーを修正してください。'})
                    return self.send(200,session['path'].read_bytes(),'application/epub+zip',{'Content-Disposition':'attachment; filename="checked.epub"'})
                media=session['report'].get('media')
                if not media: return self.send(409,{'error':'音声の安全な再生を確認できません。検査結果を確認してください。'})
                p=media['audioPath' if kind=='audio' else 'coverPath']
                if not p: return self.send(404,{'error':'表紙がありません。'})
                cache=session['path'].parent/('audio.mp3' if kind=='audio' else 'cover.bin')
                if not cache.exists(): cache.write_bytes(read_archive(session['path'])[p])
                length=cache.stat().st_size; headers={'Accept-Ranges':'bytes'}; status=200
                start=0; end=length-1
                rng=self.headers.get('Range')
                if rng:
                    m=re.fullmatch(r'bytes=(\d+)-(\d*)',rng)
                    if not m: return self.send(416,b'', 'application/octet-stream',{'Content-Range':f'bytes */{length}'})
                    start=int(m[1]); end=min(int(m[2]) if m[2] else length-1,length-1)
                    if start>end: return self.send(416,b'','application/octet-stream',{'Content-Range':f'bytes */{length}'})
                    headers['Content-Range']=f'bytes {start}-{end}/{length}'; status=206
                with cache.open('rb') as media:
                    head=media.read(8)
                    self.send_response(status)
                    self.send_header('Content-Type','audio/mpeg' if kind=='audio' else ('image/png' if head.startswith(b'\x89PNG') else 'image/jpeg'))
                    self.send_header('Content-Length',str(end-start+1))
                    self.send_header('Cache-Control','no-store')
                    self.send_header('X-Content-Type-Options','nosniff')
                    for k,v in headers.items(): self.send_header(k,v)
                    self.end_headers(); media.seek(start);remaining=end-start+1
                    while remaining:
                        chunk=media.read(min(65536,remaining)); self.wfile.write(chunk);remaining-=len(chunk)
                return
            p=ROOT/'static'/('index.html' if route=='/' else route.lstrip('/'))
            if not p.resolve().is_relative_to((ROOT/'static').resolve()) or not p.is_file(): return self.send(404,{'error':'見つかりません。'})
            return self.send(200,p.read_bytes(),mimetypes.guess_type(p)[0] or 'application/octet-stream')
        except Exception as exc: self.send(400,{'error':str(exc)})
    def do_POST(self):
        if not self.trusted() or self.headers.get('X-Checker-Token')!=TOKEN: return self.send(403,{'error':'許可されていないリクエストです。'})
        if self.path=='/api/shutdown':
            if not LOCK.acquire(blocking=False): return self.send(409,{'error':'検査中です。完了後に停止してください。'})
            self.send(200,{'stopped':True})
            threading.Thread(target=self.server.shutdown,daemon=True).start()
            return
        if not LOCK.acquire(blocking=False): return self.send(429,{'error':'別の検査を実行しています。完了後に再試行してください。'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_BODY: return self.send(413,{'error':'ファイル容量の上限を超えています。'})
            sid=secrets.token_hex(16); folder=STORE/sid; folder.mkdir()
            path=folder/'book.epub'
            if self.path=='/api/inspect':
                remaining=size
                with path.open('wb') as f:
                    while remaining:
                        chunk=self.rfile.read(min(1024**2,remaining))
                        if not chunk: raise ValueError('アップロードが中断されました。')
                        f.write(chunk); remaining-=len(chunk)
                required=self.headers.get('X-Require-Cover')=='true'
            elif self.path=='/api/edit':
                body=json.loads(self.rfile.read(size)); source=SESSIONS.get(body.get('id'))
                if not source: raise ValueError('元の検査結果がありません。')
                required=source['required']
                cover=base64.b64decode(body['cover'],validate=True) if body.get('cover') else None
                if cover and len(cover)>10*1024**2: raise ValueError('表紙は10MB以内にしてください。')
                edit(source['path'],path,body['title'],body.get('creator',''),body.get('description',''),cover,body.get('highlight'),body.get('repairCover') is True)
            else: return self.send(404,{'error':'見つかりません。'})
            report=inspect(path,required)
            SESSIONS[sid]={'path':path,'report':report,'required':required}
            report['id']=sid
            return self.send(200,report)
        except Exception as exc: self.send(400,{'error':str(exc)})
        finally: LOCK.release()

def main():
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8095); args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    # Bind before cleanup so a duplicate start cannot delete active sessions.
    for p in STORE.iterdir():
        if p.is_dir() and re.fullmatch('[a-f0-9]{32}',p.name): shutil.rmtree(p)
    print(f'Monogatari Checker: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    finally:
        server.server_close()
        for s in SESSIONS.values(): shutil.rmtree(s['path'].parent,ignore_errors=True)

if __name__=='__main__': main()
