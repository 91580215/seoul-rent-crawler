# 서울 전월세 탐험대

서울시 연립·다세대 주택의 최근 1년 전세·월세 신고 데이터를 수집하고 검색하는 학생 데이터 프로젝트입니다.

## 데이터 출처
- 서울특별시 서울 열린데이터광장, **서울시 부동산 전월세가 정보 (OA-21276)**
- 공식 페이지: https://data.seoul.go.kr/dataList/OA-21276/S/1/datasetView.do
- API 서비스: `tbLnOpendataRentV`
- 라이선스: 공공누리 제1유형(출처표시)

## 실행
1. Python 3.10 이상 설치
2. `pip install -r requirements.txt`
3. 서울 열린데이터광장에서 무료 API 인증키를 발급받습니다.
4. Windows PowerShell에서 `$env:SEOUL_API_KEY="발급받은키"` 를 설정합니다.
5. `python crawler.py` 실행
6. `docs/data.json`이 생성됩니다. `docs/index.html`을 정적 웹 호스팅에 게시하면 검색 화면을 볼 수 있습니다.

## GitHub에서 자동 갱신과 웹 공개 설정
1. 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 이름을 `SEOUL_API_KEY`, 값은 발급받은 키로 저장합니다.
2. **Actions** 탭에서 **Update Seoul rent data → Run workflow**를 눌러 수집 작업을 실행합니다.
3. **Settings → Pages**에서 **Deploy from a branch**를 선택하고 Branch는 `main`, folder는 `/docs`로 설정해 저장합니다.
4. Pages 설정 화면에 나온 주소를 부모님과 공유할 수 있습니다.
5. Actions가 매일 실행되며 `docs/data.json`을 갱신합니다.

## 주의
- API는 최근 3년 데이터 범위로 제공되며, 이 프로젝트는 그중 최근 365일 계약만 표시합니다.
- 이 수집기는 공식 API를 사용하므로 인증키가 필요합니다. 키를 코드나 공개 파일에 넣지 마세요.
- 금액은 만원 단위입니다. 신고 자료는 현재 매물의 호가가 아니며, 신고 시점에 따라 최신 자료가 늦게 반영될 수 있습니다.
