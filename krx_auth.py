import requests

# 1. 전역으로 공유할 단일 세션 생성
_session = requests.Session()

# --- requests 모듈 몽키 패칭 (FinanceDataReader 등 지원) ---
# 기존 requests의 get, post 함수를 백업해둡니다.
_original_get = requests.get
_original_post = requests.post

def _patched_get(url, params=None, **kwargs):
  # 호출 시 쿠키를 직접 명시하지 않았다면 krx 인증 세션의 쿠키를 주입합니다.
  if 'cookies' not in kwargs:
    kwargs['cookies'] = _session.cookies
  return _original_get(url, params=params, **kwargs)

def _patched_post(url, data=None, json=None, **kwargs):
  # 호출 시 쿠키를 직접 명시하지 않았다면 krx 인증 세션의 쿠키를 주입합니다.
  if 'cookies' not in kwargs:
    kwargs['cookies'] = _session.cookies
  return _original_post(url, data=data, json=json, **kwargs)

# 파이썬 환경의 기본 requests를 패치된 함수로 바꿔치기합니다.
requests.get = _patched_get
requests.post = _patched_post
# -----------------------------------------------------------

def login_krx(login_id: str, login_pw: str) -> bool:
  """KRX 정보데이터시스템 로그인 후 세션 쿠키를 갱신합니다."""
  _LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
  _LOGIN_JSP  = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
  _LOGIN_URL  = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
  _UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

  _session.get(_LOGIN_PAGE, headers={"User-Agent": _UA}, timeout=15)
  _session.get(_LOGIN_JSP, headers={"User-Agent": _UA, "Referer": _LOGIN_PAGE}, timeout=15)

  payload = {"mbrNm": "", "telNo": "", "di": "", "certType": "", "mbrId": login_id, "pw": login_pw}
  headers = {"User-Agent": _UA, "Referer": _LOGIN_PAGE}

  resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
  error_code = resp.json().get("_error_code", "")

  if error_code == "CD011":
    payload["skipDup"] = "Y"
    resp = _session.post(_LOGIN_URL, data=payload, headers=headers, timeout=15)
    error_code = resp.json().get("_error_code", "")

  return error_code == "CD001"