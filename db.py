import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session
import models  # 테이블 레지스트리 등록을 위해 반드시 임포트

load_dotenv()

# Turso DB 연결 URL 및 Auth Token
# URL 형식: libsql://[데이터베이스-이름]-[조직이름].turso.io
turso_url = os.getenv("TURSO_DATABASE_URL")
turso_token = os.getenv("TURSO_AUTH_TOKEN")

if not turso_url:
    raise ValueError("TURSO_DATABASE_URL 환경 변수가 설정되지 않았습니다.")

# 1. 원격 Turso 클라우드 엔진 (웹 서버 및 데이터 적재 파이프라인용)
remote_db_url = f"sqlite+{turso_url}/?secure=true"
engine = create_engine(
    remote_db_url,
    connect_args={'check_same_thread': False, 'auth_token': turso_token},
    echo=False
)

def create_db_and_tables():
    """앱 시작 시 원격 클라우드에 테이블이 없으면 생성"""
    SQLModel.metadata.create_all(engine)

def get_session():
    """FastAPI 의존성 주입을 위한 제너레이터 (웹 서버는 클라우드 DB 직접 조회)"""
    with Session(engine) as session:
        yield session

if __name__ == "__main__":
    # 이 파일을 직접 실행하면 테이블을 생성합니다.
    print("🚀 테이블 생성 중...")
    create_db_and_tables()
    print("✅ 테이블 생성 완료!")
