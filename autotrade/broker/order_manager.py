"""
슬롯 기반 주문 관리자
- 최대 MAX_SLOTS(5) 종목 동시 보유
- 매수/매도/일괄청산 + DB 기록 + 텔레그램 알림
"""
import logging
import os

from broker.kis_api import KISClient
from data.database import insert_trade
from notify.telegram_bot import send_message
from risk.position_sizer import calc_position_size

logger = logging.getLogger(__name__)
MAX_SLOTS = int(os.getenv("MAX_SLOTS", "5"))


class OrderManager:
    def __init__(self):
        self.client = KISClient()
        self.positions: dict[str, dict] = {}  # ticker → {buy_price, quantity, strategy, amount}

    # ── 슬롯 관리 ────────────────────────────────────────────

    def available_slots(self) -> int:
        return MAX_SLOTS - len(self.positions)

    def has_position(self, ticker: str) -> bool:
        return ticker in self.positions

    def get_position(self, ticker: str) -> dict | None:
        return self.positions.get(ticker)

    # ── 매수 ─────────────────────────────────────────────────

    def buy(self, ticker: str, strategy: str, atr_pct: float,
            price: int = 0) -> bool:
        """
        매수 실행
        - atr_pct: ATR% (포지션 사이징 기준)
        - price  : 0=시장가, 양수=지정가
        """
        if self.available_slots() <= 0:
            logger.warning(f"[OM] 슬롯 없음 ({len(self.positions)}/{MAX_SLOTS}) — {ticker} 건너뜀")
            return False

        if self.has_position(ticker):
            logger.warning(f"[OM] {ticker} 이미 보유 중 — 매수 건너뜀")
            return False

        cash   = self.client.get_cash()
        amount = calc_position_size(cash, atr_pct)

        if amount < 10_000:
            logger.warning(f"[OM] {ticker} 매수금액 부족: {amount:,.0f}원")
            return False

        cur_price = (float(price) if price > 0
                     else self.client.get_current_price(ticker))
        quantity = int(amount // cur_price)

        if quantity < 1:
            logger.warning(f"[OM] {ticker} 수량 0주 — 매수 불가")
            return False

        result = self.client.place_order(ticker, "BUY", quantity, price)

        if result.get("status") == "dry_run" or result.get("rt_cd") == "0":
            self.positions[ticker] = {
                "buy_price": cur_price,
                "quantity":  quantity,
                "strategy":  strategy,
                "amount":    cur_price * quantity,
                "atr_pct":   atr_pct,
            }
            insert_trade({
                "ticker": ticker, "side": "BUY",
                "price": cur_price, "quantity": quantity,
                "amount": cur_price * quantity,
                "strategy": strategy, "pnl": 0, "pnl_pct": 0,
            })
            send_message(
                f"<b>매수 체결</b>\n"
                f"종목: {ticker}\n수량: {quantity}주\n"
                f"단가: {cur_price:,.0f}원\n전략: {strategy}\n"
                f"투자: {cur_price * quantity:,.0f}원"
            )
            logger.info(f"[OM] 매수 완료: {ticker} {quantity}주 @ {cur_price:,.0f}원")
            return True

        logger.error(f"[OM] 매수 실패: {result.get('msg1', result)}")
        return False

    # ── 매도 ─────────────────────────────────────────────────

    def sell(self, ticker: str, reason: str = "", price: int = 0) -> bool:
        """
        매도 실행
        - reason: "STOP_LOSS" | "TAKE_PROFIT" | "MARKET_CLOSE" | 기타
        """
        if not self.has_position(ticker):
            logger.warning(f"[OM] {ticker} 포지션 없음")
            return False

        pos       = self.positions[ticker]
        cur_price = (float(price) if price > 0
                     else self.client.get_current_price(ticker))
        result    = self.client.place_order(ticker, "SELL", pos["quantity"], price)

        pnl     = (cur_price - pos["buy_price"]) * pos["quantity"]
        pnl_pct = (cur_price - pos["buy_price"]) / pos["buy_price"] * 100

        insert_trade({
            "ticker": ticker, "side": "SELL",
            "price": cur_price, "quantity": pos["quantity"],
            "amount": cur_price * pos["quantity"],
            "strategy": pos["strategy"],
            "pnl": round(pnl), "pnl_pct": round(pnl_pct, 2),
        })

        emoji = "+" if pnl >= 0 else "-"
        send_message(
            f"<b>매도 체결</b> [{reason}]\n"
            f"종목: {ticker}\n수량: {pos['quantity']}주\n"
            f"단가: {cur_price:,.0f}원\n"
            f"손익: {pnl:+,.0f}원 ({emoji}{abs(pnl_pct):.2f}%)"
        )
        logger.info(f"[OM] 매도 완료: {ticker} {pnl:+,.0f}원 ({pnl_pct:+.2f}%) [{reason}]")
        del self.positions[ticker]
        return True

    # ── 손절/익절 자동 감시 ────────────────────────────────────

    def check_stop_conditions(self,
                               stop_loss_pct: float = -0.02,
                               take_profit_pct: float = 0.03) -> list[str]:
        """보유 종목 일괄 손절/익절 체크. 청산된 티커 목록 반환."""
        closed = []
        for ticker, pos in list(self.positions.items()):
            try:
                cur = self.client.get_current_price(ticker)
                pnl_pct = (cur - pos["buy_price"]) / pos["buy_price"]
                if pnl_pct <= stop_loss_pct:
                    self.sell(ticker, "STOP_LOSS")
                    closed.append(ticker)
                elif pnl_pct >= take_profit_pct:
                    self.sell(ticker, "TAKE_PROFIT")
                    closed.append(ticker)
            except Exception as e:
                logger.error(f"[OM] {ticker} 조건 체크 실패: {e}")
        return closed

    # ── 일괄 청산 ─────────────────────────────────────────────

    def sell_all(self, reason: str = "장마감_일괄청산"):
        for ticker in list(self.positions.keys()):
            self.sell(ticker, reason)

    # ── 포지션 요약 ───────────────────────────────────────────

    def summary(self) -> dict:
        total_invested = sum(p["amount"] for p in self.positions.values())
        return {
            "slots_used":     len(self.positions),
            "slots_max":      MAX_SLOTS,
            "total_invested": total_invested,
            "positions":      list(self.positions.keys()),
        }
