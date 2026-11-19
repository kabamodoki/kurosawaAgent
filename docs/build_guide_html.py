"""手順書（setup-guide.md）から、読みやすい HTML 版（setup-guide.html）を作る。

正は setup-guide.md。HTML は手で直さず、md を直してからこのスクリプトで作り直す。

準備（初回だけ）:
    python -m pip install markdown==3.10.3 pymdown-extensions==12.3

使い方（docs フォルダで）:
    python build_guide_html.py
"""

import base64
import html
import re
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "setup-guide.md"
SVG = HERE / "architecture.svg"
OUTPUT = HERE / "setup-guide.html"


def normalize_indent(text: str) -> str:
    """リストの中の字下げを4の倍数にそろえる（Python-Markdown は4文字単位で入れ子を判断するため）。"""
    lines = []
    in_top_fence = False
    for line in text.split("\n"):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if indent == 0 and stripped.startswith("```"):
            in_top_fence = not in_top_fence
        if not in_top_fence and indent % 4 and stripped:
            line = " " * ((indent // 4 + 1) * 4) + stripped
        lines.append(line)
    return "\n".join(lines)


def convert(md_text: str) -> tuple[str, list]:
    md = markdown.Markdown(
        extensions=["tables", "pymdownx.superfences", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": lambda value, sep: "s-" + re.sub(r"[^\w]+", "-", value).strip("-").lower()}},
    )
    body = md.convert(normalize_indent(md_text))
    return body, md.toc_tokens


def decorate(body: str) -> str:
    # 構成図は SVG を埋め込む（1ファイルで開けるように）
    svg_b64 = base64.b64encode(SVG.read_bytes()).decode("ascii")
    body = re.sub(
        r'<p><img alt="構成図" src="architecture.svg" ?/?></p>',
        f'<figure class="diagram"><img alt="構成図" src="data:image/svg+xml;base64,{svg_b64}">'
        "<figcaption>番号は「1-3 通信の流れ」と同じです</figcaption></figure>",
        body,
    )
    # 【要確認】を目立つ印にする
    body = re.sub(r"【要確認(?:[:：]\s*([^】]*))?】", _check_badge, body)
    # 表は横に流せる枠に入れる（スマホ幅で画面からはみ出さないように）
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    # 外部リンクは新しいタブで開く
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    return body


def _check_badge(match: re.Match) -> str:
    note = match.group(1)
    if note:
        return f'<span class="check" title="公式ドキュメントで確かめられなかった点">要確認</span><span class="check-note">{note}</span>'
    return '<span class="check" title="公式ドキュメントで確かめられなかった点">要確認</span>'


def build_nav(tokens: list) -> str:
    items = []
    for h1 in tokens:
        for h2 in h1.get("children", []):
            children = "".join(
                f'<li><a href="#{c["id"]}" data-step="{c["id"]}">{html.escape(c["name"])}</a></li>'
                for c in h2.get("children", [])
            )
            sub = f"<ul>{children}</ul>" if children else ""
            items.append(f'<li><a href="#{h2["id"]}">{html.escape(h2["name"])}</a>{sub}</li>')
    return "<ul>" + "".join(items) + "</ul>"


TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentCore 検証チャット 手順書</title>
<style>
:root{
  --bg:#f7f8fa; --panel:#ffffff; --text:#1f2933; --muted:#5f6b7a; --line:#e2e6eb;
  --accent:#1f6fb2; --accent-soft:#e8f1fa; --code-bg:#0f1720; --code-text:#e6edf3;
  --inline-bg:#eef1f5; --warn:#a15c00; --warn-bg:#fff3dc; --ok:#1d7a4c; --ok-bg:#e4f5ec;
  --th:#f0f3f7; --zebra:#fafbfc;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0e1319; --panel:#151c24; --text:#e3e8ee; --muted:#9aa6b4; --line:#26313d;
    --accent:#6cb4f0; --accent-soft:#16283a; --code-bg:#0a0f14; --code-text:#e6edf3;
    --inline-bg:#1f2a36; --warn:#f2b45a; --warn-bg:#3a2a10; --ok:#5fd19a; --ok-bg:#12301f;
    --th:#1b2430; --zebra:#17202a;
  }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:"Yu Gothic UI","Meiryo","Hiragino Sans","Noto Sans JP",system-ui,sans-serif;
  font-size:15.5px;line-height:1.8}
.layout{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:100vh}
nav.toc{position:sticky;top:0;height:100vh;overflow-y:auto;padding:24px 18px;
  border-right:1px solid var(--line);background:var(--panel);font-size:13.5px;line-height:1.55}
nav.toc .brand{font-weight:700;font-size:15px;margin:0 0 4px}
nav.toc .progress{margin:10px 0 18px;color:var(--muted)}
nav.toc .bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:6px}
nav.toc .bar span{display:block;height:100%;width:0;background:var(--ok);transition:width .2s}
nav.toc ul{list-style:none;margin:0;padding:0}
nav.toc > ul > li{margin:0 0 10px}
nav.toc > ul > li > a{font-weight:700;color:var(--text)}
nav.toc ul ul{margin:4px 0 0 6px;padding-left:8px;border-left:2px solid var(--line)}
nav.toc ul ul li{margin:2px 0}
nav.toc a{color:var(--muted);text-decoration:none;display:block;padding:2px 6px;border-radius:5px}
nav.toc a:hover{background:var(--accent-soft);color:var(--accent)}
nav.toc a.active{background:var(--accent-soft);color:var(--accent)}
nav.toc a.done::before{content:"✓ ";color:var(--ok);font-weight:700}
main{padding:40px 48px 120px;max-width:1040px;width:100%}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:26px 28px;margin-bottom:28px}
.hero h1{margin:0 0 6px;font-size:26px;line-height:1.4}
.hero p{margin:0;color:var(--muted)}
.hero .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:2px 12px;font-size:13px}
article > h1:first-child, article > h1:first-child + ul, article > h1:first-child + ul + hr{display:none}
article > h2:first-of-type{border-top:none;margin-top:8px;padding-top:0}
h2{font-size:22px;margin:56px 0 14px;padding-top:18px;border-top:2px solid var(--line)}
h3{font-size:17.5px;margin:34px 0 10px;display:flex;align-items:center;gap:10px}
h3 .step-done{margin-left:auto;font-size:13px;font-weight:400;color:var(--muted);
  display:inline-flex;align-items:center;gap:6px;cursor:pointer;user-select:none;
  border:1px solid var(--line);border-radius:999px;padding:2px 12px;background:var(--panel)}
