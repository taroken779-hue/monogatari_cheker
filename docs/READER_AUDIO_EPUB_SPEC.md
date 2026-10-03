# Even G2 / Monogatari Reader 向け朗読EPUB仕様書

更新日: 2026-10-04 JST  
プロファイル: monogatari-audio-epub / profileVersion 1  
対象: Monogatari Studio、Monogatari Studio Cloud、第三者の作成ツール  
関連: [チェッカー設計](DESIGN.md) / [検証記録](VALIDATION.md)

## 1. 適用範囲と要件の読み方

Monogatari Readerが本文をEven G2へ表示し、音声位置に同期させるための専用Audio EPUB形式を定義する。拡張子.epub、MIME application/epub+zip。通常のテキストEPUBやMP3を添付しただけのEPUBはこの形式を満たさない。

「必須」は成果物が満たす条件、「推奨」は作成時の品質目安。「チェッカー判定」は本アプリの現行検査ルールであり、EPUB標準全体の適合判定とは区別する。既存Readerが不備を見逃しても、作成要件を省略してよい意味ではない。

## 2. ファイル構成

```text
book.epub
├─ mimetype
├─ META-INF/container.xml
└─ EPUB/
   ├─ package.opf
   ├─ nav.xhtml
   ├─ styles/book.css                 本文スタイル（任意）
   ├─ styles/checker-highlight.css    ハイライト用（任意）
   ├─ text/cover.xhtml                表紙を付ける場合
   ├─ images/cover.jpg                表紙を付ける場合（PNGも可）
   ├─ text/chapter-001.xhtml          章に応じて追加
   ├─ overlays/chapter-001.smil       各章に対応
   ├─ audio/narration.mp3             1本の連続した朗読
   └─ monogatari/
      ├─ reader.json
      └─ integrity.json
```

上記の通常資産名は例。containerとmanifestで実際の位置を結び付ける。ただし現行Readerのintegrityは`EPUB/monogatari/integrity.json`固定。互換性を優先しOPFとReader JSONも上記の配置を推奨する。

## 3. ZIPとパス

- mimetypeをZIP先頭に置き、ZIP_STORED（無圧縮）にする。内容は`application/epub+zip`のみ。改行・BOMを付けない。
- META-INF/container.xmlを必須とし、rootfile@full-pathで実在するOPFを指定する。
- ZIPエントリは`/`区切り。絶対パス、ドライブ指定、バックスラッシュ、`..`を含むエントリ、重複名を使用しない。
- XHTML・SMIL・JSON内の参照は、そのファイルが置かれたディレクトリを基準に解決する。`../audio/narration.mp3`のような相対参照は許可するが、解決結果がZIP内の安全なパスになること。
- 展開後合計250MiB、2000ファイル、XML/OPF/XHTML/SMIL/JSON各10MiB以内をReader互換上限とする。
- 本チェッカーは暗号化ZIPとXML ENTITY宣言に非対応。

```xml
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
```

## 4. OPF・目次・読書順

EPUB 3のpackageを使用する。書誌情報としてdc:identifier、dc:title、dc:language、dcterms:modifiedを記録する。朗読総時間と各SMILのmedia:durationを記録する。OPFとreader.jsonのタイトル・著者・あらすじは一致させる。

manifestには本文XHTML、SMIL、MP3、目次、利用するCSS、reader.json、integrity.json、任意の表紙画像・表紙XHTMLを登録する。item IDは一意にする。各朗読本文のmedia-overlayに対応SMILのitem IDを指定する。

```xml
<manifest xmlns="http://www.idpf.org/2007/opf">
  <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  <item id="chapter-001" href="text/chapter-001.xhtml" media-type="application/xhtml+xml" media-overlay="smil-001"/>
  <item id="smil-001" href="overlays/chapter-001.smil" media-type="application/smil+xml"/>
  <item id="audio" href="audio/narration.mp3" media-type="audio/mpeg"/>
  <item id="reader" href="monogatari/reader.json" media-type="application/json"/>
  <item id="integrity" href="monogatari/integrity.json" media-type="application/json"/>
</manifest>
```

spineは表紙（ある場合）→第1章→第2章の順。目次navはmanifestで1件宣言し、各リンクのファイルとfragment IDを実在させる。manifestの列挙順に依存して読書順を決めない。

## 5. 本文XHTML

