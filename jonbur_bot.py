"""
존버킴 봇 — 맨날 물리는 개미 투자자 (음슴체)
딜레이 25~30초 / 50% 답변
새벽 1시~오전 10시 취침
"""

import os, asyncio, logging, random, asyncpg
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from openai import AsyncOpenAI
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from telegram.constants import ChatAction

KST = ZoneInfo('Asia/Seoul')
def now_kst():
    return datetime.now(KST)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

JONGBUR_BOT_TOKEN = os.environ.get("JONGBUR_BOT_TOKEN")
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY")
GROUP_CHAT_ID     = os.environ.get("GROUP_CHAT_ID")

JONGBUR_PROMPT = """
너는 존버킴이야 코인하다가 맨날 물리는 개미 투자자고 소통방에서 자학개그로 분위기 띄워

[성격]
맨날 고점에 사서 손절하는 불운의 투자자
자학개그로 회원들 웃겨주는 역할
그래도 포기 안하고 계속 코인 함
코인이형이랑 수진이한테 가끔 조언 구함
멘탈이 자주 나가있는 상태

[말투 규칙 - 매우 중요]
무조건 음슴체로 말해야 함 (~임 ~함 ~됨 ~임ㅋㅋ)
반말 금지
마침표 금지
쉼표 금지
따옴표 금지
ㅋㅋ ㅠㅠ 많이 써도 됨
자학개그 자연스럽게
투자 권유 절대 금지
1~2줄로 짧게

[다양한 말투 예시]
나도 거기서 샀다가 손절한 경험 있음ㅋㅋ
또 물린 것 같음ㅠ 이번엔 진짜 존버할 생각임
왜 내가 사면 떨어지는지 모르겠음ㅋㅋ
코인이형 말 들을걸 그랬음ㅠ
이번엔 수익 날 수 있을 것 같음
심리적 저항선이 뭔지 몸으로 배우는 중임ㅋㅋ
나만 이런 거 아닌 것 같아서 위안이 됨ㅎㅎ
존버가 답인 것 같기도 하고 아닌 것 같기도 함ㅋㅋ
오늘도 마이너스 확정임ㅠ
손절 누르는 속도는 세계 최고 수준임ㅋㅋ
비트 오를 때 내 코인만 안 오르는 상황임ㅋㅋ
분산투자 했는데 전부 다 떨어짐ㅠ

[중요]
AI라고 절대 밝히지 않음
코인이형 수진이랑 자연스럽게 대화
음슴체 꼭 지키기
짧게 짧게
절대로 '존버킴:' '존버 킴:' 같은 이름 접두사로 시작하지 마
바로 내용부터 시작해
"""

SLEEP_MSG = [
    "오늘도 손실 확정하고 자는 중임ㅋㅋ 다들 좋은 밤",
    "물린 채로 자야 하는 상황임ㅠ 내일 봐요",
    "멘탈 충전하러 가는 중임ㅋㅋ 잘 자요",
    "오늘 하루도 존버 완료임ㅎㅎ 내일 봐요",
    "내일은 오를 거라 믿으면서 자는 중임ㅋㅋ",
    "오늘도 수고하셨음ㅎㅎ 먼저 감",
    "눈이 저절로 감기는 중임ㅠ 내일 봐요",
    "다들 좋은 밤~ 내일 제발 올라있길 바라는 중임ㅋㅋ",
    "정신적 충격으로 먼저 자는 중임ㅋㅋ 잘 자요",
    "오늘 차트 보다가 현타 와서 자러 감ㅠ",
]

WAKE_MSG = [
    "일어났음ㅋㅋ 밤새 얼마나 됐는지 무서워서 못 봄",
    "기상~ 오늘은 제발 오르길 바라는 중임ㅠ",
    "굿모닝~ 어제 자고 일어났더니 또 떨어져 있는 상황임ㅋㅋ",
    "일어났음 오늘도 존버 시작임ㅎㅎ",
    "기상~ 간밤에 BTC 어떻게 됐는지 무서운 중임ㅋㅋ",
    "굿모닝~ 오늘은 수익 낼 수 있을 것 같은 예감임ㅎㅎ",
    "일어났음ㅠ 오늘도 화이팅해야 할 것 같음",
    "아침부터 차트 확인하는 중임ㅋㅋ 다들 일어났음?",
    "기상~ 오늘 장 좋을 것 같은 느낌적인 느낌임ㅎㅎ",
    "굿모닝~ 어제 손절한 거 잊고 새출발하는 중임ㅋㅋ",
]

IDLE_MSG_PROMPT = """
너는 존버킴이야 소통방이 오래 조용해서 먼저 말 걸어야 해
음슴체로 (~임 ~함) 자연스럽게
반말 금지 마침표 금지 1~2줄
자학개그 섞어서

예) 다들 어디 갔임ㅋㅋ 나만 물려있는 중임
예) 너무 조용한 것 같음ㅋㅋ
예) 심심한 중임ㅎㅎ BTC나 보는 중
"""

_db_pool = None

async def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = await asyncpg.create_pool(os.environ.get("DATABASE_URL"), ssl="require")
    return _db_pool



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
    except:
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
    except Exception as e:
        logger.error(f"answered 오류: {e}")

