# 딜러앱 CRM PUSH 캠페인 주간 리포트

## 배포 방법 (GitHub Pages)

1. 이 폴더 전체를 새 GitHub 저장소에 push
2. 저장소 Settings > Pages > Source를 `main` 브랜치 `/ (root)`로 설정
3. `https://<username>.github.io/<repo>/` 로 접속하면 리포트 확인 가능

## 매일 오전 9시(KST) 자동 갱신 설정

1. 저장소 Settings > Secrets and variables > Actions 에서 아래 2개 등록
   - `BRAZE_API_KEY`: Braze REST API 키 (campaigns.data_series, canvas.data_series 권한 필요)
   - `BRAZE_REST_ENDPOINT`: 워크스페이스 REST 엔드포인트 (예: `https://rest.iad-01.braze.com`)
2. `.github/workflows/daily-refresh.yml` 이 매일 00:00 UTC(=09:00 KST)에 자동 실행되어
   `fetch_braze_data.py`를 돌리고 `data.json`을 갱신 후 자동 커밋합니다.
3. Actions 탭에서 수동 실행(`workflow_dispatch`)도 가능합니다.

## 파일 구조

```
index.html            # 리포트 화면 (data.json을 fetch해서 렌더링)
data.json             # 캠페인별 주간 sends/opens/rate 데이터
fetch_braze_data.py   # Braze API 호출 + data.json 재생성 스크립트
.github/workflows/daily-refresh.yml   # 매일 자동 실행 워크플로우
```

## 신규 캠페인 추가 시

`fetch_braze_data.py`의 `CAMPAIGNS` 또는 `CANVASES` 딕셔너리에
`"캠페인명": "campaign_id"` 한 줄만 추가하면 다음 자동 실행부터 반영됩니다.

## 주의사항

- Canvas(예: 인기 차량 출품 안내)는 Braze API가 1회 호출당 최대 14일만 지원해서
  스크립트가 내부적으로 여러 번 나눠 호출합니다. 요금과는 무관한 API 자체 제약입니다.
- `data.json`은 기존 데이터를 보존하면서 신규 주차만 병합(merge)하는 방식이라
  과거 백필 데이터가 매일 실행 때마다 사라지지 않습니다.
