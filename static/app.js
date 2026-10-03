import {renderAutoScrolledPageText} from './g2DisplayShared.js';
const $=id=>document.getElementById(id);let config,report,flat=[],timeline,active=-1,pendingSeek=null,animation=null;
const names={container:'EPUB構造',cover:'表紙',integrity:'SHA-256',timeline:'文と同期',audioDecode:'音声デコード',durationMatch:'音声終端',activeHighlight:'ハイライトCSS'};
const time=ms=>`${Math.floor(ms/60000)}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}`;
function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n}
async function request(url,body,headers={}){const r=await fetch(url,{method:'POST',headers:{'X-Checker-Token':config.token,...headers},body});const data=await r.json();if(!r.ok)throw Error(data.error);return data}
function operationStatus(text,state){
 for(const id of ['status','edit-status','operation-notice']){const el=$(id);el.textContent=text;el.dataset.state=state;}
 $('operation-notice').hidden=false;
 $('operation-notice').setAttribute('aria-busy',String(state==='running'));
}
async function busy(action,editing=false){
 if($('inspect').disabled)return;
 const started=performance.now();const label=editing?'修正・再検査':'検査';
 $('inspect').disabled=$('save').disabled=true;
 $('inspect').textContent=editing?'検査を開始':'検査中…';$('save').textContent=editing?'修正・再検査中…':'修正して再検査';
 const progress=()=>operationStatus(`${label}中… EPUBの構造・表紙・同期・音声を確認しています。（${Math.floor((performance.now()-started)/1000)}秒経過）`,'running');
 progress();const timer=setInterval(progress,1000);
 try{
  const data=await action();show(data);
  const seconds=((performance.now()-started)/1000).toFixed(1);
  operationStatus(`${label}が完了しました（${seconds}秒）。${data.valid?(data.issues.length?'警告があります。検査結果をご確認ください。':'すべての検査に合格しました。'):'修正が必要な項目があります。検査結果をご確認ください。'}`,'complete');
 }catch(e){operationStatus(`${label}を完了できませんでした: ${e.message}`,'error');}
 finally{clearInterval(timer);$('inspect').disabled=false;$('save').disabled=!report?.book;$('inspect').textContent='検査を開始';$('save').textContent='修正して再検査';}
}

