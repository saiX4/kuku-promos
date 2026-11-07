"""Build one self-contained HTML report with accessible conversation dialogs."""
import html
from pathlib import Path


def escape(value):
    return html.escape(str(value), quote=True)


def conversation_markup(promo):
    entries = promo['transcript']
    lead = next((e['speaker'] for e in entries if e['kind'] == 'dialogue'), '')
    lines = []
    for entry in entries:
        stamp = f'{escape(entry["start_timestamp"])} &ndash; {escape(entry["end_timestamp"])}'
        if entry['kind'] == 'action':
            lines.append(f'<div class="action"><time>{stamp}</time><p>{escape(entry["content"])}</p></div>')
        else:
            side = ' reply' if entry['speaker'] != lead else ''
            lines.append(f'<div class="utterance{side}"><div class="speaker">{escape(entry["speaker"])}<time>{stamp}</time></div><p>{escape(entry["content"])}</p></div>')
    return '\n'.join(lines) or '<p class="empty">No dialogue or action entries in this clip.</p>'


def render_report(output, promos):
    cards, templates = [], []
    for promo in sorted(promos, key=lambda item: item['rank']):
        rank = int(promo['rank'])
        segments = '<br>'.join(f'{escape(s["start_timestamp"])} &ndash; {escape(s["end_timestamp"])}' for s in promo['segments'])
        cards.append(f'''<article class="promo" role="button" tabindex="0" aria-haspopup="dialog" aria-controls="conversation" aria-label="Open conversation for promo {rank}, {escape(promo['episode_id'])}" data-conversation="clip-{rank}" data-title="#{rank} · {escape(promo['episode_id'])}" data-timing="{escape(promo['segments'][0]['start_timestamp'])} – {escape(promo['segments'][0]['end_timestamp'])}">
<div class="card-header"><div class="identity"><span class="rank">{rank:02d}</span><h2>{escape(promo['episode_id'])}</h2></div><div class="score">{promo['viral_score']:g}<span>/100</span></div></div>
<div class="meta"><span>{segments}</span><span class="dot">·</span><span>{promo['duration_sec']:.2f} seconds</span></div>
<div class="moment"><h3>Hook</h3><blockquote>{escape(promo['hook']['quote'])}</blockquote></div>
<div class="moment"><h3>Cliffhanger</h3><blockquote>{escape(promo['cliffhanger']['quote'])}</blockquote></div>
<p class="reason">{escape(promo['justification'])}</p>
<div class="card-footer"><span>View conversation</span><span aria-hidden="true">↗</span></div>
</article>''')
        templates.append(f'<template id="clip-{rank}">{conversation_markup(promo)}</template>')
    content = '\n'.join(cards) or '<p class="empty">No standalone promos met the selection rules.</p>'
    page = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>Find the Promos</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#23263b;background:#f6f7fb;font-synthesis:none;-webkit-font-smoothing:antialiased}*{box-sizing:border-box}body{margin:0}body.modal-open{overflow:hidden}.page{max-width:860px;margin:auto;padding:54px 24px 70px}h1{font-size:clamp(30px,5vw,42px);letter-spacing:-1.8px;line-height:1.2;font-weight:750;margin:0 0 36px}.promo{background:white;border:1px solid #e2e5ef;border-radius:20px;margin-bottom:22px;padding:28px 30px 0;cursor:pointer;box-shadow:0 4px 16px #26325304;transition:border-color .18s,box-shadow .18s,transform .18s}.promo:hover{border-color:#bcb0e6;box-shadow:0 12px 32px #44316c0c;transform:translateY(-2px)}.promo:focus-visible,.close:focus-visible{outline:3px solid #8a6bda;outline-offset:4px}.card-header,.identity{display:flex;align-items:center}.card-header{justify-content:space-between;gap:16px}.identity{gap:14px}.rank{display:inline-grid;place-items:center;border-radius:11px;min-width:42px;height:42px;padding:0 8px;background:#f0ebfc;color:#7354bd;font-size:14px;font-weight:750;font-variant-numeric:tabular-nums}h2{font-size:21px;font-weight:700;letter-spacing:-.4px;margin:0}.score{font-size:25px;font-weight:700;color:#514373;white-space:nowrap}.score span{font-size:12px;font-weight:500;color:#9a95a6;margin-left:3px}.meta{display:flex;align-items:center;flex-wrap:wrap;gap:9px;color:#83889a;font-size:12px;font-variant-numeric:tabular-nums;margin:16px 0 25px;padding-bottom:20px;border-bottom:1px solid #eff0f6}.dot{color:#c5c8d2}.moment{margin:0 0 22px}h3{font-size:10px;text-transform:uppercase;letter-spacing:1.6px;font-weight:750;color:#8a79a8;margin:0 0 8px}blockquote{font-size:16px;line-height:1.7;margin:0;overflow-wrap:anywhere}.reason{font-size:13px;line-height:1.75;color:#818596;border-top:1px solid #eff0f6;margin:0;padding:19px 0 22px;overflow-wrap:anywhere}.card-footer{display:flex;justify-content:space-between;align-items:center;padding:15px 0 18px;border-top:1px solid #eff0f6;color:#8063b4;font-size:12px;font-weight:600}.card-footer span:last-child{font-size:18px}.empty{padding:30px;border:1px solid #e2e5ef;background:white;border-radius:16px;color:#818596}
