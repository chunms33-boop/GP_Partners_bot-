"""
==================================================
  코인이형 텔레그램 봇 (실시간 차트 버전)
  - 메인채널: 실시간 BTC 가격 + 차트 이미지 + AI 전략
  - 소통방:   코인이형 AI 답변 (짧고 친근하게)
  - API 키는 Railway 환경변수에서 불러옴 (안전!)
==================================================
"""

import os
import io
import asyncio
import logging
import httpx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
#  🔒 API 키는 Railway 환경변수에서 자동으로 불러와요
# ──────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY")
NEWS_CHANNEL_ID    = os.environ.get("NEWS_CHANNEL_ID")
GROUP_CHAT_ID      = os.environ.get("GROUP_CHAT_ID")

NEWS_INTERVAL_MINUTES = 120  # 전략 포스팅 주기 (분)

# ──────────────────────────────────────────────
#  코인이형 성격 설정
# ──────────────────────────────────────────────

PERSONA_PROMPT = """
너는 '코인이형'이야. 코인판 8년차 베테랑 트레이더로 소통방에서 회원들과 대화하는 역할이야.

[성격]
- 친근하고 솔직한 형/오빠 스타일
- 반말과 존댓말을 자연스럽게 섞어서 사용
- 유머가 있고 틀리면 솔직하게 인정함

[말투 규칙]
- 무조건 1~2줄 이내로 짧게 끝내기
- 핵심만 딱 말하고 끊기
- 마침표(.) 절대 사용 금지 — 카톡 스타일
- 가끔 "ㅋㅋ", "ㅎㅎ" 자연스럽게 사용
- 이모지 0~1개만
- 투자 권유 절대 금지
- 모르면 "나도 모르겠다 ㅋㅋ" 하고 솔직하게

[예시]
회원: 비트코인 지금 사도 돼?
코인이형: RSI 과매수라 단기 조정 올 수 있어ㅋㅋ 좀 기다려보는게 나을 듯

회원: 이더 어때?
코인이형: 고래들이 쌓는 중이긴 한데 단기는 모르겠다 ㅎㅎ

[중요]
- 절대 AI라고 밝히지 않음
- 짧게! 길면 안됨
"""

TRADING_PROMPT = """
너는 비트코인 전문 트레이더야.
아래 실시간 데이터를 기반으로 트레이딩 전략 포스팅을 써줘.

[형식 — 이 형식 그대로 써줘]
📊 BTC 단기 전략

💰 현재가: {price} USDT
📈 24h 변동: {change}%
🔴 저항선: {resistance}
🟢 지지선: {support}

[전략 한줄 핵심]
(지금 상황 한줄 요약)

⚠️ 투자 판단은 본인 책임

[규칙]
- 저항선/지지선은 현재가 기준으로 현실적으로
- 마침표 사용 금지
- 전체 10줄 이내
- 투자 권유 절대 금지
"""

# ──────────────────────────────────────────────
#  내부 로직
# ──────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_openai_client():
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

async def get_btc_price():
    """CoinGecko에서 실시간 BTC 가격 가져오기"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true"
                },
                timeout=10
            )
            data = r.json()
            price  = data["bitcoin"]["usd"]
            change = round(data["bitcoin"]["usd_24h_change"], 2)
            return price, change
    except Exception as e:
        logger.error(f"가격 조회 오류: {e}")
        return None, None

async def get_btc_chart():
    """CoinGecko에서 7일 BTC 가격 데이터 가져와서 차트 이미지 생성"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart",
                params={"vs_currency": "usd", "days": "7"},
                timeout=15
            )
            data = r.json()
            prices = data["prices"]

        # 데이터 파싱
        times  = [datetime.fromtimestamp(p[0]/1000) for p in prices]
        values = [p[1] for p in prices]

        # 차트 그리기
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.patch.set_facecolor('#1a1a2e')
        ax.set_facecolor('#16213e')

        # 가격선
        ax.plot(times, values, color='#00d4ff', linewidth=2, zorder=3)

        # 그라데이션 채우기
        ax.fill_between(times, values, min(values), alpha=0.15, color='#00d4ff')

        # 현재가 표시
        ax.axhline(y=values[-1], color='#ffd700', linewidth=1,
                   linestyle='--', alpha=0.8)
        ax.text(times[-1], values[-1],
                f'  ${values[-1]:,.0f}',
                color='#ffd700', fontsize=11, va='center', fontweight='bold')

        # 스타일
        ax.set_title('BTC / USDT — 7일 차트',
                     color='white', fontsize=14, pad=12)
        ax.tick_params(colors='#aaaaaa')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.DayLocator())
        for spine in ax.spines.values():
            spine.set_edgecolor('#333355')
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f'${x:,.0f}')
        )
        ax.grid(color='#333355', linestyle='--', linewidth=0.5, alpha=0.5)
        plt.tight_layout()

        # 이미지 바이트로 변환
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, facecolor=fig.get_facecolor())
        buf.seek(0)
        plt.close()
        return buf

    except Exception as e:
        logger.error(f"차트 생성 오류: {e}")
        return None

async def post_trading_strategy(bot: Bot):
    """실시간 BTC 가격 + 차트 + AI 전략 포스팅"""
    try:
        # 실시간 가격 가져오기
        price, change = await get_btc_price()
        if not price:
            logger.error("가격 조회 실패")
            return

        # 저항선/지지선 자동 계산 (현재가 기준)
        resistance = f"${price * 1.03:,.0f}"
        support    = f"${price * 0.97:,.0f}"
        change_str = f"+{change}" if change > 0 else str(change)

        # AI 전략 생성
        prompt = TRADING_PROMPT.format(
            price=f"{price:,.0f}",
            change=change_str,
            resistance=resistance,
            support=support,
        )
        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user",   "content": "지금 바로 포스팅 써줘"},
            ],
            max_tokens=300,
            temperature=0.7,
        )
        strategy_text = response.choices[0].message.content.strip()

        # 차트 이미지 생성
        chart = await get_btc_chart()

        if chart:
            await bot.send_photo(
                chat_id=NEWS_CHANNEL_ID,
                photo=chart,
                caption=strategy_text,
            )
        else:
            await bot.send_message(
                chat_id=NEWS_CHANNEL_ID,
                text=strategy_text,
            )

        logger.info(f"전략 포스팅 완료 — BTC ${price:,.0f}")

    except Exception as e:
        logger.error(f"전략 포스팅 오류: {e}")

async def news_scheduler(bot: Bot):
    while True:
        await post_trading_strategy(bot)
        await asyncio.sleep(NEWS_INTERVAL_MINUTES * 60)

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat_id = str(message.chat_id)
    if chat_id != str(GROUP_CHAT_ID):
        return

    # 봇 메시지 무시
    if not message.from_user or message.from_user.is_bot:
        return

    # 채널에서 자동 전달된 메시지 무시
    if message.forward_origin:
        return

    # 채널 자동 포스팅 무시
    if message.sender_chat:
        return

    user_text = message.text.strip()
    user_name = message.from_user.first_name if message.from_user else "회원"

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(1.5)

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PERSONA_PROMPT},
                {"role": "user",   "content": f"{user_name}: {user_text}"},
            ],
            max_tokens=150,
            temperature=0.85,
        )
        reply_text = response.choices[0].message.content.strip()
        await message.reply_text(reply_text)

    except Exception as e:
        logger.error(f"AI 답변 오류: {e}")

async def post_init(application):
    asyncio.create_task(news_scheduler(application.bot))

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
