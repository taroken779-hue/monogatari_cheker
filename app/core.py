"""Completed EPUB inspection and lossless metadata editing."""
import hashlib
import io
import json
import math
import posixpath
import re
import array
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from .validator import validate_monogatari_epub, safe_path, resolve, clock_ms, get_ffmpeg_path

DC = 'http://purl.org/dc/elements/1.1/'
OPF = 'http://www.idpf.org/2007/opf'
XHTML = 'http://www.w3.org/1999/xhtml'

def detect_test_tone(audio_bytes, duration_ms):
    """Flag repeated near-pure tones; this does not establish speech correctness."""
    peaks=[]
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'audio.mp3';path.write_bytes(audio_bytes)
        duration=duration_ms/1000
        for start in [0,max(0,duration*.33),max(0,duration*.66),max(0,duration-.6)]:
            raw=subprocess.run([get_ffmpeg_path(),'-v','error','-ss',str(start),'-i',str(path),'-t','0.5','-ar','16000','-ac','1','-f','f32le','pipe:1'],capture_output=True,timeout=15,check=True).stdout
            x=array.array('f');x.frombytes(raw)
            energy=sum(v*v for v in x)
            if len(x)<1600 or energy/len(x)<1e-7: continue
            crossings=sum(x[i]<=0<x[i+1] for i in range(len(x)-1))
            guess=crossings*16000/len(x)
            if not 80<guess<4000: continue
            best=(0,0)
            frequencies=[220,440,880,1000]+[guess+step*.5 for step in range(-8,9)]
            for freq in frequencies:
                coeff=2*math.cos(2*math.pi*freq/16000);a=b=0.0
                for v in x: a,b=v+coeff*a-b,a
                power=a*a+b*b-coeff*a*b; ratio=2*power/(len(x)*energy)
                if ratio>best[1]: best=(freq,ratio)
            if best[1]>=.65: peaks.append(best)
    if len(peaks)>=3 and max(p[0] for p in peaks)-min(p[0] for p in peaks)<5:
        return round(sum(p[0] for p in peaks)/len(peaks))
    return None

def read_archive(path):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 2000 or sum(i.file_size for i in infos) > 250 * 1024**2:
            raise ValueError('EPUBの展開上限を超えています。分冊してください。')
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError('ZIPに重複したファイル名があります。')
        for i in infos:
            if not safe_path(i.filename) or i.flag_bits & 1:
                raise ValueError('危険なパスまたは暗号化されたZIPです。')
            if Path(i.filename).suffix.lower() in {'.xml','.opf','.xhtml','.smil','.json'} and i.file_size > 10 * 1024**2:
                raise ValueError('構造ファイルが10MiBを超えています。')
        files = {i.filename: z.read(i) for i in infos if not i.is_dir()}
    # External entities are never resolved; entity expansion is rejected.
    for name, data in files.items():
        if Path(name).suffix.lower() in {'.xml','.opf','.xhtml','.smil'} and b'<!ENTITY' in data.upper():
            raise ValueError(f'XMLのENTITY宣言には対応していません: {name}')
    return files

def package(files):
    container = ET.fromstring(files['META-INF/container.xml'])
    opath = next(n.get('full-path') for n in container.iter() if n.tag.split('}')[-1] == 'rootfile')
    opf = ET.fromstring(files[opath])
    items = {n.get('id'): (resolve(posixpath.dirname(opath), n.get('href','')), n) for n in opf.findall(f'.//{{{OPF}}}item')}
    rpath = next(p for p, _ in items.values() if p.endswith('monogatari/reader.json'))
    return opath, opf, items, rpath, json.loads(files[rpath])

