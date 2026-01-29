import os
import sys
from datetime import datetime
from notion_client import Client

# GitHub 환경변수
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
ROOT_PAGE_ID = os.environ.get("PARENT_PAGE_ID")

def create_notion_db():
  # 1. 필수 설정 확인
  if not NOTION_TOKEN or not ROOT_PAGE_ID:
    print("❌ Error: 토큰이나 부모 페이지 ID가 설정되지 않았습니다.")
    sys.exit(1)

  client = Client(auth=NOTION_TOKEN)
  now = datetime.now()

  # 2. 일별 DB 제목 정의
  db_title = now.strftime("%Y%m%d")     # 예: 20260211 (DB)

  print(f"🚀 Notion 일별 DB 생성 시작: Root > {db_title}")

  # 3. DB 스키마(컬럼) 정의
  db_schema = {
    # "No.": {"unique_id": {}},
    "종목명": {"title": {}},
    "순위": {"number": {"format": "number"}},
    "RS": {"number": {"format": "number"}},
    "RS_1M": {"number": {"format": "number"}},
    "RS_3M": {"number": {"format": "number"}},
    "RS_6M": {"number": {"format": "number"}},
    "RS_12M": {"number": {"format": "number"}},
    "시장": {
      "select": {
        "options": [
          {"name": "KOSPI", "color": "purple"},
          {"name": "KOSDAQ", "color": "brown"}
        ]
      }
    },
    "시가총액": {"rich_text": {}},
    "시가총액(원)": {"number": {"format": "won"}},
    "종목코드": {"rich_text": {}}
  }

  print(f"🔎 일별 DB('{db_title}') 확인 중...")

  target_db_id = None

  # 4. 기존 DB 검색 (Root 페이지 안에서 직접 검색)
  try:
    response = client.blocks.children.list(block_id=ROOT_PAGE_ID)
    for block in response.get("results", []):
      if block["type"] == "child_database":
        existing_title = block["child_database"].get("title", "")
        if existing_title == db_title:
          target_db_id = block["id"]
          print(f"✅ 이미 존재하는 오늘자 DB 발견! ID: {target_db_id}")
          break
  except Exception as e:
    print(f"⚠️ DB 목록 조회 중 오류: {e}")

  # 5. DB 생성 또는 업데이트 로직
  if not target_db_id:
    # [생성] initial_data_source 사용
    print(f"🆕 '{db_title}' DB가 없어서 Root 페이지에 새로 생성합니다...")
    try:
      new_db = client.databases.create(
          parent={"type": "page_id", "page_id": ROOT_PAGE_ID},
          title=[{"type": "text", "text": {"content": db_title}}],
          initial_data_source={
            "properties": db_schema
          }
      )
      target_db_id = new_db['id']
      print(f"🎉 새 일별 DB 생성 완료! ID: {target_db_id}")

    except Exception as e:
      print(f"❌ DB 생성 실패: {e}")
      sys.exit(1)
  else:
    # [업데이트] Data Source Update 사용
    print(f"🔄 기존 DB({db_title})의 Data Source를 업데이트합니다...")
    try:
      # 1. DB 상세 정보 조회하여 data_source_id 찾기
      db_info = client.databases.retrieve(database_id=target_db_id)

      # 2. data_sources 목록에서 첫 번째 ID 추출
      data_sources = db_info.get("data_sources", [])
      if not data_sources:
        print("⚠️ 경고: 이 데이터베이스에는 Data Source가 없습니다. (업데이트 건너뜀)")
      else:
        target_ds_id = data_sources[0]["id"]
        print(f"ℹ️ Data Source ID 발견: {target_ds_id}")

        # 3. Data Source 업데이트 (컬럼 동기화)
        client.data_sources.update(
            data_source_id=target_ds_id,
            properties=db_schema
        )
        print("✨ Data Source(컬럼) 업데이트 완료!")

    except Exception as e:
      print(f"⚠️ Data Source 업데이트 중 오류 발생: {e}")

  # 6. 결과 ID 저장 (Github Actions Env)
  env_file = os.getenv('GITHUB_ENV')
  if env_file:
    with open(env_file, "a") as f:
      f.write(f"CREATED_DB_ID={target_db_id}\n")

if __name__ == "__main__":
  create_notion_db()