UTF-8の整形式XML、XHTML名前空間を使用する。朗読区間には作品全体で一意の`s-`から始まるIDを付ける。表示本文とTTS用の読み置換を区別し、表示には原文を保持する。

```xml
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ja">
  <head><title>作品名</title></head>
  <body><p><span id="s-0001">雨が降っていた。</span><span id="s-0002">私は店の扉を開けた。</span></p></body>
</html>
```

音声に含める見出しも同期区間にする。非朗読の表紙にはs-文IDを付けず、ReaderページのsentenceIdsにも含めない。

## 6. 音声とSMIL

v1では1本の連続MP3を使用し、manifestのaudio/mpeg、reader.json.audio、全SMIL audio@srcが同じファイルを指す。MP3は全編デコードでき、実際の本文の朗読を収録すること。テスト音やダミー音声を完成品として扱わない。

SMILは章ごとに配置し、本文ファイル＋文IDと音声区間をparで結ぶ。時刻は**最終MP3先頭からの絶対時刻**。章の先頭で0へ戻さない。

```xml
<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0">
  <body><seq>
    <par id="par-0001">
      <text src="../text/chapter-001.xhtml#s-0001"/>
      <audio src="../audio/narration.mp3" clipBegin="0:00:00.000" clipEnd="0:00:02.000"/>
    </par>
    <par id="par-0002">
      <text src="../text/chapter-001.xhtml#s-0002"/>
      <audio src="../audio/narration.mp3" clipBegin="2.000s" clipEnd="4.500s"/>
    </par>
  </seq></body>
</smil>
```

開始・終了は非負かつ開始<終了。全章で再生順に並べ、逆行・重複を作らない。間・無音は区間間に残せる。全朗読文IDを一度ずつ収録し、本文・SMIL・Readerページの順序を一致させる。

SMILが同期時刻の正本。MP3実時間、最終clipEnd、reader.json.durationMsを一致させる。本チェッカーは終端差1000ms超、ページ時刻と収録SMIL範囲の差1000ms超をエラー、区間間の空白1000ms超を警告にする。この許容差を意図的なずれとして使わず、作成時は正確な時刻を記録する。

## 7. reader.json v1

UTF-8 JSON。manifest hrefはmonogatari/reader.jsonで終わること。

```json
{
  "profile": "monogatari-audio-epub",
  "profileVersion": 1,
  "bookId": "87d10dc6-d385-41cb-a954-98a4154115f0",
  "title": "作品名",
  "creator": "著者名",
  "description": "作品のあらすじ。",
  "language": "ja",
  "durationMs": 4500,
  "audio": "../audio/narration.mp3",
  "pages": [
    {"id": "page-001", "sentenceIds": ["s-0001", "s-0002"], "startMs": 0, "endMs": 4500}
  ]
}
```

| 項目 | 型・条件 | 必須 |
|---|---|---|
| profile | monogatari-audio-epub固定 | 必須 |
| profileVersion | 整数1 | 必須 |
| bookId | 空でない文字列、UUID推奨 | 必須 |
| title / language | 空でない文字列。日本語はja | 必須 |
| audio | JSON位置を基準とする収録MP3の相対パス | 必須 |
| durationMs | 正の有限数、ミリ秒 | 必須 |
| pages | 1件以上のページ配列 | 必須 |
| pages[].id | 一意の文字列 | 必須 |
| pages[].sentenceIds | 1件以上の文字列ID、重複なし、全SMIL文を読書順に一度ずつ含む | 必須 |
| pages[].startMs / endMs | 非負の有限数、開始<終了、収録文の始端・終端と一致 | 必須 |
| creator / genre / description | 文字列。あらすじ300文字以内推奨 | 任意 |
| cover | JSON位置から表紙画像への相対パス | 表紙を付ける場合 |
| production / $schema | 制作情報・スキーマ情報。Reader必須ではない | 任意 |

別作品には別bookId、同じ作品の改訂版には同じbookIdを使用する。G2のページ分割は読みやすさを優先し、原仕様の目安は150〜300文字。ページ長とG2の同時表示予算108文字は別の値であり、108文字をページの必須上限とはしない。

## 8. 表紙画像と表示用XHTML

表紙自体は任意。表紙を付けるなら、PNG/JPEG実画像、manifestのcover-image、reader.json.cover、表紙を表示するXHTML、spine先頭のitemrefを揃える。

