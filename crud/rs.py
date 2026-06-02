from sqlmodel import Session, select
from sqlalchemy import or_, desc, asc
from models import KrxDailyStock, KrxDailyStockRS

def get_rs_table_data(
    session: Session, 
    date_str: str = None,
    search: str = None,
    market: str = None,
    min_marcap: int = None,
    sort_col: str = "rs",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
    """
    RS 데이터를 DB에서 조회하고 템플릿 렌더링에 맞게 반환합니다.
    """
    if date_str:
        target_date = date_str
    else:
        # 가장 최신 날짜 가져오기
        latest_date_result = session.exec(
            select(KrxDailyStockRS.date).order_by(KrxDailyStockRS.date.desc()).limit(1)
        ).first()
        target_date = latest_date_result

    if not target_date:
        return []
    
    # 조인 기본 쿼리
    statement = (
        select(KrxDailyStock, KrxDailyStockRS)
        .join(KrxDailyStockRS, (KrxDailyStock.code == KrxDailyStockRS.code) & (KrxDailyStock.date == KrxDailyStockRS.date))
        .where(KrxDailyStockRS.date == target_date)
    )

    # 검색어 필터
    if search:
        search_pattern = f"%{search}%"
        statement = statement.where(
            or_(
                KrxDailyStock.name.like(search_pattern),
                KrxDailyStock.code.like(search_pattern)
            )
        )
    
    # 시장 필터
    if market:
        statement = statement.where(KrxDailyStock.market == market)
        
    # 시가총액 필터
    if min_marcap:
        # 프론트엔드에서 넘어오는 단위는 '억' 단위를 100000000 곱해서 넘길 수도 있고, 아닐 수도 있음.
        # 프론트에서 넘어오는 값이 5000 이라면, DB 값과 비교해야함.
        # 기존 JS에서는 minMarcap을 `parseInt(marcapFilter.value) * 100000000` 로 계산했음.
        # 여기서는 백엔드로 그대로 넘길 것이므로, 여기서 곱해줌.
        statement = statement.where(KrxDailyStock.marcap >= (min_marcap * 100000000))
        
    # 정렬 매핑
    sort_mapping = {
        "rs": KrxDailyStockRS.rs,
        "rs_1m": KrxDailyStockRS.rs_1m,
        "rs_3m": KrxDailyStockRS.rs_3m,
        "rs_6m": KrxDailyStockRS.rs_6m,
        "rs_12m": KrxDailyStockRS.rs_12m,
        "marcap": KrxDailyStock.marcap,
        "changes_ratio": KrxDailyStock.changes_ratio
    }
    
    order_column = sort_mapping.get(sort_col, KrxDailyStockRS.rs)
    if sort_order == "asc":
        statement = statement.order_by(asc(order_column))
    else:
        statement = statement.order_by(desc(order_column))
        
    # 페이징
    statement = statement.offset(offset).limit(limit)
        
    results = session.exec(statement).all()
    
    # 템플릿에 맞게 데이터 가공
    stocks = []
    for idx, (marcap, rs_data) in enumerate(results, start=offset + 1):
        stocks.append({
            "date": target_date,
            "name": marcap.name,
            "code": marcap.code,
            "market": marcap.market,
            "changes_ratio": marcap.changes_ratio,
            "changes": marcap.changes,
            "marcap": marcap.marcap,
            "amount": marcap.amount,
            "rank": idx,  # RS Rank
            "rs": rs_data.rs,
            "rs_1m": rs_data.rs_1m,
            "rs_3m": rs_data.rs_3m,
            "rs_6m": rs_data.rs_6m,
            "rs_12m": rs_data.rs_12m,
        })
    return stocks
