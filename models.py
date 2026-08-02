from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import BigInteger

class KrxDailyStock(SQLModel, table=True):
    __tablename__ = "krx_daily_stocks"
    date: str = Field(primary_key=True)
    code: str = Field(primary_key=True)
    name: str
    market: str
    open: int
    high: int
    low: int
    close: int
    volume: int = Field(sa_column=Column(BigInteger()))
    amount: int = Field(sa_column=Column(BigInteger()))
    changes: int
    changes_ratio: float
    marcap: int = Field(sa_column=Column(BigInteger()))
    stocks: int = Field(sa_column=Column(BigInteger()))
    rank: int

class KrxDailyAdjustedStock(SQLModel, table=True):
    __tablename__ = "krx_daily_adjusted_stocks"
    date: str = Field(primary_key=True)
    code: str = Field(primary_key=True)
    open: int
    high: int
    low: int
    close: int
    volume: int = Field(sa_column=Column(BigInteger()))
    change: float

class KrxDailyStockIndicator(SQLModel, table=True):
    __tablename__ = "krx_daily_stock_indicators"
    date: str = Field(primary_key=True)
    code: str = Field(primary_key=True)
    rs: float
    rs_1m: float
    rs_3m: float
    rs_6m: float
    rs_12m: float

class KrxDailyIndex(SQLModel, table=True):
    __tablename__ = "krx_daily_indices"
    date: str = Field(primary_key=True)
    market: str = Field(primary_key=True)
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(sa_column=Column(BigInteger()))
    change: float

class KrxDailyIndexIndicator(SQLModel, table=True):
    __tablename__ = "krx_daily_index_indicators"
    date: str = Field(primary_key=True)
    market: str = Field(primary_key=True)
    ma5: float
    ma20: float
    ma60: float
    ma120: float
    rsi: float
    adx: float
    di: bool
