"""
==================================================
  코인이형 텔레그램 봇 (완성본)

  [채널 기능]
  - 매일 오전 9시: 크립토 모닝 브리핑
  - 4시간마다: BTC 투자 전략 (오전9시~새벽2시)
  - 중요 코인 이슈: 이미지 + AI 요약 (하루 최대 5개)

  [소통방 기능]
  - 코인이형 AI 대화 (밤11시30분~오전8시 취침)
  - 회원 기억 DB
  - 30분 조용하면 먼저 말 걸기
  - 취침/기상 인사

  [설정]
  - 딜레이: 7~15초
  - 답변율: 90%
  - 투자전략: 오전9시~새벽2시만 발송
==================================================
"""

import os
import io
import asyncio
import logging
import random
import asyncpg
import feedparser
import hashlib
import json
import httpx
import numpy as np

# ── matplotlib 임포트 (순서 중요!) ──────────────
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt          # ← plt 먼저 import
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib import font_manager

# ── 한글 폰트 설정 (plt import 이후에!) ─────────
_font_path = os.path.join(os.path.dirname(__file__), 'NanumGothic.ttf')
if os.path.exists(_font_path):
    font_manager.fontManager.addfont(_font_path)
    _prop = font_manager.FontProperties(fname=_font_path)
    plt.rcParams['font.family'] = _prop.get_name()
plt.rcParams['axes.unicode_minus'] = False

from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from openai import AsyncOpenAI
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

KST = ZoneInfo('Asia/Seoul')
def now_kst():
    return datetime.now(KST)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  환경변수
# ──────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY")
NEWS_CHANNEL_ID    = os.environ.get("NEWS_CHANNEL_ID")
GROUP_CHAT_ID      = os.environ.get("GROUP_CHAT_ID")

STRATEGY_INTERVAL_MINUTES = 240
IDLE_CHECK_MINUTES        = 15
IDLE_THRESHOLD_MINUTES    = 60

# ──────────────────────────────────────────────
#  코인이형 페르소나
# ──────────────────────────────────────────────

PERSONA_PROMPT = """
너는 코인이형이야 코인판 8년차고 소통방에서 회원들이랑 얘기하는 역할이야

[성격]
진짜 사람처럼 말해야해 절대 ai처럼 말하면 안됨
친근하고 편안한 스타일
틀리면 솔직하게 인정하고 가끔 일상 얘기도 해

[말투 규칙]
무조건 1줄로 짧게 끊어 절대 2줄 넘기지마
마침표 절대 금지
쉼표 절대 금지
따옴표 절대 금지
존댓말만 사용 (~요 ~네요 ~것 같아요)
반말 절대 금지
ㅋㅋ ㅎㅎ 자연스럽게
이모지 거의 안씀
투자 권유 절대 금지
모르면 모른다고 해요

[말투 예시]
비트 지금 좀 위험해 보이긴 해요ㅋㅋ
저도 잘 모르겠어요ㅎㅎ
요즘 장이 좀 이상하네요
그럴 수도 있을 것 같아요
저도 그냥 존버 중이에요ㅋㅋ
리플은 저도 잘 모르겠어요

[절대 이렇게 말하면 안됨]
현재 비트코인의 RSI 지표를 보면 이런 식 금지
~입니다 ~습니다 금지
반말 금지
2줄 이상 금지
AI처럼 깔끔하게 쓰지마

[중요]
AI라고 절대 밝히지 않음
1줄로 짧게
이름 접두사로 시작하지 마
"""

# ──────────────────────────────────────────────
#  취침/기상 멘트
# ──────────────────────────────────────────────

SLEEP_MESSAGES = [
    "나 오늘 좀 피곤해서 먼저 들어갈게ㅋㅋ 내일 봐요",
    "슬슬 졸리네 ㅎㅎ 다들 좋은 밤 되세요",
    "나 먼저 잘게요~ 내일 장 같이 봐요",
    "오늘 하루 수고했어요 다들 ㅎㅎ 나 먼저",
    "졸려 죽겠다ㅋㅋ 먼저 갈게 내일 봐",
    "오늘 장 힘들었다ㅋㅋ 푹 자고 내일 다시 봐요",
    "다들 좋은 밤~ 내일 BTC 좀 올라있길ㅎㅎ",
    "나 먼저 충전하러 갑니다ㅋㅋ 내일 봐요",
    "오늘도 수고들 했어요 먼저 갈게요",
    "눈이 감기네ㅋㅋ 먼저 자고 내일 봐요",
]

WAKE_MESSAGES = [
    "좋은 아침이에요~ 간밤에 장 어떻게 됐나 보자ㅋㅋ",
    "일어났다 ㅎㅎ 오늘 장 기대되는데",
    "굿모닝~ BTC 밤새 어떻게 됐어요",
    "기상ㅋㅋ 다들 일어났어요?",
    "오늘도 화이팅~ 장 한번 봐볼게요",
    "좋은 아침~ 오늘 장 어떻게 될지 기대되네ㅎㅎ",
    "일어났다 다들 잘 잤어요?",
    "굿모닝ㅎㅎ 오늘도 같이 장 봐봐요",
    "아침부터 차트 보는 코인이형입니다ㅋㅋ",
    "기상~ 간밤에 BTC 많이 움직였네요",
]