def inspect(path, require_cover=False):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {'sha256': digest, 'issues': [], 'book': None, 'preview': None, 'media': None}
    def issue(severity, message, fix, target=''):
        result['issues'].append(dict(severity=severity,message=message,fix=fix,target=target))
    try:
        files = read_archive(path)
        validation = validate_monogatari_epub(path, expected_cover=require_cover)
        result['validation'] = validation
        for text in validation['errors']:
            issue('error', text, 'Studio / Studio Cloudで該当箇所を確認し、EPUBを再生成してください。')
        for text in validation['warnings']:
            issue('warning', text, '「ハイライトCSSを追加・修復」を選択して保存してください。' if 'ハイライト' in text else '該当区間を試聴して、意図した間か確認してください。')
        opath, opf, items, rpath, reader = package(files)
        result['book'] = {k:reader.get(k,'') for k in ['bookId','title','creator','description','language','durationMs']}
        audio_path=resolve(posixpath.dirname(rpath),reader.get('audio',''))
        audio_item=next((n for p,n in items.values() if p==audio_path),None)
        if validation['checks'].get('audioDecode') and audio_path in files and audio_item is not None and audio_item.get('media-type')=='audio/mpeg':
            result['media']={'audioPath':audio_path,'coverPath':None,'durationMs':validation.get('audioDurationMs',0)}
            tone=detect_test_tone(files[audio_path],validation.get('audioDurationMs',0))
            if tone:
                issue('error',f'朗読ではなくテスト音の可能性があります。複数箇所で約{tone}Hzの単一音を検出しました。','音声を試聴し、Studio / Studio Cloudで実際の朗読音声からEPUBを再生成してください。CSSや表紙の修復では音声は変わりません。',audio_path)
        if result['media'] is not None and reader.get('cover'):
            candidate=resolve(posixpath.dirname(rpath),reader['cover'])
            if validation['checks'].get('cover') and candidate in files: result['media']['coverPath']=candidate
        for key in ['bookId','title','language','audio']:
            if not isinstance(reader.get(key),str) or not reader[key].strip():
                issue('error',f'reader.jsonの{key}が空または文字列ではありません。','書誌情報を修正、またはStudioで再生成してください。',rpath)
        for key in ['creator','description','genre']:
            if key in reader and not isinstance(reader[key],str):
                issue('error',f'{key}の型が不正です。','文字列として設定してください。',rpath)
        if type(reader.get('profileVersion')) is not int:
            issue('error','profileVersionは整数1が必要です。','Studioで再生成してください。',rpath)
        if type(reader.get('durationMs')) not in (int,float) or not math.isfinite(reader['durationMs']) or reader['durationMs'] <= 0:
            issue('error','durationMsが不正です。','同期情報を再生成してください。',rpath)
        for field, tag in [('title','title'),('creator','creator'),('description','description')]:
            value = opf.findtext(f'.//{{{DC}}}{tag}',default='')
            if value != reader.get(field,''):
                issue('warning',f'OPFとreader.jsonの{field}が一致しません。','書誌情報編集から両方を揃えて保存してください。',opath)
        if len(reader.get('description','')) > 300:
            issue('warning','あらすじが推奨の300文字を超えています。','作品詳細で読みやすい長さに調整してください。',rpath)
        cover = resolve(posixpath.dirname(rpath),reader['cover']) if reader.get('cover') else None
        if not cover:
            issue('error' if require_cover else 'warning','表紙がありません。','書誌情報編集でPNG/JPEGの表紙を追加してください。',rpath)
        integrity = json.loads(files['EPUB/monogatari/integrity.json'])
        if integrity.get('algorithm') != 'SHA-256':
            issue('error','integrityのalgorithmがSHA-256ではありません。','元の生成物を確認し、再生成してください。')
        expected = {p for p in files if p.startswith(posixpath.dirname(opath)+'/') and p != 'EPUB/monogatari/integrity.json'}
        missing = expected - set(integrity.get('files',{}))
        if missing:
            issue('error',f'ハッシュ一覧の列挙漏れ: {", ".join(sorted(missing))}','元の生成物を確認し、再生成してください。')
        for p,n in items.values():
            if p not in files:
                issue('error',f'manifestの参照先がありません: {p}','Studioで欠落ファイルを含めて再生成してください。',p)
        navs=[p for p,n in items.values() if 'nav' in n.get('properties','').split()]
        if len(navs)!=1:
            issue('error','目次navが1件宣言されていません。','Studioで目次を含めて再生成してください。',opath)
        else:
            nav=ET.fromstring(files[navs[0]])
            for anchor in nav.iter(f'{{{XHTML}}}a'):
                href=anchor.get('href','')
                target,_,fragment=href.partition('#')
                target=resolve(posixpath.dirname(navs[0]),target)
                if target not in files:
                    issue('error',f'目次リンクが存在しません: {href}','目次を再生成してください。',navs[0])
                elif fragment and not any(n.get('id')==fragment for n in ET.fromstring(files[target]).iter()):
                    issue('error',f'目次リンクのIDが存在しません: {href}','目次を再生成してください。',navs[0])
        texts = {}
        chapters = []
        for ref in opf.findall(f'.//{{{OPF}}}spine/{{{OPF}}}itemref'):
            p,n = items[ref.get('idref')]
            doc = ET.fromstring(files[p])
            ids = []
            for node in doc.iter():
                sid = node.get('id','')
                if sid.startswith('s-'):
                    texts[sid] = ''.join(node.itertext()).strip()
                    ids.append(sid)
            if ids:
                chapters.append({'path':p,'title':doc.findtext(f'.//{{{XHTML}}}h1',default=f'章 {len(chapters)+1}'),'sentenceIds':ids})
                overlay=items.get(n.get('media-overlay'))
                if overlay:
                    for refnode in ET.fromstring(files[overlay[0]]).iter():
                        if refnode.tag.split('}')[-1]=='text':
                            dest=resolve(posixpath.dirname(overlay[0]),refnode.get('src','').split('#')[0])
                            if dest!=p: issue('error',f'media-overlayと本文ファイルの対応が違います: {p}','章とSMILの対応を再生成してください。',overlay[0])
        if cover:
            cover_pages=[]
            for ref in opf.findall(f'.//{{{OPF}}}spine/{{{OPF}}}itemref'):
                p,n=items[ref.get('idref')]
                if n.get('media-type')=='application/xhtml+xml':
                    doc=ET.fromstring(files[p])
                    if any(resolve(posixpath.dirname(p),img.get('src',''))==cover for img in doc.iter(f'{{{XHTML}}}img')): cover_pages.append(p)
            if not cover_pages: issue('error','表紙画像を表示するspine内のXHTMLがありません。','「表紙ページを追加・修復」を選択して保存してください。',opath)
        timed = {}
        for p,n in items.values():
            if n.get('media-type') != 'application/smil+xml': continue
            for par in ET.fromstring(files[p]).iter():
                if par.tag.split('}')[-1] != 'par': continue
                text = next(x for x in par if x.tag.split('}')[-1]=='text')
                audio = next(x for x in par if x.tag.split('}')[-1]=='audio')
                sid = text.get('src').split('#')[1]
                timed[sid] = {'id':sid,'text':texts.get(sid,''),'startMs':clock_ms(audio.get('clipBegin')),'endMs':clock_ms(audio.get('clipEnd'))}
        pages = []
        page_names = set()
        for page in reader['pages']:
            if not page.get('sentenceIds') or page.get('id') in page_names:
                issue('error','ページが空、またはページIDが重複しています。','ページ情報を再生成してください。',rpath)
            page_names.add(page.get('id'))
            pages.append({'id':page['id'],'sentences':[timed[s] for s in page['sentenceIds']]})
        spine_ids = [s for c in chapters for s in c['sentenceIds']]
        if spine_ids != [s for p in reader['pages'] for s in p['sentenceIds']]:
            issue('error','spineの本文順とページの文順が一致しません。','章・ページ・同期を同じ順序で再生成してください。',opath)
        result['book'] = {k:reader.get(k,'') for k in ['bookId','title','creator','description','language','durationMs']}
        result['book']['cover'] = bool(cover and cover in files)
        result['preview'] = {'pages':pages,'chapters':chapters,'audioPath':resolve(posixpath.dirname(rpath),reader['audio']),'coverPath':cover}
    except Exception as exc:
        issue('error',f'EPUBを解析できません: {exc}','EPUBを再生成してください。ZIP・XML・JSONの構造を確認してください。')
    result['valid'] = not any(i['severity']=='error' for i in result['issues'])
    # Do not present broken references as a working synchronized preview.
    if not result['valid']: result['preview'] = None
    return result

