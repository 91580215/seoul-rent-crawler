"""Public listing HTML crawler (requests + BeautifulSoup; no listing API).
Configure public listing-page URLs in sources.txt. Parses ordinary HTML cards and
server-rendered JSON embedded in HTML pages, then saves only records found there.
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
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36", "Accept-Language": "ko-KR,ko;q=0.9"}
REGIONS = ["서울특별시","부산광역시","대구광역시","인천광역시","광주광역시","대전광역시","울산광역시","세종특별자치시","경기도","강원특별자치도","충청북도","충청남도","전북특별자치도","전라남도","경상북도","경상남도","제주특별자치도"]

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def money_to_manwon(value):
    if value is None: return None
    if isinstance(value, (int, float)):
        return round(value / 10000) if value > 100000 else int(value)
    s = clean(value).replace(",", "").replace(" ", "")
    if not s: return None
    m = re.search(r"(?:(\d+)억)?(?:(\d+)만)?", s)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else None

def parse_price(text, item=None):
    item = item or {}
    deal = clean(item.get("salesType") or item.get("tradeType") or item.get("rent_type") or "")
    trade = item.get("trades") or item.get("trade") or {}
    if isinstance(trade, list): trade = trade[0] if trade else {}
    if isinstance(trade, dict):
        deposit_raw = trade.get("deposit") or trade.get("depositPrice") or trade.get("price")
        monthly_raw = trade.get("monthlyRent") or trade.get("rent") or trade.get("rentPrice")
    else:
        deposit_raw = monthly_raw = None
    deposit = money_to_manwon(deposit_raw)
    monthly = money_to_manwon(monthly_raw)
    compact = clean(text).replace(",", "").replace(" ", "")
    if "전세" in deal or "전세" in compact or "JEONSE" in deal.upper():
        if deposit is None:
            m = re.search(r"전세(?:보증금)?(\d+억?\d*만?)", compact)
            deposit = money_to_manwon(m.group(1)) if m else None
        return ("전세", deposit, 0) if deposit is not None else None
    if "월세" in deal or "월세" in compact or "MONTHLY" in deal.upper():
        if deposit is None or monthly is None:
            m = re.search(r"(?:월세)?(\d+억?\d*만?)[/·](\d+만?)", compact)
            if m:
                deposit = deposit if deposit is not None else money_to_manwon(m.group(1))
                monthly = monthly if monthly is not None else money_to_manwon(m.group(2))
        return ("월세", deposit, monthly) if deposit is not None and monthly is not None else None
    return None

def walk_dicts(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values(): yield from walk_dicts(value)
    elif isinstance(obj, list):
        for value in obj: yield from walk_dicts(value)

def embedded_json_candidates(html):
    # Parse common server-rendered JSON script blocks without calling a data API.
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        raw = raw.strip()
        if not raw: continue
        if script.get("type") == "application/ld+json":
            try: yield json.loads(raw)
            except (ValueError, TypeError): pass
        # Some sites embed JSON as a JS assignment in the delivered HTML.
        for marker in ("window.__remixContext", "window.__INITIAL_STATE__", "__NEXT_DATA__"):
            pos = raw.find(marker)
            if pos >= 0:
                start = raw.find("{", pos)
                if start < 0: continue
                depth, quoted, escaped = 0, False, False
                for i in range(start, len(raw)):
                    c = raw[i]
                    if quoted:
                        if escaped: escaped = False
                        elif c == "\\": escaped = True
                        elif c == '"': quoted = False
                    else:
                        if c == '"': quoted = True
                        elif c == "{": depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                try: yield json.loads(raw[start:i+1])
                                except (ValueError, TypeError): pass
                                break

def normalize_item(item, page_url, text=""):
    title = clean(item.get("title") or item.get("articleName") or item.get("name") or item.get("buildingName") or text)
    if not title: return None
    trade = item.get("trades") or item.get("trade") or {}
    if isinstance(trade, list): trade = trade[0] if trade else {}
    trade_label = clean(item.get("salesType") or item.get("tradeType") or item.get("dealTypeKo") or "")
    alltext = " ".join([title, clean(item.get("content")), trade_label, clean(trade)])
    if not any(k in alltext for k in ("전세","월세","JEONSE","MONTHLY_RENT")): return None
    if not any(k in alltext for k in ("원룸","투룸","빌라","다세대","연립","주택","VILLA","STUDIO","ONE_ROOM")): return None
    parsed = parse_price(alltext, item)
    if not parsed: return None
    typ, deposit, monthly = parsed
    region_text = " ".join([clean(item.get("address")), clean(item.get("region")), title, text])
    sido = next((r for r in REGIONS if r in region_text), "")
    parts = re.split(r"[\s,·|]+", region_text)
    sigungu = next((p for p in parts if p.endswith(("구","시","군"))), "")
    dong = next((p for p in parts if p.endswith(("동","읍","면","리"))), "")
    housing = next((k for k in ("원룸","투룸","빌라","다세대","연립","주택") if k in alltext), "주택")
    link = item.get("webUrl") or item.get("url") or item.get("link") or item.get("articleUrl") or ""
    if isinstance(link, dict): link = link.get("url") or link.get("href") or ""
    link = urljoin(page_url, str(link)) if link else page_url
    area = item.get("area") or item.get("areaM2") or item.get("exclusiveArea")
    if isinstance(area, dict): area = area.get("value") or area.get("m2")
    try: area = float(re.search(r"\d+(?:\.\d+)?", str(area)).group()) if area is not None and re.search(r"\d+(?:\.\d+)?", str(area)) else None
    except (ValueError, AttributeError): area = None
    return {
        "sido": sido, "sigungu": sigungu, "neighborhood": dong,
        "rent_type": typ, "housing_type": housing,
        "deposit_manwon": deposit, "monthly_rent_manwon": monthly,
        "area_m2": area, "building": title[:100], "listing_title": title[:300],
        "listing_url": link, "source_url": page_url,
        "collected_at": datetime.now().astimezone().isoformat(timespec="seconds")
    }

def main():
    if not SOURCES.exists():
        SOURCES.write_text("# 공개 HTML 매물 목록 URL을 한 줄에 하나씩 입력하세요.\\n", encoding="utf-8")
    urls = [line.strip() for line in SOURCES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not urls: raise SystemExit("sources.txt에 공개 HTML 목록 URL이 없습니다.")
    records, seen = [], set()
    for url in urls:
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            print(f"HTTP {response.status_code}: {response.url}")
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                print("건너뜀: HTML이 아닙니다."); continue
            soup = BeautifulSoup(response.text, "html.parser")
            # Extract server-rendered structured listing objects from HTML scripts.
            for obj in embedded_json_candidates(response.text):
                for item in walk_dicts(obj):
                    record = normalize_item(item, response.url)
                    if record:
                        key = (record["listing_url"], record["listing_title"])
                        if key not in seen: seen.add(key); records.append(record)
            # Fallback: parse visible HTML listing cards.
            for node in soup.select("article, li, [class*=item], [class*=room], [class*=property], a[href]"):
                title = clean(node.get_text(" ", strip=True))
                if len(title) < 8: continue
                record = normalize_item({}, response.url, title)
                if record:
                    a = node if node.name == "a" else node.select_one("a[href]")
                    if a and a.get("href"): record["listing_url"] = urljoin(response.url, a["href"])
                    key = (record["listing_url"], record["listing_title"])
                    if key not in seen: seen.add(key); records.append(record)
            time.sleep(1)
        except requests.RequestException as exc:
            print("요청 실패:", url, str(exc)[:180])
    if not records:
        raise SystemExit("HTML에서 조건에 맞는 실제 매물을 추출하지 못했습니다. 기존 data.json은 보존했습니다.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "source": "sources.txt에 설정된 공개 HTML 페이지",
        "source_urls": urls,
        "collection_method": "requests + BeautifulSoup로 전달된 HTML 및 HTML 내 서버 렌더링 데이터 파싱 (별도 매물 API 호출 없음)",
        "updated_at": datetime.now().astimezone().date().isoformat(),
        "count": len(records), "records": records,
        "note": "수집된 페이지에 노출된 정보만 저장합니다. 등록일이 제공되지 않으면 최신성은 보장되지 않습니다."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"수집 완료: {len(records)}건")

if __name__ == "__main__": main()
