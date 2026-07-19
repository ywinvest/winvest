from sqlmodel import Session, select
from models import KrxDailyStock, KrxDailyStockIndicator

def get_rs_table_data(
    session: Session, 
    date_str: str = None
) -> list[dict]:
    """
    RS 데이터를 DB에서 조회하고 템플릿 렌더링에 맞게 반환합니다.
    """
    if date_str:
        target_date = date_str
    else:
        # 가장 최신 날짜 가져오기
        latest_date_result = session.exec(
            select(KrxDailyStockIndicator.date).order_by(KrxDailyStockIndicator.date.desc()).limit(1)
        ).first()
        target_date = latest_date_result

    if not target_date:
        return []
    
    # 조인 기본 쿼리 및 기본 정렬 (통합 RS 내림차순)
    statement = (
        select(KrxDailyStock, KrxDailyStockIndicator)
        .join(KrxDailyStockIndicator, (KrxDailyStock.code == KrxDailyStockIndicator.code) & (KrxDailyStock.date == KrxDailyStockIndicator.date))
        .where(KrxDailyStockIndicator.date == target_date)
        .order_by(
            KrxDailyStockIndicator.rs.desc(),
            KrxDailyStockIndicator.rs_1m.desc(),
            KrxDailyStockIndicator.rs_3m.desc(),
            KrxDailyStockIndicator.rs_6m.desc(),
            KrxDailyStockIndicator.rs_12m.desc(),
            KrxDailyStock.marcap.desc()
        )
    )
        
    results = session.exec(statement).all()
    
    # 템플릿에 맞게 데이터 가공
    stocks = []
    for idx, (marcap, rs_data) in enumerate(results, start=1):
        stocks.append({
            "date": target_date,
            "name": marcap.name,
            "code": marcap.code,
            "market": marcap.market,
            "changes_ratio": marcap.changes_ratio,
            "changes": marcap.changes,
            "marcap": marcap.marcap,
            "amount": marcap.amount,
            "rs_rank": idx,
            "close": marcap.close,
            "rs": rs_data.rs,
            "rs_1m": rs_data.rs_1m,
            "rs_3m": rs_data.rs_3m,
            "rs_6m": rs_data.rs_6m,
            "rs_12m": rs_data.rs_12m,
        })
    return stocks