h3 .step-done input{accent-color:var(--ok);margin:0}
h3.is-done .step-done{background:var(--ok-bg);color:var(--ok);border-color:transparent}
p,li{overflow-wrap:anywhere}
a{color:var(--accent)}
strong{font-weight:700}
code{font-family:"Cascadia Code","Consolas",ui-monospace,monospace;font-size:.88em;
  background:var(--inline-bg);padding:1px 6px;border-radius:5px}
pre{position:relative;background:var(--code-bg);color:var(--code-text);border-radius:10px;
  padding:16px 18px;overflow-x:auto;line-height:1.6;margin:12px 0}
pre code{background:none;padding:0;font-size:13.5px;color:inherit;white-space:pre}
.copy{position:absolute;top:8px;right:8px;font:inherit;font-size:12px;cursor:pointer;
  background:#2a3644;color:#e6edf3;border:1px solid #3b4a5c;border-radius:6px;padding:2px 10px}
.copy:hover{background:#34445a}
.table-wrap{overflow-x:auto;margin:12px 0;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.6}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--th);white-space:nowrap}
tr:nth-child(even) td{background:var(--zebra)}
tr:last-child td{border-bottom:none}
.check{display:inline-block;background:var(--warn-bg);color:var(--warn);font-size:12px;font-weight:700;
  border-radius:5px;padding:0 7px;margin:0 2px;line-height:1.7;white-space:nowrap}
