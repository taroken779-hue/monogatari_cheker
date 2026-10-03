from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

MAX_FILES = 2_000
MAX_EXPANDED = 250 * 1024 * 1024  # 250 MiB


from .config import tool_path

def get_ffmpeg_path() -> str:
    return tool_path('ffmpeg')

def get_ffprobe_path() -> str:
    return tool_path('ffprobe')


def safe_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not value.startswith(('/', '\\'))
        and '\\' not in value
        and ':' not in path.parts[0]
        and '..' not in path.parts
    )


def resolve(base: str, relative: str) -> str:
    result = posixpath.normpath(posixpath.join(base, relative))
    if not safe_path(result):
        raise ValueError(f"危険な参照パス: {relative}")
    return result


def clock_ms(value: str) -> int:
    if value.endswith('s'):
        return round(float(value[:-1]) * 1000)
    parts = value.split(':')
    if len(parts) != 3:
        raise ValueError(f"不正なSMIL時刻: {value}")
    hours, minutes, seconds = map(float, parts)
    return round((hours * 3600 + minutes * 60 + seconds) * 1000)


def validate_monogatari_epub(epub_path: Path, expected_cover: bool = False) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    checks = {
        'container': False,
        'cover': True,  # 表紙がない場合はデフォルトTrue、存在する場合は検証
        'integrity': False,
        'timeline': False,
        'audioDecode': False,
        'durationMatch': False,
        'activeHighlight': False,
    }
    actual_audio_duration_ms = 0
    last_end = 0
    gap_count = 0
    sentence_ids: set[str] = set()
    reader_pages_count = 0
    reader_duration_ms = 0

    try:
        if not epub_path.is_file():
            errors.append(f'指定されたEPUBファイルが存在しません: {epub_path}')
            return {
                'status': 'failed',
                'valid': False,
                'checks': checks,
                'errors': errors,
                'warnings': warnings,
            }

        with zipfile.ZipFile(epub_path, "r") as archive:
            infos = archive.infolist()
            if not infos or infos[0].filename != 'mimetype':
                errors.append('mimetypeがZIPの先頭ではありません。')
            elif infos[0].compress_type != zipfile.ZIP_STORED:
                errors.append('mimetypeが無圧縮(ZIP_STORED)ではありません。')

            if len(infos) > MAX_FILES:
                errors.append(f'ファイル数が上限({MAX_FILES})を超えています: {len(infos)}')

            # 重複ファイル名エントリの検査 (F04)
            raw_filenames = [info.filename for info in infos]
            if len(raw_filenames) != len(set(raw_filenames)):
                errors.append('ZIPアーカイブ内に重複したファイル名エントリが存在します。')

            total_size = sum(info.file_size for info in infos)
            if total_size > MAX_EXPANDED:
                errors.append(f'展開後サイズが上限(250MiB)を超えています: {total_size}')

            # 単一構造ファイルおよび音声ファイルの上限検査 (F04/G06)
            MAX_STRUCTURAL_FILE = 10 * 1024 * 1024  # 構造・テキストファイル 10MiB
            MAX_MEDIA_FILE = MAX_EXPANDED       # 音声・メディアファイル 50MiB
            for info in infos:
                ext = posixpath.splitext(info.filename)[1].lower()
                limit = MAX_MEDIA_FILE if ext in {'.mp3', '.wav', '.m4a', '.ogg', '.png', '.jpg', '.jpeg'} else MAX_STRUCTURAL_FILE
                if info.file_size > limit:
                    errors.append(f'ファイルサイズが上限を超えています: {info.filename} ({info.file_size} > {limit})')
                if not safe_path(info.filename):
                    errors.append(f'危険なZIPパス: {info.filename}')

            if errors:
                checks['container'] = False
                return {
                    'valid': False,
                    'status': 'failed',
                    'checks': checks,
                    'errors': errors,
                    'warnings': warnings,
                }

            names = {info.filename for info in infos}
            if 'mimetype' not in names or archive.read('mimetype') != b'application/epub+zip':
                errors.append('EPUB mimetypeが不正です。')

            checks['container'] = (len(errors) == 0)

            # container.xml から OPF の検索
            if 'META-INF/container.xml' not in names:
                raise ValueError('META-INF/container.xml が存在しません。')

            container = ET.fromstring(archive.read('META-INF/container.xml'))
            rootfile = next((node.attrib.get('full-path') for node in container.iter() if node.tag.endswith('rootfile')), None)
            if not rootfile or rootfile not in names:
                raise ValueError('package.opf が見つからないか、META-INF/container.xml の定義が不正です。')

            opf = ET.fromstring(archive.read(rootfile))
            opf_dir = posixpath.dirname(rootfile)
            active_class = next((node.text.strip() for node in opf.iter()
                if node.attrib.get('property') == 'media:active-class' and node.text), '')

            # マニフェスト抽出
            manifest: dict[str, tuple[str, str]] = {}
            manifest_media_overlays: dict[str, str] = {}
            cover_items: list[tuple[str, str]] = []
            for item in (node for node in opf.iter() if node.tag.endswith('item')):
                item_id = item.attrib.get('id', '')
                href = item.attrib.get('href', '')
                resolved = resolve(opf_dir, href)
                media_type = item.attrib.get('media-type', '')
                manifest[item_id] = (resolved, media_type)
                mo = item.attrib.get('media-overlay')
                if mo:
                    manifest_media_overlays[item_id] = mo
                if 'cover-image' in item.attrib.get('properties', '').split():
                    cover_items.append((resolved, media_type))

            # OPF spine の検証 (G06 empty_spine / no_media_overlay 検知)
            spine = next((node for node in opf.iter() if node.tag.endswith('spine')), None)
            spine_itemrefs = [node for node in spine.iter() if node.tag.endswith('itemref')] if spine is not None else []
            if not spine_itemrefs:
                errors.append('OPFのspineにitemrefが1件も定義されていません (empty_spine)。')
                checks['container'] = False
            else:
                for itemref in spine_itemrefs:
                    idref = itemref.attrib.get('idref', '')
                    if not idref or idref not in manifest:
                        errors.append(f"spine itemref の idref '{idref}' が manifest に存在しません。")
                        checks['container'] = False
                        continue
                    if manifest[idref][1] == 'application/xhtml+xml':
                        # 表紙は朗読しない。画像を表示する実際の表紙documentだけを例外とする。
                        cover_document = False
                        if manifest[idref][0] in names and cover_items:
                            cover_doc = ET.fromstring(archive.read(manifest[idref][0]))
                            body = cover_doc.find('{http://www.w3.org/1999/xhtml}body')
                            images = cover_doc.findall('.//{http://www.w3.org/1999/xhtml}img')
                            cover_document = (body is not None and 'cover' in body.get('{http://www.idpf.org/2007/ops}type', '').split()
                                and len(images) == 1 and resolve(posixpath.dirname(manifest[idref][0]), images[0].get('src', '')) == cover_items[0][0])
                        if cover_document:
                            continue
                        if idref not in manifest_media_overlays:
                            errors.append(f'spineのXHTMLアイテム({idref})にmedia-overlay属性が指定されていません (no_media_overlay)。')
                        else:
                            smil_id = manifest_media_overlays[idref]
                            if smil_id not in manifest or manifest[smil_id][1] != 'application/smil+xml':
                                errors.append(f'XHTMLアイテム({idref})のmedia-overlay({smil_id})が有効なSMILを参照していません。')


            reader_path = next((p for p, _ in manifest.values() if p.endswith('monogatari/reader.json')), None)
            integrity_path = next((p for p, _ in manifest.values() if p.endswith('monogatari/integrity.json')), None)

            if not reader_path or not integrity_path:
                raise ValueError('reader.json または integrity.json がマニフェストにありません。')

            if reader_path not in names or integrity_path not in names:
                raise ValueError('reader.json または integrity.json がZIPアーカイブ内に実在しません。')

            # 表紙の厳格検査 (cover check: 実デコード・サイズ・寸法検査 F04)
            reader = json.loads(archive.read(reader_path).decode('utf-8'))
            reader_cover = reader.get('cover')
            css_paths = [path for path, mime in manifest.values() if mime == 'text/css' and path in names]
            css_text = '\n'.join(archive.read(path).decode('utf-8') for path in css_paths)
            css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.S)
            highlight_rule = re.search(r'\.' + re.escape(active_class) + r'\s*\{[^}]*\b(?:background(?:-color)?|color)\s*:', css_text) if active_class else None
            checks['activeHighlight'] = bool(highlight_rule)
            if not active_class:
                warnings.append('OPFのmedia:active-classがありません（朗読ハイライト設定不足）。')
            elif not highlight_rule:
                warnings.append(f'朗読ハイライト用CSSがありません: .{active_class} の色指定が必要です。')
            if expected_cover and not cover_items:
                errors.append('登録済みの表紙画像がEPUBに収録されていません。')
                checks['cover'] = False
            if len(cover_items) > 1:
                errors.append('表紙画像が複数宣言されています。')
                checks['cover'] = False
            elif cover_items:
                cover_path, cover_type = cover_items[0]
                if cover_path not in names:
                    errors.append(f'表紙画像がEPUB内にありません: {cover_path}')
                    checks['cover'] = False
                elif cover_type not in {'image/png', 'image/jpeg'}:
                    errors.append(f'表紙画像のMIME形式が不正です: {cover_type}')
                    checks['cover'] = False
                elif not reader_cover or resolve(posixpath.dirname(reader_path), reader_cover) != cover_path:
                    errors.append('reader.jsonの表紙参照がmanifestと一致しません。')
                    checks['cover'] = False
                else:
                    cover_bytes = archive.read(cover_path)
                    # 最小バイト数チェック (壊れたファイルや偽造スタブを早期排除 F04)
                    if len(cover_bytes) < 128:
                        errors.append(f'表紙画像ファイルサイズが極端に小さすぎます: {len(cover_bytes)} bytes')
                        checks['cover'] = False
                    else:
                        cover_head = cover_bytes[:8]
                        if cover_type == 'image/png' and not cover_head.startswith(b'\x89PNG\r\n\x1a\n'):
                            errors.append('表紙画像の内容がPNGバイナリと一致しません。')
                            checks['cover'] = False
                        elif cover_type == 'image/jpeg' and not cover_head.startswith(b'\xff\xd8'):
                            errors.append('表紙画像の内容がJPEGバイナリと一致しません。')
                            checks['cover'] = False
                        else:
                            # PIL による実画像デコード・寸法検証 (F04 fake_cover 検知)
                            try:
                                import io
                                from PIL import Image
                                with Image.open(io.BytesIO(cover_bytes)) as img:
                                    img.verify()
                                with Image.open(io.BytesIO(cover_bytes)) as img2:
                                    w, h = img2.size
                                    if w < 10 or h < 10:
                                        errors.append(f'表紙画像の寸法が異常です: {w}x{h}')
                                        checks['cover'] = False
                                    else:
                                        checks['cover'] = True
                            except Exception as img_err:
                                errors.append(f'表紙画像のデコードに失敗しました: {str(img_err)}')
                                checks['cover'] = False
            elif reader_cover:
                errors.append('reader.jsonが参照する表紙画像がmanifestにありません。')
                checks['cover'] = False

            # reader.json の仕様・メタデータチェック
            if reader.get('profile') != 'monogatari-audio-epub' or reader.get('profileVersion') != 1:
                errors.append('未対応のReaderプロファイルです (profileVersion must be 1)。')

            reader_duration_ms = int(reader.get('durationMs', 0))
            pages = reader.get('pages', [])
            reader_pages_count = len(pages)
            if not pages:
                errors.append('reader.jsonにページが1件も定義されていません。')

            # ページ時刻の妥当性・順序の厳格検査 (F04 invalid_page_times 検知)
            prev_page_end = 0
            for p_idx, page in enumerate(pages):
                start_ms = page.get('startMs')
                end_ms = page.get('endMs')
                if not isinstance(start_ms, (int, float)) or not isinstance(end_ms, (int, float)):
                    errors.append(f'ページ {p_idx} の開始/終了時刻が数値ではありません')
                    continue
                start_ms = int(start_ms)
                end_ms = int(end_ms)
                if start_ms < 0:
                    errors.append(f'ページ {p_idx} の開始時刻が負の値です: {start_ms}')
                if end_ms <= start_ms:
                    errors.append(f'ページ {p_idx} の終了時刻が開始時刻以下です: start={start_ms}, end={end_ms}')
                if start_ms < prev_page_end:
                    errors.append(f'ページ {p_idx} の開始時刻が前ページの終了時刻より前に逆行しています: {start_ms} < {prev_page_end}')
                if reader_duration_ms > 0:
                    if start_ms >= reader_duration_ms:
                        errors.append(f'ページ {p_idx} の開始時刻が総音声時間を超過しています: start={start_ms}, duration={reader_duration_ms}')
                    if end_ms > reader_duration_ms + 1_000:
                        errors.append(f'ページ {p_idx} の終了時刻が総音声時間を超過しています: end={end_ms}, duration={reader_duration_ms}')
                prev_page_end = end_ms

            # integrity.json の SHA-256 チェック & 必須ファイル網羅性検証 (F04 incomplete_integrity 検知)
            integrity = json.loads(archive.read(integrity_path).decode('utf-8'))
            target_files = integrity.get('files', {})
            if not target_files:
                errors.append('integrity.json に検査対象ファイルがありません。')

            for target, expected_hash in target_files.items():
                if target not in names:
                    errors.append(f'完全性検査対象がありません: {target}')
                else:
                    actual_hash = hashlib.sha256(archive.read(target)).hexdigest()
                    if actual_hash != expected_hash:
                        errors.append(f'ハッシュ不一致: {target}')

            # 必須ファイルが integrity.json に網羅されているか検査 (F04)
            required_integrity_files = set()
            for item_path, media_type in manifest.values():
                if media_type in {'application/xhtml+xml', 'application/smil+xml', 'text/css', 'audio/mpeg'}:
                    required_integrity_files.add(item_path)
            if rootfile:
                required_integrity_files.add(rootfile)
            if reader_path:
                required_integrity_files.add(reader_path)

            missing_integrity = required_integrity_files - set(target_files.keys())
            if missing_integrity:
                errors.append(f'integrity.json に必須ファイルのハッシュが網羅されていません: {sorted(missing_integrity)}')

            checks['integrity'] = not any(m.startswith(('完全性検査対象', 'ハッシュ不一致', 'integrity.json')) for m in errors)

            # XHTML 文ID の抽出とドキュメント別インデックス構築 (F04 wrong_text_path 検知)
            xhtml_ids: dict[str, set[str]] = {}
            for item_path, media_type in manifest.values():
                if media_type == 'application/xhtml+xml':
                    if item_path not in names:
                        errors.append(f'XHTMLファイルが実在しません: {item_path}')
                        continue
                    document = ET.fromstring(archive.read(item_path))
                    doc_ids: set[str] = set()
                    for element in document.iter():
                        sentence_id = element.attrib.get('id', '')
                        if sentence_id.startswith('s-'):
                            if sentence_id in sentence_ids:
                                errors.append(f'文ID重複: {sentence_id}')
                            sentence_ids.add(sentence_id)
                            doc_ids.add(sentence_id)
                    xhtml_ids[item_path] = doc_ids
                    if doc_ids:
                        linked_css = [resolve(posixpath.dirname(item_path), link.get('href', ''))
                            for link in document.findall('.//{http://www.w3.org/1999/xhtml}link')
                            if 'stylesheet' in link.get('rel', '').split()]
                        linked_text = '\n'.join(archive.read(path).decode('utf-8') for path in linked_css if path in names)
                        linked_text = re.sub(r'/\*.*?\*/', '', linked_text, flags=re.S)
                        if not active_class or not re.search(r'\.' + re.escape(active_class) + r'\s*\{[^}]*\b(?:background(?:-color)?|color)\s*:', linked_text):
                            warnings.append(f'本文が朗読ハイライト用CSSを読み込んでいません: {item_path}')
                            checks['activeHighlight'] = False

            if not sentence_ids:
                errors.append('XHTML内に文ID (id="s-...") が1件も見つかりません。')

            # SMIL タイムラインのチェック & 参照パス整合性 (F04 wrong_text_path, wrong_audio_path 検知)
            smil_ids: set[str] = set()
            smil_sentence_times: dict[str, tuple[int, int]] = {}
            smil_audio_paths: set[str] = set()
            smil_ordered_ids: list[str] = []
            # Manifest order is not reading order; follow the spine's overlays.
            ordered_smil_ids = [manifest_media_overlays.get(ref.attrib.get('idref', '')) for ref in spine_itemrefs]
            ordered_smil_ids = list(dict.fromkeys(mid for mid in ordered_smil_ids if mid in manifest))
            ordered_smil_ids += [mid for mid, (_, mt) in manifest.items() if mt == 'application/smil+xml' and mid not in ordered_smil_ids]
            for item_path, media_type in (manifest[mid] for mid in ordered_smil_ids):
                if media_type != 'application/smil+xml':
                    continue
                if item_path not in names:
                    errors.append(f'SMILファイルが実在しません: {item_path}')
                    continue

                document = ET.fromstring(archive.read(item_path))
                smil_dir = posixpath.dirname(item_path)

                for par in (node for node in document.iter() if node.tag.endswith('par')):
                    text_node = next((node for node in par if node.tag.endswith('text')), None)
                    audio_node = next((node for node in par if node.tag.endswith('audio')), None)
                    if text_node is None or audio_node is None:
                        errors.append(f'不完全なSMIL par: {item_path}')
                        continue

                    # text 参照の完全パス解決 & XHTMLドキュメント内ID存在検証 (F04 wrong_text_path)
                    ref_src = text_node.attrib.get('src', '')
                    src_parts = ref_src.split('#')
                    ref_file_rel = src_parts[0]
                    sentence_id = src_parts[1] if len(src_parts) > 1 else ''

                    resolved_text_path = resolve(smil_dir, ref_file_rel)
                    if resolved_text_path not in names or resolved_text_path not in xhtml_ids:
                        errors.append(f'SMIL参照先XHTMLファイルが存在しません: {resolved_text_path} (src={ref_src})')
                    elif sentence_id not in xhtml_ids[resolved_text_path]:
                        errors.append(f'SMIL参照先文IDが指定XHTML内に存在しません: {sentence_id} in {resolved_text_path}')

                    if sentence_id in smil_ids:
                        errors.append(f'SMIL文ID重複: {sentence_id}')

                    # audio 参照の完全パス解決 & EPUB内実在検証 & 音声形式検証 (F04/G06 wrong_audio_path, smil_audio_is_jpeg)
                    audio_src = audio_node.attrib.get('src', '')
                    if not audio_src:
                        errors.append(f'SMIL audio要素にsrcが指定されていません: {item_path}')
                    else:
                        resolved_audio_path = resolve(smil_dir, audio_src)
                        smil_audio_paths.add(resolved_audio_path)
                        if resolved_audio_path not in names:
                            errors.append(f'SMIL参照先オーディオファイルが実在しません: {resolved_audio_path} (src={audio_src})')
                        else:
                            # manifest に登録されており、かつ media-type が audio/ であるか検証
                            manifest_audio_entry = next(((mid, mt) for mid, (mpath, mt) in manifest.items() if mpath == resolved_audio_path), None)
                            if not manifest_audio_entry:
                                errors.append(f'SMIL参照先オーディオがmanifestに登録されていません: {resolved_audio_path}')
                            elif not manifest_audio_entry[1].startswith('audio/'):
                                errors.append(f'SMIL参照先オーディオが音声メディア形式ではありません: {resolved_audio_path} (media-type={manifest_audio_entry[1]})')

                    begin = clock_ms(audio_node.attrib.get('clipBegin', ''))
                    end = clock_ms(audio_node.attrib.get('clipEnd', ''))

                    if begin >= end:
                        errors.append(f'SMILの終了時刻が開始時刻以下です: {sentence_id} (begin={begin}, end={end})')
                    if begin < last_end:
                        errors.append(f'SMIL時刻順不正（時刻が逆行または重複）: {sentence_id} (begin={begin}, last_end={last_end})')

                    if last_end and begin - last_end > 1_000:
                        gap_count += 1
                        warnings.append(f'SMIL区間間に{begin - last_end}msの空白があります: {sentence_id}')

                    smil_ids.add(sentence_id)
                    smil_ordered_ids.append(sentence_id)
                    smil_sentence_times[sentence_id] = (begin, end)
                    last_end = end

            # XHTML 全文ID と SMIL 文ID の網羅性完全一致検証 (F04 uncovered_xhtml 検知)
            if sentence_ids != smil_ids:
                uncovered = sentence_ids - smil_ids
                extra_smil = smil_ids - sentence_ids
                if uncovered:
                    errors.append(f'SMILに収録されていないXHTML文IDが存在します: {sorted(uncovered)}')
                if extra_smil:
                    errors.append(f'XHTMLに存在しないSMIL文IDが存在します: {sorted(extra_smil)}')

            # reader.json の文ID集合と SMIL 文ID集合の突合
            page_ids: list[str] = []
            for page in pages:
                page_ids.extend(page.get('sentenceIds', []))

            if len(page_ids) != len(set(page_ids)):
                errors.append('reader.json のページ内で文IDが重複しています。')
            if set(page_ids) != smil_ids:
                errors.append(f'reader.jsonの文ID集合がSMIL区間と一致しません (pages={len(set(page_ids))}, smil={len(smil_ids)})。')
            elif page_ids != smil_ordered_ids:
                errors.append('reader.jsonのページ内またはページ間の文ID順序がSMILの再生順序と一致しません。')

            if abs(reader_duration_ms - last_end) > 1_000:
                errors.append(f'reader.jsonの総時間とSMIL終端の差が1秒を超えています: reader={reader_duration_ms}ms, smil={last_end}ms')

            # ページ時刻と収録文の SMIL 区間突合検査 (H05 page_times_disagree_smil 検知)
            for p_idx, page in enumerate(pages):
                p_sids = page.get('sentenceIds', [])
                if not p_sids:
                    continue
                page_start = page.get('startMs', 0)
                page_end = page.get('endMs', 0)
                valid_sids = [sid for sid in p_sids if sid in smil_sentence_times]
                if valid_sids:
                    expected_page_start = min(smil_sentence_times[sid][0] for sid in valid_sids)
                    expected_page_end = max(smil_sentence_times[sid][1] for sid in valid_sids)
                    if abs(page_start - expected_page_start) > 1_000 or abs(page_end - expected_page_end) > 1_000:
                        errors.append(
                            f'ページ {p_idx} の時刻範囲 ({page_start}〜{page_end}ms) が収録文のSMIL区間 '
                            f'({expected_page_start}〜{expected_page_end}ms) と一致しません。'
                        )

            checks['timeline'] = not any(
                m.startswith(('SMIL', 'reader.json', '文ID', 'ページ', 'XHTML')) for m in errors
            )

            # 音声ファイルのデコード確認 & 実再生時間検査 (FFmpeg / FFprobe - timeout付き F04/H03)
            audio_rel = reader.get('audio', '')
            audio_path = resolve(posixpath.dirname(reader_path), audio_rel) if audio_rel else None

            # profileVersion 1 uses one continuous narration MP3. The file
            # probed for duration must be the file actually played by SMIL.
            if not audio_path or audio_path not in names:
                errors.append('reader.jsonの朗読音声参照が存在しません。')
                checks['timeline'] = False
            elif smil_audio_paths != {audio_path}:
                errors.append('SMILの参照音声がreader.jsonの単一朗読音声と一致しません。')
                checks['timeline'] = False

            all_audio_paths = set(smil_audio_paths)
            if audio_path:
                all_audio_paths.add(audio_path)

            if not all_audio_paths:
                errors.append('検査対象のオーディオファイルが存在しません。')
                checks['audioDecode'] = False
            else:
                ffmpeg_bin = get_ffmpeg_path()
                ffprobe_bin = get_ffprobe_path()
                all_audio_decoded = True

                with tempfile.TemporaryDirectory() as tmpdir:
                    for idx, a_path in enumerate(sorted(all_audio_paths)):
                        if a_path not in names:
                            errors.append(f'オーディオファイルがアーカイブ内に存在しません: {a_path}')
                            all_audio_decoded = False
                            continue

                        ext = posixpath.splitext(a_path)[1].lower() or '.mp3'
                        temp_file = Path(tmpdir) / f'audio_{idx}{ext}'
                        temp_file.write_bytes(archive.read(a_path))

                        # 1. FFmpeg 全編デコード (30秒タイムアウト付き)
                        null_out = 'NUL' if os.name == 'nt' else '/dev/null'
                        try:
                            decode_res = subprocess.run(
                                [ffmpeg_bin, '-v', 'error', '-i', str(temp_file), '-f', 'null', null_out],
                                capture_output=True,
                                text=True,
                                timeout=180
                            )
                            if decode_res.returncode != 0:
                                errors.append(f'音声ファイル({a_path})を全編デコードできません (exit {decode_res.returncode}): {decode_res.stderr.strip()}')
                                all_audio_decoded = False
                        except subprocess.TimeoutExpired:
                            errors.append(f'FFmpeg による音声デコード処理がタイムアウトしました (30秒超過): {a_path}')
                            all_audio_decoded = False

                        # 2. FFprobe 実再生時間 (15秒タイムアウト付き) - reader.json 指定音声またはメイン音声
                        if (audio_path and a_path == audio_path) or (not audio_path and idx == 0):
                            try:
                                probe_res = subprocess.run(
                                    [
                                        ffprobe_bin, '-v', 'error',
                                        '-show_entries', 'format=duration',
                                        '-of', 'default=noprint_wrappers=1:nokey=1',
                                        str(temp_file)
                                    ],
                                    capture_output=True,
                                    text=True,
                                    timeout=15
                                )
                                if probe_res.returncode != 0:
                                    errors.append(f'朗読MP3の再生時間を取得できません: {probe_res.stderr.strip()}')
                                    checks['durationMatch'] = False
                                else:
                                    probe_out = probe_res.stdout.strip()
                                    if probe_out:
                                        actual_audio_duration_ms = round(float(probe_out) * 1000)
                                        delta_ms = abs(actual_audio_duration_ms - last_end)
                                        if delta_ms > 1_000:
                                            errors.append(f'MP3実時間とSMIL終端の差が1秒を超えています: actual={actual_audio_duration_ms}ms, smil={last_end}ms, delta={delta_ms}ms')
                                            checks['durationMatch'] = False
                                        else:
                                            checks['durationMatch'] = True
                                    else:
                                        errors.append('FFprobe の出力が空でした。')
                                        checks['durationMatch'] = False
                            except subprocess.TimeoutExpired:
                                errors.append('FFprobe による音声メタデータ解析がタイムアウトしました。')
                                checks['durationMatch'] = False

                checks['audioDecode'] = all_audio_decoded and (len(all_audio_paths) > 0)

    except Exception as e:
        errors.append(f'検査中に例外が発生しました: {str(e)}')

    # 必須 checks がすべて True かつ errors が空であること
    all_checks_passed = all(v for k,v in checks.items() if k != 'activeHighlight')
    is_passed = (len(errors) == 0) and all_checks_passed

    return {
        'status': 'passed' if is_passed else 'failed',
        'valid': is_passed,
        'checks': checks,
        'errors': errors,
        'warnings': warnings,
        'file': str(epub_path),
        'sentences': len(sentence_ids),
        'pages': reader_pages_count,
        'durationMs': reader_duration_ms,
        'audioDurationMs': actual_audio_duration_ms,
        'smilEndMs': last_end,
        'durationDeltaMs': abs(actual_audio_duration_ms - last_end) if actual_audio_duration_ms else None,
        'timelineGapCount': gap_count,
    }
