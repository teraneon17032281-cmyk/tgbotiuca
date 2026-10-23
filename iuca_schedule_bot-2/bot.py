import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# =====================================================================
# НАСТРОЙКИ
# =====================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

SCHEDULE_FILE = Path(__file__).parent / "schedule.json"
USERS_FILE = Path(__file__).parent / "users.json"

# Часовой пояс Кыргызстана (UTC+6)
KG_TZ = timezone(timedelta(hours=6))

DAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]

TIME_SLOTS = [
    "8:00 - 9:20",
    "9:30 - 10:50",
    "11:05 - 12:25",
    "13:10 - 14:30",
    "14:45 - 16:05",
    "16:20 - 17:40",
]

# =====================================================================
# ЗАГРУЗКА ДАННЫХ
# =====================================================================
with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
    SCHEDULE = json.load(f)

FACULTIES = sorted({fac for item in SCHEDULE for fac in item["f"]})
GROUPS = sorted({g for item in SCHEDULE for g in item["g"]})
TEACHERS = sorted({e for item in SCHEDULE for e in item["e"]})

VIRTUAL_ROOMS = {"Online", "Outside IUCA", "DSK"}
PHYSICAL_ROOMS = sorted({r for item in SCHEDULE for r in item["r"] if r and r not in VIRTUAL_ROOMS})
ALL_ROOMS = sorted({r for item in SCHEDULE for r in item["r"] if r})


def load_users() -> dict:
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_user_group(user_id: int, group: str):
    users = load_users()
    users[str(user_id)] = group
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user_group(user_id: int) -> str | None:
    return load_users().get(str(user_id))


# =====================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================
def parse_slot_minutes(slot: str) -> tuple[int, int]:
    start_s, end_s = [p.strip() for p in slot.split("-")]
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    return sh * 60 + sm, eh * 60 + em


def get_current_or_next_slot() -> tuple[int, str, str]:
    now = datetime.now(KG_TZ)
    day_idx = now.weekday()
    cur_mins = now.hour * 60 + now.minute

    if day_idx > 5:
        return 0, TIME_SLOTS[1], "Впереди понедельник"

    for slot in TIME_SLOTS:
        start_m, end_m = parse_slot_minutes(slot)
        if start_m <= cur_mins <= end_m:
            return day_idx, slot, "Сейчас идет пара"
        if cur_mins < start_m:
            return day_idx, slot, "Ближайшая пара"

    next_day = 0 if day_idx >= 5 else day_idx + 1
    return next_day, TIME_SLOTS[1], f"Пары на сегодня закончились ({DAYS_SHORT[next_day]})"


def format_group_day(group: str, day_idx: int) -> str:
    if day_idx > 5:
        return f"🎉 <b>Воскресенье</b> — выходной день!"

    items = [x for x in SCHEDULE if x["d"] == day_idx and group in x["g"]]
    items.sort(key=lambda x: parse_slot_minutes(x["t"])[0])

    header = f"📅 <b>{DAYS_RU[day_idx]}</b> | Группа: <b>{group}</b>\n"
    if not items:
        return header + "\n😴 В этот день пар нет!"

    lines = [header]
    for idx, item in enumerate(items, 1):
        rooms = ", ".join(item["r"]) if item["r"] else "Не указана"
        teachers = ", ".join(item["e"]) if item["e"] else "—"
        lines.append(
            f"<b>{idx}. ⏰ {item['t']}</b>\n"
            f"📚 {item['s']}\n"
            f"🚪 Ауд.: <code>{rooms}</code>\n"
            f"👤 Преп.: {teachers}"
        )
    return "\n\n".join(lines)


def get_free_rooms(day_idx: int, slot: str) -> tuple[list[str], list[str]]:
    busy = set()
    for item in SCHEDULE:
        if item["d"] == day_idx and item["t"] == slot:
            for r in item["r"]:
                if r in PHYSICAL_ROOMS:
                    busy.add(r)
    free = [r for r in PHYSICAL_ROOMS if r not in busy]
    return free, sorted(busy)