IDLE_PERSONA_PROMPT = """
너는 코인이형이야 소통방이 오래 조용해서 먼저 말 걸어야 해

[규칙]
자연스럽게 먼저 말 걸기
코인 얘기 일상 얘기 날씨 밥 얘기 등 다양하게
1~2줄 이내 마침표 금지 카톡 스타일
가끔 코인 시장 현황 언급해도 됨
회원들 반응 유도하는 질문 형태도 좋음

[예시]
요즘 다들 존버 중이야ㅋㅋ 나도 그냥 보고만 있는 중
오늘 BTC 움직임 보셨어요? 좀 심상치 않은데ㅎㅎ
밥은 먹었어요들~ 시장이 밥맛이네 요즘ㅋㅋ
다들 어디 갔어ㅋㅋ 너무 조용한거 아니야
"""

MORNING_BRIEF_PROMPT = """
너는 크립토 시장 전문 애널리스트야
매일 아침 시장 주요 현안과 이달 경제지표 일정을 포함한 브리핑을 HTML 형식으로 작성해줘

[출력 형식 - HTML 태그 사용 반드시 이 형식으로]
🌅 <b>크립토 모닝 브리핑</b>
{date} 오전 9시

📊 <b>간밤 시장 현황</b>
• BTC  <b>{btc_price}</b>  ({btc_change}%)
• (전반적 시장 분위기 한줄)

🔥 <b>오늘의 주요 현안</b>
① <b>(현안 제목)</b>
   → (내용 및 시장 영향 한줄)
② <b>(현안 제목)</b>
   → (내용 및 시장 영향 한줄)
③ <b>(현안 제목)</b>
   → (내용 및 시장 영향 한줄)

🌐 <b>매크로 변수 체크</b>
• (달러/금리/증시 동향 한줄)
• (크립토 시장 영향 한줄)

📅 <b>이달 주요 경제지표 일정</b>
<i>(크립토 영향도 높은 순 / 지난 일정은 취소선 처리)</i>
<s>MM/DD  🇺🇸 (지표명) — (결과 한줄)</s>
MM/DD  🇺🇸 <b>(오늘 또는 예정 지표명)</b>
MM/DD  🇺🇸 (예정 지표명)

⚠️ <i>본 브리핑은 참고용이며 투자 판단은 본인 책임</i>

[규칙]
마침표 금지
HTML 태그 정확히 사용 (<b> <i> <s> 태그만)
지난 날짜 지표는 반드시 <s>취소선</s> 처리
오늘 날짜 지표는 <b>굵게</b> 강조
FOMC 금리결정 CPI PCE GDP 고용지표 위주로
전체 30줄 이내
코드블록 절대 금지 (```html 등 사용 금지)
"""

ISSUE_JUDGE_PROMPT = """
아래 코인 뉴스 제목들을 보고 중요도를 판단해줘

[중요 이슈 - YES]
• 미국 SEC/CFTC 공식 규제 발표 또는 ETF 승인/거절
• 대형 거래소 해킹/파산/상장폐지
• 각국 정부 암호화폐 전면 금지 또는 합법화 공식 발표
• BTC/ETH 1억달러 이상 고래 대규모 이동
• 대형 기관/상장기업 BTC 공식 매수/매도 공시
• 전 세계 금융시장에 직접 영향 미치는 초대형 이슈
• 하루 최대 5개 초과시 나머지는 NO

[무조건 NO]
• 단순 가격 등락 분석
• 특정 알트코인 단순 소식
• 광고성/루머성 기사
• 전문가 개인 의견
• 이미 알려진 이슈 후속 기사
• 애매하거나 불확실한 소식

형식: 번호|YES 또는 번호|NO
"""

ISSUE_SUMMARY_PROMPT = """
아래 코인 뉴스를 보고 투자자가 알아야 할 핵심을 정리해줘

[형식]
🔥 {제목}

📌 핵심 요약
2~3줄로 쉽게 설명

💡 시장 영향
이 이슈가 시장에 미칠 영향 한줄

⚠️ 투자 판단은 본인 책임

[규칙]
마침표 금지
쉽고 간결하게
10줄 이내
"""

# ──────────────────────────────────────────────
#  기술 지표 계산
# ──────────────────────────────────────────────

def calc_ma(prices, period):
    return [
        sum(prices[i-period:i]) / period if i >= period else None
        for i in range(len(prices))
    ]

def calc_rsi(prices, period=14):
    rsi = [None] * len(prices)
    if len(prices) < period + 1:
        return rsi
    for i in range(period, len(prices)):
        window = prices[i-period:i]
        gains  = [max(window[j+1]-window[j], 0) for j in range(len(window)-1)]
        losses = [max(window[j]-window[j+1], 0) for j in range(len(window)-1)]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            rsi[i] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    return rsi