dialog{border:1px solid #e6e1f0;border-radius:22px;padding:0;width:min(760px,calc(100% - 32px));max-height:calc(100dvh - 64px);color:#26283c;background:#fafafe;box-shadow:0 35px 120px #18142c45;overflow:hidden}dialog[open]{display:flex;flex-direction:column}dialog::backdrop{background:#17142880;backdrop-filter:blur(5px)}.dialog-header{display:flex;justify-content:space-between;gap:18px;padding:25px 28px 22px;border-bottom:1px solid #e9e7f0;background:white;flex:none}.dialog-header h2{font-size:20px;margin:4px 0 8px}.dialog-header p{font-size:12px;color:#9692a1;margin:0;font-variant-numeric:tabular-nums}.eyebrow{font-size:9px;font-weight:750;letter-spacing:1.7px;text-transform:uppercase;color:#9b87bb}.close{flex:none;width:36px;height:36px;border:1px solid #e6e2ed;background:#faf9fd;border-radius:10px;font-size:25px;line-height:1;color:#82758f;cursor:pointer;display:grid;place-items:center}.close:hover{color:#4f3675;background:#f0ebf9}.conversation{padding:28px;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#d2c7e4 transparent}.utterance{max-width:90%;margin:0 0 23px}.speaker{display:flex;align-items:center;flex-wrap:wrap;gap:6px 12px;font-size:10px;font-weight:750;letter-spacing:.6px;color:#8b75ac;margin-bottom:8px}time{font-weight:450;letter-spacing:0;color:#9f9aa9;font-size:10px;font-variant-numeric:tabular-nums}.utterance p{font-size:15px;line-height:1.75;margin:0;padding:16px 20px;border:1px solid #e6e0f0;border-radius:3px 15px 15px;background:#f0ebf8;overflow-wrap:anywhere}.reply{margin-left:auto}.reply .speaker{justify-content:flex-end}.reply p{border-color:#e4e6ed;border-radius:15px 3px 15px 15px;background:white}.action{text-align:center;margin:0 auto 25px;max-width:88%;padding:2px 8px}.action p{font-size:12px;font-style:italic;line-height:1.75;color:#93909f;margin:6px 0 0;overflow-wrap:anywhere}
@media(max-width:540px){.page{padding:32px 16px 45px}h1{margin-bottom:26px}.promo{padding:22px 20px 0;border-radius:16px}h2{font-size:18px}.identity{gap:10px}.rank{min-width:36px;height:36px;font-size:12px}.score{font-size:22px}blockquote{font-size:15px}.dialog-header{padding:20px}.conversation{padding:22px 18px}.utterance{max-width:96%}.utterance p{font-size:14px;padding:14px 16px}dialog{max-height:calc(100dvh - 32px);border-radius:16px}.speaker{font-size:9px;letter-spacing:.3px}}
@media(prefers-reduced-motion:reduce){.promo{transition:none}.promo:hover{transform:none}}@media print{body{background:white}.page{max-width:none;padding:0}.promo{break-inside:avoid;box-shadow:none}.card-footer,dialog{display:none!important}}
</style></head><body><main class="page"><h1>Find the Promos</h1>
''' + content + '''
</main>
<dialog id="conversation" aria-labelledby="conversation-title" aria-describedby="conversation-timing">
<header class="dialog-header"><div><div class="eyebrow">Conversation</div><h2 id="conversation-title"></h2><p id="conversation-timing"></p></div><button class="close" type="button" aria-label="Close conversation" autofocus>×</button></header>
<div class="conversation" id="conversation-body"></div></dialog>
''' + '\n'.join(templates) + '''
<script>
const dialog=document.getElementById('conversation');
const body=document.getElementById('conversation-body');
let opener=null;
function openConversation(card){
  opener=card;
  document.getElementById('conversation-title').textContent=card.dataset.title;
  document.getElementById('conversation-timing').textContent=card.dataset.timing;
  body.replaceChildren(document.getElementById(card.dataset.conversation).content.cloneNode(true));
  dialog.showModal();
  body.scrollTop=0;
  document.body.classList.add('modal-open');
}
document.querySelectorAll('[data-conversation]').forEach(card=>{
  card.addEventListener('click',()=>openConversation(card));
  card.addEventListener('keydown',event=>{
    if(event.key==='Enter'||event.key===' '){event.preventDefault();openConversation(card);}
  });
});
dialog.querySelector('.close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{
  if(event.target!==dialog)return;
  const r=dialog.getBoundingClientRect();
  if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();
});
dialog.addEventListener('close',()=>{
  document.body.classList.remove('modal-open');
  if(opener)opener.focus({preventScroll:true});
});
</script></body></html>
'''
    # Replace atomically: a failed write must not leave a half-rendered report.
    path = Path(output) / 'report.html'
    temporary = path.with_suffix('.html.tmp')
    temporary.write_text(page, encoding='utf-8')
    temporary.replace(path)
