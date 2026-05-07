"""
포지션 사이징 — ATR 기반 동적 투자 금액 계산

Kelly Criterion 변형: 변동성이 클수록 투자 비율을 줄인다
ATR% 구간 → 자본 비율:
  < 0.5% (유동성 부족)  → 0% (매수 보류)
  0.5 ~ 1.5%  (저변동) → 20%
  1.5 ~ 3.0%  (중변동) → 10%
  3.0%+       (고변동) → 5%
"""
import logging
import os

logger = logging.getLogger(__name__)


def calc_position_size(total_capital: float, atr_pct: float,
                       strategy_weight: float = 1.0) -> float:
    """
    ATR% × 전략 가중치 → 투자 금액 (원)

    strategy_weight: 전략 성과에 따른 가중치 (0.5 ~ 1.5)
    MAX_POSITION_RATIO: 단일 종목 최대 비율 상한 (.env)
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

    ratio = min(base_ratio * strategy_weight, max_ratio)
    amount = total_capital * ratio

    logger.debug(f"[Sizer] ATR={atr_pct:.1f}% weight={strategy_weight:.1f} "
                 f"→ {ratio*100:.0f}% = {amount:,.0f}원")
    return amount


def calc_quantity(amount: float, price: float) -> int:
    """투자금액 / 현재가 → 매수 수량 (최소 1주)"""
    if price <= 0:
        return 0
    return max(int(amount // price), 0)


def calc_stop_price(buy_price: float, atr: float, mult: float = 1.5) -> float:
    """ATR 기반 손절가 = 매수가 - ATR × mult"""
    return round(buy_price - atr * mult, 0)


def calc_take_profit_price(buy_price: float, atr: float, mult: float = 3.0) -> float:
    """ATR 기반 익절가 = 매수가 + ATR × mult"""
    return round(buy_price + atr * mult, 0)


def max_loss_per_trade(buy_price: float, stop_loss_pct: float = 0.02) -> float:
    """단일 거래 최대 손실금 = 매수가 × 손절률"""
    return buy_price * stop_loss_pct


def calc_risk_reward(buy_price: float, stop_price: float, target_price: float) -> float:
    """손익비 계산 (목표손익 / 위험금액). 2.0 이상 권장."""
    risk   = buy_price - stop_price
    reward = target_price - buy_price
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def get_sizing_report(total_capital: float, buy_price: float,
                      atr: float, atr_pct: float) -> dict:
    """포지션 사이징 전체 보고서"""
    amount     = calc_position_size(total_capital, atr_pct)
    qty        = calc_quantity(amount, buy_price)
    stop_p     = calc_stop_price(buy_price, atr)
    target_p   = calc_take_profit_price(buy_price, atr)
    rr         = calc_risk_reward(buy_price, stop_p, target_p)
    max_loss   = max_loss_per_trade(buy_price) * qty

    return {
        "total_capital": total_capital,
        "invest_amount": round(amount),
        "quantity":      qty,
        "buy_price":     buy_price,
        "stop_price":    stop_p,
        "target_price":  target_p,
        "risk_reward":   rr,
        "max_loss":      round(max_loss),
        "atr_pct":       round(atr_pct, 2),
    }
