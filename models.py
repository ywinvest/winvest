from typing import Optional
from sqlmodel import Field, SQLModel

class KrxDailyStock(SQLModel, table=True):
    __tablename__ = "krx_daily_stock"
    date: str = Field(primary_key=True)
    code: str = Field(primary_key=True)
    name: str
    market: str
    open: int
    high: int
    low: int
    close: int
    volume: int
    amount: int
    changes: int
    changes_ratio: float
    marcap: int
    stocks: int
    rank: int

class KrxDailyStockRS(SQLModel, table=True):
    __tablename__ = "krx_daily_stock_rs"
    date: str = Field(primary_key=True)
    code: str = Field(primary_key=True)
    rs: float
    rs_1m: float
    rs_3m: float
    rs_6m: float
    rs_12m: float
