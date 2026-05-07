import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


class KISClient:
    """한국투자증권 KIS Open API 클라이언트 (모의/실전 자동 전환)"""

    PAPER_URL = "https://openapivts.koreainvestment.com:29443"
    REAL_URL  = "https://openapi.koreainvestment.com:9443"

    def __init__(self):
        self.app_key    = os.getenv("KIS_APP_KEY", "")
        self.app_secret = os.getenv("KIS_APP_SECRET", "")
        self.account_no = os.getenv("KIS_ACCOUNT_NO", "")
        self.is_paper   = os.getenv("KIS_MODE", "paper") == "paper"
        self.base_url   = self.PAPER_URL if self.is_paper else self.REAL_URL

        self._token: str | None = None
        self._token_expires: datetime | None = None

        mode = "모의투자" if self.is_paper else "실전투자"
        logger.info(f"[KIS] 초기화 완료 — {mode} 모드")

    # ── 인증 ─────────────────────────────────────────────────

    def _get_token(self) -> str:
        """OAuth2 액세스 토큰 (유효기간 24시간, 캐시 재사용)"""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token

        if not self.app_key or not self.app_secret:
            raise ValueError("[KIS] KIS_APP_KEY / KIS_APP_SECRET 미설정")

        resp = requests.post(
            f"{self.base_url}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey":     self.app_key,
                "appsecret":  self.app_secret,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires = datetime.now() + timedelta(hours=23)
        logger.info("[KIS] 토큰 발급 완료")
        return self._token

    def _headers(self, tr_id: str, custtype: str = "P") -> dict:
        return {
            "Content-Type":  "application/json; charset=utf-8",
            "authorization": f"Bearer {self._get_token()}",
            "appkey":        self.app_key,
            "appsecret":     self.app_secret,
            "tr_id":         tr_id,
            "custtype":      custtype,
        }

    def _cano(self) -> tuple[str, str]:
        """계좌번호 분리 (앞 8자리, 뒤 2자리)"""
        acc = self.account_no.replace("-", "")
        return acc[:8], acc[8:10] if len(acc) >= 10 else "01"

    # ── 시세 ─────────────────────────────────────────────────

    def get_current_price(self, ticker: str) -> float:
        """현재가 조회"""
        resp = requests.get(
            f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["output"]["stck_prpr"])

    def get_ohlcv_today(self, ticker: str) -> dict:
        """당일 시고저종 + 거래량 조회"""
        resp = requests.get(
            f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
            timeout=10,
        )
        resp.raise_for_status()
        out = resp.json()["output"]
        return {
            "open":   float(out["stck_oprc"]),
            "high":   float(out["stck_hgpr"]),
            "low":    float(out["stck_lwpr"]),
            "close":  float(out["stck_prpr"]),
            "volume": int(out["acml_vol"]),
        }

    # ── 주문 ─────────────────────────────────────────────────

    def place_order(self, ticker: str, side: str, quantity: int,
                    price: int = 0) -> dict:
        """
        주문 실행
        - side : "BUY" | "SELL"
        - price: 0 = 시장가, 양수 = 지정가
        - DRY_RUN=True 이면 실제 API 호출 없이 dry_run 응답 반환
        """
        if os.getenv("DRY_RUN", "True") == "True":
            logger.info(f"[DRY_RUN] {side} {ticker} {quantity}주 @ {price or '시장가'}")
            return {"status": "dry_run", "ticker": ticker,
                    "side": side, "quantity": quantity, "price": price}

        cano, prod = self._cano()
        order_dv = "01" if price == 0 else "00"   # 01=시장가, 00=지정가

        if side == "BUY":
            tr_id = "VTTC0802U" if self.is_paper else "TTTC0802U"
        else:
            tr_id = "VTTC0801U" if self.is_paper else "TTTC0801U"

        payload = {
            "CANO":         cano,
            "ACNT_PRDT_CD": prod,
            "PDNO":         ticker,
            "ORD_DVSN":     order_dv,
            "ORD_QTY":      str(quantity),
            "ORD_UNPR":     str(price),
        }
        resp = requests.post(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers(tr_id),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("rt_cd") == "0":
            logger.info(f"[KIS] {side} {ticker} {quantity}주 체결 성공")
        else:
            logger.error(f"[KIS] 주문 오류: {result.get('msg1')}")
        return result

    def cancel_order(self, order_no: str, ticker: str, quantity: int) -> dict:
        """주문 취소"""
        if os.getenv("DRY_RUN", "True") == "True":
            return {"status": "dry_run_cancel"}
        cano, prod = self._cano()
        tr_id = "VTTC0803U" if self.is_paper else "TTTC0803U"
        payload = {
            "CANO": cano, "ACNT_PRDT_CD": prod,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_no,
            "ORD_DVSN": "02",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        resp = requests.post(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl",
            headers=self._headers(tr_id),
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 잔고/포지션 ───────────────────────────────────────────

    def get_balance(self) -> dict:
        """잔고 및 보유 종목 조회"""
        cano, prod = self._cano()
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        params = {
            "CANO": cano, "ACNT_PRDT_CD": prod,
            "AFHR_FLPR_YN": "N", "OFL_YN": "N",
            "INQR_DVSN": "01", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        resp = requests.get(
            f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers(tr_id),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_cash(self) -> float:
        """주문 가능 현금 반환 (DRY_RUN 시 기본값 10,000,000원)"""
        if os.getenv("DRY_RUN", "True") == "True":
            return 10_000_000.0
        try:
            data = self.get_balance()
            return float(data["output2"][0]["dnca_tot_amt"])
        except Exception as e:
            logger.error(f"[KIS] 잔고 조회 실패: {e}")
            return 0.0

    def get_positions(self) -> list[dict]:
        """보유 종목 목록 반환"""
        if os.getenv("DRY_RUN", "True") == "True":
            return []
        try:
            data = self.get_balance()
            holdings = data.get("output1", [])
            return [
                {
                    "ticker":    h["pdno"],
                    "name":      h["prdt_name"],
                    "quantity":  int(h["hldg_qty"]),
                    "avg_price": float(h["pchs_avg_pric"]),
                    "cur_price": float(h["prpr"]),
                    "pnl_pct":   float(h["evlu_pfls_rt"]),
                }
                for h in holdings if int(h.get("hldg_qty", 0)) > 0
            ]
        except Exception as e:
            logger.error(f"[KIS] 포지션 조회 실패: {e}")
            return []
