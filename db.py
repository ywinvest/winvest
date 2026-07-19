import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session
import models  # 테이블 레지스트리 등록을 위해 반드시 임포트

load_dotenv()

# Supabase (PostgreSQL) 연결 URL 우선 사용
db_url = os.getenv("DATABASE_URL")
if not db_url:
    # 하위 호환성을 위해 Turso URL 지원
    turso_url = os.getenv("TURSO_DATABASE_URL")
    if turso_url:
        db_url = f"sqlite+{turso_url}/?secure=true"
    else:
        raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다.")

connect_args = {}
if "sqlite" in db_url:
    turso_token = os.getenv("TURSO_AUTH_TOKEN")
    connect_args = {'check_same_thread': False, 'auth_token': turso_token}
elif "postgres" in db_url:
    # Supabase default statement_timeout is very short. Increase to 5 minutes for massive analytics queries.
    connect_args = {"options": "-c statement_timeout=300000"}

engine = create_engine(
    db_url,
    connect_args=connect_args,
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
