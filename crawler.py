"""Public HTML crawler using requests + BeautifulSoup only. No APIs or access-control bypass.
Put verified public listing-page URLs, one per line, in sources.txt.
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
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StudentHousingResearch/1.0)", "Accept-Language": "ko-KR,ko;q=0.9"}
REGIONS = ["서울특별시","부산광역시","대구광역시","인천광역시","광주광역시","대전광역시","울산광역시","세종특별자치시","경기도","강원특별자치도","충청북도","충청남도","전북특별자치도","전라남도","경상북도","경상남도","제주특별자치도"]

def clean(value):
    return re.sub(r"\\s+", " ", value or "").strip()

def amount_manwon(raw):
    raw = (raw or "").replace(",", "").replace(" ", "").replace("만원", "").replace("원", "")
    if not raw:
        return None
    total = 0
    if "억" in raw:
        head, _, tail = raw.partition("억")
        total = int(head or 0) * 10000
        tail = tail.replace("만", "")
        if tail.isdigit():
            total += int(tail)
        return total
    raw = raw.replace("만", "")
    return int(raw) if raw.isdigit() else None

def parse_price(text):
    compact = text.replace(",", "").replace(" ", "")
    kind = "전세" if "전세" in compact else ("월세" if "월세" in compact else "")
    if not kind:
        return None
    if kind == "전세":
        match = re.search(r"전세(?:보증금)?([0-9억만]+)", compact)
        if not match:
            return None
        deposit = amount_manwon(match.group(1))
        return (kind, deposit, 0) if deposit is not None else None
    match = re.search(r"(?:보증금)?([0-9억만]+)(?:원)?[/·](?:월세)?([0-9억만]+)", compact)
    if not match:
        match = re.search(r"월세([0-9억만]+)/([0-9억만]+)", compact)
    if not match:
        return None
    deposit, monthly = amount_manwon(match.group(1)), amount_manwon(match.group(2))
    return (kind, deposit, monthly) if deposit is not None and monthly is not None else None

def region_from(text):
    sido = next((name for name in REGIONS if name in text), "")
    if not sido:
        return "", "", ""
    parts = re.split(r"[\\s,·|]+", text.split(sido, 1)[1].strip())
    sigungu = parts[0] if parts and re.search(r"(구|시|군)$", parts[0]) else ""
    dong = next((p for p in parts[1:] if re.search(r"(동|읍|면|리)$", p)), "")
    return sido, sigungu, dong

def main():
    if not SOURCES.exists():
        SOURCES.write_text("# 공개 HTML 매물 목록 페이지 URL을 한 줄에 하나씩 입력하세요.\n", encoding="utf-8")
    urls = [line.strip() for line in SOURCES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not urls:
        raise SystemExit("sources.txt에 확인된 공개 HTML 매물 페이지 주소가 없습니다. API나 임의 데이터로 대체하지 않습니다.")
    records, seen = [], set()
    for url in urls:
        if not url.startswith(("https://", "http://")):
            print("건너뜀: HTTP(S) 주소가 아님:", url)
            continue
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            print("HTTP", response.status_code, response.url)
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                print("건너뜀: HTML이 아닌 응답")
                continue
            soup = BeautifulSoup(response.content, "html.parser")
            for node in soup.select("article, li, .item, .list-item, .room, .property, a[href]"):
                title = clean(node.get_text(" ", strip=True))
                if len(title) < 8 or not any(word in title for word in ("전세", "월세")):
                    continue
                if not any(word in title for word in ("원룸", "투룸", "빌라", "다세대", "연립", "주택")):
                    continue
                parsed = parse_price(title)
                if not parsed:
                    continue
                rent_type, deposit, monthly = parsed
                link_node = node if node.name == "a" else node.select_one("a[href]")
                link = urljoin(response.url, link_node.get("href", "")) if link_node else response.url
                key = (link, title)
                if key in seen:
                    continue
                seen.add(key)
                sido, sigungu, dong = region_from(title)
                housing = next((word for word in ("원룸", "투룸", "빌라", "다세대", "연립", "주택") if word in title), "주택")
                area = re.search(r"([0-9]+(?:\\.[0-9]+)?)\\s*㎡", title)
                records.append({
                    "sido": sido, "sigungu": sigungu, "neighborhood": dong,
                    "rent_type": rent_type, "housing_type": housing,
                    "deposit_manwon": deposit, "monthly_rent_manwon": monthly,
                    "area_m2": float(area.group(1)) if area else None,
                    "building": title[:100], "listing_title": title[:300],
                    "listing_url": link, "source_url": response.url,
                    "collected_at": datetime.now().astimezone().isoformat(timespec="seconds")
                })
            time.sleep(1)
        except requests.RequestException as exc:
            print("요청 실패:", url, str(exc)[:160])
    if not records:
        raise SystemExit("실제 매물 HTML을 추출하지 못했습니다. data.json은 덮어쓰지 않았습니다.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "source": "sources.txt에 지정한 공개 HTML 페이지", "source_urls": urls,
        "collection_method": "requests + BeautifulSoup HTML 파싱 (API 미사용)",
        "updated_at": datetime.now().astimezone().date().isoformat(),
        "count": len(records), "records": records,
        "note": "공개 HTML에서 확인된 항목만 저장합니다. 등록일이 없으면 최신성을 보장하지 않습니다."
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print("수집 완료:", len(records), "건")

if __name__ == "__main__":
    main()