```xml
<manifest xmlns="http://www.idpf.org/2007/opf">
  <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
  <item id="cover-page" href="text/cover.xhtml" media-type="application/xhtml+xml"/>
</manifest>
```

```xml
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>表紙</title><style>img { max-width: 100%; max-height: 95vh; object-fit: contain; }</style></head>
  <body epub:type="cover"><img src="../images/cover.jpg" alt="表紙"/></body>
</html>
```

reader.jsonには`"cover": "../images/cover.jpg"`を設定する。表紙ページは音声同期対象外でmedia-overlayを付けない。画像拡張子・MIME・実画像形式を一致させる。表紙の登録だけでなく、表示XHTML内のimgがその画像を参照すること。

本アプリのアップロード制約は10MiB・64〜10000px。これはReaderファイル形式全体の必須画像寸法ではない。本チェッカーは表紙なしを警告、必須表紙モードでエラー、参照不備・表示ページ欠落をエラーとする。

## 9. ハイライトCSS

対応EPUBビューアでも朗読文を強調する場合に推奨する。G2独自表示には適用されない。

```xml
<meta xmlns="http://www.idpf.org/2007/opf" property="media:active-class">monogatari-checker-active</meta>
```

```css
.monogatari-checker-active {
  background-color: #ffe600 !important;
  color: #111111 !important;
}
```

CSSはmanifestでtext/cssとして登録し、各朗読本文XHTMLのheadからstylesheetリンクで参照する。OPF宣言だけ、CSSだけ、色指定だけの不完全な設定にしない。既存本文スタイルとの明暗差を試聴画面で確認する。

## 10. integrity.json

固定位置EPUB/monogatari/integrity.json。algorithmはSHA-256、filesはZIPルート基準パス→実バイト列の小文字64桁16進ハッシュ。

```json
{
  "algorithm": "SHA-256",
  "files": {
    "EPUB/package.opf": "実ファイルから計算した64桁ハッシュ",
    "EPUB/monogatari/reader.json": "実ファイルから計算した64桁ハッシュ"
  }
}
```

上記は形式説明であり、そのまま使用できない。実際はOPF、nav、CSS、全本文・表紙XHTML、全SMIL、MP3、reader.json、表紙画像を網羅する。integrity自身は除外する。mimetypeとcontainerはこのプロファイルの必須ハッシュ対象一覧に含めない。資産を変更したら一覧を再計算する。

SHA-256は破損と内容不一致の検出用で、発行者署名や真正性の証明ではない。

## 11. 作成・改訂手順

1. 表示本文と朗読区間を確定し、一意の文IDを割り当てる。
2. 実際の朗読MP3を完成させ、文ごとの時刻を最終音声に対して取得する。
3. XHTML、章SMIL、Readerページを同じ順序で生成する。
4. 書誌情報、OPF、目次、任意の表紙・ハイライトを揃える。
5. 全資産のハッシュを計算し、integrityを書き出す。
6. mimetype先頭・無圧縮でZIPを作り、.epubとして保存する。
7. チェッカーで検査し、本文・音声・章境界・末尾・長文を試聴する。
8. Even Hub / Readerへの取込とG2実機表示・再生を確認する。

書誌・表紙・CSSだけの改訂ではMP3・SMILを保持できる。本文や読み上げ作品名、朗読内容を変える改訂では、音声と同期の再生成が必要。古いファイルの確認済み状態を新しいEPUBへ流用しない。

## 12. 検査の限界と実機受入項目

Readerは専用プロファイルを読み込むが、すべてのEPUB標準項目や参照対応を検査するわけではない。本チェッカーもEPUBCheck全項目、音声の意味、読み間違い、話者の正しさを保証しない。

実機では取込、冒頭・中盤・末尾、章・ページ境界、長文スクロール、倍速、停止・再開、Bluetooth音声、G2表示を確認する。PCの576×288相当表示と実機の光学表示は区別する。

## 13. 根拠と保守

[Reader元仕様](READER_AUDIO_EPUB_SPEC.md)、[作成ガイド](READER_AUDIO_EPUB_SPEC.md)、Reader実装、Studio/Cloud生成・検査コードと本チェッカー実装に基づく整理。元仕様の更新に合わせて本書のプロファイル・上限・判定差異を見直す。EPUB標準の全文仕様を置き換える文書ではない。