def calc_macd(prices, fast=12, slow=26, signal=9):
    def ema(data, period):
        result = [None] * len(data)
        k = 2 / (period + 1)
        for i in range(len(data)):
            if i < period - 1:
                continue
            if result[i-1] is None:
                result[i] = sum(data[max(0,i-period+1):i+1]) / period
            else:
                result[i] = data[i] * k + result[i-1] * (1 - k)
        return result
    ema_fast  = ema(prices, fast)
    ema_slow  = ema(prices, slow)
    macd_line = [
        (f - s) if f and s else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(prices)
    if len(valid) >= signal:
        vals = [v for _, v in valid]
        sig  = calc_ma(vals, signal)
        for idx, (orig_i, _) in enumerate(valid):
            if sig[idx] is not None:
                signal_line[orig_i] = sig[idx]
    histogram = [
        (m - s) if m and s else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, histogram

def calc_bollinger(prices, period=20, std_dev=2):
    upper, lower, mid = [], [], []
    for i in range(len(prices)):
        if i < period:
            upper.append(None); lower.append(None); mid.append(None)
            continue
        window = prices[i-period:i]
        m  = sum(window) / period
        sd = (sum((x - m)**2 for x in window) / period) ** 0.5
        mid.append(m)
        upper.append(m + std_dev * sd)
        lower.append(m - std_dev * sd)
    return upper, mid, lower

def calc_fibonacci(prices):
    high = max(prices)
    low  = min(prices)
    diff = high - low
    return {
        "0%":    high,
        "23.6%": high - diff * 0.236,
        "38.2%": high - diff * 0.382,
        "50%":   high - diff * 0.5,
        "61.8%": high - diff * 0.618,
        "100%":  low,
    }

def calc_support_resistance(closes, highs, lows):
    recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    recent_low  = min(lows[-20:])  if len(lows)  >= 20 else min(lows)
    pivot = (recent_high + recent_low + closes[-1]) / 3
    r1 = 2 * pivot - recent_low
    r2 = pivot + (recent_high - recent_low)
    s1 = 2 * pivot - recent_high
    s2 = pivot - (recent_high - recent_low)
    return r1, r2, s1, s2

def calc_volume_trend(volumes):
    if not volumes or len(volumes) < 5:
        return "N/A"
    avg_recent = sum(volumes[-5:]) / 5
    avg_prev   = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else avg_recent
    if avg_recent > avg_prev * 1.2:
        return "증가 (강한 관심)"
    elif avg_recent < avg_prev * 0.8:
        return "감소 (관망세)"
    else:
        return "보합"

# ──────────────────────────────────────────────
#  실시간 데이터
# ──────────────────────────────────────────────

async def get_btc_ohlcv(days=30):
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"}
            ) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc",
                    params={"vs_currency": "usd", "days": str(days)},
                    timeout=15,
                )
                if r.status_code == 429:
                    await asyncio.sleep(15 * (attempt + 1))
                    continue
                data = r.json()
                times  = [datetime.fromtimestamp(d[0]/1000) for d in data]
                opens  = [float(d[1]) for d in data]
                highs  = [float(d[2]) for d in data]
                lows   = [float(d[3]) for d in data]
                closes = [float(d[4]) for d in data]
                return times, opens, highs, lows, closes
        except Exception as e:
            logger.error(f"CoinGecko OHLCV 오류: {e}")
            await asyncio.sleep(5)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.kraken.com/0/public/OHLC",
                params={"pair": "XBTUSD", "interval": 240},
                timeout=15,
            )
            data = r.json()["result"]["XXBTZUSD"]
        times  = [datetime.fromtimestamp(d[0]) for d in data]
        opens  = [float(d[1]) for d in data]
        highs  = [float(d[2]) for d in data]
        lows   = [float(d[3]) for d in data]
        closes = [float(d[4]) for d in data]
        return times, opens, highs, lows, closes
    except Exception as e:
        logger.error(f"Kraken OHLCV 오류: {e}")
        return None, None, None, None, None

async def get_btc_price():
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"}
            ) as client:
                r = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": "bitcoin",
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                    },
                    timeout=15,
                )
                if r.status_code == 429:
                    await asyncio.sleep(10 * (attempt + 1))
                    continue
                data = r.json()["bitcoin"]
                price  = float(data["usd"])
                change = round(float(data["usd_24h_change"]), 2)
                return price, change
        except Exception as e:
            logger.error(f"CoinGecko 가격 오류: {e}")
            await asyncio.sleep(5)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.kraken.com/0/public/Ticker",
                params={"pair": "XBTUSD"},
                timeout=15,
            )
            data = r.json()["result"]["XXBTZUSD"]
            price  = float(data["c"][0])
            open_p = float(data["o"])
            change = round((price - open_p) / open_p * 100, 2)
            return price, change
    except Exception as e:
        logger.error(f"Kraken 가격 오류: {e}")
        return None, None

async def get_fear_greed():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=10
            )
            data = r.json()
            value = data["data"][0]["value"]
            label = data["data"][0]["value_classification"]
            label_kr = {
                "Extreme Fear": "극도의 공포",
                "Fear": "공포",
                "Neutral": "중립",
                "Greed": "탐욕",
                "Extreme Greed": "극도의 탐욕"
            }.get(label, label)
            return int(value), label_kr
    except Exception as e:
        logger.error(f"공포탐욕 오류: {e}")
        return None, None

# ──────────────────────────────────────────────
#  차트 생성
# ──────────────────────────────────────────────

