# Site5 나라장터 모니터링

나라장터 공공데이터개방표준서비스에서 입찰공고 데이터를 수집해 SQLite에 저장하고, `/site5` 대시보드에서 조회/필터링하며, 필터에 매칭되는 신규 공고를 디스코드 웹훅으로 알립니다. Google 서비스 계정 인증을 제공하면 Google Sheets에도 주기적으로 동기화합니다.

## 실행

```bash
python3 -m uvicorn site5.app:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://<ip주소>:8000/site5`로 접속합니다. 80 포트나 `/site5` 고정 경로가 필요하면 nginx에서 이 앱으로 프록시하면 됩니다.

## 설정

기본값은 기존 텍스트 파일에서 읽습니다.

- `공공데이터api.txt`: 나라장터 API endpoint와 service key
- `디스코드웹훅주소.txt`: Discord webhook URL, Google Sheets URL

민감정보가 들어가는 위 두 파일은 커밋하지 않습니다. 처음 배포할 때는 `.example.txt` 파일을 복사해 실제 값을 채워 넣으면 됩니다.

환경변수로 덮어쓸 수 있습니다.

```bash
G2B_API_ENDPOINT=https://apis.data.go.kr/1230000/ao/PubDataOpnStdService
G2B_SERVICE_KEY=...
DISCORD_WEBHOOK_URL=...
GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit
GOOGLE_SERVICE_ACCOUNT_FILE=/absolute/path/service-account.json
SITE5_DB_PATH=data/site5.db
SITE5_COLLECT_INTERVAL_SECONDS=600
SITE5_SHEET_SYNC_INTERVAL_SECONDS=3600
SITE5_ENABLE_SCHEDULER=true
SITE5_LOGIN_USERNAME=...
SITE5_LOGIN_PASSWORD=...
SITE5_SESSION_SECRET=...
```

`/site5` 대시보드는 로그인 후 접근할 수 있습니다. 계정은 `SITE5_LOGIN_USERNAME`, `SITE5_LOGIN_PASSWORD` 환경변수로 덮어쓸 수 있습니다.

## Google Sheets 쓰기 권한

스프레드시트 URL만으로는 서버가 시트에 쓸 수 없습니다. Google Cloud 서비스 계정 JSON을 만들고, 해당 서비스 계정 이메일을 스프레드시트 편집자로 공유한 뒤 `GOOGLE_SERVICE_ACCOUNT_FILE` 또는 `GOOGLE_SERVICE_ACCOUNT_JSON`을 설정해야 합니다.

인증이 없으면 앱은 정상 동작하지만 스프레드시트 동기화는 `skipped` 상태로 기록됩니다.

## 알림 기준

디스코드 알림은 필터가 저장 또는 수정된 이후 새로 수집된 공고만 대상으로 합니다. 기존 DB에 이미 들어온 공고는 대시보드에서 검색/필터링할 수 있지만, 필터를 새로 만들었다고 과거 공고가 한 번에 발송되지는 않습니다.

## 포트 없이 `/site5`로 노출

uvicorn은 내부 포트에서 실행하고 nginx가 `/site5`를 프록시하도록 구성합니다.

예시 파일:

- `deploy/site5.service`
- `deploy/nginx-site5.conf`

적용 예:

```bash
sudo cp deploy/site5.service /etc/systemd/system/site5.service
sudo systemctl daemon-reload
sudo systemctl enable --now site5
```

nginx 설정의 `server { ... }` 블록 안에 `deploy/nginx-site5.conf` 내용을 넣고 reload하면 `http://<ip주소>/site5`로 접근할 수 있습니다.
