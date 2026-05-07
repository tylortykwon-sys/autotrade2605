"""
Streamlit 모니터링 대시보드

실행:
  cd autotrade && streamlit run dashboard/app.py

구성:
  1. 포트폴리오 요약 (현금, 보유종목, 당일 손익)
  2. 오늘 거래 내역
  3. 전략별 누적 성과
  4. 시스템 상태 (스케줄러, 서킷브레이커, AI 잔여 호출)
  5. 일별 손익 추이 차트
"""
import sys
import os

# autotrade 루트를 sys.path에 추가 (streamlit run dashboard/app.py 로 실행 시)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# ── 페이지 설정 ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="AutoTrade 대시보드",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 공통 스타일 ──────────────────────────────────────────────────────
st.markdown("""
<style>
  .metric-card {
    background: #1e1e2e; border-radius: 8px;
    padding: 16px; margin: 4px;
  }
  .pnl-pos { color: #4ade80; font-weight: bold; }
  .pnl-neg { color: #f87171; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ── DB 헬퍼 ─────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_trades(limit: int = 500) -> pd.DataFrame:
    try:
        from data.database import get_trades
        rows = get_trades(limit=limit)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["executed_at"] = pd.to_datetime(df["executed_at"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_portfolio_snapshots(days: int = 30) -> pd.DataFrame:
    try:
        from data.database import get_connection
        conn = get_connection()
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        df = pd.read_sql_query(
            "SELECT * FROM portfolio_snapshots WHERE snapshot_date >= ? ORDER BY snapshot_date",
            conn, params=(since,)
        )
        conn.close()
        if df.empty:
            return df
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_strategy_stats() -> pd.DataFrame:
    try:
        from data.database import get_connection
        conn = get_connection()
        df = pd.read_sql_query("""
            SELECT
                strategy,
                COUNT(*) as 거래수,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as 승,
                ROUND(AVG(pnl_pct), 2) as 평균손익률,
                ROUND(SUM(pnl), 0) as 누적손익
            FROM trades
            WHERE side = 'SELL'
            GROUP BY strategy
            ORDER BY 누적손익 DESC
        """, conn)
        conn.close()
        df["승률"] = (df["승"] / df["거래수"] * 100).round(1)
        return df
    except Exception:
        return pd.DataFrame()


def get_ai_calls_info() -> tuple[int, int]:
    """(사용횟수, 한도) 반환"""
    try:
        call_log = Path(_ROOT) / "ai" / ".call_log.json"
        if not call_log.exists():
            return 0, 5
        data = json.loads(call_log.read_text())
        today = str(datetime.now().date())
        used = data.get(today, 0)
        limit = int(os.getenv("AI_MAX_DAILY_CALLS", "5"))
        return used, limit
    except Exception:
        return 0, 5


def get_circuit_breaker_state() -> dict:
    try:
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        return {
            "daily_loss_triggered": cb.is_daily_loss_triggered(),
            "consecutive_loss_days": cb._get_consecutive_loss_days(),
        }
    except Exception:
        return {}


# ── 섹션 렌더러 ─────────────────────────────────────────────────────

def render_header():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
    mode_badge = "🟡 DRY RUN" if dry_run else "🟢 LIVE"
    st.title(f"📈 AutoTrade 대시보드  {mode_badge}")
    st.caption(f"최종 갱신: {now}  (30초마다 자동 갱신)")


def render_portfolio_summary(trades_df: pd.DataFrame):
    st.subheader("💼 오늘 포트폴리오")

    today = datetime.now().strftime("%Y-%m-%d")
    if trades_df.empty:
        today_df = pd.DataFrame()
    else:
        today_df = trades_df[trades_df["executed_at"].dt.strftime("%Y-%m-%d") == today]

    sells = today_df[today_df["side"] == "SELL"] if not today_df.empty else pd.DataFrame()
    buys  = today_df[today_df["side"] == "BUY"]  if not today_df.empty else pd.DataFrame()

    total_pnl = sells["pnl"].sum() if not sells.empty else 0
    wins       = (sells["pnl"] > 0).sum() if not sells.empty else 0
    win_rate   = wins / len(sells) * 100 if not sells.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("오늘 거래", f"{len(today_df)}건", f"매수 {len(buys)} / 매도 {len(sells)}")
    c2.metric("오늘 손익", f"{total_pnl:+,.0f}원")
    c3.metric("승률", f"{win_rate:.0f}%", f"{wins}승 {len(sells)-wins}패")
    c4.metric("누적 거래", f"{len(trades_df[trades_df['side']=='SELL']) if not trades_df.empty else 0}건")


def render_today_trades(trades_df: pd.DataFrame):
    st.subheader("📋 오늘 거래 내역")
    today = datetime.now().strftime("%Y-%m-%d")

    if trades_df.empty:
        st.info("거래 내역 없음")
        return

    today_df = trades_df[trades_df["executed_at"].dt.strftime("%Y-%m-%d") == today].copy()
    if today_df.empty:
        st.info("오늘 거래 없음")
        return

    display = today_df[["executed_at", "ticker", "side", "price", "quantity", "pnl", "pnl_pct", "strategy"]].copy()
    display.columns = ["시각", "종목", "구분", "단가", "수량", "손익(원)", "손익률(%)", "전략"]
    display["시각"] = display["시각"].dt.strftime("%H:%M:%S")
    display["단가"] = display["단가"].map(lambda x: f"{x:,.0f}")
    display["손익(원)"] = display["손익(원)"].map(lambda x: f"{x:+,.0f}" if x else "-")
    display["손익률(%)"] = display["손익률(%)"].map(lambda x: f"{x:+.2f}%" if x else "-")
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_strategy_performance(stats_df: pd.DataFrame):
    st.subheader("🎯 전략별 누적 성과")
    if stats_df.empty:
        st.info("누적 데이터 없음")
        return

    col_left, col_right = st.columns([2, 1])

    with col_left:
        display = stats_df[["strategy", "거래수", "승률", "평균손익률", "누적손익"]].copy()
        display.columns = ["전략", "거래수", "승률(%)", "평균손익률(%)", "누적손익(원)"]
        display["누적손익(원)"] = display["누적손익(원)"].map(lambda x: f"{x:+,.0f}")
        st.dataframe(display, use_container_width=True, hide_index=True)

    with col_right:
        if len(stats_df) > 0:
            chart_df = stats_df.set_index("strategy")[["누적손익"]].sort_values("누적손익")
            st.bar_chart(chart_df, height=300)


def render_pnl_chart(snapshots_df: pd.DataFrame, trades_df: pd.DataFrame):
    st.subheader("📉 일별 손익 추이")

    # portfolio_snapshots 있으면 우선 사용
    if not snapshots_df.empty and "daily_pnl" in snapshots_df.columns:
        chart_df = snapshots_df.set_index("snapshot_date")[["daily_pnl"]]
        chart_df.index = pd.to_datetime(chart_df.index)
        st.line_chart(chart_df, height=250)
        return

    # fallback: trades DB에서 일별 손익 집계
    if trades_df.empty:
        st.info("손익 데이터 없음")
        return

    sells = trades_df[trades_df["side"] == "SELL"].copy()
    if sells.empty:
        st.info("매도 데이터 없음")
        return

    sells["date"] = sells["executed_at"].dt.date
    daily = sells.groupby("date")["pnl"].sum().reset_index()
    daily.columns = ["날짜", "손익"]
    daily = daily.set_index("날짜")
    st.line_chart(daily, height=250)


def render_recent_trades(trades_df: pd.DataFrame):
    st.subheader("🕐 최근 거래 50건")
    if trades_df.empty:
        st.info("거래 내역 없음")
        return

    display = trades_df.head(50)[["executed_at", "ticker", "side", "price", "quantity", "pnl", "pnl_pct", "strategy"]].copy()
    display.columns = ["시각", "종목", "구분", "단가", "수량", "손익(원)", "손익률(%)", "전략"]
    display["시각"] = display["시각"].dt.strftime("%Y-%m-%d %H:%M")
    display["단가"] = display["단가"].map(lambda x: f"{x:,.0f}")
    display["손익(원)"] = display["손익(원)"].map(lambda x: f"{x:+,.0f}" if x else "-")
    display["손익률(%)"] = display["손익률(%)"].map(lambda x: f"{x:+.2f}%" if x else "-")
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_system_status():
    st.subheader("⚙️ 시스템 상태")

    c1, c2, c3 = st.columns(3)

    # AI 호출 잔여
    ai_used, ai_limit = get_ai_calls_info()
    ai_remain = ai_limit - ai_used
    c1.metric("AI 호출 잔여", f"{ai_remain}/{ai_limit}", f"오늘 {ai_used}회 사용")

    # 운용 모드
    dry_run = os.getenv("DRY_RUN", "True").lower() == "true"
    c2.metric("운용 모드", "DRY RUN" if dry_run else "LIVE", "모의" if dry_run else "실거래")

    # 서킷 브레이커
    cb = get_circuit_breaker_state()
    if cb:
        triggered = cb.get("daily_loss_triggered", False)
        consec    = cb.get("consecutive_loss_days", 0)
        c3.metric("서킷 브레이커", "발동" if triggered else "정상", f"연속 손실 {consec}일")
    else:
        c3.metric("서킷 브레이커", "확인 불가")

    # 환경변수 체크
    st.caption("**환경변수 설정 상태**")
    env_keys = {
        "ANTHROPIC_API_KEY": "Haiku AI",
        "TELEGRAM_BOT_TOKEN": "텔레그램 봇",
        "KIS_APP_KEY": "KIS API",
        "TAVILY_API_KEY": "뉴스(Tavily)",
    }
    cols = st.columns(len(env_keys))
    for col, (key, label) in zip(cols, env_keys.items()):
        val = os.getenv(key, "")
        icon = "✅" if val else "❌"
        col.markdown(f"{icon} **{label}**")


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    render_header()

    # 자동 새로고침 (30초)
    st_autorefresh = None
    try:
        from streamlit_autorefresh import st_autorefresh  # type: ignore
        st_autorefresh(interval=30_000, key="refresh")
    except ImportError:
        st.info("자동 갱신: 브라우저를 수동으로 새로고침하세요 (streamlit-autorefresh 미설치)")

    trades_df    = load_trades(limit=500)
    snapshots_df = load_portfolio_snapshots(days=30)
    stats_df     = load_strategy_stats()

    # 탭 구성
    tab1, tab2, tab3, tab4 = st.tabs(["오늘 현황", "전략 성과", "손익 추이", "시스템"])

    with tab1:
        render_portfolio_summary(trades_df)
        st.divider()
        render_today_trades(trades_df)
        st.divider()
        render_recent_trades(trades_df)

    with tab2:
        render_strategy_performance(stats_df)

    with tab3:
        render_pnl_chart(snapshots_df, trades_df)

    with tab4:
        render_system_status()


if __name__ == "__main__":
    main()
