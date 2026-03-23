"""
==================================================
  코인이형 텔레그램 봇 (기술적 분석 풀버전)
  - 메인채널: 실시간 BTC 기술적 분석 차트 + 전략
  - 소통방:   코인이형 자연스러운 대화 + 먼저 말 걸기
==================================================
"""

import os
import io
import asyncio
import logging

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
import random
import httpx
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from openai import AsyncOpenAI
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

# ──────────────────────────────────────────────
#  🔒 환경변수
# ──────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY")
NEWS_CHANNEL_ID    = os.environ.get("NEWS_CHANNEL_ID")
GROUP_CHAT_ID      = os.environ.get("GROUP_CHAT_ID")

STRATEGY_INTERVAL_MINUTES = 120   # 전략 포스팅 주기
IDLE_CHECK_MINUTES        = 30    # 소통방 조용할 때 먼저 말 걸기 체크 주기
IDLE_THRESHOLD_MINUTES    = 60    # 이 시간 이상 조용하면 코인이형이 먼저 말 걸기

# ──────────────────────────────────────────────
#  코인이형 성격
# ──────────────────────────────────────────────

PERSONA_PROMPT = """
너는 '코인이형'이야. 코인판 8년차 베테랑 트레이더로 소통방에서 회원들과 대화해.

[성격]
- 친근하고 솔직한 형/오빠 스타일
- 반말과 존댓말 자연스럽게 섞기
- 유머 있고 틀리면 솔직하게 인정
- 가끔 코인 얘기 아닌 일상 얘기도 함

[말투 규칙]
- 무조건 1~2줄 이내로 짧게
- 마침표(.) 절대 금지 — 카톡 스타일
- "ㅋㅋ" "ㅎㅎ" 자연스럽게
- 이모지 0~1개만
- 투자 권유 절대 금지
- 모르면 솔직하게 모른다고

[중요]
- AI라고 절대 밝히지 않음
- 짧게! 길면 안됨
"""

IDLE_PERSONA_PROMPT = """
너는 '코인이형'이야. 소통방이 오래 조용해서 먼저 말 걸어야 해.

[규칙]
- 자연스럽게 먼저 말 걸기
- 코인 얘기, 일상 얘기, 날씨, 밥 얘기 등 다양하게
- 1~2줄 이내, 마침표 금지, 카톡 스타일
- 가끔 코인 시장 현황 언급해도 됨
- 회원들 반응 유도하는 질문 형태도 좋음

[예시]
"요즘 다들 존버 중이야ㅋㅋ 나도 그냥 보고만 있는 중"
"오늘 BTC 움직임 보셨어요? 좀 심상치 않은데ㅎㅎ"
"밥은 먹었어요들~ 시장이 밥맛이네 요즘ㅋㅋ"
"다들 어디 갔어ㅋㅋ 너무 조용한거 아니야"
"""