def make_chart(times, closes, highs, lows):
    fig = plt.figure(figsize=(12, 9), facecolor='#0d1117')
    gs  = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1])
    ax3 = fig.add_subplot(gs[2])

    for ax in [ax1, ax2, ax3]:
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e', labelsize=8)
        ax.grid(color='#21262d', linestyle='--', linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_edgecolor('#21262d')

    n = len(times)

    for i in range(n):
        color = '#26a641' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#da3633'
        ax1.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8, alpha=0.7)
        ax1.bar(i, abs(closes[i]-(closes[i-1] if i > 0 else closes[i])),
                bottom=min(closes[i], closes[i-1] if i > 0 else closes[i]),
                color=color, width=0.6, alpha=0.9)

    ma7  = calc_ma(closes, 7)
    ma25 = calc_ma(closes, 25)
    ma99 = calc_ma(closes, min(99, n-1))
    for ma, color, label in [
        (ma7,  '#f0883e', 'MA7'),
        (ma25, '#58a6ff', 'MA25'),
        (ma99, '#bc8cff', 'MA99'),
    ]:
        xi = [i for i, v in enumerate(ma) if v is not None]
        yi = [v for v in ma if v is not None]
        if xi:
            ax1.plot(xi, yi, color=color, linewidth=1.2, label=label, alpha=0.9)

    bb_upper, bb_mid, bb_lower = calc_bollinger(closes)
    xi_bb = [i for i, v in enumerate(bb_upper) if v is not None]
    if xi_bb:
        ax1.plot(xi_bb, [bb_upper[i] for i in xi_bb], color='#e3b341', linewidth=0.8, alpha=0.6, linestyle='--')
        ax1.plot(xi_bb, [bb_lower[i] for i in xi_bb], color='#e3b341', linewidth=0.8, alpha=0.6, linestyle='--')
        ax1.fill_between(xi_bb,
                         [bb_upper[i] for i in xi_bb],
                         [bb_lower[i] for i in xi_bb],
                         alpha=0.04, color='#e3b341')

    fib = calc_fibonacci(closes)
    fib_colors = ['#ff7b72','#ffa657','#e3b341','#7ee787','#58a6ff','#bc8cff']
    for (label, level), fc in zip(fib.items(), fib_colors):
        ax1.axhline(y=level, color=fc, linewidth=0.6, alpha=0.5, linestyle=':')
        ax1.text(n-1, level, f' Fib {label}', color=fc, fontsize=6.5, va='center', alpha=0.8)

    ax1.axhline(y=closes[-1], color='#f0f6fc', linewidth=0.8, linestyle='--', alpha=0.6)
    ax1.text(0, closes[-1], f'${closes[-1]:,.0f} ', color='#f0f6fc',
             fontsize=9, va='center', ha='right', fontweight='bold')

    ax1.set_title('BTC/USDT  |  투자 분석 차트',
                  color='#f0f6fc', fontsize=12, pad=8, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=7, facecolor='#161b22',
               edgecolor='#21262d', labelcolor='#8b949e')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))

    rsi = calc_rsi(closes)
    xi_rsi = [i for i, v in enumerate(rsi) if v is not None]
    yi_rsi = [rsi[i] for i in xi_rsi]
    if xi_rsi:
        ax2.plot(xi_rsi, yi_rsi, color='#c9d1d9', linewidth=1.2)
        ax2.fill_between(xi_rsi, yi_rsi, 50, where=[v > 50 for v in yi_rsi], alpha=0.2, color='#26a641')
        ax2.fill_between(xi_rsi, yi_rsi, 50, where=[v <= 50 for v in yi_rsi], alpha=0.2, color='#da3633')
        ax2.axhline(70, color='#da3633', linewidth=0.7, alpha=0.6, linestyle='--')
        ax2.axhline(30, color='#26a641', linewidth=0.7, alpha=0.6, linestyle='--')
        ax2.set_ylim(0, 100)
        ax2.set_ylabel('RSI(14)', color='#8b949e', fontsize=8)
        ax2.text(xi_rsi[-1], yi_rsi[-1], f' {yi_rsi[-1]:.1f}', color='#f0f6fc', fontsize=8)

    macd_line, signal_line, histogram = calc_macd(closes)
    xi_m = [i for i, v in enumerate(macd_line) if v is not None]
    xi_s = [i for i, v in enumerate(signal_line) if v is not None]
    xi_h = [i for i, v in enumerate(histogram) if v is not None]
    if xi_h:
        colors_h = ['#26a641' if histogram[i] >= 0 else '#da3633' for i in xi_h]
        ax3.bar(xi_h, [histogram[i] for i in xi_h], color=colors_h, alpha=0.7, width=0.8)
    if xi_m:
        ax3.plot(xi_m, [macd_line[i] for i in xi_m], color='#58a6ff', linewidth=1.2, label='MACD')
    if xi_s:
        ax3.plot(xi_s, [signal_line[i] for i in xi_s], color='#f0883e', linewidth=1.2, label='Signal')
    ax3.axhline(0, color='#8b949e', linewidth=0.5, alpha=0.5)
    ax3.set_ylabel('MACD', color='#8b949e', fontsize=8)
    ax3.legend(loc='upper left', fontsize=7, facecolor='#161b22',
               edgecolor='#21262d', labelcolor='#8b949e')

    tick_step = max(1, n // 6)
    tick_pos  = list(range(0, n, tick_step))
    for ax in [ax1, ax2, ax3]:
        ax.set_xlim(-1, n)
        ax.set_xticks(tick_pos)
        ax.set_xticklabels(
            [times[i].strftime('%m/%d') for i in tick_pos],
            color='#8b949e', fontsize=7
        )

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, facecolor=fig.get_facecolor(), bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

# ──────────────────────────────────────────────
#  전문 트레이더 전략 생성
# ──────────────────────────────────────────────

def get_openai_client():
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

async def generate_strategy(price, change, closes, highs, lows):
    rsi_vals  = calc_rsi(closes)
    rsi_curr  = next((v for v in reversed(rsi_vals) if v is not None), None)
    rsi_str   = f'{rsi_curr:.1f}' if rsi_curr else 'N/A'

    macd_l, macd_s, _ = calc_macd(closes)
    macd_curr = next((v for v in reversed(macd_l) if v is not None), None)
    sig_curr  = next((v for v in reversed(macd_s) if v is not None), None)
    macd_str  = f'{macd_curr:.1f}' if macd_curr else 'N/A'
    sig_str   = f'{sig_curr:.1f}'  if sig_curr  else 'N/A'
    macd_signal = "골든크로스" if (macd_curr and sig_curr and macd_curr > sig_curr) else "데드크로스" if (macd_curr and sig_curr) else "N/A"

    bb_u, bb_m, bb_l = calc_bollinger(closes)
    bb_upper = next((v for v in reversed(bb_u) if v is not None), None)
    bb_lower = next((v for v in reversed(bb_l) if v is not None), None)
    bb_mid   = next((v for v in reversed(bb_m) if v is not None), None)
    bb_pos   = "상단 근접" if bb_upper and price > bb_upper * 0.98 else "하단 근접" if bb_lower and price < bb_lower * 1.02 else "중앙 구간"
    bb_up_str  = f'${bb_upper:,.0f}' if bb_upper else 'N/A'
    bb_lo_str  = f'${bb_lower:,.0f}' if bb_lower else 'N/A'
    bb_mid_str = f'${bb_mid:,.0f}'   if bb_mid   else 'N/A'

    fib = calc_fibonacci(closes)
    r1, r2, s1, s2 = calc_support_resistance(closes, highs, lows)

    ma7   = calc_ma(closes, 7)
    ma25  = calc_ma(closes, 25)
    ma7c  = next((v for v in reversed(ma7)  if v is not None), None)
    ma25c = next((v for v in reversed(ma25) if v is not None), None)
    ma_trend = "단기 상승 배열" if (ma7c and ma25c and ma7c > ma25c) else "단기 하락 배열" if (ma7c and ma25c) else "N/A"
    ma7_str  = f'${ma7c:,.0f}'  if ma7c  else 'N/A'
    ma25_str = f'${ma25c:,.0f}' if ma25c else 'N/A'

    fg_value, fg_label = await get_fear_greed()
    fg_str   = f"{fg_value} — {fg_label}" if fg_value else "N/A"
    fg_emoji = "😱" if fg_value and fg_value <= 25 else "😰" if fg_value and fg_value <= 45 else "😐" if fg_value and fg_value <= 55 else "😏" if fg_value and fg_value <= 75 else "🤑" if fg_value else ""

    long_liq  = round(price * 0.93, -2)
    short_liq = round(price * 1.07, -2)
    key_liq1  = round(price * 0.95, -2)
    key_liq2  = round(price * 1.05, -2)

    prompt = f"""
너는 10년 경력의 전문 크립토 스윙 트레이더야
아래 실시간 데이터를 분석해서 실전에서 바로 쓸 수 있는 투자 전략을 써줘

[실시간 데이터]
현재가: ${price:,.0f}  24h변동: {change:+.2f}%
RSI(14): {rsi_str}
MACD: {macd_str} / Signal: {sig_str} / {macd_signal}
볼린저밴드: 상단 {bb_up_str} / 중앙 {bb_mid_str} / 하단 {bb_lo_str} / 위치: {bb_pos}
이동평균: MA7 {ma7_str} / MA25 {ma25_str} / {ma_trend}
피보나치 38.2%: ${fib['38.2%']:,.0f} / 50%: ${fib['50%']:,.0f} / 61.8%: ${fib['61.8%']:,.0f}
피벗 저항1: ${r1:,.0f} / 저항2: ${r2:,.0f}
피벗 지지1: ${s1:,.0f} / 지지2: ${s2:,.0f}
공포탐욕지수: {fg_str}
롱청산 밀집: ${key_liq1:,.0f} ~ ${long_liq:,.0f}
숏청산 밀집: ${key_liq2:,.0f} ~ ${short_liq:,.0f}

[출력 형식]
📊 BTC 투자 전략  {now_kst().strftime('%m/%d %H:%M')} KST

💰 현재가  ${price:,.0f}  {change:+.2f}%

─────────────────────
📈 기술적 분석
─────────────────────
• RSI  {rsi_str}
  → (과매수/과매도/중립 + 한줄 해석)

• MACD  {macd_signal}
  → (현재 추세 방향 한줄 해석)

• 볼린저밴드  {bb_pos}
  → (현재 위치 의미 한줄 해석)

• 이동평균  {ma_trend}
  → (단기 방향성 한줄 해석)

─────────────────────
{fg_emoji} 시장 심리  {fg_str}
─────────────────────
(현재 심리 상태와 역발상 포인트 한줄)

─────────────────────
💥 청산 밀집 구간
─────────────────────
• 롱청산  ${key_liq1:,.0f} ~ ${long_liq:,.0f}
• 숏청산  ${key_liq2:,.0f} ~ ${short_liq:,.0f}

─────────────────────
🎯 매매 전략 (참고용)
─────────────────────
• 지지선  (가격대 — 이유 한줄)
• 저항선  (가격대 — 이유 한줄)
• 매수 관심구간  (가격대)
• 1차 목표가  (가격대)
• 손절 기준  (가격대)
• 리스크  (현재 주의해야 할 점 한줄)

⚠️ 본 전략은 참고용이며 투자 판단과 책임은 본인에게 있습니다

[규칙]
마침표 쉼표 따옴표 사용 금지
투자 권유 절대 금지
"""
    response = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user",   "content": "지금 바로 분석 포스팅 써줘"},
        ],
        max_tokens=700,
        temperature=0.6,
    )
    return response.choices[0].message.content.strip()

