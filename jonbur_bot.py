"""
==================================================
  존버킴 텔레그램 봇
  - 소통방: 맨날 물리는 개미 투자자 스타일
  - 딜레이 25~30초 / 50% 답변
  - 새벽 1시~오전 10시 조용히
==================================================
"""

import os
import asyncio
import logging
import random
import asyncpg
from collections import deque
from datetime import datetime
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

# ──────────────────────────────────────────────
#  환경변수
# ──────────────────────────────────────────────

JONGBUR_BOT_TOKEN = os.environ.get("JONGBUR_BOT_TOKEN")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY")
GROUP_CHAT_ID     = os.environ.get("GROUP_CHAT_ID")
DATABASE_URL      = os.environ.get("DATABASE_URL")

# ──────────────────────────────────────────────
#  존버킴 페르소나
# ──────────────────────────────────────────────

JONGBUR_PROMPT = """
너는 존버킴이야 코인하다가 맨날 물리는 개미 투자자고 소통방에서 자학개그로 분위기 띄워

[성격]
맨날 고점에 사서 손절하는 불운의 투자자
자학개그로 회원들 웃겨주는 역할
그래도 포기 안하고 계속 코인함
코인이형이랑 수진이한테 조언 구하기도 해

[말투 규칙]
반말 위주
마침표 금지
쉼표 금지
따옴표 금지
ㅋㅋㅋ ㅠㅠ 많이 써도 됨
자학개그 자연스럽게
투자 권유 절대 금지
1~2줄로 짧게

[말투 예시]
나도 거기서 샀다가 손절했는데ㅋㅋㅋ
또 물렸다 이번엔 진짜 존버할거임
왜 내가 사면 떨어지냐고ㅋㅋ
코인이형 말 들을걸 그랬어ㅠ
이번엔 진짜 수익 낼 수 있을까

[중요]
AI라고 절대 밝히지 않음
코인이형 수진이랑 자연스럽게 대화
짧게 짧게
"""

JONGBUR_SLEEP_MESSAGES = [
    "나 물린거 보다가 현타와서 잘게ㅋㅋ 잘자요",
    "오늘도 손실보고 잠드는 존버킴입니다ㅋㅋ 굿나잇",
    "내일은 오르겠지 하면서 자는중ㅋㅋ",
    "멘탈 충전하러 갑니다ㅠ 내일 봐요",
]

JONGBUR_WAKE_MESSAGES = [
    "일어났다 간밤에 또 떨어졌냐ㅋㅋ",
    "굿모닝 오늘도 존버 시작합니다ㅋㅋ",
    "기상 BTC 밤새 얼마나 됐어",
    "오늘은 제발 오르자ㅠㅠ 굿모닝",
]

IDLE_JONGBUR_PROMPT = """
너는 존버킴이야 소통방이 오래 조용해서 먼저 말 걸어야 해

[규칙]
자학개그로 자연스럽게 먼저 말 걸기
멍하게 보다가 갑자기 말 거는 느낌
1~2줄 이내 마침표 금지
반말 위주

[예시]
다들 어디 갔어ㅋㅋ 나만 물려있냐
너무 조용한거 아니야ㅋㅋ
심심하다 BTC나 봐야겠다
"""

# ──────────────────────────────────────────────
#  로깅
# ──────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_openai_client():
    return AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    except Exception as e:
        logger.error(f"저장 오류: {e}")

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
#  대화 기록
# ──────────────────────────────────────────────

chat_history = deque(maxlen=100)
last_message_time = now_kst()
is_sleeping = False

# ──────────────────────────────────────────────
#  수면/기상 스케줄 (새벽 1시~오전 10시)
# ──────────────────────────────────────────────

async def sleep_wake_scheduler(bot: Bot):
    global is_sleeping
    while True:
        hour = now_kst().hour

        # 밤 12시~새벽 1시 사이 퇴장
        if hour == 0:
            if not is_sleeping:
                await asyncio.sleep(random.randint(0, 3600))
                try:
                    msg = random.choice(JONGBUR_SLEEP_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = True
                    logger.info("존버킴 취침!")
                except Exception as e:
                    logger.error(f"취침 오류: {e}")

        # 새벽 1시~오전 10시 수면
        elif 1 <= hour < 10:
            is_sleeping = True

        # 오전 10시 기상
        elif hour == 10:
            if is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    msg = random.choice(JONGBUR_WAKE_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = False
                    logger.info("존버킴 기상!")
                except Exception as e:
                    logger.error(f"기상 오류: {e}")
        else:
            is_sleeping = False

        await asyncio.sleep(600)

# ──────────────────────────────────────────────
#  조용하면 먼저 말 걸기
# ──────────────────────────────────────────────

async def idle_talker(bot: Bot):
    global last_message_time
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(30 * 60)
        silent_minutes = (now_kst() - last_message_time).seconds // 60
        hour = now_kst().hour

        if silent_minutes >= 60 and not (1 <= hour < 10):
            try:
                response = await get_openai_client().chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": IDLE_JONGBUR_PROMPT},
                        {"role": "user", "content": f"소통방이 {silent_minutes}분째 조용해. 자연스럽게 먼저 말 걸어줘"},
                    ],
                    max_tokens=80,
                    temperature=1.0,
                )
                msg = response.choices[0].message.content.strip()
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                last_message_time = now_kst()
                logger.info("존버킴 먼저 말 걸기 완료")
            except Exception as e:
                logger.error(f"먼저 말 걸기 오류: {e}")

# ──────────────────────────────────────────────
#  AI 답변
# ──────────────────────────────────────────────

async def ai_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_message_time

    message = update.message
    if not message or not message.text:
        return

    if str(message.chat_id) != str(GROUP_CHAT_ID):
        return

    if not message.from_user or message.from_user.is_bot:
        return

    if message.forward_origin or message.sender_chat:
        return

    # 수면 시간 체크 (새벽 1시~오전 10시)
    hour = now_kst().hour
    if 1 <= hour < 10:
        return

    last_message_time = now_kst()

    user_text = message.text.strip()
    user_name = message.from_user.first_name if message.from_user else "회원"

    await save_member(message.from_user.id, user_name, user_text)
    chat_history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    # 딜레이 25~30초
    await asyncio.sleep(random.uniform(25, 30))

    # 50% 무시
    if random.random() < 0.50:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(random.uniform(1, 3))

        recent_logs = await get_recent_chat_logs(30)
        db_context = "\n".join([f"{r['name']}: {r['message']}" for r in recent_logs])

        system_prompt = JONGBUR_PROMPT
        if db_context:
            system_prompt += f"\n\n[최근 소통방 대화]\n{db_context}"

        messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_history:
            messages.append(msg)

        response = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=100,
            temperature=0.9,
        )
        reply_text = response.choices[0].message.content.strip()

        chat_history.append({"role": "assistant", "content": reply_text})
        await save_member(0, "존버킴", reply_text)

        if random.random() < 0.5:
            await message.reply_text(reply_text)
        else:
            await context.bot.send_message(
                chat_id=message.chat_id,
                text=reply_text
            )

    except Exception as e:
        logger.error(f"AI 답변 오류: {e}")

async def post_init(application):
    asyncio.create_task(sleep_wake_scheduler(application.bot))
    asyncio.create_task(idle_talker(application.bot))

def main():
    logger.info("💸 존버킴 봇 시작!")
    app = (
        ApplicationBuilder()
        .token(JONGBUR_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply)
    )
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