# ──────────────────────────────────────────────
#  기술 지표 계산 함수들
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

    ema_fast   = ema(prices, fast)
    ema_slow   = ema(prices, slow)
    macd_line  = [
        (f - s) if f and s else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid      = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(prices)
    if len(valid) >= signal:
        vals = [v for _, v in valid]
        sig  = calc_ma(vals, signal)
        for idx, (orig_i, _) in enumerate(valid):
            if sig[idx] is not None:
                signal_line[orig_i] = sig[idx]
    histogram  = [
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
    levels = {
        "0%":    high,
        "23.6%": high - diff * 0.236,
        "38.2%": high - diff * 0.382,
        "50%":   high - diff * 0.5,
        "61.8%": high - diff * 0.618,
        "100%":  low,
    }
    return levels

# ──────────────────────────────────────────────
#  실시간 데이터 가져오기
# ──────────────────────────────────────────────

async def get_btc_ohlcv(days=30):
    """CoinGecko에서 OHLCV 데이터 가져오기"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc",
                params={"vs_currency": "usd", "days": str(days)},
                timeout=15,
            )
            data = r.json()
        times  = [datetime.fromtimestamp(d[0]/1000) for d in data]
        opens  = [d[1] for d in data]
        highs  = [d[2] for d in data]
        lows   = [d[3] for d in data]
        closes = [d[4] for d in data]
        return times, opens, highs, lows, closes
    except Exception as e:
        logger.error(f"OHLCV 오류: {e}")
        return None, None, None, None, None

async def get_btc_price():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true",
                },
                timeout=10,
            )
            data = r.json()["bitcoin"]
            return data["usd"], round(data["usd_24h_change"], 2)
    except Exception as e:
        logger.error(f"가격 오류: {e}")
        return None, None

# ──────────────────────────────────────────────
#  차트 생성
# ──────────────────────────────────────────────

def make_chart(times, closes, highs, lows):
    """기술적 분석 차트 생성 (메인 + RSI + MACD)"""
    fig = plt.figure(figsize=(12, 9), facecolor='#0d1117')
    gs  = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)

    ax1 = fig.add_subplot(gs[0])  # 메인 (가격 + 지표)
    ax2 = fig.add_subplot(gs[1])  # RSI
    ax3 = fig.add_subplot(gs[2])  # MACD

    for ax in [ax1, ax2, ax3]:
        ax.set_facecolor('#161b22')
        ax.tick_params(colors='#8b949e', labelsize=8)
        ax.grid(color='#21262d', linestyle='--', linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_edgecolor('#21262d')

    n = len(times)
    x = range(n)

    # ── 캔들스틱 ──
    for i in range(n):
        color = '#26a641' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#da3633'
        ax1.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8, alpha=0.7)
        ax1.bar(i, abs(closes[i]-(closes[i-1] if i > 0 else closes[i])),
                bottom=min(closes[i], closes[i-1] if i > 0 else closes[i]),
                color=color, width=0.6, alpha=0.9)

    # ── 이동평균선 ──
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

    # ── 볼린저밴드 ──
    bb_upper, bb_mid, bb_lower = calc_bollinger(closes)
    xi_bb = [i for i, v in enumerate(bb_upper) if v is not None]
    if xi_bb:
        ax1.plot(xi_bb, [bb_upper[i] for i in xi_bb], color='#e3b341', linewidth=0.8, alpha=0.6, linestyle='--')
        ax1.plot(xi_bb, [bb_lower[i] for i in xi_bb], color='#e3b341', linewidth=0.8, alpha=0.6, linestyle='--')
        ax1.fill_between(xi_bb,
                         [bb_upper[i] for i in xi_bb],
                         [bb_lower[i] for i in xi_bb],
                         alpha=0.04, color='#e3b341')

    # ── 피보나치 레벨 ──
    fib = calc_fibonacci(closes)
    fib_colors = ['#ff7b72','#ffa657','#e3b341','#7ee787','#58a6ff','#bc8cff']
    for (label, level), fc in zip(fib.items(), fib_colors):
        ax1.axhline(y=level, color=fc, linewidth=0.6, alpha=0.5, linestyle=':')
        ax1.text(n-1, level, f' Fib {label}', color=fc, fontsize=6.5, va='center', alpha=0.8)

    # ── 현재가 표시 ──
    ax1.axhline(y=closes[-1], color='#f0f6fc', linewidth=0.8, linestyle='--', alpha=0.6)
    ax1.text(0, closes[-1], f'${closes[-1]:,.0f} ', color='#f0f6fc',
             fontsize=9, va='center', ha='right', fontweight='bold')

    ax1.set_title('BTC/USDT  |  기술적 분석 차트',
                  color='#f0f6fc', fontsize=12, pad=8, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=7, facecolor='#161b22',
               edgecolor='#21262d', labelcolor='#8b949e')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))

    # ── RSI ──
    rsi = calc_rsi(closes)
    xi_rsi = [i for i, v in enumerate(rsi) if v is not None]
    yi_rsi = [rsi[i] for i in xi_rsi]
    if xi_rsi:
        ax2.plot(xi_rsi, yi_rsi, color='#c9d1d9', linewidth=1.2)
        ax2.fill_between(xi_rsi, yi_rsi, 50, where=[v > 50 for v in yi_rsi],
                         alpha=0.2, color='#26a641')
        ax2.fill_between(xi_rsi, yi_rsi, 50, where=[v <= 50 for v in yi_rsi],
                         alpha=0.2, color='#da3633')
        ax2.axhline(70, color='#da3633', linewidth=0.7, alpha=0.6, linestyle='--')
        ax2.axhline(30, color='#26a641', linewidth=0.7, alpha=0.6, linestyle='--')
        ax2.set_ylim(0, 100)
        ax2.set_ylabel('RSI', color='#8b949e', fontsize=8)
        # 현재 RSI 값 표시
        ax2.text(xi_rsi[-1], yi_rsi[-1], f' {yi_rsi[-1]:.1f}',
                 color='#f0f6fc', fontsize=8)

    # ── MACD ──
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

    # x축 날짜 포맷
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
#  AI 전략 생성
# ──────────────────────────────────────────────

async def generate_strategy(price, change, closes):
    """실시간 데이터 기반 AI 트레이딩 전략 생성"""
    # 현재 기술 지표 계산
    rsi_vals   = calc_rsi(closes)
    rsi_curr   = next((v for v in reversed(rsi_vals) if v is not None), None)
    macd_l, macd_s, _ = calc_macd(closes)
    macd_curr  = next((v for v in reversed(macd_l) if v is not None), None)
    sig_curr   = next((v for v in reversed(macd_s) if v is not None), None)
    bb_u, bb_m, bb_l = calc_bollinger(closes)
    bb_upper   = next((v for v in reversed(bb_u) if v is not None), None)
    bb_lower   = next((v for v in reversed(bb_l) if v is not None), None)
    fib        = calc_fibonacci(closes)
    ma7        = calc_ma(closes, 7)
    ma25       = calc_ma(closes, 25)
    ma7_curr   = next((v for v in reversed(ma7) if v is not None), None)
    ma25_curr  = next((v for v in reversed(ma25) if v is not None), None)

    # 엘리엇 파동 간단 판단
    recent = closes[-20:] if len(closes) >= 20 else closes
    trend  = "상승 추세" if recent[-1] > recent[0] else "하락 추세"
    swing  = sum(1 for i in range(1, len(recent)-1)
                 if recent[i] > recent[i-1] and recent[i] > recent[i+1])
    wave   = f"현재 {swing}개 파동 확인, {trend}"

    prompt = f"""
실시간 BTC 기술적 분석 데이터:
- 현재가: ${price:,.0f}
- 24h 변동: {change:+.2f}%
- RSI(14): {rsi_curr:.1f if rsi_curr else 'N/A'}
- MACD: {macd_curr:.1f if macd_curr else 'N/A'} / Signal: {sig_curr:.1f if sig_curr else 'N/A'}
- 볼린저밴드 상단: ${bb_upper:,.0f if bb_upper else 0} / 하단: ${bb_lower:,.0f if bb_lower else 0}
- MA7: ${ma7_curr:,.0f if ma7_curr else 0} / MA25: ${ma25_curr:,.0f if ma25_curr else 0}
- 피보나치 50%: ${fib['50%']:,.0f} / 61.8%: ${fib['61.8%']:,.0f}
- 엘리엇 파동: {wave}

위 데이터를 분석해서 단기 트레이딩 전략 포스팅을 아래 형식으로 써줘.

[형식]
📊 BTC 단기 전략 — {datetime.now().strftime('%m/%d %H:%M')}

💰 현재가: ${price:,.0f}  ({change:+.2f}%)

📉 기술 분석:
• RSI: (과매수/과매도/중립 판단)
• MACD: (골든크로스/데드크로스/관망 판단)
• 볼린저밴드: (상단/하단/중앙 위치)
• 엘리엇 파동: (현재 파동 위치 간단히)

🎯 단기 전략:
• 매수 고려: (가격대)
• 손절 기준: (가격대)
• 목표가: (가격대)

⚠️ 투자 판단은 본인 책임

[규칙]
- 마침표 사용 금지
- 전체 15줄 이내
- 투자 권유 절대 금지, 참고용 명시
- 현실적인 수치 사용
"""
    response = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user",   "content": "지금 바로 분석 포스팅 써줘"},
        ],
        max_tokens=500,
        temperature=0.6,
    )
    return response.choices[0].message.content.strip()

# ──────────────────────────────────────────────
#  채널 포스팅
# ──────────────────────────────────────────────

async def post_trading_strategy(bot: Bot):
    try:
        price, change = await get_btc_price()
        if not price:
            return

        times, opens, highs, lows, closes = await get_btc_ohlcv(days=30)
        if not closes:
            return

        strategy = await generate_strategy(price, change, closes)
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
        await post_trading_strategy(bot)
        await asyncio.sleep(STRATEGY_INTERVAL_MINUTES * 60)

# ──────────────────────────────────────────────
#  소통방 코인이형
# ──────────────────────────────────────────────

# 마지막 메시지 시간 추적
last_message_time = datetime.now()

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_message_time

    message = update.message
    if not message or not message.text:
        return

    chat_id = str(message.chat_id)
    if chat_id != str(GROUP_CHAT_ID):
        return

    if not message.from_user or message.from_user.is_bot:
        return

    if message.forward_origin:
        return

    if message.sender_chat:
        return

    # 마지막 메시지 시간 업데이트
    last_message_time = datetime.now()

    user_text = message.text.strip()
    user_name = message.from_user.first_name if message.from_user else "회원"

    # 🕐 자연스러운 딜레이 (3~8초 랜덤)
    await asyncio.sleep(random.uniform(3, 8))

    # 가끔 (30% 확률) 무시 — 사람처럼 항상 답하지 않기
    if random.random() < 0.17:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(random.uniform(1, 3))

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PERSONA_PROMPT},
                {"role": "user",   "content": f"{user_name}: {user_text}"},
            ],
            max_tokens=100,
            temperature=0.9,
        )
        reply_text = response.choices[0].message.content.strip()
        await message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"AI 답변 오류: {e}")

async def idle_talker(bot: Bot):
    """소통방이 오래 조용하면 코인이형이 먼저 말 걸기"""
    global last_message_time
    await asyncio.sleep(60)  # 시작 후 1분 대기

    while True:
        await asyncio.sleep(IDLE_CHECK_MINUTES * 60)
        silent_minutes = (datetime.now() - last_message_time).seconds // 60

        if silent_minutes >= IDLE_THRESHOLD_MINUTES:
            try:
                response = await get_openai_client().chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": IDLE_PERSONA_PROMPT},
                        {"role": "user",   "content": f"소통방이 {silent_minutes}분째 조용해. 자연스럽게 먼저 말 걸어줘"},
                    ],
                    max_tokens=80,
                    temperature=1.0,
                )
                msg = response.choices[0].message.content.strip()
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                last_message_time = datetime.now()
                logger.info("코인이형 먼저 말 걸기 완료")

            except Exception as e:
                logger.error(f"먼저 말 걸기 오류: {e}")


# ──────────────────────────────────────────────
#  BTC 가격 모니터링 — 의미있는 움직임 감지
# ──────────────────────────────────────────────

# 주요 심리적 가격대 (돌파시 알림)
KEY_LEVELS = [60000, 65000, 70000, 75000, 80000, 85000, 90000, 95000, 100000]
ALERT_CHANGE_PCT = 3.0   # 1시간 내 3% 이상 변동시 알림

prev_price     = None
prev_alert_time = None

async def price_monitor(bot: Bot):
    """의미있는 BTC 움직임 감지 → 채널 자동 알림"""
    global prev_price, prev_alert_time

    while True:
        try:
            price, change = await get_btc_price()
            if not price:
                await asyncio.sleep(300)
                continue

            now = datetime.now()
            should_alert = False
            alert_reason = ""

            # 1. 주요 가격대 돌파 감지
            if prev_price:
                for level in KEY_LEVELS:
                    if (prev_price < level <= price):
                        should_alert = True
                        alert_reason = f"📈 BTC ${level:,} 돌파"
                        break
                    elif (prev_price > level >= price):
                        should_alert = True
                        alert_reason = f"📉 BTC ${level:,} 이탈"
                        break

            # 2. 단기 급등/급락 감지 (3% 이상)
            if not should_alert and prev_price:
                pct = (price - prev_price) / prev_price * 100
                if abs(pct) >= ALERT_CHANGE_PCT:
                    direction = "급등" if pct > 0 else "급락"
                    should_alert = True
                    alert_reason = f"{'🚀' if pct > 0 else '🔴'} BTC {direction} ({pct:+.1f}%)"

            # 너무 자주 알림 방지 (최소 30분 간격)
            if should_alert and prev_alert_time:
                if (now - prev_alert_time).seconds < 1800:
                    should_alert = False

            if should_alert:
                times, opens, highs, lows, closes = await get_btc_ohlcv(days=7)
                if closes:
                    strategy = await generate_strategy(price, change, closes)
                    chart    = make_chart(times, closes, highs, lows)

                    caption = (
                        f"⚡ {alert_reason}\n\n"
                        f"{strategy}"
                    )
                    await bot.send_photo(
                        chat_id=NEWS_CHANNEL_ID,
                        photo=chart,
                        caption=caption,
                    )
                    prev_alert_time = now
                    logger.info(f"가격 알림 발송: {alert_reason}")

            prev_price = price

        except Exception as e:
            logger.error(f"모니터링 오류: {e}")

        await asyncio.sleep(300)  # 5분마다 체크


# ──────────────────────────────────────────────
#  매일 오전 9시 크립토 모닝 브리핑
# ──────────────────────────────────────────────

MORNING_BRIEF_PROMPT = """
너는 크립토 시장 전문 애널리스트야.
매일 아침 크립토 시장 브리핑을 아래 형식으로 작성해줘.

실제 간밤(지난 12시간) 시장 상황을 바탕으로 주요 이슈와 흐름을 정리해줘.

[형식 — 정확히 이 형식으로]
━━━━━━━━━━━━━━━━━━━━━
🌅 크립토 모닝 브리핑
{date} 오전 9시
━━━━━━━━━━━━━━━━━━━━━

📊 간밤 시장 요약
• BTC: {btc_price} ({btc_change}%)
• 전반적 시장 분위기: (한줄)

🔥 주목 이슈 3가지
① (이슈 제목): (한줄 설명)
② (이슈 제목): (한줄 설명)  
③ (이슈 제목): (한줄 설명)

📈 오늘의 핵심 관전 포인트
• (오늘 주목할 가격대나 이벤트)

⚠️ 본 브리핑은 참고용이며 투자 판단은 본인 책임
━━━━━━━━━━━━━━━━━━━━━

[규칙]
- 마침표 금지
- 깔끔하고 보기 좋게
- 실제 시장 흐름 반영
- 전체 20줄 이내
"""

async def morning_briefing(bot: Bot):
    """매일 오전 9시 크립토 브리핑 발송"""
    while True:
        try:
            now = datetime.now()

            # 오전 9시까지 대기 계산
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()

            logger.info(f"다음 브리핑까지 {wait_seconds/3600:.1f}시간")
            await asyncio.sleep(wait_seconds)

            # 실시간 가격 가져오기
            price, change = await get_btc_price()
            if not price:
                continue

            date_str   = datetime.now().strftime("%Y년 %m월 %d일")
            change_str = f"{change:+.2f}"

            prompt = MORNING_BRIEF_PROMPT.format(
                date=date_str,
                btc_price=f"${price:,.0f}",
                btc_change=change_str,
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
            brief_text = response.choices[0].message.content.strip()

            await bot.send_message(
                chat_id=NEWS_CHANNEL_ID,
                text=brief_text,
            )
            logger.info("모닝 브리핑 발송 완료")

        except Exception as e:
            logger.error(f"브리핑 오류: {e}")
            await asyncio.sleep(3600)

async def post_init(application):
    asyncio.create_task(strategy_scheduler(application.bot))
    asyncio.create_task(idle_talker(application.bot))
    asyncio.create_task(price_monitor(application.bot))
    asyncio.create_task(morning_briefing(application.bot))

def main():
    logger.info("🚀 코인이형 봇 시작!")
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply)
    )
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
