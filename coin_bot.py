"""
==================================================
  코인이형 텔레그램 봇 (보안 안전 버전)
  - 메인채널: RSS 뉴스 자동 포스팅
  - 소통방:   AI(GPT) 가 코인이형으로 모든 대화에 참여
  - API 키는 Railway 환경변수에서 불러옴 (안전!)
==================================================
"""

import os
import asyncio
import logging
import feedparser
import hashlib
import json
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
#     여기는 절대 건드리지 마세요!
# ──────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY")
NEWS_CHANNEL_ID    = os.environ.get("NEWS_CHANNEL_ID")
GROUP_CHAT_ID      = os.environ.get("GROUP_CHAT_ID")

# ──────────────────────────────────────────────
#  뉴스 RSS 주소 (원하는 것 추가/삭제 가능)
# ──────────────────────────────────────────────

RSS_FEEDS = [
    "https://feeds.feedburner.com/coindesk",
    "https://news.google.com/rss/search?q=코인+암호화폐&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=비트코인+이더리움&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=주식+코스피&hl=ko&gl=KR&ceid=KR:ko",
]

NEWS_INTERVAL_MINUTES = 60  # 뉴스 발송 주기 (분)

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

[대화 예시]
회원: 비트코인 지금 사도 돼?
코인이형: 지금 BTC RSI가 71이거든~ 단기 과매수 구간이라 조정 나올 수 있어. 근데 장기로 보면 또 얘기가 달라지지 ㅎㅎ 어떤 목적으로 사려고?

회원: 이더리움 전망 어때요?
코인이형: 요즘 ETH는 ETF 이슈랑 온체인 데이터 보면 고래들이 조용히 쌓는 중이야 🐋 개인적으론 긍정적으로 보는데, 이건 내 생각이고 투자는 항상 본인이 판단해야 해!

[중요]
- 절대 "AI입니다" 또는 "챗봇입니다" 라고 밝히지 않음
- 질문이 코인/주식과 무관해도 자연스럽게 대화에 참여
- 짧고 자연스럽게 (너무 긴 답변 금지, 3~5줄 이내)
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

SENT_NEWS_FILE = "sent_news.json"

def load_sent_news():
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_sent_news(sent: set):
    with open(SENT_NEWS_FILE, "w") as f:
        json.dump(list(sent), f)

def make_news_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

async def fetch_and_post_news(bot: Bot):
    sent_ids = load_sent_news()
    new_count = 0

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                news_id = make_news_id(entry.get("link", ""))
                if news_id in sent_ids:
                    continue

                title  = entry.get("title", "제목 없음")
                link   = entry.get("link", "")
                source = feed.feed.get("title", "뉴스")

                message = (
                    f"📰 <b>{title}</b>\n\n"
                    f"🔗 <a href='{link}'>원문 보기</a>\n"
                    f"📡 출처: {source}"
                )

                await bot.send_message(
                    chat_id=NEWS_CHANNEL_ID,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
                sent_ids.add(news_id)
                new_count += 1
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"RSS 오류 ({feed_url}): {e}")

    save_sent_news(sent_ids)
    logger.info(f"뉴스 발송 완료: {new_count}건")

async def news_scheduler(bot: Bot):
    while True:
        await fetch_and_post_news(bot)
        await asyncio.sleep(NEWS_INTERVAL_MINUTES * 60)

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat_id = str(message.chat_id)
    if chat_id != str(GROUP_CHAT_ID):
        return

    if message.from_user and message.from_user.is_bot:
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
