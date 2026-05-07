"""
ATR 기반 포지션 사이징
ATR% 구간에 따라 자본 대비 투자 비율을 동적으로 조정
"""
import os


def calc_position_size(total_capital: float, atr_pct: float) -> float:
    """
    ATR% → 투자 금액 (원)
    - atr_pct < 0.5 : 유동성 부족 → 0원 (매수 보류)
    - 0.5 ~ 1.5     : 저변동  → 자본의 20%
    - 1.5 ~ 3.0     : 중변동  → 자본의 10%
    - 3.0+          : 고변동  → 자본의 5%
    """
    max_ratio = float(os.getenv("MAX_POSITION_RATIO", "0.5"))

    if atr_pct < 0.5:
        base_ratio = 0.0
    elif atr_pct < 1.5:
        base_ratio = 0.20
    elif atr_pct < 3.0:
        base_ratio = 0.10
    else:
        base_ratio = 0.05

    ratio = min(base_ratio, max_ratio)
    return total_capital * ratio


def calc_stop_price(buy_price: float, atr: float, mult: float = 1.5) -> float:
    """ATR 기반 손절가 = 매수가 - ATR × 배수"""
    return buy_price - atr * mult


def calc_take_profit_price(buy_price: float, atr: float, mult: float = 3.0) -> float:
    """ATR 기반 익절가 = 매수가 + ATR × 배수"""
    return buy_price + atr * mult
