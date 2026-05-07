import logging
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock

from data.database import insert_market_data

logger = logging.getLogger(__name__)


def get_top_tickers(market: str = "KOSPI", top_n: int = 100) -> list[str]:
    """
    거래량 상위 N개 종목 코드 반환
    1차: DB에 저장된 종목을 최근 거래량 기준으로 정렬
    2차: DB 없으면 KOSPI 대형주 기본 목록 반환
    """
    from data.database import get_connection
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # 최근 5일 평균 거래량 기준 상위 종목
        cursor.execute("""
            SELECT ticker, AVG(volume) as avg_vol
            FROM market_data
            WHERE date >= date('now', '-7 days')
            GROUP BY ticker
            ORDER BY avg_vol DESC
            LIMIT ?
        """, (top_n,))
        tickers = [row[0] for row in cursor.fetchall()]
        conn.close()
        if tickers:
            logger.info(f"[Collector] DB 기반 상위 {len(tickers)}종목 반환")
            return tickers
    except Exception as e:
        logger.error(f"[Collector] DB 종목 조회 실패: {e}")

    # fallback — KOSPI/KOSDAQ 대형주 고정 목록
    FALLBACK = [
        "005930", "000660", "035420", "005380", "051910",
        "006400", "028260", "003550", "066570", "105560",
        "032830", "055550", "096770", "034730", "018260",
        "011200", "000270", "207940", "068270", "035720",
        "323410", "003490", "316140", "015760", "010950",
        "009150", "033780", "030200", "086790", "017670",
    ]
    logger.info(f"[Collector] fallback 목록 {len(FALLBACK[:top_n])}종목 반환")
    return FALLBACK[:top_n]


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
