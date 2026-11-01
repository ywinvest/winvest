from sqlmodel import SQLModel, create_engine, Session
from app.core.config import DATABASE_URL
import app.models  # noqa: F401 — Register SQLModel table metadata

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL 환경 변수가 설정되지 않았습니다.")

        connect_args = {}
        if "postgres" in DATABASE_URL:
            # Supabase default statement_timeout is very short. Increase to 5 minutes for massive analytics queries.
            connect_args = {"options": "-c statement_timeout=300000"}

        _engine = create_engine(
            DATABASE_URL,
            connect_args=connect_args,
            echo=False,
        )
    return _engine


def __getattr__(name: str):
    if name == "engine":
        return get_engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_db_and_tables():
    """앱 시작 시 원격 클라우드에 테이블이 없으면 생성"""
    SQLModel.metadata.create_all(get_engine())


def get_session():
    """FastAPI 의존성 주입을 위한 제너레이터 (웹 서버는 클라우드 DB 직접 조회)"""
    with Session(get_engine()) as session:
        yield session


if __name__ == "__main__":
    print("🚀 테이블 생성 중...")
    create_db_and_tables()
    print("✅ 테이블 생성 완료!")
