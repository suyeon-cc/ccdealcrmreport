"""
딜러앱 CRM PUSH 캠페인 주간 리포트 - 데이터 갱신 스크립트

GitHub Actions에서 매일 오전 9시(KST)에 실행되어 Braze REST API를 호출하고
data.json을 최신 상태로 재생성합니다.

필요 환경변수 (GitHub repo Settings > Secrets and variables > Actions):
  BRAZE_API_KEY   - Braze REST API 키 (campaigns.data_series 권한 필요)
  BRAZE_REST_ENDPOINT - 예: https://rest.iad-01.braze.com (워크스페이스별 상이)

캠페인 ID는 아래 CAMPAIGNS 딕셔너리에 고정되어 있습니다.
신규 캠페인 추가 시 이 딕셔너리에 항목만 추가하면 됩니다.
"""

import os
import json
import datetime
import time
import urllib.request
import urllib.error

BRAZE_API_KEY = os.environ.get("BRAZE_API_KEY")
BRAZE_REST_ENDPOINT = os.environ.get("BRAZE_REST_ENDPOINT", "https://rest.iad-01.braze.com")

# name -> campaign_id
CAMPAIGNS = {
    "매물 입고 알림": "f2c19487-278e-41de-a808-3a6e6807c7b8",
    "생애 최초": "56c71250-3714-4ac6-8677-4f7c50157f00",
    "최빈 입찰 CA": "10d5ad0e-9434-4422-89dc-62ae048fd900",
    "최신 낙찰 CA": "c4d1ca7a-187e-482a-a96a-5fc731100590",
    # 신규 세그먼트 (2026-07-13 라이브) - A/B/C 문안 로테이션이므로 3개 ID를 합산
    "입찰 독려_입찰경험O": ["86c63b25-e7de-4e37-9e28-224a8fae8f08", "e12f9c93-ccea-4ce9-be93-679aaf47a1af", "6d4fcaaa-236d-410b-9a90-101270d9b2c2"],
    "입찰 독려_매입딜러_입찰경험X": ["fe70bff8-2de8-45b2-86c0-4729551e2343", "9cdad36e-027f-4c16-840a-853c29c34424", "a5ea2ace-45e0-49ec-ba2e-a275e4a4ca56"],
    "입찰 독려_광고딜러_입찰경험X": ["4f7a5890-9914-44d7-8e5c-a9d3b739bd6b", "4e2dbd6c-9ebc-4986-b0f4-8575a86048d8", "72c72f50-66e7-4ea1-9e6e-ce5a9cadca4c"],
    # 인기 차량 출품 안내는 Canvas이므로 별도 canvas/data_series 엔드포인트 사용
}

CANVASES = {
    "인기 차량 출품 안내": "69731c0bdb779f006348aff7",
}

LENGTH_DAYS = 100  # campaigns/data_series 최대 100일
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


def braze_get(path, params):
    url = f"{BRAZE_REST_ENDPOINT}{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {BRAZE_API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"  [HTTP {e.code}] {url}")
        print(f"  응답 본문: {body}")
        raise


def week_key(date_str):
    dt = datetime.date.fromisoformat(date_str)
    monday = dt - datetime.timedelta(days=dt.weekday())
    return monday.isoformat()


def fetch_campaign_weekly(campaign_id_or_ids):
    """캠페인의 unique_recipients(sends) / direct_opens(ios+android) 를 주간 집계.
    A/B/C 문안 로테이션처럼 여러 campaign_id를 합산해야 하는 경우 리스트로 전달."""
    ids = campaign_id_or_ids if isinstance(campaign_id_or_ids, list) else [campaign_id_or_ids]
    ending_at = datetime.date.today().isoformat()
    weekly = {}
    for cid in ids:
        resp = braze_get(
            "/campaigns/data_series",
            {"campaign_id": cid, "length": LENGTH_DAYS, "ending_at": ending_at},
        )
        for row in resp.get("data", []):
            wk = week_key(row["time"])
            weekly.setdefault(wk, {"sends": 0, "opens": 0})
            weekly[wk]["sends"] += row.get("unique_recipients") or 0
            msgs = row.get("messages", {})
            for ch in ("ios_push", "android_push"):
                arr = msgs.get(ch)
                if not arr:
                    continue
                for v in arr:
                    weekly[wk]["opens"] += v.get("direct_opens") or 0
    return weekly


def fetch_canvas_weekly(canvas_id):
    """캔버스는 1회 최대 14일만 지원 -> 여러 번 나눠 호출 후 병합"""
    weekly = {}
    ending_at = datetime.date.today()
    # 최근 ~10회(140일) 정도만 커버. 필요시 range 늘리기.
    for _ in range(10):
        ending_str = ending_at.isoformat()
        resp = braze_get(
            "/canvas/data_series",
            {"canvas_id": canvas_id, "length": 14, "ending_at": ending_str},
        )
        rows = resp.get("data", {}).get("stats", []) or resp.get("data", [])
        if not rows:
            break
        for row in rows:
            wk = week_key(row["time"])
            weekly.setdefault(wk, {"sends": 0, "opens": 0})
            # 캔버스 응답 구조는 step/variant 단위이므로 총합만 추출
            total_stats = row.get("total_stats", {})
            weekly[wk]["sends"] += total_stats.get("unique_recipients") or 0
            weekly[wk]["opens"] += total_stats.get("direct_opens") or 0
        ending_at = ending_at - datetime.timedelta(days=14)
        time.sleep(0.3)
    return weekly


def main():
    if not BRAZE_API_KEY:
        raise SystemExit("BRAZE_API_KEY 환경변수가 설정되어 있지 않습니다.")

    all_weekly = {}
    for name, cid in CAMPAIGNS.items():
        print(f"fetching {name} ...")
        all_weekly[name] = fetch_campaign_weekly(cid)

    for name, cvid in CANVASES.items():
        print(f"fetching canvas {name} ...")
        try:
            all_weekly[name] = fetch_canvas_weekly(cvid)
        except urllib.error.HTTPError as e:
            print(f"  canvas fetch failed: {e}")
            all_weekly[name] = {}

    # 기존 data.json 로드 (백필된 과거 데이터 보존 목적)
    existing = {"weeks": [], "campaigns": {}}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    merged_campaigns = existing.get("campaigns", {})
    all_weeks = set(existing.get("weeks", []))

    for name, weekly in all_weekly.items():
        existing_rows = {r["week"]: r for r in merged_campaigns.get(name, [])}
        for wk, v in weekly.items():
            rate = round(v["opens"] / v["sends"] * 100, 2) if v["sends"] else 0
            existing_rows[wk] = {"week": wk, "sends": v["sends"], "opens": v["opens"], "rate": rate}
            all_weeks.add(wk)
        merged_campaigns[name] = [existing_rows[wk] for wk in sorted(existing_rows.keys())]

    result = {
        "weeks": sorted(all_weeks),
        "campaigns": merged_campaigns,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("data.json updated.")


if __name__ == "__main__":
    main()
