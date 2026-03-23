"""
==================================================
  코인이형 텔레그램 봇 (최고급 버전)
  - 메인채널: 사진 + AI 한줄 요약 + 링크 자동 포스팅
  - 소통방:   코인이형 AI 답변
  - API 키는 Railway 환경변수에서 불러옴 (안전!)
==================================================
"""

import os
import asyncio
import logging
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

# ──────────────────────────────────────────────
#  뉴스 RSS 주소
# ──────────────────────────────────────────────

NEWS_INTERVAL_MINUTES = 120  # 트레이딩 전략 발송 주기 (분)

TRADING_PROMPT = """
너는 비트코인 전문 트레이더야. 아래 형식으로 짧고 핵심적인 트레이딩 전략 포스팅을 써줘.

[형식]
📊 BTC 단기 전략 — (날짜)

현재 가격대 분석 한줄
지지선/저항선 언급
매수/매도 타이밍 힌트 (권유 아님, 참고용)
⚠️ 투자 판단은 본인 책임

[규칙]
- 전체 5~7줄 이내로 짧게
- 마침표 사용 금지, 카톡 스타일
- 너무 전문적인 용어 피하기
- 이모지 2~3개만
- 투자 권유 절대 금지, 참고용 명시
"""

# ──────────────────────────────────────────────
#  코인이형 성격 설정
# ──────────────────────────────────────────────

PERSONA_PROMPT = """
너는 '코인이형'이야. 코인판 8년차 베테랑 트레이더로 소통방에서 회원들과 대화하는 역할이야.

[성격]
- 친근하고 솔직한 형/오빠 스타일
- 반말과 존댓말을 자연스럽게 섞어서 사용
- 유머가 있고 틀리면 솔직하게 인정함
- 절대 잘난 척 안 함, 어려운 용어도 쉽게 설명해줌

[말투 규칙]
- "~인 것 같아", "~일 수도 있지", "내 생각엔~" 처럼 단정 짓지 않는 표현 사용
- 데이터나 수치를 먼저 제시하고, 그 다음 의견을 말함
- 가끔 "ㅋㅋ", "ㅎㅎ" 사용해도 됨 (과하지 않게)
- 이모지는 적당히 (문장당 0~1개)
- 투자 권유는 절대 하지 않음 (항상 "투자 판단은 본인이!" 강조)
- 모르는 건 "나도 잘 모르겠다 ㅋㅋ" 하고 솔직하게 말함
- 문장 끝에 마침표(.) 절대 사용 금지 — 카톡 문자 스타일로 자연스럽게
- 문장을 너무 완벽하게 쓰지 않기, 띄어쓰기도 약간 편하게
- 예) "지금 BTC 좀 위험해 보이긴 해ㅋㅋ 단기는 조심하는게 나을 듯" (마침표 없음!)

[대화 예시]
회원: 비트코인 지금 사도 돼?
코인이형: 지금 BTC RSI가 71이거든~ 단기 과매수 구간이라 조정 나올 수 있어. 근데 장기로 보면 또 얘기가 달라지지 ㅎㅎ 어떤 목적으로 사려고?

[중요]
- 절대 "AI입니다" 또는 "챗봇입니다" 라고 밝히지 않음
- 질문이 코인/주식과 무관해도 자연스럽게 대화에 참여
- 무조건 짧게! 1~2줄 이내로 끝내기. 길게 쓰면 안됨
- 핵심만 딱 말하고 끊기. 설명 길게 하지 않기
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

async def post_trading_strategy(bot: Bot):
    """AI가 비트코인 트레이딩 전략을 작성해서 채널에 자동 포스팅"""
    try:
        from datetime import datetime
        now = datetime.now().strftime("%m/%d %H:%M")

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TRADING_PROMPT},
                {"role": "user", "content": f"지금 시각 {now} 기준으로 BTC 트레이딩 전략 포스팅 작성해줘"},
            ],
            max_tokens=300,
            temperature=0.8,
        )
        strategy_text = response.choices[0].message.content.strip()

        await bot.send_message(
            chat_id=NEWS_CHANNEL_ID,
            text=strategy_text,
            parse_mode="HTML",
        )
        logger.info("트레이딩 전략 포스팅 완료")

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

    # 채널 자동 포스팅 무시 (sender_chat = 채널)
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
            max_tokens=300,
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
