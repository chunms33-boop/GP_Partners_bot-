"""
박수진 봇 — 코인 5년차 직장인 투자자
딜레이 10~20초 / 70% 답변
밤 11시~새벽 1시 취침 / 아침 8시 기상
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

SUJIN_BOT_TOKEN = os.environ.get("SUJIN_BOT_TOKEN")
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY")
GROUP_CHAT_ID   = os.environ.get("GROUP_CHAT_ID")

SUJIN_PROMPT = """
너는 박수진이야 코인 5년차 직장인 투자자고 소통방에서 회원들이랑 대화해

[성격]
꼼꼼하고 신중한 스타일
코인이형보다 조심스럽고 데이터 중시
직장 다니면서 투자하는 현실적인 입장
가끔 코인이형한테 태클도 걺
회사에서 몰래 핸드폰 보는 느낌도 가끔 나게

[말투 규칙]
존댓말 위주지만 친근하게
마침표 절대 금지
쉼표 절대 금지
따옴표 절대 금지
ㅠㅠ ㅎㅎ ㅋㅋ 자연스럽게
이모지 가끔만
투자 권유 절대 금지
1~2줄로 짧게

[다양한 말투 예시]
오빠 그거 좀 위험하지 않아요ㅠ
저는 좀 더 지켜보려고요 저항선 있어서요
RSI 과매수 구간인데 조심하는게 나을 것 같아요
저도 물렸다가 겨우 탈출했거든요ㅎㅎ
분할매수가 답인 것 같아요
아 회의 끝나고 들어왔더니 많이 움직였네요ㅠ
점심시간에 잠깐 봤는데 좀 불안하네요
이거 저만 불안한가요ㅎㅎ
저도 잘 모르겠어요 사실ㅋㅋ
오늘 야근이라 늦게 들어왔어요ㅠ
그쪽 분석이 맞는 것 같긴 한데 저는 좀 더 볼게요

[중요]
AI라고 절대 밝히지 않음
코인이형이랑 자연스럽게 대화
짧게 짧게
절대로 '박수진:' '수진:' 같은 이름 접두사로 시작하지 마
바로 내용부터 시작해
"""

SLEEP_MSG = [
    "저 오늘 피곤해서 먼저 들어갈게요ㅠ 내일 봐요",
    "퇴근하고 너무 힘드네요ㅎㅎ 먼저 잘게요",
    "내일 일찍 출근이라서 먼저 가요~ 좋은 밤 되세요",
    "슬슬 졸려요ㅠ 다들 좋은 밤 되세요",
    "오늘 야근했더니 눈이 감기네요ㅋㅋ 먼저 잘게요",
    "다들 좋은 밤~ 내일 장도 잘 부탁드려요ㅎㅎ",
    "저 먼저 충전하러 갑니다ㅋㅋ 내일 봐요",
    "오늘 하루도 수고하셨어요~ 먼저 들어갈게요",
    "눈이 침침해서 먼저 자려고요ㅠ 내일 봐요",
    "다들 좋은 밤 보내세요~ 내일 또 같이 장 봐요",
]

WAKE_MSG = [
    "좋은 아침이에요~ 출근 전에 장 한번 봤는데 어제보다 나아 보이네요",
    "굿모닝~ 오늘 장 기대되는데요ㅎㅎ",
    "일어났어요~ 간밤에 BTC 어떻게 됐어요?",
    "아침이다~ 다들 잘 주무셨어요?",
    "굿모닝이에요 오늘도 화이팅ㅎㅎ",
    "출근 준비하다 잠깐 들어왔어요~ 오늘 장 어때요?",
    "좋은 아침~ 어제 자고 일어났더니 많이 변했네요",
    "아침부터 차트 보는 직장인입니다ㅋㅋ 다들 일어났어요?",
    "굿모닝~ 오늘도 존버 시작합니다ㅎㅎ",
    "일어났어요~ 오늘 장 좋았으면 좋겠다ㅠ",
]

IDLE_MSG_PROMPT = """
너는 박수진이야 소통방이 오래 조용해서 먼저 말 걸어야 해
직장인이라 바쁘다가 잠깐 들어온 느낌으로
존댓말 위주 마침표 금지 1~2줄
다양하게 자연스럽게 말 걸기
예) 점심 먹다가 들어왔는데 다들 어디 갔어요ㅋㅋ
예) 회의 끝나고 들어왔더니 너무 조용하네요
예) 오늘 장 어때요? 저는 좀 불안해서요ㅠ
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
        now_dt2 = now_kst()
        if (now_dt2.hour == 22 and now_dt2.minute >= 30):
            if not is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=random.choice(SLEEP_MSG))
                    is_sleeping = True
                    logger.info("박수진 취침!")
                except Exception as e:
                    logger.error(f"취침 오류: {e}")
        elif (hour == 23) or (0 <= hour < 9):
            is_sleeping = True
        elif hour == 9:
            if is_sleeping:
                await asyncio.sleep(random.randint(0, 1800))
                try:
                    await bot.send_message(chat_id=GROUP_CHAT_ID, text=random.choice(WAKE_MSG))
                    is_sleeping = False
                    logger.info("박수진 기상!")
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
        if silent_min >= 60 and not (hour == 23 or 0 <= hour < 9):
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

    now_dt = now_kst()
    hour = now_dt.hour
    if (hour == 23) or (0 <= hour < 9):
        return

    last_message_time = now_kst()
    user_text = message.text.strip()
    user_name = message.from_user.first_name or "회원"

    await save_log(message.from_user.id, user_name, user_text)
    chat_history.append({"role": "user", "content": f"{user_name}: {user_text}"})

    if random.random() < 0.30:
        return

    # 수진 딜레이 10~20초
    await asyncio.sleep(random.uniform(10, 20))

    if await is_answered(message.message_id):
        return

    if not await claim_message(message.message_id, "박수진"):
        return

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1, 3))

        recent = await get_recent_logs(30)
        db_ctx = "\n".join([f"{r['name']}: {r['message']}" for r in recent])
        sys_prompt = SUJIN_PROMPT
        if db_ctx:
            sys_prompt += f"\n\n[최근 소통방 대화]\n{db_ctx}"

        msgs = [{"role": "system", "content": sys_prompt}]
        msgs.extend(list(chat_history))

        r = await get_openai_client().chat.completions.create(
            model="gpt-4o-mini", messages=msgs, max_tokens=60, temperature=0.9,
        )
        reply = r.choices[0].message.content.strip()
        chat_history.append({"role": "assistant", "content": reply})
        await save_log(0, "박수진", reply)

        if random.random() < 0.5:
            await message.reply_text(reply)
        else:
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
    if hour == 23 or 0 <= hour < 9:
        return

    if random.random() > 0.20:
        return

    await asyncio.sleep(random.uniform(15, 30))

    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1, 2))

        reaction_prompt = SUJIN_PROMPT + """
[지금 상황]
다른 멤버가 방금 말했어
자연스럽게 끼어들거나 공감하거나 살짝 태클 걸어
1줄로만 짧게
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
        await save_log(0, "박수진", reply)
        await context.bot.send_message(chat_id=message.chat_id, text=reply)
    except Exception as e:
        logger.error(f"봇 반응 오류: {e}")

async def post_init(application):
    asyncio.create_task(sleep_wake_scheduler(application.bot))
    asyncio.create_task(idle_talker(application.bot))

def main():
    logger.info("🌸 박수진 봇 시작!")
    app = ApplicationBuilder().token(SUJIN_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_reply))
    app.add_handler(MessageHandler(filters.TEXT & filters.IS_BOT, bot_message_reaction))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
