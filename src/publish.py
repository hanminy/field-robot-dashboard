"""Export only the field-robot dashboard and explicitly selected research notes."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, quote

from bs4 import BeautifulSoup
from PIL import Image
import markdown
import dashboard_renderer as renderer

FIELD = Path('02_research/필드로봇')
DASHBOARD = FIELD / '통합대시보드'
MAIN = '필드로봇_연구통합_대시보드.html'
IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


class Exporter:
    def __init__(self, vault: Path, output: Path):
        self.vault, self.output = vault.resolve(), output.resolve()
        self.root = self.vault / DASHBOARD
        self.assets = {}
        self.notes = {}
        self.omitted = set()
        self.files_by_name = {}
        for base in (self.vault / FIELD, self.vault / 'attachments'):
            for path in base.rglob('*'):
                if path.is_file():
                    self.files_by_name.setdefault(path.name, []).append(path)

    def resolve(self, value, source):
        value = unquote(value).replace('\\', '/')
        if re.match(r'^[A-Za-z]:/', value):
            marker = '/obsidian_work/'
            if marker not in value:
                return None
            value = value.split(marker, 1)[1]
        variants = [value] if value.endswith('.md') else [value, value + '.md']
        for candidate in [base / variant for variant in variants
                          for base in (source.parent, self.vault)]:
            candidate = candidate.resolve()
            if candidate.is_relative_to(self.vault) and candidate.is_file():
                return candidate
        matches = self.files_by_name.get(Path(value).name, [])
        if not matches:
            matches = self.files_by_name.get(Path(value).name + '.md', [])
        return matches[0] if len(matches) == 1 else None

    def write(self, relative, content):
        path = self.output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def asset(self, source):
        source = source.resolve()
        if source in self.assets:
            return self.assets[source]
        if not any(source.is_relative_to(self.vault / p) for p in (FIELD, Path('attachments'))):
            raise ValueError('Image outside publication scope')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:24]
        target = Path('media') / (digest + '.webp')
        destination = self.output / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            with Image.open(source) as image:
                image.save(destination, 'WEBP', lossless=True, method=0)
        self.assets[source] = target
        return target

    def note_path(self, source):
        digest = hashlib.sha256(source.relative_to(self.vault).as_posix().encode()).hexdigest()[:16]
        return Path('notes') / (digest + '.html')

    def link(self, raw, source, target, image=False):
        parsed = urlsplit(raw)
        if parsed.scheme in {'https', 'http', 'mailto'} or raw.startswith(('#', 'data:image/')):
            return raw
        if parsed.scheme and parsed.scheme not in {'file'}:
            return None
        path = self.resolve(parsed.path, source)
        if path is None:
            self.omitted.add(raw)
            return None
        if path.is_relative_to(self.root) and path.suffix in {'.html', '.css', '.js'}:
            destination = path.relative_to(self.root)
        elif path in self.notes:
            destination = self.notes[path]
        elif path.suffix.lower() in IMAGES:
            destination = self.asset(path)
        else:
            self.omitted.add(path.suffix)
            return None
        url = quote(os.path.relpath(destination, target.parent), safe='/')
        return url + ('#' + parsed.fragment if parsed.fragment else '')

    def rewrite(self, content, source, target):
        soup = BeautifulSoup(content, 'html.parser')
        for tag in soup.select('[href], [src]'):
            attr = 'href' if tag.has_attr('href') else 'src'
            raw = tag[attr]
            url = self.link(raw, source, target, tag.name == 'img')
            if url:
                tag[attr] = url
            elif tag.name == 'a':
                tag.name = 'span'
                del tag[attr]
                tag['title'] = 'Obsidian 볼트에서 확인할 수 있는 자료'
                if 'pdf-btn' in tag.get('class', []) or 'pdf-link' in tag.get('class', []):
                    tag.string = '📄 원문 · Obsidian'
            elif tag.name == 'img':
                tag.replace_with(soup.new_string(tag.get('alt', '이미지')))
            else:
                raise ValueError(f'Missing asset: {source.name}: {raw}')
        # Hide machine-specific evidence paths while retaining meaningful filenames.
        for tag in soup.find_all(['a', 'span']):
            if tag.string and str(tag.string).startswith(('../../../', 'C:/Users/')):
                tag.string = Path(str(tag.string)).name
        script = soup.new_tag('script', src=os.path.relpath('assets/live.js', target.parent))
        soup.body.append(script)
        return str(soup)

    def render_note(self, source, target):
        text = source.read_text(encoding='utf-8')
        text = re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.S)
        text = re.sub(r'%%.*?%%', '', text, flags=re.S)
        def wikilink(match):
            embedded, value = match.groups()
            path, _, label = value.partition('|')
            label = label or Path(path.split('#')[0]).stem
            return (f'<img src="{html.escape(path, quote=True)}" alt="{html.escape(label, quote=True)}">'
                    if embedded else f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>')
        text = re.sub(r'(!?)\[\[([^\]]+)\]\]', wikilink, text)
        content = markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists', 'toc'])
        # Notes are content, never executable web pages.
        clean = BeautifulSoup(content, 'html.parser')
        for tag in clean.find_all(['script', 'iframe', 'object', 'embed', 'style']):
            tag.decompose()
        for tag in clean.find_all(True):
            for attr in list(tag.attrs):
                if attr.startswith('on'):
                    del tag[attr]
        title = html.escape(source.stem)
        page = f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title></head><body><nav><a href="../index.html">← 대시보드</a> · <a href="index.html">요약 노트 목록</a></nav><main><h1>{title}</h1>{clean}</main></body></html>'
        page = self.rewrite(page, source, target)
        # Generated navigation is already site-relative, so add it after source resolution.
        soup = BeautifulSoup(page, 'html.parser')
        soup.nav.clear()
        soup.nav.append(BeautifulSoup('<a href="../index.html">← 대시보드</a> · <a href="index.html">요약 노트 목록</a>', 'html.parser'))
        soup.head.append(BeautifulSoup('<link rel="stylesheet" href="../assets/notes.css">', 'html.parser'))
        self.write(target, str(soup))

    def build(self, revision):
        if self.output.exists() and any(self.output.iterdir()):
            raise ValueError('Output directory must be empty')
        self.output.mkdir(parents=True, exist_ok=True)
        renderer.ROOT = self.root
        renderer.WORKTREE_VAULT = self.vault
        renderer.DATA_DIR = self.root / 'data'
        renderer.FRAGMENT_DIR = renderer.DATA_DIR / 'fragments'
        renderer.ENRICHED_DIR = renderer.DATA_DIR / 'enriched'
        renderer.IMAGE_MAP_PATH = renderer.DATA_DIR / 'image_map.json'
        records, manifest = renderer.load_records()
        records = renderer.merge_enriched(records)
        images = renderer.load_image_map(records)
        # Encode the independent figure images concurrently. Pillow releases the GIL.
        assets = sorted({p.resolve() for folder in ('images', 'detail/figs')
                         for p in (self.root / folder).rglob('*')
                         if p.suffix.lower() in IMAGES})
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.asset, assets))
        # Explicit linked notes plus new summary notes; unrelated vault notes stay private.
        for record in records:
            links = [x['path'] for x in record['source_links']] + record['evidence_sources']
            for raw in links:
                path = self.resolve(raw, self.root / MAIN)
                if path and path.suffix == '.md' and path.is_relative_to(self.vault / FIELD):
                    self.notes[path] = self.note_path(path)
        for path in (self.vault / FIELD).rglob('*요약.md'):
            if not path.is_relative_to(self.root):
                self.notes[path] = self.note_path(path)
        shutil.copytree(self.root / 'assets', self.output / 'assets')
        (self.output / 'detail').mkdir()
        shutil.copy2(self.root / 'detail/paper.css', self.output / 'detail/paper.css')
        main = renderer.v2_render_dashboard(records, manifest, images)
        main = self.rewrite(main, self.root / MAIN, Path(MAIN))
        soup = BeautifulSoup(main, 'html.parser')
        soup.header.append(BeautifulSoup('<p><a href="notes/index.html">📚 Obsidian 요약 노트 · 자동 동기화</a></p>', 'html.parser'))
        self.write(MAIN, str(soup))
        self.write('index.html', str(soup))
        for index, record in enumerate(records):
            target = Path(record['detail_page'])
            previous = records[index - 1] if index else None
            following = records[index + 1] if index + 1 < len(records) else None
            page = renderer.v2_render_detail(record, previous, following, images[record['rank']])
            page = self.rewrite(page, self.root / target, target)
            # Surface current Markdown separately from the reviewed dashboard prose.
            note_links = []
            for raw in [x['path'] for x in record['source_links']] + record['evidence_sources']:
                path = self.resolve(raw, self.root / MAIN)
                if path in self.notes:
                    href = '../' + self.notes[path].as_posix()
                    link = f'<li><a href="{href}">{html.escape(path.stem)}</a></li>'
                    if link not in note_links:
                        note_links.append(link)
            if note_links:
                page = page.replace('<main>', '<main><aside class="callout note"><b>Obsidian 최신 요약·근거 노트</b><ul>' + ''.join(note_links) + '</ul></aside>', 1)
            self.write(target, page)
        for source, target in sorted(self.notes.items()):
            self.render_note(source, target)
        items = ''.join(f'<li><a href="{target.name}">{html.escape(source.stem)}</a></li>' for source, target in sorted(self.notes.items()))
        self.write('notes/index.html', '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="../assets/notes.css"><title>Obsidian 요약 노트</title></head><body><nav><a href="../index.html">← 대시보드</a></nav><main><h1>Obsidian 요약 노트</h1><p>볼트에 저장된 요약과 근거 노트를 배포 때마다 갱신합니다.</p><ul>' + items + '</ul></main><script src="../assets/live.js"></script></body></html>')
        self.write('assets/notes.css', 'body{background:#0f1115;color:#e6e9ef;font:17px/1.8 system-ui;margin:0;padding:24px;overflow-wrap:anywhere}main,nav{max-width:1000px;margin:auto}a{color:#79b5ff}img{max-width:100%;height:auto}table{display:block;overflow:auto;border-collapse:collapse}td,th{border:1px solid #454952;padding:8px}pre{overflow:auto;background:#181b22;padding:16px}blockquote{border-left:3px solid #79b5ff;margin:16px 0;padding:4px 18px}h1{font-size:28px}nav{margin-bottom:24px}')
        self.write('assets/live.js', '''(() => {
  const base = new URL('../version.json', document.currentScript.src);
  const current = document.querySelector('meta[name="deployment-revision"]')?.content;
  async function check() {
    if (document.hidden || !current) return;
    try {
      const url = new URL(base); url.searchParams.set('t', Date.now());
      const response = await fetch(url, {cache: 'no-store'});
      if (!response.ok) return;
      const next = await response.json();
      if (next.revision && next.revision !== current) {
        const page = new URL(location.href);
        page.searchParams.set('v', next.revision);
        location.replace(page);
      }
    } catch (_) { /* Offline viewing remains available. */ }
  }
  setInterval(check, 60000);
  document.addEventListener('visibilitychange', check);
})();
''')
        for path in self.output.rglob('*.html'):
            content = path.read_text(encoding='utf-8')
            content = content.replace('</head>', f'<meta name="deployment-revision" content="{html.escape(revision, quote=True)}"></head>')
            path.write_text(content, encoding='utf-8')
        result = {'revision': revision, 'published_at': datetime.now(timezone.utc).isoformat(), 'papers': len(records), 'notes': len(self.notes), 'images': len(self.assets)}
        self.write('version.json', json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        self.write('.nojekyll', '')
        validate(self.output)
        print(json.dumps(result, ensure_ascii=False))


def validate(root):
    errors = []
    for path in root.rglob('*.html'):
        soup = BeautifulSoup(path.read_text(encoding='utf-8'), 'html.parser')
        for tag in soup.select('[href], [src], [data-detail]'):
            for attr in ('href', 'src', 'data-detail'):
                raw = tag.get(attr)
                if not raw or raw.startswith('#') or urlsplit(raw).scheme:
                    continue
                target = (path.parent / unquote(urlsplit(raw).path)).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    errors.append(f'{path.relative_to(root)}: {raw}')
    if errors:
        raise ValueError('Broken public links:\n' + '\n'.join(errors[:30]))
    if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) > 950_000_000:
        raise ValueError('Site exceeds publication size budget')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    Exporter(args.vault, args.output).build(args.revision)
