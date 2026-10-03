import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from app.core import inspect, edit, read_archive
from app.config import tool_path

class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        audio=self.root/'voice.mp3'
        subprocess.run([tool_path('ffmpeg'),'-v','error','-f','lavfi','-i','anoisesrc=color=pink:amplitude=0.1:duration=2','-y',str(audio)],check=True)
        self.files={
          'META-INF/container.xml':b'<container><rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles></container>',
          'EPUB/package.opf':b'''<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0"><metadata><dc:title>Test</dc:title><dc:creator>Author</dc:creator><dc:description>Summary</dc:description></metadata><manifest><item id="text" href="text/ch.xhtml" media-type="application/xhtml+xml" media-overlay="smil"/><item id="smil" href="overlays/ch.smil" media-type="application/smil+xml"/><item id="audio" href="audio/narration.mp3" media-type="audio/mpeg"/><item id="reader" href="monogatari/reader.json" media-type="application/json"/><item id="integrity" href="monogatari/integrity.json" media-type="application/json"/></manifest><spine><itemref idref="text"/></spine></package>''',
          'EPUB/text/ch.xhtml':b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Test</title></head><body><span id="s-0001">Hello.</span><span id="s-0002">World.</span></body></html>',
          'EPUB/overlays/ch.smil':b'<smil><body><seq><par><text src="../text/ch.xhtml#s-0001"/><audio src="../audio/narration.mp3" clipBegin="0s" clipEnd="1s"/></par><par><text src="../text/ch.xhtml#s-0002"/><audio src="../audio/narration.mp3" clipBegin="1s" clipEnd="2s"/></par></seq></body></smil>',
          'EPUB/audio/narration.mp3':audio.read_bytes(),
          'EPUB/monogatari/reader.json':json.dumps({'profile':'monogatari-audio-epub','profileVersion':1,'bookId':'test','title':'Test','creator':'Author','description':'Summary','language':'ja','audio':'../audio/narration.mp3','durationMs':2000,'pages':[{'id':'page-1','sentenceIds':['s-0001','s-0002'],'startMs':0,'endMs':2000}]}).encode()}
        self.path=self.root/'test.epub';self.write()
    def tearDown(self): self.tmp.cleanup()
    def write(self):
        if 'EPUB/nav.xhtml' not in self.files:
            self.files['EPUB/nav.xhtml']=b'<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><a href="text/ch.xhtml#s-0001">Start</a></nav></body></html>'
            self.files['EPUB/package.opf']=self.files['EPUB/package.opf'].replace(b'</manifest>',b'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>')
        self.files['EPUB/monogatari/integrity.json']=json.dumps({'algorithm':'SHA-256','files':{p:hashlib.sha256(b).hexdigest() for p,b in self.files.items() if p.startswith('EPUB/') and not p.endswith('integrity.json')}}).encode()
        with zipfile.ZipFile(self.path,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('mimetype',b'application/epub+zip',compress_type=zipfile.ZIP_STORED)
            for p,b in self.files.items(): z.writestr(p,b)
    def test_valid_optional_cover_and_css(self):
        r=inspect(self.path);self.assertTrue(r['valid'],r['issues']);self.assertEqual(len(r['preview']['pages'][0]['sentences']),2)
        self.assertFalse(inspect(self.path,True)['valid'])
    def test_wrong_reference(self):
        self.files['EPUB/overlays/ch.smil']=self.files['EPUB/overlays/ch.smil'].replace(b'../text/ch.xhtml',b'../text/missing.xhtml');self.write()
        r=inspect(self.path);self.assertFalse(r['valid']);self.assertIsNone(r['preview'])
    def test_metadata_and_cover_preserve_audio_smil(self):
        from PIL import Image
        import io
        b=io.BytesIO();Image.new('RGB',(128,192),'green').save(b,format='PNG')
        out=self.root/'edited.epub';edit(self.path,out,'New title','New author','New summary',b.getvalue())
        r=inspect(out,True);self.assertTrue(r['valid'],r['issues']);self.assertEqual(r['book']['title'],'New title')
        files=read_archive(out)
        for p in ['EPUB/audio/narration.mp3','EPUB/overlays/ch.smil']:self.assertEqual(files[p],self.files[p])
    def test_hash_tampering(self):
        with zipfile.ZipFile(self.path,'a') as z:z.writestr('EPUB/extra.txt',b'unlisted')
        self.assertFalse(inspect(self.path)['valid'])
    def test_zip_traversal(self):
        with zipfile.ZipFile(self.path,'a') as z:z.writestr('../escape',b'bad')
        self.assertFalse(inspect(self.path)['valid'])
    def test_page_order(self):
        r=json.loads(self.files['EPUB/monogatari/reader.json']);r['pages'][0]['sentenceIds'].reverse();self.files['EPUB/monogatari/reader.json']=json.dumps(r).encode();self.write()
        self.assertFalse(inspect(self.path)['valid'])
    def test_highlight_generation_and_repeat_repair(self):
        from xml.etree import ElementTree as ET
        from app.core import package,OPF,XHTML
        out=self.root/'highlight.epub'
        edit(self.path,out,'Test','Author','Summary',highlight={'background':'#ABCDEF','foreground':'#112233'})
        report=inspect(out);self.assertTrue(report['valid'],report['issues']);self.assertTrue(report['validation']['checks']['activeHighlight'])
        files=read_archive(out)
        for p in ['EPUB/audio/narration.mp3','EPUB/overlays/ch.smil']:
            self.assertEqual(files[p],self.files[p])
        self.assertEqual(files['EPUB/nav.xhtml'],self.files['EPUB/nav.xhtml'])
        before=ET.fromstring(self.files['EPUB/text/ch.xhtml']);after=ET.fromstring(files['EPUB/text/ch.xhtml'])
        self.assertEqual(ET.tostring(before.find(f'{{{XHTML}}}body')),ET.tostring(after.find(f'{{{XHTML}}}body')))
        self.assertIn(b'#abcdef',files['EPUB/styles/checker-highlight.css'])
        second=self.root/'second.epub'
        edit(out,second,'Test','Author','Summary',highlight={'background':'#ffe600','foreground':'#111111'})
        repeat=read_archive(second);_,opf,items,_,_=package(repeat)
        self.assertEqual(len(opf.findall(f'.//{{{OPF}}}meta[@property="media:active-class"]')),1)
        self.assertEqual(len([p for p in repeat if 'checker-highlight' in p]),1)
        doc=ET.fromstring(repeat['EPUB/text/ch.xhtml'])
        self.assertEqual(len(doc.findall(f'.//{{{XHTML}}}link')),1)
        self.assertTrue(inspect(second)['validation']['checks']['activeHighlight'])
    def test_highlight_preserves_existing_css_and_avoids_collision(self):
        self.files['EPUB/styles/checker-highlight.css']=b'body { font-size: 2em; }'
        self.write();out=self.root/'collision.epub'
        edit(self.path,out,'Test','Author','Summary',highlight={})
        files=read_archive(out)
        self.assertEqual(files['EPUB/styles/checker-highlight.css'],self.files['EPUB/styles/checker-highlight.css'])
        self.assertIn('EPUB/styles/checker-highlight-1.css',files)
        self.assertTrue(inspect(out)['validation']['checks']['activeHighlight'])
    def test_invalid_highlight_color_rejected(self):
        for settings in [{'background':'red; } body {display:none'},False,{'foreground':'#fff'}]:
            with self.assertRaises(ValueError):
                edit(self.path,self.root/'bad.epub','Test','Author','Summary',highlight=settings)
    def cover_without_page(self, missing_document=False):
        from PIL import Image
        import io
        b=io.BytesIO();Image.new('RGB',(128,192),'blue').save(b,format='PNG')
        self.files['EPUB/images/cover.png']=b.getvalue()
        item=b'<item id="cover-image" href="images/cover.png" media-type="image/png" properties="cover-image"/>'
        if missing_document:
            item+=b'<item id="cover-page" href="text/cover.xhtml" media-type="application/xhtml+xml"/>'
            self.files['EPUB/package.opf']=self.files['EPUB/package.opf'].replace(b'<spine>',b'<spine><itemref idref="cover-page"/>')
        self.files['EPUB/package.opf']=self.files['EPUB/package.opf'].replace(b'</manifest>',item+b'</manifest>')
        r=json.loads(self.files['EPUB/monogatari/reader.json']);r['cover']='../images/cover.png';self.files['EPUB/monogatari/reader.json']=json.dumps(r).encode();self.write()
    def test_existing_cover_page_repair_and_repeat(self):
        from app.core import package, OPF
        self.cover_without_page();self.assertFalse(inspect(self.path)['valid'])
        out=self.root/'repaired.epub';edit(self.path,out,'Test','Author','Summary',repair_cover=True)
        report=inspect(out,True);self.assertTrue(report['valid'],report['issues'])
        files=read_archive(out)
        for p in ['EPUB/images/cover.png','EPUB/audio/narration.mp3','EPUB/overlays/ch.smil','EPUB/text/ch.xhtml']:
            self.assertEqual(files[p],self.files[p])
        second=self.root/'repeat.epub';edit(out,second,'Test','Author','Summary',repair_cover=True)
        f=read_archive(second);_,opf,items,_,_=package(f)
        refs=opf.findall(f'.//{{{OPF}}}spine/{{{OPF}}}itemref')
        self.assertEqual(len(refs),2);self.assertEqual(refs[0].get('idref'),'checker-cover-page')
        self.assertEqual(len([p for p in f if p.endswith('checker-cover.xhtml')]),1)
        self.assertTrue(inspect(second,True)['valid'])
    def test_missing_declared_cover_document(self):
        self.cover_without_page(True)
        out=self.root/'restored.epub';edit(self.path,out,'Test','Author','Summary',repair_cover=True)
        self.assertTrue(inspect(out,True)['valid'])
        self.assertIn('EPUB/text/cover.xhtml',read_archive(out))
    def test_repair_cover_requires_image(self):
        with self.assertRaisesRegex(ValueError,'表紙画像がありません'):
            edit(self.path,self.root/'no-cover.epub','Test','Author','Summary',repair_cover=True)
    def test_audio_available_before_cover_repair(self):
        self.cover_without_page()
        r=inspect(self.path,True)
        self.assertFalse(r['valid']);self.assertIsNone(r['preview'])
        self.assertEqual(r['media']['audioPath'],'EPUB/audio/narration.mp3')
    def test_broken_audio_cannot_be_played(self):
        self.files['EPUB/audio/narration.mp3']=b'broken audio';self.write()
        r=inspect(self.path)
        self.assertFalse(r['valid']);self.assertIsNone(r['media'])
    def test_test_tone_is_not_valid_narration(self):
        tone=self.root/'tone.mp3'
        subprocess.run([tool_path('ffmpeg'),'-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-y',str(tone)],check=True)
        self.files['EPUB/audio/narration.mp3']=tone.read_bytes();self.write()
        r=inspect(self.path)
        self.assertFalse(r['valid']);self.assertTrue(r['media']);self.assertIsNone(r['preview'])
        self.assertTrue(any('テスト音' in i['message'] for i in r['issues']))

if __name__=='__main__':unittest.main()
