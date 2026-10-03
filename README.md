# Monogatari Checker

Monogatari Reader / Even G2向けAudio EPUBのローカルWebチェッカー。

## ドキュメント

- [アプリ設計書](docs/DESIGN.md): 構成、検査、プレビュー、編集・修復、API、運用。
- [Even G2向け朗読EPUB仕様書](docs/READER_AUDIO_EPUB_SPEC.md): ファイル構成、OPF、XHTML、SMIL、Reader JSON、表紙、CSS、ハッシュ、作成手順。
- [検証記録](docs/VALIDATION.md): 自動テスト、実成果物、ブラウザ確認と未実施項目。

## 環境構築・起動・停止

### PCごとの設定

`config.example.json`を`config.local.json`へコピーし、このPCの実行ファイルのパスを指定する。空欄ならPATHから検出する。相対パスはプロジェクトフォルダを基準に解決する。`config.local.json`はGit管理対象外なので、別のPCでは個別に設定する。

```json
{
  "python": "",
  "ffmpeg": "",
  "ffprobe": ""
}
```

`python`は環境構築用Python、`ffmpeg`と`ffprobe`はそれぞれの実行ファイル。音声ツールは`FFMPEG_PATH` / `FFPROBE_PATH`環境変数の指定を優先し、その次にローカル設定、PATHの順で検出する。設定エラーは検査結果に表示する。

### PCごとの設定

`config.example.json`を`config.local.json`へコピーし、このPCの実行ファイルのパスを指定する。空欄ならPATHから検出する。相対パスはプロジェクトフォルダを基準に解決する。`config.local.json`はGit管理対象外なので、別のPCでは個別に設定する。

```json
{
  "python": "",
  "ffmpeg": "",
  "ffprobe": ""
}
```

`python`は環境構築用Python、`ffmpeg`と`ffprobe`はそれぞれの実行ファイル。音声ツールは`FFMPEG_PATH` / `FFPROBE_PATH`環境変数の指定を優先し、その次にローカル設定、PATHの順で検出する。設定エラーは検査結果に表示する。

初回はPowerShellで本フォルダを開き、`.\Setup.ps1`を実行する。Python専用環境は.venv。Pillowを使用し、既存のFFmpeg/FFprobeをPATHまたはFFMPEG_PATH/FFPROBE_PATHから再利用する。既存Studio環境やグローバルPATHは変更しない。

- Start-Checker.batをダブルクリック: バックグラウンド起動しブラウザを開く。二重起動を防止する。
- Stop-Checker.batをダブルクリック: 本フォルダのチェッカーのみ停止。検査中なら完了後に再実行する。
- 詳細診断: `.\Start-Checker.ps1`を直接実行。停止はCtrl+C。

画面: http://127.0.0.1:8095/

## 操作

EPUBを選択して「検査を開始」。処理中・経過秒数と完了メッセージを表示する。エラー・警告の理由と修正方法を確認し、収録音声を試聴する。音声検査が通っていれば、不合格作品でも音声のみ試聴できる。同期プレビューとダウンロードは合格時に有効になる。

音声は再生・一時停止・先頭へ停止・倍速・音量・ミュート・単体表示に対応。合格した作品では文クリック、章・ページ・前後文・中盤・末尾移動とG2相当表示が連動する。

書誌情報でタイトル・著者・あらすじ・表紙を編集する。「表紙ページを追加・修復」は収録画像から表示XHTMLを生成してspine先頭へ配置。「ハイライトCSSを追加・修復」は色設定とOPF・CSS・本文参照を更新する。「修正して再検査」で別の修正版を作り、合格後にダウンロードする。元ファイルは変更しない。レポートはJSONで保存できる。

本文・音声中の作品名は書誌編集だけでは変わらない。テスト音の疑いは音声を試聴し、Studio / Studio Cloudで実朗読から再生成する。ハイライトCSSは対応EPUBビューア向けで、G2独自表示の色は変更しない。

## データと検証範囲

外部送信なし。作品は.runtimeへ一時保存し、正常停止時・次回起動時に削除。再起動後は再検査する。公開サーバー用途は対象外。検査合格は朗読内容やG2実機動作の保証ではない。

テスト実行:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

EPUBCheckによる全項目検査、STTによる音声内容照合、TTS合成は未実装。
