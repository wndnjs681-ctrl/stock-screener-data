# KRX Open API 설정
1. 새 Public repo `wndnjs681-ctrl/stock-screener-data` 생성
2. ZIP 파일을 경로 그대로 업로드
3. GitHub repo → Settings → Secrets and variables → Actions → New repository secret
4. Name: `KRX_API_KEY`
5. Secret: 발급받은 KRX 인증키 전체 문자열 → Add secret
6. KRX Data Marketplace에서 `유가증권 일별매매정보`, `코스닥 일별매매정보` 활용 승인이 되어 있어야 함
7. Actions → Build screener data → Run workflow → `kr`

키는 코드에 저장되지 않고 Actions 환경변수로만 전달되어 HTTP `AUTH_KEY` 헤더에 들어갑니다.
최초 KR 실행은 최근 약 430일 평일을 조회해 `cache/kr_ohlcv.csv.gz`를 만들고, 다음부터 마지막 캐시 날짜 이후만 증분 조회합니다.
코드를 리포에 올린 뒤 변경사항은 다음 Actions 실행부터 적용됩니다.
