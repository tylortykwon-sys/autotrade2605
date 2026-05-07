import logging
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

from data.database import insert_market_data

logger = logging.getLogger(__name__)


def get_top_tickers(market: str = "KOSPI", top_n: int = 100) -> list[str]:
    """거래대금 상위 N개 종목 코드 반환"""
    today = datetime.now().strftime("%Y%m%d")
    try:
        df = stock.get_market_trading_value_by_ticker(today, market=market)
        if df.empty:
            # 당일 데이터 없으면 전 영업일 시도
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = stock.get_market_trading_value_by_ticker(yesterday, market=market)
        df = df.sort_values("거래대금", ascending=False)
        tickers = df.index.tolist()[:top_n]
        logger.info(f"[Collector] {market} 상위 {len(tickers)}종목 조회 완료")
        return tickers
    except Exception as e:
        logger.error(f"[Collector] 종목 목록 조회 실패: {e}")
        return []


def fetch_ohlcv(ticker: str, days: int = 365) -> pd.DataFrame:
    """단일 종목 OHLCV 수집 (pykrx)"""
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    df = stock.get_market_ohlcv_by_date(start, end, ticker)
    if df.empty:
        return df
    df.index = df.index.strftime("%Y-%m-%d")
    # pykrx 컬럼명 정규화
    col_map = {
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume"
    }
    df = df.rename(columns=col_map)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_and_store(ticker: str, days: int = 365):
    """OHLCV 수집 후 DB 저장"""
    try:
        df = fetch_ohlcv(ticker, days)
        if df.empty:
            logger.warning(f"[Collector] {ticker}: 데이터 없음")
            return
        rows = [
            {
                "ticker": ticker, "date": date,
                "open": int(row["open"]), "high": int(row["high"]),
                "low": int(row["low"]), "close": int(row["close"]),
                "volume": int(row["volume"]),
            }
            for date, row in df.iterrows()
        ]
        insert_market_data(rows)
        logger.info(f"[Collector] {ticker}: {len(rows)}건 저장")
    except Exception as e:
        logger.error(f"[Collector] {ticker} 수집 실패: {e}")


def fetch_all_top(market: str = "KOSPI", top_n: int = 100, days: int = 365):
    """거래대금 상위 종목 전체 수집"""
    tickers = get_top_tickers(market=market, top_n=top_n)
    for i, ticker in enumerate(tickers, 1):
        fetch_and_store(ticker, days)
        if i % 20 == 0:
            logger.info(f"[Collector] 진행: {i}/{len(tickers)}")
    logger.info(f"[Collector] 전체 {len(tickers)}종목 수집 완료")


def get_ticker_name(ticker: str) -> str:
    """종목코드 → 종목명"""
    try:
        return stock.get_market_ticker_name(ticker)
    except Exception:
        return ticker