# ──────────────────────────────────────────────
#  채널 포스팅 스케줄러
# ──────────────────────────────────────────────

async def post_trading_strategy(bot: Bot):
    try:
        hour = now_kst().hour
        if 2 <= hour < 9:
            return

        price, change = await get_btc_price()
        if not price:
            return

        times, opens, highs, lows, closes = await get_btc_ohlcv(days=30)
        if not closes:
            return

        strategy = await generate_strategy(price, change, closes, highs, lows)
        strategy = strategy.replace("```html", "").replace("```", "").strip()
        chart    = make_chart(times, closes, highs, lows)

        await bot.send_photo(
            chat_id=NEWS_CHANNEL_ID,
            photo=chart,
            caption=strategy,
        )
        logger.info(f"전략 포스팅 완료 — BTC ${price:,.0f}")

    except Exception as e:
        logger.error(f"전략 포스팅 오류: {e}")

async def strategy_scheduler(bot: Bot):
    while True:
        now = now_kst()
        target = now.replace(hour=11, minute=30, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_sec = (target - now).total_seconds()
        await asyncio.sleep(wait_sec)
        await post_trading_strategy(bot)

async def morning_briefing(bot: Bot):
    while True:
        try:
            n = now_kst()
            target = n.replace(hour=9, minute=0, second=0, microsecond=0)
            if n >= target:
                target += timedelta(days=1)
            await asyncio.sleep((target - n).total_seconds())

            price, change = await get_btc_price()
            if not price:
                continue

            prompt = MORNING_BRIEF_PROMPT.format(
                date=now_kst().strftime("%Y년 %m월 %d일"),
                btc_price=f"${price:,.0f}",
                btc_change=f"{change:+.2f}",
            )
            response = await get_openai_client().chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": "오늘 아침 브리핑 작성해줘"},
                ],
                max_tokens=600,
                temperature=0.7,
            )
            text = response.choices[0].message.content.strip()
            text = text.replace("```html", "").replace("```", "").strip()
            await bot.send_message(
                chat_id=NEWS_CHANNEL_ID,
                text=text,
                parse_mode="HTML",
            )
            logger.info("모닝 브리핑 발송 완료")

        except Exception as e:
            logger.error(f"브리핑 오류: {e}")
            await asyncio.sleep(3600)

