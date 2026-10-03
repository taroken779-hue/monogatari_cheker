# Monogatari Checker 設計書

更新日: 2026-10-04 JST  
状態: ローカル版の実装に対応  
関連: [朗読EPUB仕様書](READER_AUDIO_EPUB_SPEC.md) / [検証記録](VALIDATION.md) / [利用手順](../README.md)

## 1. 目的と対象

Monogatari Studio / Monogatari Studio Cloudが生成した、Monogatari Reader向けAudio EPUB profile v1の完成ファイルを検査する。表紙・書誌情報・同期・音声を確認し、修復可能な内容を編集して再出力する。通常EPUBのReader形式への変換、小説生成、TTS合成、本文やSMIL時刻の直接編集は対象外。

検査合格、PCプレビュー確認、音声の聴取確認、Even G2実機確認を区別する。形式が正しくても実際の朗読内容やG2動作を保証しない。

## 2. システム構成

```text
ブラウザ（HTML / CSS / JavaScript）
  ├─ EPUB選択・検査状況・修正案
  ├─ 書誌情報・表紙・ハイライト編集
  └─ 音声再生・本文同期・G2相当表示
        │ localhost HTTP / JSON / MP3 Range
Python HTTPサーバー（127.0.0.1:8095）
  ├─ app/server.py: HTTP、セッション、配信、停止
  ├─ app/core.py: ZIP解析、追加検査、編集、再パッケージ
  ├─ app/validator.py: EPUB、同期、画像、音声検査
  ├─ Pillow: 表紙の画像デコード
  ├─ FFmpeg / FFprobe: 音声デコード、実時間、テスト音検出
  └─ .runtime/<ランダムID>/: 元EPUB、修正版、抽出メディア
```

専用Python環境は本フォルダの`.venv`。HTTP処理は標準ライブラリを使用し、追加Webフレームワークは不要。既存のFFmpeg/FFprobeを再利用し、既存Studio環境とグローバルPATHは変更しない。G2表示処理はevenappsの`g2DisplayShared.js`を複製した共有元ベースの実装。参照元の更新は自動追従しないため、変更時に差分を確認する。

## 3. ユーザーフロー

1. EPUBを選択し、必要に応じて「表紙必須」を指定する。
2. 「検査を開始」で検査。画面上部と操作欄に処理中・経過秒数を表示する。
3. 完了時に合格、警告、修正が必要な項目と修正方法を表示する。処理失敗は別メッセージにする。
4. 音声を試聴し、合格した作品は本文同期・G2相当表示も確認する。
5. 書誌情報、表紙、表紙ページ、ハイライトを必要に応じて編集する。
6. 「修正して再検査」で別の修正版EPUBを作成する。完了メッセージと新しい検査結果を表示する。
7. 合格した修正版をダウンロードする。JSONレポートも保存できる。

現行の状況表示は処理中表示と経過時間であり、実処理フェーズ毎の進捗率ではない。

## 4. 検査モデル

| 分類 | 内容 | 判定 |
|---|---|---|
| ZIP・安全性 | 重複・危険パス・暗号化・ENTITY、展開容量・ファイル数、mimetype | 不備はエラー |
| EPUB構造 | container、OPF、manifest、spine、目次リンク | 不備はエラー |
| Readerプロファイル | v1、書誌項目、ページ、音声参照 | 不備はエラー |
| 本文・SMIL | 文ID、本文ファイル、音声参照、章との対応、網羅性・順序 | 不備はエラー |
| 時刻 | 区間逆転・重複、ページとの対応、MP3/SMIL/総時間 | 不整合はエラー。区間間の長い間は警告 |
| 表紙 | 実画像、MIME、cover参照、表示XHTML・spine | 表紙なしは警告、必須モードならエラー。参照不備はエラー |
| 書誌情報 | OPFとReader情報の差異、あらすじの推奨長 | 差異・300文字超は警告 |
| 完全性 | SHA-256一致、一覧の列挙漏れ | 不備はエラー |
| ハイライト | active-class、CSS色指定、本文のCSS参照 | 不足は警告 |
| 音声 | 全編デコード、実再生時間、複数位置の単一音 | 破損・テスト音の疑いはエラー |

入力上限はZIP展開後250MiB・2000項目・構造ファイル10MiB。HTTP本文上限は340MiB。音声デコードのタイムアウトは180秒、時間計測は15秒。上限を超える作品には分冊を案内する。

テスト音検出は最大4箇所の0.5秒サンプルに対する周波数集中を調べ、複数位置で近い単一音が続く場合に疑いを示す。音楽・効果音での誤検出、サンプル外の見逃しがあり、人による試聴を要する。音声が正しい文章を読んでいることを自動証明する検査ではない。

## 5. 検査結果とプレビュー

検査結果は`valid`、`issues`（severity/message/fix/target）、`validation`、`book`、`media`、`preview`、`sha256`、セッション`id`を返す。

- `media`: 展開が安全でReader指定音声がmanifestのaudio/mpegとして存在し、音声デコード検査が通った場合に提供する。エラー作品でも音声のみ試聴できる。
- `preview`: エラーがない場合のみ提供する。完成EPUBのXHTML本文、SMIL時刻、reader.jsonページを使う。
- `valid`: エラーがないことを示す。警告は残り得る。配布・実機動作の保証ではない。

