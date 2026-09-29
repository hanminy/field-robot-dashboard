# 필드로봇 연구 대시보드

공개 페이지: https://hanminy.github.io/field-robot-dashboard/

Obsidian의 `02_research/필드로봇/통합대시보드`를 공개 웹으로 내보내는 독립 구현 저장소다. 원본 볼트는 비공개로 유지한다. `main`은 게시 도구, `gh-pages`는 검증된 공개 산출물이다.

## 갱신 경로

1. 각 PC의 Obsidian Git이 원본 볼트 변경을 push한다.
2. 볼트의 선언형 workflow가 이 저장소의 재사용 workflow를 호출한다.
3. 검토 JSON에서 검토된 논문의 대시보드를 재생성하고, 연결된 Markdown 근거 노트 및 필드로봇 폴더의 `*요약.md`를 현재 내용으로 변환한다.
4. 이미지 무손실 WebP 변환과 전체 내부 링크 검증 후 `gh-pages`에 push한다.
5. 공개 저장소의 Pages workflow가 배포한다. 열린 페이지는 60초마다 배포 버전을 검사한다.

로컬 저장과 원격 push 사이에는 Obsidian Git 동기화 간격이 있고, GitHub Actions 대기/실행 및 Pages 배포에도 시간이 든다. 실시간 공동 편집이 아닌 push 기반 자동 배포다. PC가 꺼져 있어도 push된 변경의 배포는 GitHub에서 실행된다.

## 공개 범위

- 대시보드 목록·상세 요약·대표 그림·Figure/Table
- 레코드가 명시적으로 참조하는 필드로봇 Markdown 노트
- 필드로봇 폴더의 `*요약.md`와 위 노트에서 직접 참조하는 이미지
- 원본 PDF, 원본 HTML, 기타 볼트 파일과 비밀 설정은 복사하지 않는다. 공개하지 않은 원문 링크는 Obsidian 자료로 표시한다.

대시보드 본문은 `data/fragments/`, `data/enriched/`, `data/image_map.json`의 검토 데이터를 사용한다. MD 편집은 각 상세의 **Obsidian 최신 요약·근거 노트** 및 **요약 노트 목록**에 반영된다. MD 편집을 AI로 재요약하여 검토 JSON에 자동 덮어쓰지는 않는다. 새 `*요약.md`는 목록에 자동 추가되며, 카탈로그에 새 연구를 등록하려면 기존 검토 데이터와 이미지 매핑을 함께 갱신해야 한다.

CSS/JS는 볼트의 assets를 사용하고, HTML 템플릿은 `src/dashboard_renderer.py`에 있다. 볼트의 생성된 HTML을 직접 편집하는 대신 템플릿 또는 검토 데이터를 수정한다.

## 로컬 검증

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/publish.py --vault /path/to/obsidian_work --output site --revision local
```

출력 경로는 비어 있어야 한다. 빌드는 원본 볼트를 변경하지 않으며, 내부 링크가 끊기거나 사이트가 950 MB를 넘으면 실패한다. `tests/`에는 공개 범위, Markdown 갱신, 링크 검증의 회귀 테스트를 둔다.

## 운영 및 복구

볼트 Actions의 `Publish field robotics` → 공개 저장소 Actions의 `Deploy public dashboard` 순서로 확인한다. 실패 시 기존 공개본은 유지된다. 볼트 workflow는 `workflow_dispatch`로 수동 재시도할 수 있다. 롤백은 `gh-pages`의 정상 커밋을 새 커밋으로 복원해 배포한다.

`FIELD_ROBOT_PUBLISH_KEY`는 이 공개 저장소 하나에만 쓰기 가능한 SSH deploy key다. 개인 토큰을 저장하지 않으며 비공개 볼트 읽기는 해당 workflow의 `GITHUB_TOKEN`을 사용한다. 키 교체 시 공개 저장소 deploy key와 볼트 Actions secret을 함께 교체한다.

## 논문 추가와 주소 유지

`data/fragments/`에 서지·근거, `data/enriched/`에 동일 스키마의 검토 본문을 추가하고 `data/image_map.json`에 대표 이미지와 원문 그림을 등록한다. 기존 id/rank를 유지하고 신규 논문에는 마지막 rank 다음 번호를 부여한다. 연도 정렬은 브라우저에서 처리하므로 과거 논문을 추가해도 기존 공개 주소가 바뀌지 않는다. 논문·상세 본문·이미지 매핑이 일대일로 일치하지 않으면 빌드가 실패한다.

볼트의 로컬 상세 HTML도 같은 템플릿으로 재생성한다:

```bash
.venv/bin/python src/dashboard_renderer.py --vault /path/to/obsidian_work
```

2026-09-29에 Park (2002)를 #081로 추가했다. 기존 80개 주소를 유지하고 총 81편을 제공한다. 볼트의 `tools/`는 80편 기준의 이전 도구이므로 이후 갱신은 이 저장소를 사용한다.