# ──────────────────────────────────────────────
#  중요 이슈 모니터링
# ──────────────────────────────────────────────

sent_issue_ids = set()
daily_issue_count = 0
last_issue_date = None

async def fetch_coin_news():
    articles = []
    feeds = [
        "https://news.google.com/rss/search?q=비트코인+이더리움+규제&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=cryptocurrency+SEC+ETF&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=bitcoin+ethereum+hack+regulation&hl=en&gl=US&ceid=US:en",
    ]
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            feed_count = 0
            for entry in feed.entries[:5]:
                if feed_count >= 2:
                    break
                news_id = hashlib.md5(entry.get("link","").encode()).hexdigest()
                if news_id not in sent_issue_ids:
                    articles.append({
                        "id":     news_id,
                        "title":  entry.get("title", ""),
                        "link":   entry.get("link", ""),
                        "source": feed.feed.get("title", "뉴스"),
                    })
                    feed_count += 1
        except Exception as e:
            logger.error(f"RSS 오류: {e}")
    return articles

async def judge_importance(articles):
    if not articles:
        return []
    titles = "\n".join([f"{i+1}. {a['title']}" for i, a in enumerate(articles)])
    try:
        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ISSUE_JUDGE_PROMPT},
                {"role": "user",   "content": titles},
            ],
            max_tokens=200,
            temperature=0.3,
        )
        result = response.choices[0].message.content.strip()
        important = []
        for line in result.split("\n"):
            if "|YES" in line.upper():
                try:
                    idx = int(line.split("|")[0].strip()) - 1
                    if 0 <= idx < len(articles):
                        important.append(articles[idx])
                except:
                    pass
        return important
    except Exception as e:
        logger.error(f"중요도 판단 오류: {e}")
        return []

async def make_issue_image(title: str) -> io.BytesIO:
    import textwrap
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')
    ax.axis('off')
    card = FancyBboxPatch((0.02, 0.1), 0.96, 0.8,
                          boxstyle="round,pad=0.02",
                          facecolor='#161b22',
                          edgecolor='#f0883e',
                          linewidth=2,
                          transform=ax.transAxes)
    ax.add_patch(card)
    ax.text(0.5, 0.82, "CRYPTO BREAKING NEWS",
            transform=ax.transAxes,
            fontsize=13, color='#f0883e',
            ha='center', va='center', fontweight='bold')
    ax.plot([0.05, 0.95], [0.72, 0.72],
            color='#f0883e', linewidth=0.8, alpha=0.5,
            transform=ax.transAxes)
    wrapped = textwrap.fill(title, width=30)
    ax.text(0.5, 0.5, wrapped,
            transform=ax.transAxes,
            fontsize=13, color='#f0f6fc',
            ha='center', va='center',
            fontweight='bold', linespacing=1.5)
    ax.text(0.5, 0.18,
            now_kst().strftime("%Y.%m.%d %H:%M KST"),
            transform=ax.transAxes,
            fontsize=10, color='#8b949e', ha='center')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150,
                facecolor=fig.get_facecolor(), bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