def add_highlight(files, opath, opf, items, settings):
    if not isinstance(settings,dict): raise ValueError('ハイライト設定が不正です。')
    background=settings.get('background','#ffe600'); foreground=settings.get('foreground','#111111')
    if not all(isinstance(c,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',c) for c in (background,foreground)):
        raise ValueError('ハイライト色は#RRGGBB形式で指定してください。')
    metadata=opf.find(f'{{{OPF}}}metadata'); manifest=opf.find(f'{{{OPF}}}manifest')
    if metadata is None or manifest is None: raise ValueError('OPFのmetadataまたはmanifestがありません。')
    active_class='monogatari-checker-active'
    for meta in list(metadata):
        if meta.get('property')=='media:active-class': metadata.remove(meta)
    ET.SubElement(metadata,f'{{{OPF}}}meta',{'property':'media:active-class'}).text=active_class
    marker=b'/* Monogatari Checker highlight */'
    existing=next(((p,n) for p,n in items.values() if n.get('media-type')=='text/css' and files.get(p,b'').startswith(marker)),None)
    if existing:
        csspath=existing[0]
    else:
        csspath=resolve(posixpath.dirname(opath),'styles/checker-highlight.css')
        suffix=1
        while csspath in files or any(p==csspath for p,n in items.values()):
            csspath=resolve(posixpath.dirname(opath),f'styles/checker-highlight-{suffix}.css');suffix+=1
        cid='checker-highlight'
        while cid in items: cid+='-new'
        ET.SubElement(manifest,f'{{{OPF}}}item',{'id':cid,'href':posixpath.relpath(csspath,posixpath.dirname(opath)),'media-type':'text/css'})
    files[csspath]=(marker.decode()+'\n.'+active_class+' {\n  background-color: '+background.lower()+' !important;\n  color: '+foreground.lower()+' !important;\n}\n').encode()
    for path,item in items.values():
        if item.get('media-type')!='application/xhtml+xml': continue
        doc=ET.fromstring(files[path])
        if not any(n.get('id','').startswith('s-') for n in doc.iter()): continue
        head=doc.find(f'{{{XHTML}}}head')
        if head is None:
            head=ET.Element(f'{{{XHTML}}}head');doc.insert(0,head)
        for link in list(head):
            if link.tag==f'{{{XHTML}}}link' and 'stylesheet' in link.get('rel','').split() and resolve(posixpath.dirname(path),link.get('href',''))==csspath:
                head.remove(link)
        ET.SubElement(head,f'{{{XHTML}}}link',{'rel':'stylesheet','type':'text/css','href':posixpath.relpath(csspath,posixpath.dirname(path))})
        files[path]=ET.tostring(doc,encoding='utf-8',xml_declaration=True)

def ensure_cover_page(files, opath, opf, reader, rpath):
    manifest=opf.find(f'{{{OPF}}}manifest'); spine=opf.find(f'{{{OPF}}}spine')
    if manifest is None or spine is None: raise ValueError('表紙ページ生成にはmanifestとspineが必要です。')
    items={n.get('id'):(resolve(posixpath.dirname(opath),n.get('href','')),n) for n in manifest}
    covers=[(p,n) for p,n in items.values() if 'cover-image' in n.get('properties','').split()]
    if len(covers)>1: raise ValueError('表紙画像が複数あります。表紙画像の宣言を1件にしてください。')
    if covers:
        cpath,citem=covers[0]
    elif reader.get('cover'):
        cpath=resolve(posixpath.dirname(rpath),reader['cover'])
        citem=next((n for p,n in items.values() if p==cpath),None)
        if citem is None:
            cid='checker-cover'
            while cid in items: cid+='-new'
            citem=ET.SubElement(manifest,f'{{{OPF}}}item',{'id':cid,'href':posixpath.relpath(cpath,posixpath.dirname(opath))})
        citem.set('properties',' '.join(dict.fromkeys(citem.get('properties','').split()+['cover-image'])))
    else: raise ValueError('表紙画像がありません。PNG/JPEGの表紙を追加してください。')
    if cpath not in files: raise ValueError('表紙画像の実ファイルがありません。表紙を追加してください。')
    from PIL import Image
    with Image.open(io.BytesIO(files[cpath])) as image:
        fmt=image.format; image.verify()
    if fmt not in ('PNG','JPEG'): raise ValueError('表紙画像はPNG/JPEGが必要です。')
    citem.set('media-type','image/png' if fmt=='PNG' else 'image/jpeg')
    reader['cover']=posixpath.relpath(cpath,posixpath.dirname(rpath))
    candidates=[]
    for path,item in items.values():
        if item.get('media-type')!='application/xhtml+xml': continue
        if path not in files:
            if posixpath.basename(path) in ('cover.xhtml','checker-cover.xhtml') and not item.get('media-overlay'): candidates.append((path,item))
            continue
        doc=ET.fromstring(files[path])
        if any(n.get('id','').startswith('s-') for n in doc.iter()): continue
        body=doc.find(f'{{{XHTML}}}body')
        marked=body is not None and 'cover' in body.get('{http://www.idpf.org/2007/ops}type','').split()
        matches=any(resolve(posixpath.dirname(path),img.get('src',''))==cpath for img in doc.iter(f'{{{XHTML}}}img'))
        if marked or matches: candidates.append((path,item))
    if len(candidates)>1: raise ValueError('表紙ページ候補が複数あります。重複した表紙ページをStudioで整理してください。')
    if candidates: pagepath,pitem=candidates[0]
    else:
        pagepath=resolve(posixpath.dirname(opath),'text/checker-cover.xhtml');suffix=1
        while pagepath in files or any(p==pagepath for p,n in items.values()):
            pagepath=resolve(posixpath.dirname(opath),f'text/checker-cover-{suffix}.xhtml');suffix+=1
        pid='checker-cover-page'
        while pid in items or pid==citem.get('id'): pid+='-new'
        pitem=ET.SubElement(manifest,f'{{{OPF}}}item',{'id':pid,'href':posixpath.relpath(pagepath,posixpath.dirname(opath)),'media-type':'application/xhtml+xml'})
    doc=ET.Element(f'{{{XHTML}}}html');head=ET.SubElement(doc,f'{{{XHTML}}}head')
    ET.SubElement(head,f'{{{XHTML}}}title').text='表紙'
    ET.SubElement(head,f'{{{XHTML}}}style').text='body { margin: 0; text-align: center; } img { max-width: 100%; max-height: 95vh; object-fit: contain; }'
    body=ET.SubElement(doc,f'{{{XHTML}}}body',{'{http://www.idpf.org/2007/ops}type':'cover'})
    ET.SubElement(body,f'{{{XHTML}}}img',{'src':posixpath.relpath(cpath,posixpath.dirname(pagepath)),'alt':'表紙'})
    files[pagepath]=ET.tostring(doc,encoding='utf-8',xml_declaration=True)
    pitem.attrib.pop('media-overlay',None)
    for ref in list(spine):
        if ref.get('idref')==pitem.get('id'): spine.remove(ref)
    spine.insert(0,ET.Element(f'{{{OPF}}}itemref',{'idref':pitem.get('id')}))

def edit(source, output, title, creator, description, cover=None, highlight=None, repair_cover=False):
    if not title.strip(): raise ValueError('タイトルを入力してください。')
    if len(title)>500 or len(creator)>500 or len(description)>10000: raise ValueError('書誌情報が長すぎます。')
    files = read_archive(source)
    opath, opf, items, rpath, reader = package(files)
    old_title = reader.get('title','')
    for key,value in [('title',title),('creator',creator),('description',description)]:
        reader[key] = value
        node = opf.find(f'.//{{{DC}}}{key}')
        if node is None: node = ET.SubElement(opf.find(f'{{{OPF}}}metadata'),f'{{{DC}}}{key}')
        node.text = value
    # Only replace metadata/title nodes; synchronized text and MP3 remain untouched.
    for p,n in items.values():
        if n.get('media-type') != 'application/xhtml+xml': continue
        if p not in files and repair_cover and posixpath.basename(p) in ('cover.xhtml','checker-cover.xhtml') and not n.get('media-overlay'): continue
        doc = ET.fromstring(files[p]); changed = False
        for node in doc.iter():
            if title != old_title and node.tag == f'{{{XHTML}}}title' and node.text == old_title:
                node.text = title; changed = True
        if changed: files[p] = ET.tostring(doc,encoding='utf-8',xml_declaration=True)
    if cover:
        from PIL import Image
        with Image.open(io.BytesIO(cover)) as image:
            fmt = image.format; w,h = image.size
            if fmt not in ('PNG','JPEG') or not (64<=w<=10000 and 64<=h<=10000): raise ValueError('表紙は64〜10000pxのPNG/JPEGにしてください。')
            image.verify()
        ext,mime = ('png','image/png') if fmt=='PNG' else ('jpg','image/jpeg')
        manifest = opf.find(f'{{{OPF}}}manifest'); spine = opf.find(f'{{{OPF}}}spine')
        cpath = resolve(posixpath.dirname(opath),f'images/checker-cover.{ext}')
        existing = next((n for p,n in items.values() if 'cover-image' in n.get('properties','').split()),None)
        if existing is not None:
            cpath = items[existing.get('id')][0]
            existing.set('media-type',mime)
        else:
            used=set(items)
            cid='checker-cover'
            while cid in used: cid+='-new'
            ET.SubElement(manifest,f'{{{OPF}}}item',{'id':cid,'href':posixpath.relpath(cpath,posixpath.dirname(opath)),'media-type':mime,'properties':'cover-image'})
        files[cpath]=cover
        reader['cover']=posixpath.relpath(cpath,posixpath.dirname(rpath))
    if highlight is not None:
        add_highlight(files,opath,opf,items,highlight)
    if repair_cover or cover:
        ensure_cover_page(files,opath,opf,reader,rpath)
    from datetime import datetime, timezone
    modified=opf.find(f'.//{{{OPF}}}meta[@property="dcterms:modified"]')
    if modified is None: modified=ET.SubElement(opf.find(f'{{{OPF}}}metadata'),f'{{{OPF}}}meta',{'property':'dcterms:modified'})
    modified.text=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    files[opath]=ET.tostring(opf,encoding='utf-8',xml_declaration=True)
    files[rpath]=json.dumps(reader,ensure_ascii=False,indent=2).encode()
    ipath='EPUB/monogatari/integrity.json'
    files[ipath]=json.dumps({'algorithm':'SHA-256','files':{p:hashlib.sha256(b).hexdigest() for p,b in files.items() if p.startswith(posixpath.dirname(opath)+'/') and p!=ipath}},indent=2).encode()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype',b'application/epub+zip',compress_type=zipfile.ZIP_STORED)
        for p,b in files.items():
            if p!='mimetype': z.writestr(p,b)
