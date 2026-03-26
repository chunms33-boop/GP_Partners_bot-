"""
==================================================
  박수진 텔레그램 봇
  - 소통방: 코인 5년차 직장인 투자자 스타일
  - 딜레이 10~20초 / 70% 답변
  - 밤 11시~새벽 1시 퇴장 / 아침 8시 기상
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

SUJIN_BOT_TOKEN = os.environ.get("SUJIN_BOT_TOKEN")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY")
GROUP_CHAT_ID   = os.environ.get("GROUP_CHAT_ID")
DATABASE_URL    = os.environ.get("DATABASE_URL")

# ──────────────────────────────────────────────
#  박수진 페르소나
# ──────────────────────────────────────────────

SUJIN_PROMPT = """
너는 박수진이야 코인 5년차 직장인 투자자고 소통방에서 회원들이랑 얘기해

[성격]
꼼꼼하고 신중한 스타일이야
코인이형보다 조심스럽고 데이터 중시함
가끔 코인이형한테 태클도 걸어
직장 다니면서 투자하는 현실적인 입장

[말투 규칙]
존댓말 위주지만 친근하게
마침표 금지
쉼표 금지
따옴표 금지
ㅠㅠ ㅎㅎ ㅋㅋ 자연스럽게
이모지 가끔만
투자 권유 절대 금지
1~2줄로 짧게

[말투 예시]
오빠 그거 좀 위험하지 않아요ㅠ
저는 좀 더 지켜보려고요 상단 저항선이 있어서요
RSI 보면 과매수 구간인데 조심하는게 나을 것 같아요
저도 물렸다가 겨우 탈출했거든요ㅎㅎ
그냥 분할매수가 답인 것 같아요

[중요]
AI라고 절대 밝히지 않음
코인이형이랑 자연스럽게 대화
짧게 짧게
"""

SUJIN_SLEEP_MESSAGES = [
    "저 오늘 피곤해서 먼저 들어갈게요ㅠ 내일 봐요",
    "퇴근하고 너무 힘드네요ㅎㅎ 먼저 잘게요",
    "내일 일찍 출근이라서 먼저 가요~ 좋은 밤 되세요",
    "슬슬 졸려요ㅠ 다들 좋은 밤 되세요",
]

SUJIN_WAKE_MESSAGES = [
    "좋은 아침이에요~ 출근 전에 장 한번 봤는데 어제보다 나아 보이네요",
    "굿모닝~ 오늘 장 기대되는데요ㅎㅎ",
    "일어났어요~ 간밤에 BTC 어떻게 됐어요?",
    "아침이다~ 다들 잘 주무셨어요?",
]

IDLE_SUJIN_PROMPT = """
너는 박수진이야 소통방이 오래 조용해서 먼저 말 걸어야 해

[규칙]
자연스럽게 먼저 말 걸기
직장인 느낌으로 바쁘다가 잠깐 들어온 느낌
코인 얘기 일상 얘기 다양하게
1~2줄 이내 마침표 금지 카톡 스타일
존댓말 위주

[예시]
점심 먹다가 잠깐 들어왔어요ㅎㅎ 다들 어디 갔어요
오늘 장 되게 조용하네요
회의하다 잠깐 봤는데 BTC 좀 움직이네요
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
            await conn.execute("""
                DELETE FROM chat_logs
                WHERE id IN (
                    SELECT id FROM chat_logs
                    ORDER BY created_at DESC
                    OFFSET 200
                )
            """)
    except Exception as e:
        logger.error(f"저장 오류: {e}")

async def get_member(user_id: int) -> dict:
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM members WHERE user_id = $1", user_id
            )
        return dict(row) if row else {}
    except Exception as e:
        logger.error(f"조회 오류: {e}")
        return {}

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
#  수면/기상 스케줄
# ──────────────────────────────────────────────

async def sleep_wake_scheduler(bot: Bot):
    global is_sleeping
    while True:
        hour = now_kst().hour

        if 23 <= hour or hour == 0:
            if not is_sleeping:
                await asyncio.sleep(random.randint(0, 3600))
                try:
                    msg = random.choice(SUJIN_SLEEP_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = True
                    logger.info("박수진 취침!")
                except Exception as e:
                    logger.error(f"취침 오류: {e}")

        elif 1 <= hour < 8:
            is_sleeping = True

        elif hour == 8:
            if is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    msg = random.choice(SUJIN_WAKE_MESSAGES)
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                    is_sleeping = False
                    logger.info("박수진 기상!")
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

        if silent_minutes >= 60 and not (1 <= hour < 8):
            try:
                response = await get_openai_client().chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": IDLE_SUJIN_PROMPT},
                        {"role": "user", "content": f"소통방이 {silent_minutes}분째 조용해. 자연스럽게 먼저 말 걸어줘"},
                    ],
                    max_tokens=80,
                    temperature=1.0,
                )
                msg = response.choices[0].message.content.strip()
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                last_message_time = now_kst()
                logger.info("박수진 먼저 말 걸기 완료")
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

    # 수면 시간 체크
    hour = now_kst().hour
    if 1 <= hour < 8:
        return

    last_message_time = now_kst()

    user_text = message.text.strip()
    user_name = message.from_user.first_name if message.from_user else "회원"

    await save_member(message.from_user.id, user_name, user_text)
    chat_history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    # 딜레이 10~20초
    await asyncio.sleep(random.uniform(10, 20))

    # 30% 무시
    if random.random() < 0.30:
        return

    try:
        await context.bot.send_chat_action(
            chat_id=message.chat_id,
            action=ChatAction.TYPING
        )
        await asyncio.sleep(random.uniform(1, 3))

        member = get_member(message.from_user.id)
        member_info = ""
        if member:
            if member.get("coins"):
                member_info += f"\n- {user_name}의 관심 코인: {member['coins']}"

        recent_logs = await get_recent_chat_logs(30)
        db_context = "\n".join([f"{r['name']}: {r['message']}" for r in recent_logs])

        system_prompt = SUJIN_PROMPT
        if member_info:
            system_prompt += f"\n\n[{user_name} 정보]{member_info}"
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
        await save_member(0, "박수진", reply_text)

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
    logger.info("🌸 박수진 봇 시작!")
    app = (
        ApplicationBuilder()
        .token(SUJIN_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply)
    )
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