本文はテキストとして描画し、収録HTML・JavaScript・外部CSSをブラウザへ実行させない。音声は同じ成果物から抽出し、64KiB単位のRange配信に対応する。ZIP解析時には上限内の展開内容をメモリに保持する。

再生・一時停止・先頭へ停止・速度・音量・ミュート・音声単体表示、文クリック、章・ページ・前後文・中盤・末尾ジャンプを提供する。メタデータ読込前のシークは保留する。現在文とG2表示を再生位置に連動させ、区間外では「音声の間」と表示する。

G2画面は576×288相当のPCシミュレーション。表示予算108文字と長文の文内スクロールを使用する。光学表示・実機フォント・BLE・Bluetooth音声は再現しない。表紙は作品詳細に表示する。

## 6. 編集と修復

| 操作 | 更新対象 | 保持する内容 |
|---|---|---|
| 書誌編集 | OPFとreader.jsonのタイトル・著者・あらすじ、旧作品名と一致するhead/title | 本文、目次ラベル、画像内の文字、朗読中の作品名 |
| 表紙追加・差替え | PNG/JPEG資産、manifest、reader.json.cover、表紙ページ | 本文、MP3、SMIL |
| 表紙ページ修復 | 既存画像からXHTML生成、manifest登録、spine先頭へ一度だけ配置 | 元の表紙画像、本文、MP3、SMIL |
| ハイライト修復 | active-class、専用CSS、manifest、全朗読XHTMLのCSSリンク | 既存CSS、本文body、MP3、SMIL |

表紙アップロードは10MiB以内、64〜10000pxのPNG/JPEG。既存表紙の修復はcover-imageまたはreader.json.coverを利用し、候補が複数なら整理を求める。非朗読の既存表紙ページを再利用し、欠落した宣言済みcover.xhtmlも復元する。

ハイライトは`monogatari-checker-active`へ統一。色は#RRGGBB形式で検証する。専用CSSを別資産にし、既存ファイルとの衝突を避け、再修復では同じ生成資産を更新する。G2独自表示の色は変更しない。

全編集でbookId・同期文ID・MP3・SMILを保持する。更新日時とintegrityを再計算し、mimetypeを先頭・無圧縮で再パッケージする。元ファイルは変更せず、修正版を別セッションで再検査する。

## 7. API

| メソッド・パス | 用途 |
|---|---|
| GET /api/config | アプリ識別、プロジェクトroot、POSTトークン、外部ツール検出 |
| POST /api/inspect | EPUBバイナリを検査。X-Require-Coverで必須表紙指定 |
| POST /api/edit | id/title/creator/description、任意のcover（Base64）/highlight/repairCover |
| GET /api/books/{id}/audio | 収録MP3。Range対応 |
| GET /api/books/{id}/cover | 収録表紙画像 |
| GET /api/books/{id}/download | 合格した成果物のEPUB |
| POST /api/shutdown | 検査中以外で正常終了 |

POSTには起動毎の`X-Checker-Token`が必要。検査は同時1件。重複検査は429、検査中の停止や不合格ファイルのダウンロードは409を返す。

## 8. 起動・停止・データ管理

PC固有パスはconfig.local.jsonに分離。配布用config.example.jsonは空欄でPATH検出を初期値とする。Pythonセットアップと音声ツールの設定を共有し、実際の設定はGitへ含めない。音声ツールは環境変数、ローカル設定、PATHの順で選択する。ファイルが存在しない指定を黙って他のツールへ置き換えない。

`Setup.ps1`で専用環境を準備する。`Start-Checker.bat`はサーバーをバックグラウンド起動してブラウザを開き、既に起動していれば二重起動しない。`Stop-Checker.bat`はアプリ識別とrootを照合し、HTTPで本アプリのみ停止する。詳細診断は`Start-Checker.ps1`の前面実行を使う。

データは外部へ送信しない。ローカルでのみ待受け、Host照合・POSTトークン・CSP・テキスト描画を使用する。作品は.runtimeのランダムID配下に保存し、正常停止時と次回起動時に削除する。稼働中は自動期限削除しない。再起動後は再検査が必要。

クラウド公開には認証、セッション所有権、ジョブ隔離、容量管理、保存期限、ログ方針が別途必要。現行を公開サーバーとして使わない。

## 9. 検証と今後の範囲

[検証記録](VALIDATION.md)にテスト・実成果物・ブラウザ確認を記載。現在の自動テストは15件。CLI合格と実機再生は分ける。EPUBCheck、STTによる本文照合、Studio API連携、クラウド公開は未実装。外部配布時は複製元の利用権を確認する。

## 10. 根拠資料

- [Reader元仕様](READER_AUDIO_EPUB_SPEC.md)
- [Studioプレビュー設計](DESIGN.md)
- Monogatari Readerリポジトリ内のsrc/domain/audioEpub.ts、g2DisplayShared.js
- Monogatari Studio Cloudリポジトリ内のservices/media/app/epub_validator.py、epub_builder.py
- 本プロジェクトのapp/core.py、app/validator.py、app/server.py、static/app.js
