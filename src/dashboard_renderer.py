#!/usr/bin/env python3
"""Build the offline field-robot research dashboard from reviewed JSON fragments."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
WORKTREE_VAULT = ROOT.parents[2]
CANONICAL_VAULT = Path(r"C:/Users/hmlee/Documents/obsidian_work")
DATA_DIR = ROOT / "data"
FRAGMENT_DIR = DATA_DIR / "fragments"
DETAIL_DIR = ROOT / "detail"
ASSET_DIR = ROOT / "assets"
IMAGE_DIR = ROOT / "images"
IMAGE_MAP_PATH = DATA_DIR / "image_map.json"
ENRICHED_DIR = DATA_DIR / "enriched"

CATEGORIES = [
    "환경인식",
    "측위·매핑",
    "작업·궤적계획",
    "제어·MPC",
    "학습·RL·IL·VLA",
    "안전·HRI",
    "시스템통합·현장실증",
    "서베이·산업동향",
]

REQUIRED_FIELDS = [
    "id",
    "rank",
    "title",
    "title_ko",
    "institution",
    "year",
    "publication",
    "category",
    "secondary_categories",
    "platform",
    "environment",
    "methods",
    "one_line",
    "summary",
    "source_kind",
    "source_links",
    "detail_page",
    "evidence_sources",
]

DETAIL_FIELDS = [
    "problem",
    "approach",
    "system",
    "experiment",
    "results",
    "limitations",
    "connection",
]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def clean_text(value, fallback=""):
    if value is None:
        return fallback
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or fallback


def clean_path(value):
    """Trim path edges without changing significant repeated spaces in filenames."""
    if value is None:
        return ""
    return str(value).strip()


def portable_vault_path(value):
    """Serialize local vault links independently of canonical/worktree location."""
    raw = clean_path(value)
    if not raw or re.match(r"^(?:https?://|mailto:|#)", raw, flags=re.I):
        return raw
    path = Path(raw)
    candidates = [path.resolve()] if path.is_absolute() else [(ROOT / path).resolve()]
    for candidate in candidates:
        for vault_root in (CANONICAL_VAULT, WORKTREE_VAULT):
            try:
                relative = candidate.relative_to(vault_root.resolve())
            except ValueError:
                continue
            return (Path("../../..") / relative).as_posix()
    return raw


def normalize_supported_meta(value):
    """Keep only the evidence-backed portion of a metadata string."""
    text = clean_text(value)
    if "확인 필요" not in text:
        return text
    text = re.sub(r"\s*[,;/·-]?\s*(?:세부\s+)?서지\s+확인\s+필요.*$", "", text)
    text = text.replace("확인 필요", "")
    return text.strip(" \t,;/·-:.")


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    text = re.sub(r"\([^)]*(?:요약|슬라이드|인포그래픽|html)[^)]*\)", " ", text)
    text = re.sub(r"[_\-–—:·•/\\()[\]{}'\".,!?]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def unique_strings(values):
    seen = set()
    result = []
    for value in values or []:
        value = clean_text(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def unique_paths(values):
    seen = set()
    result = []
    for value in values or []:
        value = clean_path(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_link(link):
    if isinstance(link, str):
        link = {"kind": "관련 자료", "label": Path(link).name, "path": link, "available": True}
    path = clean_path(link.get("path") or link.get("href"))
    kind = clean_text(link.get("kind"), "관련 자료")
    label = clean_text(link.get("label"), Path(path).name if path else kind)
    available = bool(link.get("available", bool(path)))
    return {"kind": kind, "label": label, "path": path, "available": available}


def record_key(record):
    doi = clean_text(record.get("doi")).lower()
    if doi:
        return "doi:" + doi.removeprefix("https://doi.org/").removeprefix("doi:")
    title = normalize_title(record.get("title") or record.get("title_ko"))
    return "title:" + title


def record_keys(record):
    keys = [record_key(record)]
    title_key = "title:" + normalize_title(record.get("title") or record.get("title_ko"))
    if title_key not in keys:
        keys.append(title_key)
    for link in record.get("source_links") or []:
        path = clean_path(link.get("path"))
        kind = clean_text(link.get("kind")).casefold()
        if path and ("pdf" in kind or kind in {"원문", "original"}):
            keys.append("source:" + unicodedata.normalize("NFKC", path).casefold())
    return unique_strings(keys)


def record_id(record):
    seed = record_key(record)
    return "fr-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def normalize_record(raw, fragment_name):
    title = clean_text(raw.get("title"))
    title_ko = clean_text(raw.get("title_ko"))
    if not title and not title_ko:
        raise ValueError(f"{fragment_name}: title/title_ko 모두 없음")
    if not title:
        title = title_ko
    if not title_ko:
        title_ko = title

    year = raw.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    if not isinstance(year, int) or not 1900 <= year <= 2100:
        year = None

    category = clean_text(raw.get("category"), "서베이·산업동향")
    if category not in CATEGORIES:
        raise ValueError(f"{fragment_name}: 허용되지 않은 category: {category}")
    secondary = [item for item in unique_strings(raw.get("secondary_categories")) if item in CATEGORIES and item != category]

    links = []
    seen_links = set()
    for item in raw.get("source_links") or []:
        link = normalize_link(item)
        if not link["path"]:
            continue
        key = (link["kind"], link["path"])
        if key not in seen_links:
            seen_links.add(key)
            links.append(link)

    detail_raw = raw.get("detail") or {}
    detail = {field: clean_text(detail_raw.get(field), "분석 미완료") for field in DETAIL_FIELDS}
    summary = clean_text(raw.get("summary"), "분석 미완료")
    one_line = clean_text(raw.get("one_line"), "분석 미완료")
    publication = clean_text(raw.get("publication"), "확인 필요")
    authors = unique_strings(raw.get("authors"))
    evidence_sources = unique_paths(raw.get("evidence_sources"))
    doi = clean_text(raw.get("doi"))

    metadata_gaps = []
    evidence_reasons = []
    if publication == "확인 필요":
        metadata_gaps.append("발표처 미확인")
    if not authors:
        metadata_gaps.append("저자 미확인")
    if not doi:
        metadata_gaps.append("DOI 미확인")
    if any(value == "분석 미완료" for value in detail.values()):
        evidence_reasons.append("상세 분석 일부 미완료")
    if not any(link["available"] for link in links):
        evidence_reasons.append("열 수 있는 원문·관련 자료 없음")

    result = {
        "id": record_id({"title": title, "title_ko": title_ko, "doi": doi}),
        "rank": 0,
        "title": title,
        "title_ko": title_ko,
        "institution": clean_text(raw.get("institution"), "확인 필요"),
        "year": year,
        "authors": authors,
        "publication": publication,
        "doi": doi,
        "category": category,
        "secondary_categories": secondary,
        "platform": clean_text(raw.get("platform"), "확인 필요"),
        "environment": clean_text(raw.get("environment"), "확인 필요"),
        "methods": unique_strings(raw.get("methods")),
        "one_line": one_line,
        "summary": summary,
        "source_kind": clean_text(raw.get("source_kind"), "학술 논문"),
        "source_links": links,
        "detail_page": "",
        "evidence_sources": evidence_sources,
        "detail": detail,
        "evidence_status": "근거 제한" if evidence_reasons else ("서지 일부 미확인" if metadata_gaps else "확인됨"),
        "evidence_gaps": evidence_reasons,
        "metadata_gaps": metadata_gaps,
        "provisional_key": clean_text(raw.get("provisional_key")),
        "fragment": fragment_name,
    }
    return result


def merge_records(kept, incoming):
    for field in ["authors", "methods", "secondary_categories", "evidence_sources"]:
        kept[field] = unique_strings((kept.get(field) or []) + (incoming.get(field) or []))
    link_keys = {(item["kind"], item["path"]) for item in kept["source_links"]}
    for item in incoming["source_links"]:
        if (item["kind"], item["path"]) not in link_keys:
            kept["source_links"].append(item)
            link_keys.add((item["kind"], item["path"]))
    for field in ["title", "title_ko", "institution", "publication", "platform", "environment", "one_line", "summary"]:
        current = clean_text(kept.get(field))
        candidate = clean_text(incoming.get(field))
        if current in {"", "확인 필요", "분석 미완료"} and candidate not in {"", "확인 필요", "분석 미완료"}:
            kept[field] = candidate
        elif field in {"one_line", "summary"} and len(candidate) > len(current):
            kept[field] = candidate
    if kept.get("year") is None and incoming.get("year") is not None:
        kept["year"] = incoming["year"]
    if not kept.get("doi") and incoming.get("doi"):
        kept["doi"] = incoming["doi"]
    for field in DETAIL_FIELDS:
        current = kept["detail"].get(field, "분석 미완료")
        candidate = incoming["detail"].get(field, "분석 미완료")
        if current == "분석 미완료" or (candidate != "분석 미완료" and len(candidate) > len(current)):
            kept["detail"][field] = candidate
    kept["evidence_gaps"] = unique_strings((kept.get("evidence_gaps") or []) + (incoming.get("evidence_gaps") or []))
    kept["metadata_gaps"] = unique_strings((kept.get("metadata_gaps") or []) + (incoming.get("metadata_gaps") or []))
    kept["evidence_status"] = "근거 제한" if kept["evidence_gaps"] else ("서지 일부 미확인" if kept["metadata_gaps"] else "확인됨")


def load_records():
    fragments = sorted(FRAGMENT_DIR.glob("*.json"))
    if not fragments:
        raise SystemExit("data/fragments/*.json이 없습니다.")

    manifest_sources = []
    excluded = []
    unavailable = []
    unique = {}
    key_index = {}
    duplicate_merges = []

    for path in fragments:
        payload = read_json(path)
        raw_records = payload.get("records") or []
        manifest_sources.append(
            {
                "fragment": path.relative_to(ROOT).as_posix(),
                "source": payload.get("source") or payload.get("sources") or [],
                "expected_count": payload.get("expected_count"),
                "extracted_count": len(raw_records),
                "source_accounting": payload.get("source_accounting") or {},
            }
        )
        excluded.extend(payload.get("excluded") or [])
        unavailable.extend(payload.get("unavailable_sources") or [])
        for raw in raw_records:
            record = normalize_record(raw, path.name)
            keys = record_keys(record)
            matched_key = next((key_index[key] for key in keys if key in key_index), None)
            if matched_key:
                kept = unique[matched_key]
                matching_reason = next(key for key in keys if key_index.get(key) == matched_key)
                duplicate_merges.append(
                    {
                        "kept": kept["provisional_key"] or kept["title"],
                        "merged": record["provisional_key"] or record["title"],
                        "reason": {
                            "doi": "DOI 일치",
                            "title": "정규화 제목 일치",
                            "source": "동일 원문 PDF 경로 일치",
                        }.get(matching_reason.split(":", 1)[0], "중복 키 일치"),
                    }
                )
                merge_records(kept, record)
                for key in keys:
                    key_index[key] = matched_key
            else:
                primary_key = keys[0]
                unique[primary_key] = record
                for key in keys:
                    key_index[key] = primary_key

    records = list(unique.values())
    records.sort(
        key=lambda item: (
            -(item["year"] or 0),
            item["institution"].casefold(),
            normalize_title(item["title"]),
        )
    )
    # Published addresses belong to paper IDs, not to their year-sort positions.
    saved = read_json(IMAGE_MAP_PATH).get("images", []) if IMAGE_MAP_PATH.exists() else []
    ranks = {item["id"]: item["rank"] for item in saved}
    if len(ranks) != len(saved) or len(set(ranks.values())) != len(saved):
        raise SystemExit("image_map의 id/rank는 고유해야 합니다.")
    if any(type(rank) is not int or rank < 1 for rank in ranks.values()):
        raise SystemExit("image_map rank는 양의 정수여야 합니다.")
    next_rank = max(ranks.values(), default=0) + 1
    for record in records:
        if record["id"] not in ranks:
            ranks[record["id"]] = next_rank
            next_rank += 1
        record["rank"] = ranks[record["id"]]
        record["detail_page"] = f"detail/paper-{record['rank']:03d}.html"
        record.pop("provisional_key", None)
        record.pop("fragment", None)
    records.sort(key=lambda item: item["rank"])

    manifest = build_manifest(records, manifest_sources, duplicate_merges, excluded, unavailable)
    return records, manifest


def merge_enriched(records):
    """Attach the reviewed v3 prose package without re-summarizing it."""
    enriched = []
    for path in sorted(ENRICHED_DIR.glob("*.json")):
        payload = read_json(path)
        items = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("schema_version") != 3 or not isinstance(items, list):
            raise SystemExit(f"{path.name}: schema_version=3, records 배열이 필요합니다.")
        if payload.get("record_count", len(items)) != len(items):
            raise SystemExit(f"{path.name}: record_count 불일치")
        enriched.extend(items)
    by_rank = {int(item["rank"]): item for item in enriched}
    if len(enriched) != len(records) or set(by_rank) != {record["rank"] for record in records}:
        raise SystemExit("enriched 레코드는 논문별 고유 rank와 일대일로 일치해야 합니다.")
    for record in records:
        for link in record.get("source_links", []):
            link["path"] = portable_vault_path(link.get("path"))
        record["evidence_sources"] = [portable_vault_path(path) for path in record.get("evidence_sources", [])]
        record["authors"] = [
            normalized for author in record.get("authors", [])
            if (normalized := normalize_supported_meta(author))
        ]
        record["publication"] = normalize_supported_meta(record.get("publication"))
        record["doi"] = normalize_supported_meta(record.get("doi"))
        for field in ("platform", "environment"):
            if "확인 필요" in clean_text(record.get(field)):
                record[field] = ""
        for field in DETAIL_FIELDS:
            if "확인 필요" in clean_text(record.get("detail", {}).get(field)):
                record["detail"][field] = ""
        item = by_rank[record["rank"]]
        if item.get("id") != record["id"]:
            raise SystemExit(f"enriched id 불일치: rank={record['rank']}")
        if not 120 <= len(item.get("card_summary", "")) <= 190:
            raise SystemExit(f"card_summary 길이 계약 불일치: rank={record['rank']}")
        record["card_summary"] = item["card_summary"]
        record["one_line"] = item["one_line"]
        record["sections"] = item["sections"]
        record["key_figure_labels"] = item["key_figure_labels"]
        record["evidence_pages"] = item["evidence_pages"]
    return records


def build_manifest(records, sources, duplicate_merges, excluded, unavailable):
    institutions = Counter(record["institution"] for record in records)
    primary_categories = Counter(record["category"] for record in records)
    category_tags = Counter()
    for record in records:
        category_tags.update([record["category"], *record["secondary_categories"]])
    source_kinds = Counter(record["source_kind"] for record in records)
    years = [record["year"] for record in records if record["year"]]
    grouped_assets = [
        {
            "id": record["id"],
            "title": record["title"],
            "reason": "동일 연구의 원문·요약·HTML·그림 등 파생 자료를 단일 레코드에 병합",
            "source_links": record["source_links"],
        }
        for record in records
        if len(record["source_links"]) > 1
    ]
    return {
        "generated_on": date.today().isoformat(),
        "deduplication_rules": [
            "DOI가 확인된 경우 DOI 정규화 값 우선",
            "그 외에는 영문 제목(없으면 한국어 제목)의 Unicode NFKC·소문자·구두점 제거 정규화 값 사용",
            "동일 연구의 PDF·Markdown·HTML·슬라이드·인포그래픽은 source_links로 병합",
            "정확한 목표 수에 맞추기 위한 생성·복제 금지",
        ],
        "sources": sources,
        "candidate_record_count": sum(source["extracted_count"] for source in sources),
        "duplicate_merges": duplicate_merges,
        "same_research_asset_groups": grouped_assets,
        "excluded": excluded,
        "unavailable_sources": unavailable,
        "final_count": len(records),
        "insufficient_evidence_count": sum(record["evidence_status"] == "근거 제한" for record in records),
        "metadata_gap_count": sum(bool(record.get("metadata_gaps")) for record in records),
        "institution_counts": dict(sorted(institutions.items())),
        "primary_category_counts": {category: primary_categories.get(category, 0) for category in CATEGORIES},
        "category_tag_counts": {category: category_tags.get(category, 0) for category in CATEGORIES},
        "source_kind_counts": dict(sorted(source_kinds.items())),
        "year_range": {"min": min(years) if years else None, "max": max(years) if years else None},
    }


def esc(value):
    return html.escape(clean_text(value), quote=True)


def encode_href(raw, detail=False):
    raw = clean_path(raw)
    if not raw:
        return ""
    if re.match(r"^(?:https?://|mailto:|#)", raw, flags=re.I):
        return html.escape(raw, quote=True)
    adjusted = "../" + raw if detail else raw
    return html.escape(quote(adjusted, safe="/:?=&%#.-_~"), quote=True)


def chips(values, class_name="chip"):
    return "".join(f'<span class="{class_name}">{esc(value)}</span>' for value in values if clean_text(value))


def category_class(category):
    return "cat-" + str(CATEGORIES.index(category) + 1)


def primary_link(record):
    available = [link for link in record["source_links"] if link["available"]]
    if not available:
        return None
    priority = {"pdf": 0, "원문 pdf": 0, "원문": 1, "url": 2, "md": 3, "markdown": 3, "html": 4}
    return sorted(available, key=lambda item: priority.get(item["kind"].casefold(), 9))[0]


def render_card(record):
    all_categories = [record["category"], *record["secondary_categories"]]
    search_text = " ".join(
        [
            record["title"], record["title_ko"], record["institution"],
            " ".join(record["authors"]), " ".join(record["methods"]),
            record["one_line"], record["summary"], record["publication"],
            record["platform"], record["environment"], " ".join(all_categories),
        ]
    ).casefold()
    source = primary_link(record)
    if source:
        source_button = (
            f'<a class="btn source-btn" href="{encode_href(source["path"])}" '
            f'target="_blank" rel="noopener" aria-label="{esc(record["title_ko"])} 원문 또는 근거 자료 열기">원문 보기</a>'
        )
    else:
        source_button = '<span class="btn source-btn disabled" aria-disabled="true" title="열 수 있는 원문 근거가 없습니다">원문 없음</span>'
    methods = record["methods"][:6] or ["방법 확인 필요"]
    return f'''<article class="card {category_class(record["category"])}" data-id="{record["id"]}" data-institution="{esc(record["institution"])}" data-year="{record["year"] or ''}" data-kind="{esc(record["source_kind"])}" data-categories="{esc('|'.join(all_categories))}" data-search="{esc(search_text)}">
  <div class="card-head"><span class="rank">#{record["rank"]:03d}</span><span class="institution">{esc(record["institution"])}</span><span class="year">{record["year"] or '연도 확인 필요'}</span></div>
  <div class="card-body">
    <div class="meta-row"><span class="chip primary">{esc(record["category"])}</span>{chips(record["secondary_categories"])}</div>
    <p class="title-en" lang="en">{esc(record["title"])}</p>
    <h2 class="title-ko">{esc(record["title_ko"])}</h2>
    <p class="one-line">{esc(record["one_line"])}</p>
    <div class="method-tags">{chips(methods, 'method')}</div>
    <div class="expanded-summary" id="summary-{record["id"]}" hidden><p>{esc(record["summary"])}</p><p class="evidence-state">근거 상태: {esc(record["evidence_status"])}</p></div>
  </div>
  <div class="card-actions">
    <button class="btn summary-toggle" type="button" aria-expanded="false" aria-controls="summary-{record["id"]}">요약 보기</button>
    {source_button}
    <a class="btn detail-btn" href="{record["detail_page"]}" aria-label="{esc(record["title_ko"])} 상세 요약 보기">상세 요약</a>
  </div>
</article>'''


def render_dashboard(records, manifest):
    years = [record["year"] for record in records if record["year"]]
    institutions = sorted({record["institution"] for record in records})
    source_kinds = sorted({record["source_kind"] for record in records})
    cards = "\n".join(render_card(record) for record in records)
    embedded = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    category_buttons = "".join(
        f'<button type="button" class="filter-chip {category_class(category)}" data-category="{esc(category)}" aria-pressed="false">{esc(category)}</button>'
        for category in CATEGORIES
    )
    institution_options = "".join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in institutions)
    year_options = "".join(f'<option value="{year}">{year}</option>' for year in sorted(set(years), reverse=True))
    kind_options = "".join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in source_kinds)
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>필드로봇 연구 통합 대시보드</title>
<link rel="stylesheet" href="assets/dashboard.css">
</head>
<body data-record-count="{len(records)}">
<a class="skip-link" href="#results">연구 목록으로 건너뛰기</a>
<header class="hero">
  <p class="eyebrow">FIELD ROBOTICS RESEARCH ATLAS</p>
  <h1>필드로봇 연구 통합 대시보드</h1>
  <p class="subtitle">자율굴착·건설로봇 연구를 기관, 연도, 자료 유형, 기술 분류로 탐색하는 오프라인 연구 지도</p>
  <div class="stats" aria-label="대시보드 통계">
    <div class="stat"><strong>{len(records)}</strong><span>고유 연구</span></div>
    <div class="stat"><strong>{len(institutions)}</strong><span>기관·출처</span></div>
    <div class="stat"><strong>{min(years) if years else '—'}–{max(years) if years else '—'}</strong><span>연도 범위</span></div>
    <div class="stat"><strong>{sum(1 for category in CATEGORIES if manifest['category_tag_counts'].get(category))}</strong><span>기술 분류</span></div>
  </div>
</header>

<main>
  <section class="controls" aria-label="연구 검색과 필터">
    <div class="control-top">
      <label class="search-label" for="searchInput"><span>통합 검색</span><input id="searchInput" type="search" placeholder="제목, 기관, 저자, 키워드, 요약 검색" autocomplete="off"></label>
      <label>기관<select id="institutionFilter"><option value="">전체 기관</option>{institution_options}</select></label>
      <label>연도<select id="yearFilter"><option value="">전체 연도</option>{year_options}</select></label>
      <label>자료 유형<select id="kindFilter"><option value="">전체 유형</option>{kind_options}</select></label>
      <label>정렬<select id="sortSelect"><option value="newest">최신순</option><option value="oldest">오래된순</option><option value="institution">기관순</option><option value="title">제목순</option></select></label>
    </div>
    <fieldset class="category-filter"><legend>기술 분류 · 복수 선택 가능</legend><div class="filter-chips">{category_buttons}</div></fieldset>
    <div class="control-status"><p id="resultCount" aria-live="polite"></p><button id="resetFilters" type="button" class="reset-btn">필터 초기화</button></div>
  </section>

  <section id="results" class="grid" aria-label="연구 결과" tabindex="-1">{cards}</section>
  <section id="emptyState" class="empty" hidden><h2>조건에 맞는 연구가 없습니다</h2><p>검색어 또는 필터 조합을 바꾸거나 초기화하세요.</p><button type="button" class="reset-btn">필터 초기화</button></section>
</main>

<footer>근거 자료를 재구성한 로컬 대시보드 · 생성일 {manifest['generated_on']} · 외부 CDN 없음</footer>
<script id="papers-data" type="application/json">{embedded}</script>
<script src="assets/dashboard.js" defer></script>
</body>
</html>
'''


def render_links(record, detail=True):
    items = []
    for link in record["source_links"]:
        if link["available"]:
            items.append(f'<li><a href="{encode_href(link["path"], detail=detail)}" target="_blank" rel="noopener">{esc(link["label"])}</a> <span>{esc(link["kind"])}</span></li>')
        else:
            items.append(f'<li><span class="unavailable">{esc(link["label"])} — 경로 확인 필요</span></li>')
    return "".join(items) or '<li><span class="unavailable">연결 가능한 관련 자료 없음</span></li>'


def render_evidence(record):
    items = []
    for path in record["evidence_sources"]:
        items.append(f'<li><a href="{encode_href(path, detail=True)}" target="_blank" rel="noopener">{esc(path)}</a></li>')
    return "".join(items) or "<li>직접 연결된 근거 파일 확인 필요</li>"


def detail_section(number, title, value, css=""):
    status = value == "분석 미완료"
    body = '<p class="incomplete">분석 미완료</p>' if status else f"<p>{esc(value)}</p>"
    return f'<section class="detail-section {css}"><h2><span>{number:02d}</span>{esc(title)}</h2>{body}</section>'


def render_detail(record, previous_record, next_record):
    categories = [record["category"], *record["secondary_categories"]]
    authors = ", ".join(record["authors"]) if record["authors"] else "확인 필요"
    doi = record["doi"] or "확인 필요"
    methods = record["methods"] or ["방법 키워드 확인 필요"]
    prev_html = ""
    next_html = ""
    if previous_record:
        prev_html = f'<a class="prev" href="paper-{previous_record["rank"]:03d}.html"><span>이전 연구</span>{esc(previous_record["title_ko"])}</a>'
    if next_record:
        next_html = f'<a class="next" href="paper-{next_record["rank"]:03d}.html"><span>다음 연구</span>{esc(next_record["title_ko"])}</a>'
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>{esc(record["title_ko"])} — 필드로봇 연구 통합 대시보드</title>
<link rel="stylesheet" href="paper.css">
</head>
<body>
<nav class="topbar" aria-label="상세 페이지 탐색"><a class="back-btn" href="../필드로봇_연구통합_대시보드.html">← 대시보드</a><span class="crumb">연구 #{record["rank"]:03d}</span></nav>
<header class="hero">
  <div class="badges"><span class="badge institution">{esc(record["institution"])}</span><span class="badge">{record["year"] or '연도 확인 필요'}</span>{chips(categories, 'badge')}</div>
  <p class="eyebrow">RESEARCH BRIEF · {record["id"]}</p>
  <h1>{esc(record["title_ko"])}</h1>
  <p class="title-en" lang="en">{esc(record["title"])}</p>
  <p class="authors">저자: {esc(authors)} · 발표처: {esc(record["publication"])} · DOI: {esc(doi)}</p>
</header>
<main>
  <aside class="oneliner"><strong>핵심</strong><p>{esc(record["one_line"])}</p></aside>
  <section class="summary-block"><h2><span>00</span>3줄 핵심</h2><p>{esc(record["summary"])}</p></section>
  {detail_section(1, '연구 문제', record['detail']['problem'])}
  {detail_section(2, '제안 방법과 시스템 구성', record['detail']['approach'])}
  {detail_section(3, '시스템·플랫폼', record['detail']['system'])}
  {detail_section(4, '실험 환경·장비·데이터', record['detail']['experiment'])}
  {detail_section(5, '핵심 결과와 정량 수치', record['detail']['results'])}
  {detail_section(6, '한계', record['detail']['limitations'], 'limitations')}
  {detail_section(7, '자율작업굴착기 연구와의 연결점', record['detail']['connection'], 'connection')}
  <section class="detail-section"><h2><span>08</span>키워드와 분류</h2><div class="keywords">{chips(categories + methods, 'keyword')}</div><dl class="facts"><div><dt>플랫폼</dt><dd>{esc(record['platform'])}</dd></div><div><dt>환경</dt><dd>{esc(record['environment'])}</dd></div><div><dt>자료 유형</dt><dd>{esc(record['source_kind'])}</dd></div><div><dt>근거 상태</dt><dd>{esc(record['evidence_status'])}</dd></div></dl></section>
  <section class="detail-section trace"><h2><span>09</span>원문·기존 요약·관련 자료</h2><ul class="source-list">{render_links(record)}</ul><h3>추출·교차검증 근거</h3><ul class="evidence-list">{render_evidence(record)}</ul></section>
  <nav class="pager" aria-label="이전 다음 연구">{prev_html}{next_html}</nav>
</main>
<footer><a href="../필드로봇_연구통합_대시보드.html">필드로봇 연구 통합 대시보드</a> · 근거가 없는 정보는 확인 필요 또는 분석 미완료로 표시</footer>
</body>
</html>
'''


def render_index(records, manifest):
    institutions = manifest["institution_counts"]
    categories = manifest["category_tag_counts"]
    years = manifest["year_range"]
    institution_links = "\n".join(
        f'- [{name} {count}건](필드로봇_연구통합_대시보드.html#institution={quote(name)})'
        for name, count in institutions.items()
    )
    category_links = "\n".join(
        f'- [{category} {categories.get(category, 0)}건](필드로봇_연구통합_대시보드.html#category={quote(category)})'
        for category in CATEGORIES
    )
    return f'''---
title: 필드로봇 연구 통합
aliases:
  - 필드로봇 통합 대시보드
tags:
  - 필드로봇
  - 자율굴착기
  - 연구대시보드
  - research-dashboard
date: {manifest['generated_on']}
---

# 필드로봇 연구 통합

> [!abstract] 통합 현황
> 기관별 카드 요약과 로컬 원문을 정규화 제목·DOI·원문 경로 기준으로 병합한 **{len(records)}개 고유 연구**를 수록한다. 확인되지 않은 서지·정량 정보는 만들지 않고 `확인 필요` 또는 `분석 미완료`로 표시한다.

## 대시보드

- [필드로봇 연구 통합 대시보드 열기](필드로봇_연구통합_대시보드.html)
- 데이터: [papers.json](data/papers.json)
- 추출·중복·제외 근거: [manifest.json](data/manifest.json)
- 구조와 갱신 방법: [[README]]

## 전체 통계

| 항목 | 값 |
|---|---:|
| 고유 연구 | {len(records)} |
| 기관·출처 | {len(institutions)} |
| 연도 범위 | {years['min'] or '확인 필요'}–{years['max'] or '확인 필요'} |
| 상세 분석 미완료·원문 부재 | {manifest['insufficient_evidence_count']} |
| 서지 메타데이터 일부 미확인 | {manifest['metadata_gap_count']} |

## 기관별 바로가기

{institution_links}

## 기술별 바로가기

{category_links}

## 자료 범위

- ETH 자율굴착 논문 카드 요약 2014–2026
- Baidu 자율굴착 논문 카드 요약 2019–2024
- 서울대 자율굴착 논문 카드 요약 2018–2025
- 세 기관 최신 연구 동향 Markdown과 기존 기관별 HTML/PDF
- `기타 기관/`의 학술 논문·리뷰·보고서
- 굴착기 버켓 궤적 생성 서베이와 2025 earthmoving automation review
- 상세 원본별 추출 수와 제외·병합 사유는 `data/manifest.json`에 기록

## 갱신 방법

1. `data/fragments/`의 기관별 검토 데이터를 원본 근거와 함께 갱신한다.
2. 새 레코드는 같은 연구의 파생 파일을 별도 카드로 만들지 말고 `source_links`에 묶는다.
3. `python tools/build_dashboard.py`를 실행한다.
4. `python tools/qa_dashboard.py`가 0 오류인지 확인한다.

> [!warning]
> 이 대시보드는 원본을 수정하거나 복제하지 않는다. 로컬 링크가 바뀌면 원본 위치를 먼저 확인한 뒤 fragment 경로만 갱신한다.
'''


def render_readme(records, manifest):
    return f'''# 필드로봇 연구 통합 대시보드

기관별 카드 요약과 로컬 연구 자료를 고유 연구 단위로 묶은 오프라인 정적 대시보드다. 현재 수록 수는 {len(records)}개이며, 수록·중복·제외 근거는 `data/manifest.json`에 있다.

## 구조

- `00_필드로봇_연구통합_Index.md`: Obsidian 허브와 필터 바로가기
- `필드로봇_연구통합_대시보드.html`: 오프라인 메인 화면
- `assets/`: 메인 화면의 로컬 CSS/JavaScript
- `data/papers.json`: 정규화된 최종 레코드
- `data/manifest.json`: 추출 수, 중복 병합, 제외·미확보 범위, 집계
- `data/fragments/`: 기관·자료군별 검토 입력
- `detail/paper-NNN.html`: 레코드별 상세 페이지
- `detail/paper.css`: 상세 페이지 공통 스타일
- `tools/build_dashboard.py`: 병합·중복 제거·정적 파일 생성
- `tools/qa_dashboard.py`: 스키마·중복·링크·CDN·개수 검증

## 재생성 및 검증

볼트 루트에서 실행한다.

```powershell
python "02_research/필드로봇/통합대시보드/tools/build_dashboard.py"
python "02_research/필드로봇/통합대시보드/tools/qa_dashboard.py"
```

로컬 브라우저 검증이 필요하면 볼트 루트에서 다음 서버를 실행하고 `/02_research/필드로봇/통합대시보드/필드로봇_연구통합_대시보드.html`을 연다.

```powershell
python -m http.server 8765
```

## 갱신 원칙

1. 원본 MD/PDF/HTML은 수정·이동·복제하지 않는다.
2. 새 자료는 먼저 해당 fragment에 근거 경로와 함께 추가한다.
3. DOI가 있으면 DOI, 없으면 정규화 제목과 원문 경로로 중복을 검토한다.
4. 동일 연구의 PDF·Markdown·HTML·슬라이드·인포그래픽은 한 레코드의 `source_links`에 넣는다.
5. 확인되지 않은 연도·저자·학회·DOI·정량 결과는 공란으로 두거나 UI에서 해당 메타 조각을 생략한다.
6. 생성 후 QA 0 오류와 브라우저 상호작용을 다시 확인한다.

## 한계

- 상세 분석 미완료 또는 로컬 원문·근거 링크 부재로 분류된 `근거 제한` 항목은 {manifest['insufficient_evidence_count']}개다.
- 저자·발표처·DOI 중 하나 이상이 현재 근거에서 확인되지 않은 `서지 메타데이터 일부 미확인` 항목은 {manifest['metadata_gap_count']}개다. 공란과 `확인 필요` 표시는 추정으로 채우지 않는다.
- PDF 본문 전체를 자동으로 추론하지 않는다. 기존 요약과 파일명에서 확인되지 않는 서지는 보수적으로 미확인 처리한다.
- 상세 페이지 순번은 현재 정렬 결과를 반영하므로 자료 추가 시 달라질 수 있다. 레코드 식별에는 안정적인 `id`를 사용한다.
- 외부 원문 URL은 관련 자료 링크일 뿐이며 대시보드 실행에는 필요하지 않다.
'''


def load_image_map(records):
    """Load the reviewed 1:1 image mapping used by both catalogue and details."""
    if not IMAGE_MAP_PATH.exists():
        raise SystemExit("data/image_map.json이 없습니다. 대표 이미지 매핑을 먼저 준비하세요.")
    payload = read_json(IMAGE_MAP_PATH)
    entries = payload.get("images", payload.get("records")) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SystemExit("data/image_map.json은 배열 또는 images 배열이어야 합니다.")
    by_rank = {}
    for item in entries:
        rank = item.get("rank")
        image = clean_path(item.get("image") or item.get("bundle_path") or item.get("path") or item.get("output"))
        if not isinstance(rank, int) or not image:
            raise SystemExit("image_map 항목에 rank와 image/bundle_path가 필요합니다.")
        item = dict(item)
        item["image"] = image
        by_rank[rank] = item
    if len(entries) != len(records) or set(by_rank) != {record["rank"] for record in records}:
        raise SystemExit(f"image_map과 papers 순번이 일치하지 않습니다: images={len(entries)}, papers={len(records)}")
    for record in records:
        item = by_rank[record["rank"]]
        if item.get("id") != record["id"]:
            raise SystemExit(f"image_map id 불일치: rank={record['rank']}")
        if not (ROOT / item["image"]).is_file():
            raise SystemExit(f"대표 이미지 누락: {item['image']}")
    return by_rank


def institution_group(record):
    name = record["institution"]
    if name == "ETH Zurich":
        return "ETH"
    if name == "서울대학교":
        return "SNU"
    if name == "Baidu Research":
        return "Baidu"
    return "other"


def institution_class(record):
    return {"ETH": "cat-exc", "SNU": "cat-field", "Baidu": "cat-core", "other": "cat-other"}[institution_group(record)]


def v2_render_card(record, image_item):
    categories = [record["category"], *record["secondary_categories"]]
    searchable = " ".join([
        record["title"], record["title_ko"], record["institution"], " ".join(record["authors"]),
        " ".join(record["methods"]), record["one_line"], record["card_summary"], record["publication"],
        record["platform"], record["environment"], " ".join(categories),
    ]).casefold()
    source = primary_link(record)
    if source:
        pdf = (f'<a class="pdf-btn" href="{encode_href(source["path"])}" target="_blank" rel="noopener" '
               f'aria-label="{esc(record["title_ko"])} 원문 보기">📄 원문 보기</a>')
    else:
        pdf = '<span class="pdf-btn disabled" aria-disabled="true" title="확인된 원문 근거가 없습니다">📄 원문 없음</span>'
    cls = institution_class(record)
    image_path = esc(image_item["image"])
    methods = record["methods"][:6]
    year_badge = f'<span class="score-badge">{record["year"]}</span>' if record.get("year") else ""
    return f'''<article class="card {cls}" data-rank="{record['rank']}" data-inst="{institution_group(record)}" data-institution="{esc(record['institution'])}" data-year="{record['year'] or ''}" data-kind="{esc(record['source_kind'])}" data-categories="{esc('|'.join(categories))}" data-text="{esc(searchable)}" data-detail="{record['detail_page']}">
  <div class="thumb-wrap">
    <img class="thumb" src="{image_path}" alt="{esc(image_item.get('caption') or record['title_ko'])}" loading="lazy" tabindex="0" aria-label="{esc(record['title_ko'])} 대표 그림 확대">
    <span class="rank-badge">#{record['rank']:03d}</span>
    {year_badge}
    <span class="detail-ribbon">📖 상세요약</span>
  </div>
  <div class="card-body">
    <div class="meta-row"><span class="chip {cls}">{esc(record['institution'])}</span><span class="chip">{esc(record['category'])}</span><span class="chip">{esc(record['source_kind'])}</span></div>
    <h3 class="title-ko">{esc(record['title_ko'])}</h3>
    <p class="title-en" lang="en">{esc(record['title'])}</p>
    <p class="summary">{esc(record['card_summary'])}</p>
    <div class="tags">{chips(methods, 'tag')}</div>
    <a class="detail-btn" href="{record['detail_page']}" aria-label="{esc(record['title_ko'])} 상세 요약 보기">📖 상세 요약 보기</a>
    {pdf}
  </div>
</article>'''


def v2_render_dashboard(records, manifest, image_map):
    groups = Counter(institution_group(record) for record in records)
    years = sorted({record["year"] for record in records if record["year"]}, reverse=True)
    kinds = sorted({record["source_kind"] for record in records})
    cards = "\n".join(v2_render_card(record, image_map[record["rank"]]) for record in records)
    category_buttons = "".join(
        f'<button class="fbtn" type="button" data-tech="{esc(category)}" aria-label="{esc(category)} 기술 분류 필터">{esc(category)}</button>'
        for category in CATEGORIES
    )
    year_options = "".join(f'<option value="{value}">{value}</option>' for value in years)
    kind_options = "".join(f'<option value="{esc(value)}">{esc(value)}</option>' for value in kinds)
    search_records = [
        {
            "id": record["id"], "rank": record["rank"], "title": record["title"],
            "title_ko": record["title_ko"], "institution": record["institution"],
            "year": record["year"], "publication": record["publication"],
            "category": record["category"], "secondary_categories": record["secondary_categories"],
            "methods": record["methods"], "card_summary": record["card_summary"],
            "one_line": record["one_line"], "detail_page": record["detail_page"],
        }
        for record in records
    ]
    embedded = json.dumps(search_records, ensure_ascii=False).replace("</", "<\\/")
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>필드로봇 연구 통합 대시보드</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%234f9cff'/%3E%3Cpath d='M7 21h18v4H7zm3-11h12l3 9H7z' fill='white'/%3E%3C/svg%3E">
<link rel="stylesheet" href="assets/dashboard.css">
</head>
<body data-record-count="{len(records)}">
<a class="skip-link" href="#grid">연구 목록으로 건너뛰기</a>
<header>
  <h1>🏗️ 필드로봇 연구 통합 대시보드</h1>
  <div class="subtitle">자율굴착기 · 건설기계 · 필드로봇 연구를 한 화면에서 탐색 · 검토된 고유 연구 <b>{len(records)}편</b></div>
  <div class="stats" aria-label="수록 통계">
    <div class="stat"><span class="stat-num">{len(records)}</span><span class="stat-lbl">전체 연구</span></div>
    <div class="stat cat-exc"><span class="stat-num">{groups['ETH']}</span><span class="stat-lbl">ETH</span></div>
    <div class="stat cat-core"><span class="stat-num">{groups['Baidu']}</span><span class="stat-lbl">Baidu</span></div>
    <div class="stat cat-field"><span class="stat-num">{groups['SNU']}</span><span class="stat-lbl">서울대</span></div>
    <div class="stat cat-other"><span class="stat-num">{groups['other']}</span><span class="stat-lbl">기타기관</span></div>
    <div class="stat"><span class="stat-num">{min(years) if years else ''}–{max(years) if years else ''}</span><span class="stat-lbl">연도 범위</span></div>
  </div>
</header>
<div class="controls" aria-label="검색 및 필터">
  <label class="search">🔎<input id="q" type="search" placeholder="제목·기관·저자·키워드·요약 검색" autocomplete="off" aria-label="통합 검색"></label>
  <div class="filter-group" id="instFilters" aria-label="대표기관 필터">
    <button class="fbtn active" type="button" data-inst="all">전체</button>
    <button class="fbtn exc" type="button" data-inst="ETH">ETH</button>
    <button class="fbtn field" type="button" data-inst="SNU">서울대</button>
    <button class="fbtn core" type="button" data-inst="Baidu">Baidu</button>
    <button class="fbtn" type="button" data-inst="other">기타기관</button>
  </div>
  <select id="yearFilter" aria-label="연도 필터"><option value="">전체 연도</option>{year_options}</select>
  <select id="kindFilter" aria-label="자료 유형 필터"><option value="">전체 자료유형</option>{kind_options}</select>
  <select id="sort" aria-label="정렬"><option value="newest">최신순</option><option value="oldest">오래된순</option><option value="institution">기관순</option><option value="title">제목순</option></select>
  <button id="resetFilters" class="reset-btn" type="button">필터 초기화</button>
  <span class="count-info" id="countInfo" aria-live="polite"></span>
  <div class="filter-group tech" id="techFilters" aria-label="기술 분류 필터"><span class="group-label">기술 분류</span>{category_buttons}</div>
</div>
<main id="grid" class="grid" aria-label="연구 카드 목록">{cards}
  <div class="empty" id="empty" hidden><h2>검색 결과가 없습니다.</h2><p>검색어나 필터 조합을 바꿔 보세요.</p></div>
</main>
<div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-hidden="true" aria-label="대표 그림 확대 보기"><img id="lbimg" src="images/paper-001.png" alt="확대 대표 그림"></div>
<footer>생성일 {manifest['generated_on']} · 검토된 로컬 원문과 기존 요약 기반 · 외부 UI CDN 없음</footer>
<script id="papers-data" type="application/json">{embedded}</script>
<script src="assets/dashboard.js" defer></script>
</body>
</html>
'''


def source_and_evidence(record):
    return f'''<section class="trace" aria-label="근거 추적">
  <h3>원문·기존 요약·관련 자료</h3><ul>{render_links(record)}</ul>
  <h3>추출·교차검증 근거</h3><ul>{render_evidence(record)}</ul>
</section>'''


def representative_image_source_label(extraction_method):
    """Convert provenance keys into concise, reader-facing Korean labels."""
    method = str(extraction_method or "").strip()
    if method == "card_markdown_embed":
        return "기존 논문 분석 자료의 대표 그림"
    if method == "pdf_figure_caption":
        return "원문에서 추출한 대표 그림"
    if method.startswith("pdf_first_page_fallback"):
        return "원문 첫 페이지"
    return "대표 이미지 원본"


def render_paragraphs(values):
    if isinstance(values, str):
        values = [values]
    return "".join(f"<p>{esc(value)}</p>" for value in (values or []) if clean_text(value))


def render_bullets(values, class_name=""):
    if isinstance(values, str):
        values = [values]
    items = "".join(f"<li>{esc(value)}</li>" for value in (values or []) if clean_text(value))
    cls = f' class="{class_name}"' if class_name else ""
    return f"<ul{cls}>{items}</ul>" if items else ""


def normalized_figure_label(value):
    text = clean_text(value).casefold()
    text = re.sub(r"^(?:fig(?:ure)?\.?|그림|table|표)\s*", "", text)
    return re.sub(r"[^0-9a-z가-힣.-]", "", text)


def allocate_detail_figures(record, image_item):
    figures = [dict(item) for item in image_item.get("figures", [])]
    sections = {name: [] for name in ["background", "methodology", "core_technology", "experiments", "results"]}
    used = set()
    requested = record.get("key_figure_labels") or {}
    for section_name in sections:
        for requested_label in requested.get(section_name, []):
            wanted = normalized_figure_label(requested_label)
            match = next(
                (
                    item for item in figures
                    if item.get("kind") == "figure"
                    and item.get("figure_id") not in used
                    and normalized_figure_label(item.get("label")) == wanted
                ),
                None,
            )
            if match:
                sections[section_name].append(match)
                used.add(match["figure_id"])
    if figures and not used:
        sections["background"].append(figures[0])
        used.add(figures[0]["figure_id"])
    gallery = [item for item in figures if item.get("figure_id") not in used]
    all_paths = [item.get("image_path") for values in sections.values() for item in values] + [item.get("image_path") for item in gallery]
    expected_paths = [item.get("image_path") for item in figures]
    if len(all_paths) != len(set(all_paths)) or set(all_paths) != set(expected_paths):
        raise SystemExit(f"상세 그림 배치 불일치: rank={record['rank']}")
    return sections, gallery


def render_figure_asset(item, lazy=False):
    path = "../" + clean_path(item["image_path"])
    loading = ' loading="lazy"' if lazy else ""
    kind_class = "table-asset" if item.get("kind") == "table" else "figure-asset"
    return f'''<figure class="source-figure {kind_class}" data-figure-id="{esc(item['figure_id'])}">
  <img class="w700" src="{esc(path)}" alt="{esc(item.get('alt'))}"{loading} tabindex="0" onclick="zoom(this)" onkeydown="if(event.key==='Enter'||event.key===' '){{event.preventDefault();zoom(this)}}">
  <figcaption><b>{esc(item.get('display_source_label'))}</b> — {esc(item.get('caption'))}</figcaption>
</figure>'''


def render_section_figures(items):
    return "".join(render_figure_asset(item) for item in items)


def render_result_metrics(metrics):
    rows = "".join(
        f"<tr><td>{esc(item.get('item'))}</td><td>{esc(item.get('value'))}</td>"
        f"<td>{esc(item.get('context'))}</td><td>PDF p.{esc(item.get('source_page'))}</td></tr>"
        for item in (metrics or [])
    )
    if not rows:
        return ""
    return f'''<div class="tbl-wrap"><table class="metric-table">
<thead><tr><th>평가 항목</th><th>정량 결과</th><th>조건·맥락</th><th>원문 근거</th></tr></thead>
<tbody>{rows}</tbody></table></div>'''


def render_evidence_pages(record):
    labels = {
        "background": "배경", "methodology": "방법론", "experiments": "실험",
        "results": "결과", "limitations": "한계",
    }
    items = []
    for name, pages in (record.get("evidence_pages") or {}).items():
        page_text = ", ".join(f"p.{page}" for page in pages)
        items.append(f"<li><b>{esc(labels.get(name, name))}</b>: {esc(page_text)}</li>")
    return f'<div class="evidence-pages"><h3>섹션별 원문 근거 페이지</h3><ul>{"".join(items)}</ul></div>'


def render_equations(equations):
    """Compile reviewed TeX at build time; no browser script or CDN is needed."""
    if not equations:
        return ""
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("render_math.cjs"))],
        input=json.dumps([item.get("latex", "") for item in equations]),
        text=True, capture_output=True, timeout=30,
    )
    if result.returncode:
        raise ValueError(f"Equation rendering failed: {result.stderr.strip()}")
    rendered = json.loads(result.stdout)
    return "".join(
        f'<div class="eq"><h4>{esc(item.get("label"))}</h4>'
        f'<div class="math-display" tabindex="0" aria-label="수식">{math}</div>'
        f'<p>{esc(item.get("explanation"))}</p></div>'
        for item, math in zip(equations, rendered, strict=True)
    )


def v2_render_detail(record, previous_record, next_record, image_item):
    cls = institution_class(record)
    categories = [record["category"], *record["secondary_categories"]]
    methods = record["methods"]
    authors = ", ".join(record["authors"]) if record["authors"] else ""
    source = primary_link(record)
    if source:
        pdf_link = f'<a class="pdf-link" href="{encode_href(source["path"], detail=True)}" target="_blank" rel="noopener">📄 PDF 원문</a>'
    else:
        pdf_link = '<span class="pdf-link disabled" aria-disabled="true" title="확인된 원문 근거가 없습니다">📄 원문 없음</span>'
    prev_html = (f'<a class="prev" href="paper-{previous_record["rank"]:03d}.html"><span class="lbl">← 이전 #{previous_record["rank"]}</span>{esc(previous_record["title_ko"])}</a>'
                 if previous_record else '<span class="spacer"></span>')
    next_html = (f'<a class="next" href="paper-{next_record["rank"]:03d}.html"><span class="lbl">다음 #{next_record["rank"]} →</span>{esc(next_record["title_ko"])}</a>'
                 if next_record else '<span class="spacer"></span>')
    keyword_html = "".join(f'<span>#{esc(value)}</span>' for value in unique_strings(categories + methods))
    meta_parts = [value for value in (authors, record.get("publication")) if clean_text(value)]
    if record.get("doi"):
        meta_parts.append(f"DOI {record['doi']}")
    metadata_html = f'<p class="authors">{esc(" · ".join(meta_parts))}</p>' if meta_parts else ""
    year_badge = f'<span class="badge">{record["year"]}</span>' if record.get("year") else ""
    sections = record["sections"]
    background = sections["background"]
    methodology = sections["methodology"]
    core_technology = sections["core_technology"]
    experiments = sections["experiments"]
    results = sections["results"]
    limitations = sections["limitations"]
    takeaway = sections["takeaway"]
    connection = sections["connection"]
    placed, gallery = allocate_detail_figures(record, image_item)
    pipeline_html = "".join(
        f'<div class="pipeline-card"><span class="step-num">{index}</span><h4>{esc(item.get("title"))}</h4><p>{esc(item.get("body"))}</p></div>'
        for index, item in enumerate(methodology.get("pipeline", []), 1)
    )
    equation_html = render_equations(methodology.get("equations", []))
    core_html = "".join(
        f'<article class="tech-card"><h3>{esc(item.get("title"))}</h3>{render_paragraphs(item.get("paragraphs"))}{render_bullets(item.get("points"))}</article>'
        for item in core_technology
    )
    gallery_html = "".join(render_figure_asset(item, lazy=True) for item in gallery)
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<title>#{record['rank']} {esc(record['title_ko'])} — 필드로봇 연구 통합 대시보드</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%234f9cff'/%3E%3Cpath d='M7 21h18v4H7zm3-11h12l3 9H7z' fill='white'/%3E%3C/svg%3E">
<link rel="stylesheet" href="paper.css">
</head>
<body>
<nav class="topbar" aria-label="상세 페이지 탐색">
  <a class="back-btn" href="../필드로봇_연구통합_대시보드.html">← 목록으로</a>
  <span class="crumb">필드로봇 연구 · {esc(record['institution'])} · #{record['rank']:03d}</span>{pdf_link}
</nav>
<header class="hero">
  <div class="badges"><span class="badge {cls}">{esc(record['institution'])}</span>{year_badge}<span class="badge">#{record['rank']:03d}</span><span class="badge score">{esc(record['category'])}</span><span class="badge">{esc(record['source_kind'])}</span></div>
  <h1>{esc(record['title_ko'])}</h1>
  <p class="title-en" lang="en">{esc(record['title'])}</p>
  {metadata_html}
</header>
<main>
  <div class="oneliner"><b>한줄 요약</b> — {esc(record['one_line'])}</div>
  <h2><span class="sec-num">1.</span>연구 배경 및 동기</h2>
  <h3>{esc(background.get('heading'))}</h3>
  {render_paragraphs(background.get('paragraphs'))}
  {render_section_figures(placed['background'])}
  <div class="callout supp"><b>선행 연구의 한계</b>{render_bullets(background.get('prior_limits'))}</div>
  <div class="callout note"><b>이 연구의 기여</b>{render_bullets(background.get('contributions'))}</div>
  <h2><span class="sec-num">2.</span>방법론 및 시스템 구성</h2>
  {render_paragraphs(methodology.get('overview'))}
  <h3>처리 파이프라인</h3><div class="pipeline">{pipeline_html}</div>
  <h3>원문 수식과 의미</h3><div class="equations">{equation_html}</div>
  {render_section_figures(placed['methodology'])}
  <h2><span class="sec-num">3.</span>핵심 기술</h2>
  <div class="tech-grid">{core_html}</div>
  {render_section_figures(placed['core_technology'])}
  <h2><span class="sec-num">4.</span>실험 결과</h2>
  <h3>실험 환경·장비·데이터</h3>{render_bullets(experiments.get('setup'))}
  <h3>실험 프로토콜</h3>{render_bullets(experiments.get('protocol'))}
  <h3>비교 기준</h3>{render_bullets(experiments.get('baselines'))}
  <h3>평가 지표</h3>{render_bullets(experiments.get('metrics'))}
  {render_section_figures(placed['experiments'])}
  <h3>핵심 결과 해석</h3>{render_paragraphs(results.get('paragraphs'))}
  <h3>정량 결과</h3>{render_result_metrics(results.get('metrics'))}
  <div class="callout supp"><b>실패 사례와 경계조건</b>{render_bullets(results.get('failure_cases'))}</div>
  {render_section_figures(placed['results'])}
  <h2><span class="sec-num">5.</span>한계 및 향후 연구</h2>
  <div class="wrap-grid"><div class="wrap-card l"><h4>현재 한계</h4>{render_bullets(limitations.get('current'))}</div><div class="wrap-card r"><h4>향후 연구</h4>{render_bullets(limitations.get('future'))}</div></div>
  <h2><span class="sec-num">6.</span>한마디로 정리</h2>
  <div class="wrap-grid"><div class="wrap-card"><h4>핵심 방법은?</h4><p>{esc(takeaway.get('method'))}</p></div><div class="wrap-card r"><h4>핵심 결과는?</h4><p>{esc(takeaway.get('result'))}</p></div><div class="wrap-card l"><h4>한계는?</h4><p>{esc(takeaway.get('limit'))}</p></div></div>
  <div class="kw">{keyword_html}</div>
  <div class="opinion"><h2>나의 의견 / 우리 연구와의 연관성</h2>{render_paragraphs(connection.get('paragraphs'))}{render_bullets(connection.get('bullets'))}</div>
  <h2><span class="sec-num">7.</span>전체 그림·표</h2>
  <p class="gallery-intro">본문 핵심 위치에 배치하지 않은 원문 Figure와 Table을 원문 페이지 순서로 수록한다.</p>
  <div class="figure-gallery">{gallery_html}</div>
  {render_evidence_pages(record)}
  {source_and_evidence(record)}
  <div class="pager">{prev_html}{next_html}</div>
</main>
<div class="lightbox" id="lb" role="dialog" aria-modal="true" aria-hidden="true" onclick="closeZoom()"><img id="lbimg" alt="확대 원문 그림"></div>
<script>
function zoom(el){{var lb=document.getElementById('lb');var image=document.getElementById('lbimg');image.src=el.currentSrc||el.src;image.alt=el.alt;lb.classList.add('open');lb.setAttribute('aria-hidden','false');}}
function closeZoom(){{var lb=document.getElementById('lb');lb.classList.remove('open');lb.setAttribute('aria-hidden','true');}}
document.addEventListener('keydown',function(e){{if(e.key==='Escape')closeZoom();}});
</script>
<footer>필드로봇 연구 통합 대시보드 · 확인되지 않은 서지·수치는 추정하지 않음</footer>
</body>
</html>
'''


def v2_render_index(records, manifest, image_map):
    groups = Counter(institution_group(record) for record in records)
    counts = manifest["category_tag_counts"]
    figure_count = sum(sum(asset.get("kind") == "figure" for asset in item.get("figures", [])) for item in image_map.values())
    table_count = sum(sum(asset.get("kind") == "table" for asset in item.get("figures", [])) for item in image_map.values())
    cat_links = "\n".join(f'- [{category} {counts.get(category, 0)}건](필드로봇_연구통합_대시보드.html#category={quote(category)})' for category in CATEGORIES)
    institution_links = "\n".join(
        f'- [{name} {count}건](필드로봇_연구통합_대시보드.html#q={quote(name)})'
        for name, count in manifest["institution_counts"].items()
    )
    return f'''---
title: 필드로봇 연구 통합
aliases:
  - 필드로봇 통합 대시보드
tags:
  - 필드로봇
  - 자율굴착기
  - 연구대시보드
date: {manifest['generated_on']}
---

# 필드로봇 연구 통합

> [!abstract] ICRA2026 카탈로그형 통합 화면
> 검토된 **{len(records)}개 고유 연구**와 실제 논문 대표 그림 {len(records)}개를 한 화면에서 탐색한다. 카드에는 4줄 요약이 항상 보이며, 상세 페이지는 ICRA2026형 7개 섹션과 원문 Figure/Table 전체 갤러리를 제공한다.

## 바로 열기

- [전체 {len(records)}편](필드로봇_연구통합_대시보드.html)
- [ETH {groups['ETH']}편](필드로봇_연구통합_대시보드.html#institution=ETH)
- [서울대 {groups['SNU']}편](필드로봇_연구통합_대시보드.html#institution=SNU)
- [Baidu {groups['Baidu']}편](필드로봇_연구통합_대시보드.html#institution=Baidu)
- [기타기관 {groups['other']}편](필드로봇_연구통합_대시보드.html#institution=other)

## 세부 기관별 바로가기

{institution_links}

## 전체 통계

| 항목 | 값 |
|---|---:|
| 고유 연구 | {len(records)} |
| ETH / Baidu / 서울대 / 기타기관 | {groups['ETH']} / {groups['Baidu']} / {groups['SNU']} / {groups['other']} |
| 연도 범위 | 1995–2026 |
| 기술 분류 | 8개 |
| 대표 그림 | {len(records)}개 |
| 원문 Figure / Table | {figure_count} / {table_count} |
| 근거 제한 항목 | {manifest['insufficient_evidence_count']} |
| 서지 일부 미확인 | {manifest['metadata_gap_count']} |

## 기술별 바로가기

{cat_links}

## 자료와 갱신

- 최종 레코드: [papers.json](data/papers.json)
- 원본별 추출·중복·제외: [manifest.json](data/manifest.json)
- 논문-대표·전체 그림 추적표: [image_map.json](data/image_map.json)
- PDF별 전체 그림 추출 기록: [figure_manifest.json](data/figure_manifest.json)
- 구조·재생성·한계: [[README]]

1. `data/fragments/`와 `data/enriched/`의 검토 레코드·근거 경로를 갱신한다.
2. 카드 대표 그림을 `images/paper-NNN.png`에 준비한다.
3. PDF Figure/Table을 추출·검토하고 `data/figure_manifest.json`과 `data/image_map.json`에 근거·배치 정보를 기록한다.
4. 외부 구현 저장소 `field-robot-dashboard`에서 `python src/dashboard_renderer.py --vault /path/to/obsidian_work`로 로컬 HTML을 재생성한다.
5. 같은 저장소의 `src/publish.py`로 공개본을 빌드하고 내부 링크·브라우저 화면을 검증한다. 기존 `tools/`는 80편 기준의 이전 도구이므로 새 논문 재생성에는 사용하지 않는다.

> [!warning]
> 같은 연구의 MD/PDF/HTML/인포그래픽은 별도 카드가 아니라 `source_links`에 묶는다. 확인할 수 없는 메타데이터나 수치는 만들지 않는다.
'''


def v2_render_readme(records, manifest, image_map):
    groups = Counter(institution_group(record) for record in records)
    fallback = sum("fallback" in str(item.get("extraction_method", "")) for item in image_map.values())
    figure_count = sum(sum(asset.get("kind") == "figure" for asset in item.get("figures", [])) for item in image_map.values())
    table_count = sum(sum(asset.get("kind") == "table" for asset in item.get("figures", [])) for item in image_map.values())
    return f'''# 필드로봇 연구 통합 대시보드 v3

**외부 공개**: https://hanminy.github.io/field-robot-dashboard/ · [[공개 대시보드 및 자동 동기화|자동 갱신 방식과 운영 안내]]

ICRA2026 분야추천 TOP50의 조밀한 카탈로그와 상세 정보 밀도를 기준으로 만든 오프라인 대시보드다. 고유 연구 {len(records)}건, 대표 그림 {len(records)}개, 원문 Figure {figure_count}개와 Table {table_count}개를 수록한다.

## 구조

- `필드로봇_연구통합_대시보드.html`: ICRA형 메인 카탈로그
- `assets/dashboard.css`, `assets/dashboard.js`: 오프라인 스타일·검색·조합 필터·hash·라이트박스
- `images/paper-NNN.png`: 카드와 상세가 공유하는 대표 그림 {len(records)}개
- `data/papers.json`: 정규화된 고유 연구 레코드 {len(records)}건
- `data/image_map.json`: stable id/rank, 대표 그림과 전체 Figure/Table 추적 정보
- `data/figure_manifest.json`: PDF별 탐지·추출·fallback·실패 재현 기록
- `data/manifest.json`: 원본별 추출 수, 중복 병합, 제외·미확보 범위
- `detail/paper-NNN.html`, `detail/paper.css`: ICRA형 상세 페이지 {len(records)}개와 공통 스타일
- 외부 구현 저장소 `field-robot-dashboard/src/dashboard_renderer.py`: 검토 데이터에서 메인·상세·문서를 재생성
- 외부 구현 저장소 `field-robot-dashboard/src/publish.py`: 공개 범위 변환·내부 링크 검증
- `tools/`: 80편 기준의 이전 도구 보관본. 새 논문 추가 후에는 위 외부 구현을 사용
- `visual-qa/`: 동일 1440px 기준 원본/완성 스크린샷과 시각 검증 자료

## 재생성·검증

외부 구현 저장소 `/home/hmlee/dev/field-robot-dashboard`에서 실행한다. 볼트에는 구현 소스를 추가하지 않는다.

```bash
.venv/bin/python src/dashboard_renderer.py --vault /home/hmlee/obsidian/obsidian_work
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python src/publish.py --vault /home/hmlee/obsidian/obsidian_work --output /tmp/field-robot-public-review --revision local
```

공개본 출력 경로는 비어 있어야 한다. 브라우저에서 검색·기관 필터·이미지 확대와 데스크톱/모바일 overflow를 확인한다.

브라우저에서는 `/02_research/필드로봇/통합대시보드/필드로봇_연구통합_대시보드.html`을 연다. 대표기관 버튼의 기대 결과는 전체 {len(records)}, ETH {groups['ETH']}, 서울대 {groups['SNU']}, Baidu {groups['Baidu']}, 기타기관 {groups['other']}다.

## 이미지 갱신 원칙

기존 카드 대표 이미지 80개는 유지한다. 상세 페이지에는 원문 캡션 occurrence별 Figure/Table을 전부 배치하며, 캡션이 없는 발표자료 rank 67·80만 검증된 slide fallback을 사용한다. 기존 대표 이미지의 첫 페이지 fallback은 {fallback}건이다.

## 데이터 갱신 원칙

1. 원본 MD/PDF/HTML은 수정·이동하지 않는다.
2. 새 자료는 `data/fragments/`에 근거 경로와 함께 추가한다.
3. DOI, 정규화 제목, 동일 원문 PDF 경로 순으로 중복을 점검한다.
4. 동일 연구의 파생 자료는 한 레코드의 `source_links`에 묶는다.
5. 확인되지 않은 연도·저자·학회·DOI·정량 결과는 공란으로 두고 UI에서 해당 메타 조각을 생략한다.
6. 기존 id/rank와 공개 주소는 유지하고 새 논문은 다음 rank로 추가한다.

## 한계

- 근거 제한 항목은 {manifest['insufficient_evidence_count']}건, 저자·발표처·DOI 중 하나 이상이 미확인인 항목은 {manifest['metadata_gap_count']}건이다.
- 통합 대상 {len(records)}편 외의 별도 `국내보고서/` PDF 9개는 원본이 없어 `manifest.json`의 미확보 참고 항목으로만 남아 있다.
- 카드 대표 이미지 2건은 Figure caption 기반 대표 그림을 확보하지 못해 원문 첫 페이지를 사용한다. 상세 페이지의 Figure/Table 전체 추출과는 별도다.
- 외부 원문 URL은 관련 링크일 뿐 대시보드 구동에는 사용하지 않는다. 외부 UI CDN은 없다.
'''


def configure_vault(vault):
    global ROOT, WORKTREE_VAULT, DATA_DIR, FRAGMENT_DIR, DETAIL_DIR, ASSET_DIR, IMAGE_DIR, IMAGE_MAP_PATH, ENRICHED_DIR
    WORKTREE_VAULT = Path(vault).resolve()
    ROOT = WORKTREE_VAULT / "02_research/필드로봇/통합대시보드"
    DATA_DIR = ROOT / "data"
    FRAGMENT_DIR = DATA_DIR / "fragments"
    DETAIL_DIR = ROOT / "detail"
    ASSET_DIR = ROOT / "assets"
    IMAGE_DIR = ROOT / "images"
    IMAGE_MAP_PATH = DATA_DIR / "image_map.json"
    ENRICHED_DIR = DATA_DIR / "enriched"


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    configure_vault(parser.parse_args().vault)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    records, manifest = load_records()
    records = merge_enriched(records)
    image_map = load_image_map(records)
    manifest["representative_images"] = {
        "total": len(image_map),
        "card_markdown_embed": sum(item.get("extraction_method") == "card_markdown_embed" for item in image_map.values()),
        "pdf_figure_caption": sum(item.get("extraction_method") == "pdf_figure_caption" for item in image_map.values()),
        "pdf_first_page_fallback": sum("fallback" in str(item.get("extraction_method", "")) for item in image_map.values()),
        "mapping": "data/image_map.json",
    }
    write_json(DATA_DIR / "papers.json", records)
    write_json(DATA_DIR / "manifest.json", manifest)
    write_text(ROOT / "필드로봇_연구통합_대시보드.html", v2_render_dashboard(records, manifest, image_map))
    write_text(ROOT / "00_필드로봇_연구통합_Index.md", v2_render_index(records, manifest, image_map))
    write_text(ROOT / "README.md", v2_render_readme(records, manifest, image_map))
    for old_page in DETAIL_DIR.glob("paper-[0-9][0-9][0-9].html"):
        old_page.unlink()
    for index, record in enumerate(records):
        previous_record = records[index - 1] if index else None
        next_record = records[index + 1] if index + 1 < len(records) else None
        write_text(DETAIL_DIR / f"paper-{record['rank']:03d}.html", v2_render_detail(record, previous_record, next_record, image_map[record["rank"]]))
    print(f"generated {len(records)} records and {len(records)} detail pages")


if __name__ == "__main__":
    main()
