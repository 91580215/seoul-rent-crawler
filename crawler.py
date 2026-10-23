"""서울시 전월세 공개 API 수집기.
공식 데이터: 서울 열린데이터광장 OA-21276 (tbLnOpendataRentV)
GitHub Actions에서 SEOUL_API_KEY 환경변수로 인증키를 전달합니다.
"""
import csv
import json
import os
import time
from urllib.parse import quote
from datetime import date, timedelta
from pathlib import Path

import requests

API_KEY = os.getenv("SEOUL_API_KEY", "").strip()
BASE_URL = "http://openapi.seoul.go.kr:8088"
OUTPUT = Path("docs/data.json")
PAGE_SIZE = 1000
TARGET_USAGE = "연립다세대"
HEADERS = {"User-Agent": "SeoulRentScout/1.0 (student data project)"}


def get_rows(contract_date: date) -> list[dict]:
    """계약일 하루치의 연립·다세대 전월세 데이터를 API에서 가져온다."""
    if not API_KEY:
        raise RuntimeError(
            "SEOUL_API_KEY가 설정되지 않았어요. 서울 열린데이터광장에서 인증키를 발급한 뒤 "
            "GitHub 저장소 Settings > Secrets and variables > Actions에 등록해 주세요."
        )

    rows: list[dict] = []
    start = 1
    total = None
    while total is None or start <= total:
        end = start + PAGE_SIZE - 1
        date_filter = quote(f"CTRT_DAY={contract_date.strftime('%Y%m%d')}", safe="=")
        usage_filter = quote(f"BLDG_USG={TARGET_USAGE}", safe="=")
        url = f"{BASE_URL}/{API_KEY}/json/tbLnOpendataRentV/{start}/{end}/{date_filter}/{usage_filter}"
        response = requests.get(url, headers=HEADERS, timeout=(10, 45))
        response.raise_for_status()
        payload = response.json()
        block = payload.get("tbLnOpendataRentV", {})
        result = block.get("RESULT", {})
        if result and result.get("CODE") != "INFO-000":
            raise RuntimeError(f"서울시 API 오류: {result.get('CODE')} - {result.get('MESSAGE')}")
        page_rows = block.get("row", [])
        if not page_rows:
            break
        rows.extend(page_rows)
        total = int(block.get("list_total_count", len(rows)))
        print(f"{contract_date}: {len(rows):,} / {total:,}건 확인")
        start += PAGE_SIZE
        time.sleep(0.1)
    return rows

def first_value(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def main() -> None:
    today = date.today()
    cutoff = today - timedelta(days=6)  # 오늘 포함 최근 7일
    collected: list[dict] = []

    current = cutoff
    while current <= today:
        for row in get_rows(current):
            contract_day = first_value(row, "CTRT_DAY", "계약일")
            if len(contract_day) != 8 or not contract_day.isdigit():
                continue
            try:
                contract_date = date(int(contract_day[:4]), int(contract_day[4:6]), int(contract_day[6:8]))
            except ValueError:
                continue
            if not (cutoff <= contract_date <= today):
                continue

            usage = first_value(row, "BLDG_USG", "건물용도")
            if usage and usage not in ("연립다세대", "연립", "다세대"):
                continue

            collected.append({
                "contract_date": contract_date.isoformat(),
                "district": first_value(row, "CGG_NM", "자치구명"),
                "neighborhood": first_value(row, "STDG_NM", "법정동명"),
                "building": first_value(row, "BLDG_NM", "건물명"),
                "rent_type": first_value(row, "RENT_SE", "전월세구분"),
                "deposit_manwon": first_value(row, "GRFE", "보증금"),
                "monthly_rent_manwon": first_value(row, "RTFE", "임대료"),
                "area_m2": first_value(row, "RENT_AREA", "임대면적"),
                "building_year": first_value(row, "ARCH_YR", "건축년도"),
                "floor": first_value(row, "FLR", "층"),
                "contract_period": first_value(row, "CTRT_PRD", "계약기간"),
            })
        current += timedelta(days=1)

    collected.sort(key=lambda item: item["contract_date"], reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "source": "서울특별시 서울 열린데이터광장 OA-21276 (tbLnOpendataRentV)",
        "source_url": "https://data.seoul.go.kr/dataList/OA-21276/S/1/datasetView.do",
        "updated_at": today.isoformat(),
        "period_from": cutoff.isoformat(),
        "period_to": today.isoformat(),
        "count": len(collected),
        "records": collected,
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: {len(collected):,}건 → {OUTPUT}")


if __name__ == "__main__":
    main()
