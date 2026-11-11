# Workspace マネージャー 手順書

スプレッドシートとドキュメントを会話で作る・直す道具。MCP は 3 本：`ws_look`（見る）・`ws_do`（作る・直す）・`ws_undo`（戻す）。
通り道は専用の GAS エンジン（`shu-workspace-engine` = [workspace_engine.gs](workspace_engine.gs)）1 本。型（棚）はエンジンが持ち、AI は **棚の名前と引数の JSON** だけ渡す。使い捨ての GAS コードは書かない。

## 最初の 1 回
初めて撃つと、エンジンが無ければ道具が作り（Drive に `shu-workspace-engine` を 1 つ）、許可待ちなら **URL と押す所を 3 行で返して止まる**。
ブラウザで URL を開き「権限を確認」→「詳細」→「移動」→「許可」を押す（許可するのはスプレッドシートと文書だけ。Drive 全体は求めない）。押したらもう一度頼む。
エンジンの版が違えば、道具が自動で差し替える。

## 使い方（3 手）
1. `ws_look(target)` … 相手を決めて覚える。シート＝シート一覧と表の形（見出しの行・明細・合計行・列）。`range="A1:E20"` で中身。文書＝見出しと段落番号。
2. `ws_do(ops, target="", ok=False)` … 棚を順に撃つ。**1 回の呼び出し＝1 往復＝控え 1 つ**。返事は「対象／直した所／残り／URL・控え番号」。
3. `ws_undo()` … 直前に戻す。`list=True` で台帳、`to="番号"` でそこまで。

**目で確かめる**: `ws_do` で見た目を変えたら、報告の前に `ws_look(image=True)` を 1 回撃ち、返ってきた PNG を開いて確かめる（見出しの色・罫線・合計行・寄せ・桁区切り）。
シートは値・文字色・背景（条件付き書式の色も）・太字・寄せ・結合・列幅・罫線・固定行、文書は見出し・箇条書き・表・太字と色を描き直す。
グラフ・画像・図形・プルダウンは写らない。初回は Playwright が要る（`py -m pip install playwright` → `py -m playwright install chromium`）。

`target`: URL・ID・名前・`"new:名前"`（新規）・空（今の相手）。名前が 2 件以上当たったら、書かずに候補を返して止まる。
ops は 1 個でも配列。シートの棚と文書の棚は同じ呼び出しに混ぜない。棚の名前を外すと一覧が返る。

## 安全の決まり
- 書く前に必ず控え（シート＝`GASマネージャー_控え` ブックにタブ 20 枚で回す／文書＝控え文書 5 個を使い回す。シュウさんのファイルの中には何も残さない）。
- 失敗したら**同じ実行の中で**控えから戻して返す。だから撃ち直しても行が二重にならない。やり直しは同じ相手で 3 回続けて失敗したら止まる。
- 人の値を消す手（＊印）は `ok=True` のときだけ実行。無ければ何も変えずに「何行目が消えるか」を返して止まる。**`ok=True` は会話に「消してよい」「置き換えてよい」等の言葉があるときだけ。**
- 時間切れで終わった同じ頼みは同じ呼び出し番号で撃ち直す（エンジンが 6 時間覚えているので二重に走らない）。
- `ws_undo` は書き終わった時点の指紋と今を比べ、**道具が書いた後に人が手で直した所があれば止まる**（`ok=True` で戻す）。戻す前の状態も控えに取るので undo の undo もできる。
- 新しく作ったファイルは undo では消さない（URL を返すだけ）。新しく足したシートは undo で消える。
- 行の高さは戻しの対象外（列幅・値・式・書式・罫線は戻る）。

## 棚（シート）
| 棚 | 主な引数 | 中身 |
|---|---|---|
| `table.new` | headers, rows, title, sheet, number(列), total(列の配列), label | 表を作る。番号・合計行・整えまで 1 手。同じ表がすでにあれば「変更なし」 |
| `sheet.add` | name / rename{from,to} / move{name,index} | シートの追加・名前変更・並び順 |
| `tidy` | sheet, range | 見出し・罫線・列幅・数値の桁区切り・日付・見出し行の固定・合計行の体裁 |
| `seiri` | trim, halfwidth, numbers, blank_rows＊, dedupe＊, renumber | 空白・全角→半角・文字列の数字→数値。空行・重複行の削除は＊。最後に tidy |
| `renumber` | col, start | 番号の列を連番に |
| `width` | cols{列:幅}, rows{行:高さ}, auto[列] | 列幅・行の高さ |
| `total` | cols, label | 合計行。**あれば足さずに範囲だけ直す** |
| `summary` | by, values[], func(sum/count/avg), into | 「○○ごと」の集計表を新しいシートに（SUMIFS 等の式。元を直すと追従）。作り直しが要るときは＊ |
| `sort` | col, desc, filter, where{col,equals} | 並べ替え・フィルタ |
| `write` | cells{番地:値} / range+tsv | 値・式を書く |
| `format` | range / col / header, bold, color, bg, number_format, align, wrap, borders, merge | その範囲だけ書式 |
| `rows` | rows[] / cols[], action(insert/delete/move) | 行・列の挿入／削除＊／移動 |
| `replace` | find, with, range, match_case, whole | 検索して置換 |

列は見出しの名前でも列記号でも指せる（`"col":"金額"` / `"col":"D"`）。`sheet` を省けば今のシート。

## 棚（文書）
| 棚 | 主な引数 | 中身 |
|---|---|---|
| `doc.new` | markdown | 空の文書に Markdown から作る（見出し・箇条書き・番号・表・太字・斜体）。同じなら「変更なし」 |
| `doc.append` | markdown, under(見出し) | 末尾、または見出しの節の終わりに追記。同じ 1 行がすでにあれば足さない |
| `doc.replace` | find, with, match_case | 文字の置換（段落番号を返す） |
| `doc.section` | heading, action(replace/delete)＊, markdown | 見出しの節を差し替え・削除 |
| `doc.table` | rows, under / row, col, text, table | 表を入れる／表のセルを直す |
| `doc.style` | font, size, line_spacing | 見出し・本文・表の見出し行をそろえる。空の文書を作るだけにも使える |

## 例
```json
[{"shelf":"table.new","headers":["No","品名","数量","単価","金額"],
  "rows":[["","りんご",3,120,"=C2*D2"],["","みかん",5,80,"=C3*D3"]],
  "number":"A","total":["E"]}]
```
```json
[{"shelf":"rows","rows":[3]},{"shelf":"renumber","col":"A"}]      // 要 ok=True
[{"shelf":"doc.append","under":"決定事項","markdown":"- 次回は 12/2"},{"shelf":"doc.replace","find":"山田","with":"山田（総務）"}]
```

## 棚に無い頼み
「棚にありません」と返す。その場しのぎのコードは流さない（第 2 便の候補：プルダウン・条件付き書式・グラフ・ピボット・文書の画像・ヘッダー）。

## 手元の状態
`.ws_state.json`（今の相手・エンジンの場所・やり直し回数）は git に入れない。台帳はエンジン側（`ws_undo(list=True)`）。
