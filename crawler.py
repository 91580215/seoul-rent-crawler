"""Public real-estate listing HTML crawler. No listing API calls.
Reads visible listing summaries from publicly indexed Daangn Realty HTML pages.
Only listings actually present in the downloaded HTML are written to docs/data.json.
"""
import json, re, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
SOURCES = ROOT / "sources.txt"
OUTPUT = ROOT / "docs" / "data.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
TYPE_WORDS = ("빌라", "원룸", "주택", "다세대", "연립", "투룸", "오피스텔")
MONEY = r"(?:\d+(?:억\s*)?(?:\d[\d, ]*만?)?|\d[\d, ]*)"

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def money_manwon(s):
    s = clean(s).replace(",", "").replace("만원", "만").replace(" ", "")
    if not s:
        return None
    total = 0
    m = re.search(r"(\d+)억", s)
    if m:
        total += int(m.group(1)) * 10000
    rest = re.search(r"억(\d+)만?", s)
    if rest:
        total += int(rest.group(1))
    elif not m:
        m2 = re.search(r"(\d+)만?", s)
        if m2:
            total = int(m2.group(1))
    return total if total or s in ("0", "0만") else None

def infer_region(title, url):
    combined = title + " " + url
    provinces = ("서울특별시","부산광역시","대구광역시","인천광역시","광주광역시","대전광역시","울산광역시","세종특별자치시","경기도","강원특별자치도","충청북도","충청남도","전북특별자치도","전라남도","경상북도","경상남도","제주특별자치도")
    sido = next((x for x in provinces if x in combined), "")
    district = ""
    if sido:
        m = re.search(re.escape(sido) + r"\s*([^/·]+?(?:구|시|군))", title)
        if m:
            district = clean(m.group(1))
    return sido, district

def parse_line(line, page_title, source_url, collected_at):
    line = clean(line)
    # SEO summaries commonly look like: 동네 빌라 월세 500 / 45만원 47m² 매물
    if not any(x in line for x in TYPE_WORDS):
        return None
    if "전세" not in line and "월세" not in line:
        return None
    if "매매" in line and not ("전세" in line or "월세" in line):
        return None
    kind = "전세" if "전세" in line else "월세"
    area_match = re.search(r"(\d+(?:\.\d+)?)\s*m²", line)
    area = float(area_match.group(1)) if area_match else None
    # Parse deposit/monthly values from Korean visible summary text.
    deposit = monthly = None
    if kind == "전세":
        price_match = re.search(r"전세\s*(" + MONEY + r")\s*만원?", line)
        if not price_match:
            price_match = re.search(r"전세\s*(\d+(?:억\s*\d[\d, ]*만?)?)", line)
        if price_match:
            deposit = money_manwon(price_match.group(1))
    else:
        price_match = re.search(r"월세\s*(" + MONEY + r")\s*/\s*(" + MONEY + r")\s*만원?", line)
        if price_match:
            deposit = money_manwon(price_match.group(1))
            monthly = money_manwon(price_match.group(2))
        else:
            # Some pages show "월세 500 / 45만원" with spaces and the first amount in 만원.
            price_match = re.search(r"월세\s*([\d,억만 ]+)\s*/\s*([\d,억만 ]+)", line)
            if price_match:
                deposit = money_manwon(price_match.group(1))
                monthly = money_manwon(price_match.group(2))
    if deposit is None or (kind == "월세" and monthly is None):
        return None
    sido, sigungu = infer_region(page_title, source_url)
    dong_match = re.search(r"([가-힣0-9·]+(?:동|읍|면|리))\s+(?:빌라|원룸|주택|다세대|연립|투룸)", line)
    neighborhood = dong_match.group(1) if dong_match else ""
    housing = next((x for x in TYPE_WORDS if x in line), "주택")
    return {
        "sido": sido, "sigungu": sigungu, "neighborhood": neighborhood,
        "rent_type": kind, "housing_type": housing,
        "deposit_manwon": deposit, "monthly_rent_manwon": monthly if kind == "월세" else 0,
        "area_m2": area, "building": line[:100], "listing_title": line[:300],
        "listing_url": source_url, "source_url": source_url, "collected_at": collected_at,
        "data_note": "공개 HTML 페이지에 표시된 요약 정보; 개별 매물 상세 URL은 원문 페이지에서 확인"
    }

def main():
    if not SOURCES.exists():
        raise SystemExit("sources.txt가 없습니다.")
    urls = [x.strip() for x in SOURCES.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.lstrip().startswith("#")]
    records, seen, failures = [], set(), []
    for url in urls:
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            print(f"HTTP {response.status_code}: {response.url}")
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "").lower():
                failures.append({"url": url, "error": "HTML 응답이 아님"})
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            page_title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
            # Keep visible text lines only; deduplication prevents repeated cards/headings.
            lines = [clean(x) for x in soup.stripped_strings]
            collected_at = datetime.now().astimezone().isoformat(timespec="seconds")
            found_here = 0
            for line in lines:
                record = parse_line(line, page_title, response.url, collected_at)
                if not record:
                    continue
                key = (record["listing_title"], record["rent_type"], record["deposit_manwon"], record["monthly_rent_manwon"], record["area_m2"])
                if key in seen:
                    continue
                seen.add(key)
                records.append(record)
                found_here += 1
            print(f"  페이지 제목: {page_title} / 추출: {found_here}건")
            if found_here == 0:
                failures.append({"url": url, "error": "매물 요약을 추출하지 못함(페이지 구조 변경 또는 차단 가능)"})
            time.sleep(1.2)
        except requests.RequestException as e:
            print("요청 실패:", url, str(e)[:160])
            failures.append({"url": url, "error": str(e)[:200]})
    if not records:
        raise SystemExit("실제 매물을 추출하지 못했습니다. 기존 data.json은 덮어쓰지 않았습니다. sources.txt의 공개 HTML 주소나 사이트 접근 가능 여부를 확인하세요.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "source": "당근부동산 공개 HTML 페이지",
        "source_urls": urls,
        "collection_method": "Python requests + BeautifulSoup으로 공개 HTML의 실제 매물 요약 텍스트를 수집 (매물 API 호출 없음)",
        "updated_at": datetime.now().astimezone().date().isoformat(),
        "count": len(records), "records": records,
        "failures": failures,
        "note": "이 결과는 sources.txt에 등록한 페이지에서 실제로 추출된 요약만 포함합니다. 전국 모든 지역을 망라한 전체 매물 목록은 아니며, 각 지역 페이지의 공개 범위와 HTML에 따라 달라집니다."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: 실제 HTML에서 {len(records)}건 저장 -> {OUTPUT}")

if __name__ == "__main__":
    main()
