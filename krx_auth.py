import requests
from pykrx.website.comm import webio

# 1. 전역으로 공유할 단일 세션 생성
_session = requests.Session()

# 2. 모듈이 임포트될 때 pykrx 통신 모듈을 Monkey Patching
def _session_post_read(self, **params):
  return _session.post(self.url, headers=self.headers, data=params)

def _session_get_read(self, **params):
  return _session.get(self.url, headers=self.headers, params=params)

webio.Post.read = _session_post_read
webio.Get.read = _session_get_read

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