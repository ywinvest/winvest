import os
import sys
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from sqlmodel import Session
from sqlalchemy.dialects.postgresql import insert

# Ensure parent directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import engine
from models import KrxMarketStatus
import market

SIGNAL_MAP = {
  "green": "양호🟢",
  "yellow": "주의🟡",
  "red": "경고🔴"
}

def sync_market_status():
    start_date = (datetime.today() - timedelta(days=100)).strftime('%Y-%m-%d')
    today_str = datetime.today().strftime('%Y-%m-%d')
    
    # KOSPI (KS11) and KOSDAQ (KQ11)
    market_codes = ["KS11", "KQ11"]
    
    with Session(engine) as session:
        for market_code in market_codes:
            print(f"Syncing market status for {market_code}...")
            df = fdr.DataReader(market_code, start_date)
            if df.empty:
                print(f"No data for {market_code}")
                continue
                
            df = market.add_indicators(df.dropna())
            if len(df) < 2:
                print(f"Not enough data for {market_code}")
                continue
                
            today_data = df.iloc[-1]
            today_close = float(today_data['Close'])
            today_change = float(today_data['Change'])
            
            today_signal_raw = market.get_signal(
                today_data['MA20_Up'], today_data['ADX'], today_data['DI'], today_data['MA5_Up']
            )
            yesterday_data = df.iloc[-2]
            yesterday_signal_raw = market.get_signal(
                yesterday_data['MA20_Up'], yesterday_data['ADX'], yesterday_data['DI'], yesterday_data['MA5_Up']
            )
            
            today_signal = SIGNAL_MAP[today_signal_raw]
            yesterday_signal = SIGNAL_MAP[yesterday_signal_raw]
            
            if today_signal == yesterday_signal:
                status_msg = f"{today_signal} 유지"
            else:
                status_msg = f"{yesterday_signal} ➡ {today_signal} 전환"
            
            stmt = insert(KrxMarketStatus).values(
                date=today_str,
                market=market_code,
                close=today_close,
                change=today_change,
                signal=today_signal_raw,
                signal_text=today_signal,
                status_msg=status_msg
            )
            
            stmt = stmt.on_conflict_do_update(
                index_elements=['date', 'market'],
                set_={
                    'close': stmt.excluded.close,
                    'change': stmt.excluded.change,
                    'signal': stmt.excluded.signal,
                    'signal_text': stmt.excluded.signal_text,
                    'status_msg': stmt.excluded.status_msg
                }
            )
            
            session.exec(stmt)
        session.commit()
        print(f"Successfully synced market status for {today_str}")

if __name__ == "__main__":
    sync_market_status()