.check-note{color:var(--warn);font-size:13px;margin-left:2px}
figure.diagram{margin:16px 0;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
figure.diagram img{width:100%;height:auto;display:block}
figcaption{color:var(--muted);font-size:13px;margin-top:6px;text-align:center}
blockquote{margin:14px 0;padding:12px 16px;border-left:4px solid var(--accent);background:var(--accent-soft);border-radius:0 10px 10px 0}
blockquote p{margin:0}
hr{border:none;border-top:1px solid var(--line);margin:28px 0}
.menu-btn{display:none}
@media (max-width: 900px){
  .layout{grid-template-columns:minmax(0,1fr)}
  nav.toc{position:fixed;inset:0 25% 0 0;z-index:10;transform:translateX(-105%);transition:transform .2s;
    box-shadow:0 0 24px rgba(0,0,0,.25)}
  body.nav-open nav.toc{transform:none}
  main{padding:20px 16px 100px}
  .menu-btn{display:inline-block;position:fixed;right:16px;bottom:16px;z-index:11;font:inherit;
    background:var(--accent);color:#fff;border:none;border-radius:999px;padding:10px 18px;
    box-shadow:0 4px 14px rgba(0,0,0,.25)}
  h3{flex-wrap:wrap}
  h3 .step-done{margin-left:0}
}
@media print{
  nav.toc,.menu-btn,.copy,.step-done{display:none!important}
  .layout{display:block} main{max-width:none;padding:0}
}
</style>
</head>
<body>
<div class="layout">
  <nav class="toc" aria-label="目次">
    <p class="brand">AgentCore 検証チャット 手順書</p>
    <div class="progress"><span id="progress-text">0 / 0 手順 済み</span><div class="bar"><span id="progress-bar"></span></div></div>
    __NAV__
  </nav>
  <main>
    <header class="hero">
      <h1>黒澤クエスト AgentCore 検証チャット 構築手順書</h1>
      <p>ローカルPC → SSM → EC2 → AgentCore Runtime → LLM・ナレッジベース・S3・Lambda を、自分の AWS アカウントに作る手順です。</p>
      <div class="chips"><span class="chip">東京リージョン ap-northeast-1</span><span class="chip">AWS 初心者向け</span><span class="chip">公式ドキュメント確認日 2026-11-20</span><span class="chip">各手順の「済」は、このブラウザに保存されます</span></div>
    </header>
    <article>
__BODY__
    </article>
  </main>
</div>
<button class="menu-btn" type="button" aria-label="目次を開く">目次</button>
<script>
(function(){
  // コードのコピー
  document.querySelectorAll("pre").forEach(function(pre){
    var btn=document.createElement("button");btn.className="copy";btn.type="button";btn.textContent="コピー";
    btn.addEventListener("click",function(){
      var text=pre.querySelector("code")?pre.querySelector("code").innerText:pre.innerText;
      var done=function(){btn.textContent="コピーしました";setTimeout(function(){btn.textContent="コピー"},1500)};
      if(navigator.clipboard){navigator.clipboard.writeText(text).then(done,function(){fallback(text);done()})}else{fallback(text);done()}
    });
    pre.appendChild(btn);
  });
  function fallback(text){var t=document.createElement("textarea");t.value=text;document.body.appendChild(t);t.select();try{document.execCommand("copy")}catch(e){}document.body.removeChild(t)}

  // 手順の「済」チェック（このブラウザに保存）
  var KEY="kq-guide-done";var state={};
  try{state=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){state={}}
  function save(){try{localStorage.setItem(KEY,JSON.stringify(state))}catch(e){}}
  // 作業の章（2〜13章）の手順だけに付ける
  var steps=Array.prototype.slice.call(document.querySelectorAll("article h3[id]")).filter(function(h){
    var m=/^s-(\d+)-/.exec(h.id);return m&&+m[1]>=2&&+m[1]<=13});
  steps.forEach(function(h){
    var label=document.createElement("label");label.className="step-done";
    var box=document.createElement("input");box.type="checkbox";box.checked=!!state[h.id];
    label.appendChild(box);label.appendChild(document.createTextNode("済"));h.appendChild(label);
    box.addEventListener("change",function(){state[h.id]=box.checked;save();refresh()});
  });
  function refresh(){
    var n=0;steps.forEach(function(h){var on=!!state[h.id];if(on)n++;h.classList.toggle("is-done",on);
      var a=document.querySelector('nav.toc a[data-step="'+h.id+'"]');if(a)a.classList.toggle("done",on)});
    document.getElementById("progress-text").textContent=n+" / "+steps.length+" 手順 済み";
    document.getElementById("progress-bar").style.width=(steps.length?n*100/steps.length:0)+"%";
  }
  refresh();

  // いま読んでいる章を目次で光らせる
  var links={};document.querySelectorAll("nav.toc a").forEach(function(a){links[a.getAttribute("href").slice(1)]=a});
  if("IntersectionObserver" in window){
    var io=new IntersectionObserver(function(entries){entries.forEach(function(e){
      if(e.isIntersecting&&links[e.target.id]){Object.keys(links).forEach(function(k){links[k].classList.remove("active")});links[e.target.id].classList.add("active")}})},{rootMargin:"0px 0px -75% 0px"});
    document.querySelectorAll("article h2[id], article h3[id]").forEach(function(h){io.observe(h)});
  }

  // スマホ幅での目次の開け閉め
  var btn=document.querySelector(".menu-btn");
  btn.addEventListener("click",function(){document.body.classList.toggle("nav-open")});
  document.querySelectorAll("nav.toc a").forEach(function(a){a.addEventListener("click",function(){document.body.classList.remove("nav-open")})});
})();
</script>
</body>
</html>
"""


def main() -> None:
    body, tokens = convert(SOURCE.read_text(encoding="utf-8"))
    page = TEMPLATE.replace("__NAV__", build_nav(tokens)).replace("__BODY__", decorate(body))
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"できました: {OUTPUT}")


if __name__ == "__main__":
    main()