function show(data){$('audio').pause();$('audio').removeAttribute('src');$('audio').load();report=data;active=-1;flat=[];$('result').hidden=false;$('verdict').textContent=data.valid?(data.issues.length?'合格・警告あり':'合格'):'修正が必要';$('hash').textContent=`対象EPUB SHA-256: ${data.sha256}`;$('summary').textContent=data.book?`${data.book.title} · ${data.validation?.sentences??0}文 · ${data.validation?.pages??0}ページ · ${time(data.book.durationMs)}`:'構造を読み取れませんでした。';$('checks').replaceChildren();for(const [key,value] of Object.entries(data.validation?.checks??{}))$('checks').append(node('span',`${names[key]??key}: ${value?'確認済み':'未確認 / 不備'}`,'check'));
 $('issues').replaceChildren();for(const issue of data.issues){const box=node('div','',`issue ${issue.severity}`);box.append(node('strong',`${issue.severity==='error'?'エラー':'警告'} · ${issue.message}`),node('p',issue.fix));if(issue.target)box.append(node('small',issue.target));$('issues').append(box)}
 for(const key of ['title','creator','description'])$(key).value=data.book?.[key]??'';$('count').textContent=`${$('description').value.length}文字 / 推奨300文字以内`;$('newcover').value='';$('save').disabled=!data.book;$('download').hidden=!data.valid;$('download').href=`/api/books/${data.id}/download`;$('cover').hidden=!data.media?.coverPath;if(data.media?.coverPath)$('cover').src=`/api/books/${data.id}/cover`;
 pendingSeek=null;cancelAnimationFrame(animation);$('player').hidden=false;for(const id of ['play','pause','stop','speed','volume','mute'])$(id).disabled=!data.media;$('audio').hidden=!data.media;$('audio-direct').hidden=!data.media;$('audio-direct').href=`/api/books/${data.id}/audio`;$('playback-note').textContent=data.media?(data.preview?'EPUBに収録された朗読音声を再生できます。':'同期プレビューは検査エラーのため停止しています。収録音声のみ試聴できます。検査合格を意味しません。'):'音声を再生できません。音声ファイルの欠落・破損や検査エラーを確認してください。';$('audio-status').textContent=data.media?'音声を読み込んでいます…':'再生不可';if(data.media){$('audio').src=`/api/books/${data.id}/audio`;$('audio').playbackRate=Number($('speed').value);}$('preview').hidden=!data.preview;if(!data.preview)return;timeline={pages:data.preview.pages};$('page').replaceChildren();$('chapter').replaceChildren();$('sentences').replaceChildren();timeline.pages.forEach((p,pi)=>{$('page').append(new Option(`ページ ${pi+1}`,pi));p.sentences.forEach((s,si)=>{const index=flat.length;flat.push({...s,pageIndex:pi,sentenceIndex:si});const b=node('button',`${time(s.startMs)} · ${s.text}`,'sentence');b.onclick=()=>seek(index);b.dataset.index=index;$('sentences').append(b)})});data.preview.chapters.forEach((c,i)=>$('chapter').append(new Option(c.title,i)));seek(0);
}
function seek(i){const s=flat[Math.max(0,Math.min(i,flat.length-1))];if(!s)return;if($('audio').readyState===0)pendingSeek=s.startMs/1000;else $('audio').currentTime=s.startMs/1000;update(s.startMs)}
function update(ms=$('audio').currentTime*1000){if(!flat.length)return;let i=flat.findIndex(s=>ms>=s.startMs&&ms<s.endMs);const gap=i<0;if(i<0){i=flat.findIndex(s=>s.startMs>ms);if(i<0)i=flat.length-1}const s=flat[i];if(active!==i||Boolean($('sentences').children[i]?.classList.contains('active'))===gap){$('sentences').querySelector('.active')?.classList.remove('active');const b=$('sentences').children[i];if(!gap)b.classList.add('active');const list=$('sentences');if(b.offsetTop<list.scrollTop+list.offsetTop||b.offsetTop+b.offsetHeight>list.scrollTop+list.offsetTop+list.clientHeight)list.scrollTop=b.offsetTop-list.offsetTop;active=i}$('page').value=s.pageIndex;$('g2').textContent=gap?'（音声の間）':renderAutoScrolledPageText(timeline,{...s,sentence:s},108,ms);$('position').textContent=`${time(ms)} / ${time(report.book.durationMs)} · ページ ${s.pageIndex+1}${gap?' · 区間外':''}`;$('timeline').textContent=`${s.id} · ${s.startMs}〜${s.endMs} ms · ${s.endMs-s.startMs} ms`}
$('inspect').onclick=()=>{const f=$('file').files[0];if(!f){$('status').textContent='EPUBファイルを選択してください。';return}busy(()=>request('/api/inspect',f,{'Content-Type':'application/epub+zip','X-Require-Cover':String($('required').checked)}))};
$('save').onclick=()=>busy(async()=>{const f=$('newcover').files[0];let cover;if(f){if(f.size>10*1024**2)throw Error('表紙は10MB以内にしてください。');cover=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(f)})}return request('/api/edit',JSON.stringify({id:report.id,title:$('title').value,creator:$('creator').value,description:$('description').value,cover,repairCover:$('repair-cover').checked,highlight:$('highlight').checked?{background:$('highlight-bg').value,foreground:$('highlight-fg').value}:undefined}),{'Content-Type':'application/json'})},true);
$('description').oninput=()=>$('count').textContent=`${$('description').value.length}文字 / 推奨300文字以内`;$('audio').ontimeupdate=()=>update();$('speed').onchange=()=>$('audio').playbackRate=Number($('speed').value);$('page').onchange=()=>seek(flat.findIndex(s=>s.pageIndex===Number($('page').value)));$('chapter').onchange=()=>seek(flat.findIndex(s=>s.id===report.preview.chapters[Number($('chapter').value)].sentenceIds[0]));$('prev').onclick=()=>seek(active-1);$('next').onclick=()=>seek(active+1);$('middle').onclick=()=>seek(Math.floor(flat.length/2));$('last').onclick=()=>seek(flat.length-1);
$('report').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=node('a','');a.href=url;a.download='monogatari-check-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
fetch('/api/config').then(r=>r.json()).then(c=>config=c).catch(()=>$('status').textContent='検査サーバーに接続できません。');