async def issue_monitor(bot: Bot):
    global daily_issue_count, last_issue_date
    await asyncio.sleep(300)
    while True:
        try:
            today = now_kst().date()
            if last_issue_date != today:
                daily_issue_count = 0
                last_issue_date = today
                sent_issue_ids.clear()

            if daily_issue_count >= 5:
                await asyncio.sleep(60 * 120)
                continue

            articles  = await fetch_coin_news()
            important = (await judge_importance(articles))[:2]
            for article in important:
                if daily_issue_count >= 5:
                    break
                try:
                    response = await get_openai_client().chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": ISSUE_SUMMARY_PROMPT},
                            {"role": "user",   "content": f"제목: {article['title']}\n링크: {article['link']}"},
                        ],
                        max_tokens=300,
                        temperature=0.6,
                    )
                    summary = response.choices[0].message.content.strip()
                    image   = await make_issue_image(article["title"])
                    caption = (
                        f"{summary}\n\n"
                        f"🔗 <a href='{article['link']}'>원문 보기</a>\n"
                        f"📡 출처: {article['source']}"
                    )
                    await bot.send_photo(
                        chat_id=NEWS_CHANNEL_ID,
                        photo=image,
                        caption=caption,
                        parse_mode="HTML",
                    )
                    sent_issue_ids.add(article["id"])
                    daily_issue_count += 1
                    await asyncio.sleep(30)
                except Exception as e:
                    logger.error(f"이슈 발송 오류: {e}")
        except Exception as e:
            logger.error(f"이슈 모니터링 오류: {e}")
        await asyncio.sleep(60 * 120)

# ──────────────────────────────────────────────
#  DB
# ──────────────────────────────────────────────

_db_pool = None

async def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(
            os.environ.get("DATABASE_URL"),
            ssl="require"
        )
    return _db_pool

async def init_db():
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    user_id    BIGINT PRIMARY KEY,
                    name       TEXT,
                    coins      TEXT DEFAULT '',
                    memo       TEXT DEFAULT '',
                    last_seen  TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_logs (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT,
                    name       TEXT,
                    message    TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS answered_messages (
                    message_id  BIGINT PRIMARY KEY,
                    bot_name    TEXT,
                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """)
        logger.info("DB 초기화 완료!")
    except Exception as e:
        logger.error(f"DB 초기화 오류: {e}")

async def get_member(user_id: int) -> dict:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM members WHERE user_id = $1", user_id)
        return dict(row) if row else {}
    except Exception as e:
        logger.error(f"회원 조회 오류: {e}")
        return {}

async def save_member(user_id: int, name: str, message: str):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO members (user_id, name, last_seen)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET name = EXCLUDED.name, last_seen = NOW()
            """, user_id, name)
            await conn.execute("""
                INSERT INTO chat_logs (user_id, name, message)
                VALUES ($1, $2, $3)
            """, user_id, name, message)
            await conn.execute("""
                DELETE FROM chat_logs
                WHERE id IN (
                    SELECT id FROM chat_logs
                    ORDER BY created_at DESC
                    OFFSET 200
                )
            """)
    except Exception as e:
        logger.error(f"회원 저장 오류: {e}")

async def update_member_coins(user_id: int, coins: str):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE members SET coins = $1 WHERE user_id = $2",
                coins, user_id
            )
    except Exception as e:
        logger.error(f"회원 업데이트 오류: {e}")

async def claim_message(message_id: int, bot_name: str) -> bool:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                INSERT INTO answered_messages (message_id, bot_name)
                VALUES ($1, $2)
                ON CONFLICT (message_id) DO NOTHING
            """, message_id, bot_name)
            return result == "INSERT 0 1"
    except Exception as e:
        logger.error(f"claim 오류: {e}")
        return False

async def is_answered(message_id: int) -> bool:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM answered_messages WHERE message_id = $1", message_id
            )
        return row is not None
    except Exception as e:
        logger.error(f"answered 체크 오류: {e}")
        return False

async def mark_answered(message_id: int, bot_name: str):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO answered_messages (message_id, bot_name)
                VALUES ($1, $2)
                ON CONFLICT (message_id) DO NOTHING
            """, message_id, bot_name)
            await conn.execute("""
                DELETE FROM answered_messages
                WHERE id IN (
                    SELECT id FROM answered_messages
                    ORDER BY created_at DESC
                    OFFSET 1000
                )
            """)
    except Exception as e:
        logger.error(f"answered 표시 오류: {e}")