# =====================================================================
# НИЖНЯЯ КЛАВИАТУРА ИНТЕРФЕЙСА (REPLY KEYBOARD)
# =====================================================================
def main_menu_kb(user_group: str | None = None) -> ReplyKeyboardMarkup:
    grp_label = f"🎓 Группа: {user_group}" if user_group else "🎓 Выбрать группу"
    kb = [
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
        [KeyboardButton(text="🗓 Расписание по дням"), KeyboardButton(text="🟢 Свободные кабинеты")],
        [KeyboardButton(text="👨‍🏫 Поиск преподавателя"), KeyboardButton(text="🚪 Расписание кабинета")],
        [KeyboardButton(text=grp_label)],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, persistent=True)


def faculties_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for fac in FACULTIES:
        builder.button(text=fac, callback_data=f"fac:{fac}")
    builder.adjust(4)
    return builder.as_markup()


def groups_by_fac_kb(fac: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fac_groups = sorted({g for item in SCHEDULE if fac in item["f"] for g in item["g"] if g.startswith(fac)})
    if not fac_groups:
        fac_groups = sorted({g for item in SCHEDULE if fac in item["f"] for g in item["g"]})
    for g in fac_groups:
        builder.button(text=g, callback_data=f"setgrp:{g}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="⬅️ Назад к факультетам", callback_data="back_facs"))
    return builder.as_markup()


def days_inline_kb(group: str, active_day: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d_idx, short_name in enumerate(DAYS_SHORT):
        text = f"• {short_name} •" if d_idx == active_day else short_name
        builder.button(text=text, callback_data=f"day:{group}:{d_idx}")
    builder.adjust(6)
    builder.row(InlineKeyboardButton(text="📋 Вся неделя целиком", callback_data=f"week:{group}"))
    return builder.as_markup()


def free_rooms_kb(day_idx: int, active_slot_idx: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d_i, short_name in enumerate(DAYS_SHORT):
        mark = f"✅ {short_name}" if d_i == day_idx else short_name
        builder.button(text=mark, callback_data=f"free:{d_i}:{active_slot_idx}")
    builder.adjust(6)

    time_builder = InlineKeyboardBuilder()
    for s_i, slot in enumerate(TIME_SLOTS):
        mark = f"🕒 {slot}" if s_i == active_slot_idx else slot
        time_builder.button(text=mark, callback_data=f"free:{day_idx}:{s_i}")
    time_builder.adjust(2)

    builder.attach(time_builder)
    return builder.as_markup()


class SearchState(StatesGroup):
    waiting_teacher = State()
    waiting_room = State()


router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    grp = get_user_group(message.from_user.id)
    text = (
        "👋 <b>Добро пожаловать в расписание IUCA!</b>\n\n"
        "Используйте кнопки навигации внизу экрана 👇"
    )
    await message.answer(text, reply_markup=main_menu_kb(grp), parse_mode="HTML")
    if not grp:
        await message.answer("👇 Сначала выберите своё направление:", reply_markup=faculties_kb())


@router.message(F.text.startswith("🎓"))
async def choose_group_msg(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("👇 Выберите своё направление (департамент):", reply_markup=faculties_kb())


@router.callback_query(F.data == "back_facs")
async def cb_back_facs(call: CallbackQuery):
    await call.message.edit_text("👇 Выберите своё направление (департамент):", reply_markup=faculties_kb())
    await call.answer()


@router.callback_query(F.data.startswith("fac:"))
async def cb_select_fac(call: CallbackQuery):
    fac = call.data.split(":")[1]
    await call.message.edit_text(
        f"Направление <b>{fac}</b>. Выберите группу:",
        reply_markup=groups_by_fac_kb(fac),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("setgrp:"))
async def cb_set_group(call: CallbackQuery):
    grp = call.data.split(":")[1]
    save_user_group(call.from_user.id, grp)
    now_day = datetime.now(KG_TZ).weekday()
    show_day = 0 if now_day > 5 else now_day

    await call.message.edit_text(
        f"✅ Группа <b>{grp}</b> успешно сохранена!",
        parse_mode="HTML",
    )
    await call.message.answer(
        format_group_day(grp, show_day),
        reply_markup=days_inline_kb(grp, show_day),
        parse_mode="HTML",
    )
    await call.message.answer("Меню обновлено 👇", reply_markup=main_menu_kb(grp))
    await call.answer(f"Выбрана группа {grp}")


@router.message(F.text.in_({"📅 Сегодня", "📆 Завтра"}))
async def show_today_tomorrow(message: Message, state: FSMContext):
    await state.clear()
    grp = get_user_group(message.from_user.id)
    if not grp:
        await message.answer("Сначала выберите свою группу кнопкой в меню 👇", reply_markup=main_menu_kb(None))
        await message.answer("👇 Выберите направление:", reply_markup=faculties_kb())
        return

    now_day = datetime.now(KG_TZ).weekday()
    target_day = now_day if message.text == "📅 Сегодня" else (now_day + 1) % 7
    day_for_kb = 0 if target_day > 5 else target_day

    await message.answer(
        format_group_day(grp, target_day),
        reply_markup=days_inline_kb(grp, day_for_kb),
        parse_mode="HTML",
    )


@router.message(F.text == "🗓 Расписание по дням")
async def show_by_days(message: Message, state: FSMContext):
    await state.clear()
    grp = get_user_group(message.from_user.id)
    if not grp:
        await message.answer("Сначала выберите свою группу кнопкой в меню 👇", reply_markup=main_menu_kb(None))
        await message.answer("👇 Выберите направление:", reply_markup=faculties_kb())
        return

    now_day = datetime.now(KG_TZ).weekday()
    show_day = 0 if now_day > 5 else now_day
    await message.answer(
        format_group_day(grp, show_day),
        reply_markup=days_inline_kb(grp, show_day),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("day:"))
async def cb_switch_day(call: CallbackQuery):
    _, grp, d_str = call.data.split(":")
    d_idx = int(d_str)
    text = format_group_day(grp, d_idx)
    try:
        await call.message.edit_text(text, reply_markup=days_inline_kb(grp, d_idx), parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("week:"))
async def cb_full_week(call: CallbackQuery):
    _, grp = call.data.split(":")
    blocks = []
    for d_idx in range(6):
        items = [x for x in SCHEDULE if x["d"] == d_idx and grp in x["g"]]
        if not items:
            continue
        items.sort(key=lambda x: parse_slot_minutes(x["t"])[0])
        day_lines = [f"📌 <b>{DAYS_RU[d_idx].upper()}</b>"]
        for item in items:
            rooms = ", ".join(item["r"]) if item["r"] else "—"
            day_lines.append(f"• <code>{item['t']}</code> — {item['s']} (<b>{rooms}</b>)")
        blocks.append("\n".join(day_lines))

    full_text = f"🗓 <b>Расписание на всю неделю | {grp}</b>\n\n" + "\n\n".join(blocks)
    try:
        await call.message.edit_text(full_text, reply_markup=days_inline_kb(grp, -1), parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


def render_free_rooms_text(day_idx: int, slot_idx: int, status_note: str = "") -> str:
    slot = TIME_SLOTS[slot_idx]
    free, busy = get_free_rooms(day_idx, slot)
    free_A = [r for r in free if r.startswith("A") or r.startswith("(A)")]
    free_B = [r for r in free if r.startswith("B")]

    note_line = f"ℹ️ <i>{status_note}</i>\n" if status_note else ""
    return (
        f"🟢 <b>Свободные аудитории</b>\n"
        f"{note_line}"
        f"📅 День: <b>{DAYS_RU[day_idx]}</b>\n"
        f"⏰ Время: <b>{slot}</b>\n\n"
        f"🏢 <b>Корпус A ({len(free_A)} своб.):</b>\n"
        f"<code>{', '.join(free_A) if free_A else 'Нет свободных'}</code>\n\n"
        f"🏢 <b>Корпус B ({len(free_B)} своб.):</b>\n"
        f"<code>{', '.join(free_B) if free_B else 'Нет свободных'}</code>\n\n"
        f"🔴 Занято аудиторий: <b>{len(busy)}</b> из {len(PHYSICAL_ROOMS)}"
    )


@router.message(F.text == "🟢 Свободные кабинеты")
async def msg_free_rooms(message: Message, state: FSMContext):
    await state.clear()
    d_idx, slot, status = get_current_or_next_slot()
    slot_idx = TIME_SLOTS.index(slot)
    text = render_free_rooms_text(d_idx, slot_idx, status)
    await message.answer(text, reply_markup=free_rooms_kb(d_idx, slot_idx), parse_mode="HTML")


@router.callback_query(F.data.startswith("free:"))
async def cb_free_rooms(call: CallbackQuery):
    _, d_str, s_str = call.data.split(":")
    d_idx, s_idx = int(d_str), int(s_str)
    text = render_free_rooms_text(d_idx, s_idx)
    try:
        await call.message.edit_text(text, reply_markup=free_rooms_kb(d_idx, s_idx), parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@router.message(F.text == "👨‍🏫 Поиск преподавателя")
async def start_teacher_search(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_teacher)
    await message.answer(
        "🔍 Введите фамилию преподавателя (например: <code>Veis</code>, <code>Kim</code>, <code>Tarasov</code>, <code>Kabak</code>):",
        parse_mode="HTML",
    )


@router.message(SearchState.waiting_teacher)
async def process_teacher_search(message: Message, state: FSMContext):
    query = message.text.strip().lower()
    matched = [t for t in TEACHERS if query in t.lower()]

    if not matched:
        await message.answer("❌ Преподаватель не найден. Попробуйте ввести часть фамилии на латинице (например, <code>Kim</code>):", parse_mode="HTML")
        return

    await state.clear()
    if len(matched) == 1:
        await send_teacher_schedule(message, matched[0])
    else:
        builder = InlineKeyboardBuilder()
        for t in matched[:15]:
            builder.button(text=t, callback_data=f"tchr:{t}")
        builder.adjust(2)
        await message.answer("Найдено несколько преподавателей, выберите нужного:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("tchr:"))
async def cb_teacher_schedule(call: CallbackQuery):
    t_name = call.data.split(":", 1)[1]
    await send_teacher_schedule(call.message, t_name, edit=True)
    await call.answer()


async def send_teacher_schedule(message: Message, teacher: str, edit: bool = False):
    blocks = []
    for d_idx in range(6):
        items = [x for x in SCHEDULE if x["d"] == d_idx and teacher in x["e"]]
        if not items:
            continue
        items.sort(key=lambda x: parse_slot_minutes(x["t"])[0])
        lines = [f"📌 <b>{DAYS_RU[d_idx]}</b>"]
        for it in items:
            rooms = ", ".join(it["r"]) if it["r"] else "—"
            grps = ", ".join(it["g"])
            lines.append(f"• <code>{it['t']}</code> | {it['s']} | Ауд: <b>{rooms}</b> ({grps})")
        blocks.append("\n".join(lines))

    text = f"👨‍🏫 <b>Преподаватель: {teacher}</b>\n\n" + ("\n\n".join(blocks) if blocks else "Пар не найдено.")
    if edit:
        await message.edit_text(text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🚪 Расписание кабинета")
async def start_room_search(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_room)
    builder = InlineKeyboardBuilder()
    for r in PHYSICAL_ROOMS[:18]:
        builder.button(text=r, callback_data=f"rm:{r}")
    builder.adjust(4)
    await message.answer(
        "🚪 Напишите номер аудитории (например: <code>B106</code>, <code>A108</code>, <code>Cyber Lab</code>) или выберите из списка:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.message(SearchState.waiting_room)
async def process_room_search(message: Message, state: FSMContext):
    query = message.text.strip().lower()
    matched = [r for r in ALL_ROOMS if query in r.lower()]

    if not matched:
        await message.answer("❌ Аудитория не найдена. Попробуйте еще раз (например, <code>B201</code> или <code>A314</code>):", parse_mode="HTML")
        return

    await state.clear()
    await send_room_schedule(message, matched[0])


@router.callback_query(F.data.startswith("rm:"))
async def cb_room_schedule(call: CallbackQuery, state: FSMContext):
    await state.clear()
    room = call.data.split(":", 1)[1]
    await send_room_schedule(call.message, room, edit=True)
    await call.answer()


async def send_room_schedule(message: Message, room: str, edit: bool = False):
    blocks = []
    for d_idx in range(6):
        items = [x for x in SCHEDULE if x["d"] == d_idx and room in x["r"]]
        if not items:
            continue
        items.sort(key=lambda x: parse_slot_minutes(x["t"])[0])
        lines = [f"📌 <b>{DAYS_RU[d_idx]}</b>"]
        for it in items:
            grps = ", ".join(it["g"])
            teachers = ", ".join(it["e"])
            lines.append(f"• <code>{it['t']}</code> — {it['s']} ({grps}, {teachers})")
        blocks.append("\n".join(lines))

    text = f"🚪 <b>Расписание аудитории: {room}</b>\n\n" + ("\n\n".join(blocks) if blocks else "В этой аудитории нет пар.")
    if edit:
        await message.edit_text(text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("🚀 Бот расписания IUCA запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