function highlightSample(){
 const bg=$('highlight-bg').value,fg=$('highlight-fg').value;
 $('highlight-sample').style.backgroundColor=bg;$('highlight-sample').style.color=fg;
 const luminance=hex=>{const rgb=hex.match(/[a-f0-9]{2}/gi).map(x=>parseInt(x,16)/255).map(x=>x<=0.04045?x/12.92:((x+0.055)/1.055)**2.4);return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722};
 const a=luminance(bg),b=luminance(fg),ratio=(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
 $('contrast').textContent=`明暗差 ${ratio.toFixed(1)}:1${ratio<4.5?' · 文字が読みづらくなる場合があります。色を調整してください。':''}`;
}
$('highlight-bg').oninput=$('highlight-fg').oninput=highlightSample;highlightSample();

function audioStatus(){const a=$('audio');if(a.error)return;$('audio-status').textContent=`${a.ended?'再生終了':a.paused?'一時停止 / 再生待ち':'再生中'} · ${time(a.currentTime*1000)} / ${time((Number.isFinite(a.duration)?a.duration:0)*1000)}`;}
$('audio').onloadedmetadata=()=>{if(pendingSeek!==null){$('audio').currentTime=pendingSeek;pendingSeek=null;}audioStatus();};
$('audio').ontimeupdate=()=>{update();audioStatus();};
$('audio').onerror=()=>{$('audio-status').textContent='音声を読み込めません。サーバーが再起動された場合はEPUBを再検査してください。';};
$('audio').onplay=()=>{const tick=()=>{update();if(!$('audio').paused)animation=requestAnimationFrame(tick);};cancelAnimationFrame(animation);animation=requestAnimationFrame(tick);audioStatus();};
$('audio').onpause=()=>{cancelAnimationFrame(animation);audioStatus();};$('audio').onended=()=>{cancelAnimationFrame(animation);audioStatus();};
$('play').onclick=async()=>{try{await $('audio').play();}catch(e){$('audio-status').textContent=`再生できません: ${e.message}`;}};
$('pause').onclick=()=>$('audio').pause();$('stop').onclick=()=>{$('audio').pause();if($('audio').readyState) $('audio').currentTime=0;pendingSeek=0;update(0);audioStatus();};

function volumeStatus(){const a=$('audio');$('volume').value=Math.round(a.volume*100);$('volume-value').textContent=`${Math.round(a.volume*100)}%`;$('mute').textContent=a.muted?'ミュート解除':'ミュート';}
$('volume').oninput=()=>{const a=$('audio');a.volume=Number($('volume').value)/100;if(a.volume>0)a.muted=false;volumeStatus();};
$('mute').onclick=()=>{$('audio').muted=!$('audio').muted;volumeStatus();};$('audio').onvolumechange=volumeStatus;volumeStatus();
$('audio').onwaiting=()=>{$('audio-status').textContent='音声をバッファリング中…';};
$('audio').onstalled=()=>{$('audio-status').textContent='音声の受信を待っています。続く場合は「音声単体を開く」で確認してください。';};