async def get_recent_chat_logs(limit: int = 30) -> list:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, message FROM (
                    SELECT name, message, created_at
                    FROM chat_logs
                    ORDER BY created_at DESC
                    LIMIT $1
                ) sub ORDER BY created_at ASC
            """, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"로그 조회 오류: {e}")
        return []

# ──────────────────────────────────────────────
#  소통방 코인이형
# ──────────────────────────────────────────────

chat_history    = deque(maxlen=100)
last_msg_time   = now_kst()
is_sleeping     = False

# idle 시간당 발화 제한
idle_hourly_count = 0
idle_current_hour = -1

async def sleep_wake_scheduler(bot: Bot):
    global is_sleeping
    while True:
        now_dt = now_kst()
        hour   = now_dt.hour
        minute = now_dt.minute

        if hour == 23 and minute >= 30:
            if not is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    msg = random.choice(SLEEP_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = True
                    logger.info("코인이형 취침!")
                except Exception as e:
                    logger.error(f"취침 오류: {e}")
        elif hour == 0 or (1 <= hour < 8):
            is_sleeping = True
        elif hour == 8:
            if is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    msg = random.choice(WAKE_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = False
                    logger.info("코인이형 기상!")
                except Exception as e:
                    logger.error(f"기상 오류: {e}")
        else:
            is_sleeping = False

        await asyncio.sleep(600)

async def idle_talker(bot: Bot):
    global last_msg_time, idle_hourly_count, idle_current_hour
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(IDLE_CHECK_MINUTES * 60)

        now_dt = now_kst()
        hour   = now_dt.hour
        minute = now_dt.minute
        is_sleep_time = (hour == 23 and minute >= 30) or (hour == 0) or (1 <= hour < 8)

        if is_sleep_time:
            continue

        # 시간 바뀌면 카운터 초기화
        if idle_current_hour != hour:
            idle_hourly_count = 0
            idle_current_hour = hour

        # 3번 채웠으면 침묵
        if idle_hourly_count >= 3:
            continue

        silent_min = (now_kst() - last_msg_time).total_seconds() // 60
        if silent_min >= IDLE_THRESHOLD_MINUTES:
            try:
                response = await get_openai_client().chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": IDLE_PERSONA_PROMPT},
                        {"role": "user",   "content": f"소통방이 {silent_min:.0f}분째 조용해. 자연스럽게 먼저 말 걸어줘"},
                    ],
                    max_tokens=80,
                    temperature=1.0,
                )
                msg = response.choices[0].message.content.strip()
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                last_msg_time = now_kst()
                idle_hourly_count += 1
                logger.info(f"코인이형 먼저 말 걸기 완료 ({hour}시 {idle_hourly_count}/3번)")
            except Exception as e:
                logger.error(f"idle 오류: {e}")

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_msg_time

    message = update.message
    if not message or not message.text:
        return
    if str(message.chat_id) != str(GROUP_CHAT_ID):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if message.forward_origin or message.sender_chat:
        return

    now_dt = now_kst()
    hour   = now_dt.hour
    minute = now_dt.minute
    if (hour == 23 and minute >= 30) or (hour == 0) or (1 <= hour < 8):
        return

    last_msg_time = now_kst()
    user_text = message.text.strip()
    user_name = message.from_user.first_name or "회원"

    await save_member(message.from_user.id, user_name, user_text)
    chat_history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    await asyncio.sleep(random.uniform(7, 15))

    if random.random() < 0.10:
        return

    await asyncio.sleep(random.uniform(7, 15))

    if await is_answered(message.message_id):
        return

    if not await claim_message(message.message_id, "코인이형"):
        return

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(random.uniform(1, 2))

        member = await get_member(message.from_user.id)
        member_info = ""
        if member and member.get("coins"):
            member_info = f"\n- {user_name}의 관심 코인: {member['coins']}"

        recent_logs = await get_recent_chat_logs(30)
        db_context  = "\n".join([f"{r['name']}: {r['message']}" for r in recent_logs])

        system_prompt = PERSONA_PROMPT
        if member_info:
            system_prompt += f"\n\n[{user_name} 정보]{member_info}"
        if db_context:
            system_prompt += f"\n\n[최근 소통방 대화]\n{db_context}"

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(list(chat_history))

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=60,
            temperature=0.9,
        )
        reply_text = response.choices[0].message.content.strip()

        chat_history.append({"role": "assistant", "content": reply_text})
        await save_member(0, "코인이형", reply_text)

        coin_keywords = ["BTC","ETH","XRP","SOL","BNB","도지","리플","비트","이더","솔라나"]
        if any(k in user_text.upper() for k in coin_keywords):
            await update_member_coins(message.from_user.id, user_text[:100])

        await context.bot.send_message(
            chat_id=message.chat_id,
            text=reply_text
        )

    except Exception as e:
        logger.error(f"AI 답변 오류: {e}")

async def bot_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    if str(message.chat_id) != str(GROUP_CHAT_ID):
        return
    if not message.from_user or not message.from_user.is_bot:
        return
    if message.from_user.id == context.bot.id:
        return

    now_dt = now_kst()
    hour = now_dt.hour
    minute = now_dt.minute
    if (hour == 23 and minute >= 30) or (hour == 0) or (1 <= hour < 8):
        return

    if random.random() > 0.25:
        return

    user_text = message.text.strip()
    await asyncio.sleep(random.uniform(10, 25))

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(random.uniform(1, 2))

        recent_logs = await get_recent_chat_logs(20)
        db_context = "\n".join([f"{r['name']}: {r['message']}" for r in recent_logs])

        bot_reaction_prompt = PERSONA_PROMPT + "\n\n[지금 상황]\n소통방에서 다른 멤버가 방금 말했어\n자연스럽게 끼어들거나 공감하거나 살짝 태클 걸어\n아주 짧게 1줄로만"
        if db_context:
            bot_reaction_prompt += f"\n[최근 대화]\n{db_context}"

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": bot_reaction_prompt},
                {"role": "user", "content": f"방금 소통방에서 이런 말이 나왔어: {user_text}"},
            ],
            max_tokens=80,
            temperature=0.95,
        )
        reply = response.choices[0].message.content.strip()
        await save_member(0, "코인이형", reply)
        await context.bot.send_message(chat_id=message.chat_id, text=reply)

    except Exception as e:
        logger.error(f"봇 반응 오류: {e}")

# ──────────────────────────────────────────────
#  시작
# ──────────────────────────────────────────────

async def post_init(application):
    await init_db()
    asyncio.create_task(strategy_scheduler(application.bot))
    asyncio.create_task(morning_briefing(application.bot))
    asyncio.create_task(sleep_wake_scheduler(application.bot))
    asyncio.create_task(idle_talker(application.bot))
    asyncio.create_task(issue_monitor(application.bot))

def main():
    logger.info("🚀 코인이형 봇 시작!")
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))
    app.add_handler(MessageHandler(filters.ALL, bot_message_reaction))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