async def save_log(user_id: int, name: str, message: str):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO members (user_id, name, last_seen)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id) DO UPDATE SET name=EXCLUDED.name, last_seen=NOW()
            """, user_id, name)
            await conn.execute("INSERT INTO chat_logs (user_id, name, message) VALUES ($1, $2, $3)", user_id, name, message)
    except Exception as e:
        logger.error(f"DB 오류: {e}")

async def get_recent_logs(limit=30):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, message FROM (
                    SELECT name, message, created_at FROM chat_logs
                    ORDER BY created_at DESC LIMIT $1
                ) sub ORDER BY created_at ASC
            """, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"로그 조회 오류: {e}")
        return []

def get_openai_client():
    return AsyncOpenAI(api_key=OPENAI_API_KEY)

chat_history = deque(maxlen=100)
last_message_time = now_kst()
is_sleeping = False

async def sleep_wake_scheduler(bot: Bot):
    global is_sleeping
    while True:
        hour = now_kst().hour
        if hour == 0:
            if not is_sleeping:
                await asyncio.sleep(random.randint(0, 3600))
                try:
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=random.choice(SLEEP_MSG))
                    is_sleeping = True
                    logger.info("존버킴 취침!")
                except Exception as e:
                    logger.error(f"취침 오류: {e}")
        elif 1 <= hour < 10:
            is_sleeping = True
        elif hour == 10:
            if is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=random.choice(WAKE_MSG))
                    is_sleeping = False
                    logger.info("존버킴 기상!")
                except Exception as e:
                    logger.error(f"기상 오류: {e}")
        else:
            is_sleeping = False
        await asyncio.sleep(600)

async def idle_talker(bot: Bot):
    global last_message_time
    await asyncio.sleep(60)
    while True:
        await asyncio.sleep(30 * 60)
        silent_min = (now_kst() - last_message_time).seconds // 60
        hour = now_kst().hour
        if silent_min >= 60 and not (1 <= hour < 10):
            try:
                r = await get_openai_client().chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": IDLE_MSG_PROMPT},
                        {"role": "user", "content": f"소통방이 {silent_min}분째 조용해. 자연스럽게 먼저 말 걸어줘"},
                    ],
                    max_tokens=80, temperature=1.0,
                )
                msg = r.choices[0].message.content.strip()
                await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg)
                last_message_time = now_kst()
            except Exception as e:
                logger.error(f"idle 오류: {e}")

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

    hour = now_kst().hour
    if 1 <= hour < 10:
        return

    last_message_time = now_kst()
    user_text = message.text.strip()
    user_name = message.from_user.first_name or "회원"

    await save_log(message.from_user.id, user_name, user_text)
    chat_history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    if random.random() < 0.50:
        return

    # 존버킴 딜레이 25~35초 (가장 늦게)
    await asyncio.sleep(random.uniform(25, 35))

    if await is_answered(message.message_id):
        return

    if not await claim_message(message.message_id, "존버킴"):
        return

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1, 3))

        recent = await get_recent_logs(30)
        db_ctx = "\n".join([f"{r['name']}: {r['message']}" for r in recent])
        sys_prompt = JONGBUR_PROMPT
        if db_ctx:
            sys_prompt += f"\n\n[최근 소통방 대화]\n{db_ctx}"

        msgs = [{"role": "system", "content": sys_prompt}]
        msgs.extend(list(chat_history))

        r = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini", messages=msgs, max_tokens=100, temperature=0.9,
        )
        reply = r.choices[0].message.content.strip()
        chat_history.append({"role": "assistant", "content": reply})
        await save_log(0, "존버킴", reply)

        await context.bot.send_message(chat_id=message.chat_id, text=reply)

    except Exception as e:
        logger.error(f"AI 오류: {e}")


async def bot_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """다른 봇 말에 가끔 끼어들기"""
    message = update.message
    if not message or not message.text:
        return
    if str(message.chat_id) != str(GROUP_CHAT_ID):
        return
    if not message.from_user or not message.from_user.is_bot:
        return
    if message.from_user.id == context.bot.id:
        return

    hour = now_kst().hour
    if 1 <= hour < 10:
        return

    if random.random() > 0.20:
        return

    await asyncio.sleep(random.uniform(20, 35))

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1, 2))

        reaction_prompt = JONGBUR_PROMPT + """
[지금 상황]
다른 멤버가 방금 말했어
자연스럽게 끼어들거나 공감하거나 자학개그 해
음슴체로 1줄만 짧게
"""
        r = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": reaction_prompt},
                {"role": "user", "content": f"방금 이런 말이 나왔어: {message.text}"},
            ],
            max_tokens=80, temperature=0.95,
        )
        reply = r.choices[0].message.content.strip()
        await save_log(0, "존버킴", reply)
        await context.bot.send_message(chat_id=message.chat_id, text=reply)
    except Exception as e:
        logger.error(f"봇 반응 오류: {e}")

async def post_init(application):
    asyncio.create_task(sleep_wake_scheduler(application.bot))
    asyncio.create_task(idle_talker(application.bot))

def main():
    logger.info("💸 존버킴 봇 시작!")
    app = ApplicationBuilder().token(JONGBUR_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))
    app.add_handler(MessageHandler(filters.TEXT & filters.IS_BOT, bot_message_reaction))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
