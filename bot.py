import asyncio
import logging
import os
import io
from datetime import datetime
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont, ImageOps

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8900420211:AAGnvaCXcpp9u4cuQD5paFh554kxg9lzrLA")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://Ismoil18_db_user:yUsS5lkh2JEgBxUp@cluster0.6lisl9o.mongodb.net/photo_bot")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── MongoDB ───────────────────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.get_default_database()
users_col = db["users"]
photos_col = db["photos"]

async def db_get_or_create_user(user_id: int, username: str = None, full_name: str = None):
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "processed_count": 0,
            "joined_at": datetime.utcnow(),
        }
        await users_col.insert_one(user)
    return user

async def db_increment_stats(user_id: int, effect_name: str):
    await users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"processed_count": 1}, "$set": {"last_active": datetime.utcnow()}}
    )
    await photos_col.insert_one({
        "user_id": user_id,
        "effect": effect_name,
        "created_at": datetime.utcnow()
    })

async def db_get_stats(user_id: int):
    user = await users_col.find_one({"user_id": user_id})
    total_users = await users_col.count_documents({})
    user_effects = await photos_col.find({"user_id": user_id}).to_list(length=None)
    effects_count = {}
    for p in user_effects:
        e = p.get("effect", "Noma'lum")
        effects_count[e] = effects_count.get(e, 0) + 1
    return {
        "processed_count": user.get("processed_count", 0) if user else 0,
        "total_users": total_users,
        "effects_breakdown": effects_count
    }

# ─── Bot & Dispatcher ──────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

# FSM States
class ResizeState(StatesGroup):
    waiting_for_size = State()

class WatermarkState(StatesGroup):
    waiting_for_text = State()

# ─── Papkalar ─────────────────────────────────────────────────────────────────
for folder in ["asl_rasmlar", "tayyor_rasmlar", "original_photos", "processed_photos"]:
    os.makedirs(folder, exist_ok=True)

user_last_photo = {}

# ─── RAZMERLAR (Fotoshop standartlari) ────────────────────────────────────────
PHOTO_SIZES = {
    # ── Hujjat / Pasport formatlari (300 DPI) ──
    "🪪 3×4 sm (pasport)":          (354,  472),   # 3×4 sm @ 300dpi
    "🪪 3.5×4.5 sm":                (413,  531),   # 3.5×4.5 sm @ 300dpi
    "🪪 4×6 sm (vizitka)":          (472,  709),   # 4×6 sm @ 300dpi
    "🪪 5×7 sm":                    (591,  827),   # 5×7 sm @ 300dpi
    "🪪 6×9 sm":                    (709, 1063),   # 6×9 sm @ 300dpi
    "🖼 9×12 sm":                   (1063, 1417),  # 9×12 sm @ 300dpi
    "🖼 10×15 sm (foto)":           (1181, 1772),  # 10×15 sm @ 300dpi
    "🖼 13×18 sm":                  (1535, 2126),  # 13×18 sm @ 300dpi
    "🖼 15×21 sm":                  (1772, 2480),  # 15×21 sm @ 300dpi
    "🖼 20×30 sm":                  (2362, 3543),  # 20×30 sm @ 300dpi
    # ── Instagram ──
    "📸 Instagram Post (1:1)":      (1080, 1080),
    "📸 Instagram Story (9:16)":    (1080, 1920),
    "📸 Instagram Landscape (1.91:1)": (1080, 566),
    "📸 Instagram Portrait (4:5)":  (1080, 1350),
    # ── Facebook ──
    "📘 Facebook Cover":            (851,  315),
    "📘 Facebook Post":             (1200, 630),
    "📘 Facebook Profile":          (170,  170),
    # ── YouTube ──
    "▶️ YouTube Thumbnail":         (1280, 720),
    "▶️ YouTube Channel Art":       (2560, 1440),
    # ── LinkedIn ──
    "💼 LinkedIn Banner":           (1584, 396),
    "💼 LinkedIn Post":             (1200, 627),
    # ── Twitter / X ──
    "🐦 Twitter Header":            (1500, 500),
    "🐦 Twitter Post":              (1200, 675),
    # ── Umumiy ──
    "🖨 A4 (300dpi)":               (2480, 3508),
    "🖨 HD (1920×1080)":            (1920, 1080),
    "🖨 4K (3840×2160)":            (3840, 2160),
    "🔳 Kvadrat kichik (512×512)":  (512,  512),
    "🔳 Kvadrat o'rta (800×800)":   (800,  800),
    "🔳 Kvadrat katta (1500×1500)": (1500, 1500),
}

# ─── Klaviaturalar ────────────────────────────────────────────────────────────
def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Rasm haqida"), KeyboardButton(text="📐 Razmer o'zgartirish")],
            [KeyboardButton(text="⬛ Qora-oq"), KeyboardButton(text="🟤 Sepiya")],
            [KeyboardButton(text="🔄 Negativ"), KeyboardButton(text="🌫 Xiralashtirish")],
            [KeyboardButton(text="☀️ Yorqinlik"), KeyboardButton(text="🎨 Kontrast")],
            [KeyboardButton(text="🔃 90° Aylantirish"), KeyboardButton(text="↔️ Gorizontal Flip")],
            [KeyboardButton(text="↕️ Vertikal Flip"), KeyboardButton(text="🔍 Aniqlik")],
            [KeyboardButton(text="🟦 Piksellashtirish"), KeyboardButton(text="🗜 Siqish")],
            [KeyboardButton(text="🖼 Ramka qo'shish"), KeyboardButton(text="💧 Watermark")],
            [KeyboardButton(text="✂️ Markazdan kesish"), KeyboardButton(text="🌈 Rang to'yinishi")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="❓ Yordam")],
        ],
        resize_keyboard=True
    )

def get_size_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i, name in enumerate(PHOTO_SIZES.keys()):
        row.append(InlineKeyboardButton(text=name, callback_data=f"size:{name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ O'z razmerimni kiritish", callback_data="size:custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ─── /start ───────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(message: Message):
    await db_get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name
    )
    await message.answer(
        "📷 *Foto Editing Bot*\n\n"
        "Fotoshop ishchilar uchun professional bot!\n\n"
        "🔹 Rasm yuboring\n"
        "🔹 Kerakli effekt yoki razmer tanlang\n\n"
        "/stats — statistika\n"
        "/help — yordam",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

# ─── /help ────────────────────────────────────────────────────────────────────
@router.message(Command("help"))
@router.message(F.text == "❓ Yordam")
async def cmd_help(message: Message):
    await message.answer(
        "📷 *Yordam*\n\n"
        "1⃣ Rasm yuboring\n"
        "2⃣ Menyudan funksiya tanlang\n\n"
        "*Effektlar:*\n"
        "⬛ Qora-oq | 🟤 Sepiya | 🔄 Negativ\n"
        "🌫 Xiralashtirish | ☀️ Yorqinlik | 🎨 Kontrast\n"
        "🔃 Aylantirish | ↔️ Flip | 🔍 Aniqlik | 🟦 Piksel\n\n"
        "*Fotoshop funksiyalar:*\n"
        "📐 Razmer — Instagram, YouTube, Facebook va boshqa\n"
        "   standart o'lchamlarga o'zgartirish yoki custom razmer\n"
        "🖼 Ramka — chiroyli ramka qo'shish\n"
        "💧 Watermark — matn belgi qo'shish\n"
        "✂️ Kesish — markazdan kvadrat kesish\n"
        "🌈 Rang — to'yinishni oshirish\n"
        "🗜 Siqish — hajmni kamaytirish",
        parse_mode="Markdown"
    )

# ─── /stats ───────────────────────────────────────────────────────────────────
@router.message(Command("stats"))
@router.message(F.text == "📊 Statistika")
async def cmd_stats(message: Message):
    stats = await db_get_stats(message.from_user.id)
    top_effects = sorted(stats["effects_breakdown"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_text = "\n".join([f"   • {e}: {c} marta" for e, c in top_effects]) or "   Hali yo'q"
    await message.answer(
        f"📊 *Statistika*\n\n"
        f"👤 Sizning ishlangan rasmlaringiz: *{stats['processed_count']}*\n"
        f"👥 Jami foydalanuvchilar: *{stats['total_users']}*\n\n"
        f"*Eng ko'p ishlatilgan effektlar:*\n{top_text}",
        parse_mode="Markdown"
    )

# ─── Rasm qabul qilish ────────────────────────────────────────────────────────
@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_last_photo[user_id] = message.photo[-1]

    # Rasmni saqlash
    file = await bot.get_file(message.photo[-1].file_id)
    downloaded = await bot.download_file(file.file_path)
    filename = f"asl_rasmlar/{user_id}_{message.photo[-1].file_id}.jpg"
    with open(filename, "wb") as f:
        f.write(downloaded.getvalue())

    await state.clear()
    await message.answer(
        "✅ Rasm qabul qilindi!\n"
        "Quyidagi menyudan funksiya tanlang 👇",
        reply_markup=get_main_keyboard()
    )

# ─── Effekt qo'llovchi ────────────────────────────────────────────────────────
async def apply_effect(message: Message, effect_name: str, effect_func):
    user_id = message.from_user.id
    photo = user_last_photo.get(user_id)
    if not photo:
        await message.answer("❗ Avval rasm yuboring!")
        return

    status_msg = await message.answer(f"⏳ {effect_name} qo'llanmoqda...")
    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue()))
        processed_image = effect_func(image)

        output_buffer = io.BytesIO()
        processed_image.save(output_buffer, format="JPEG", quality=95)
        output_buffer.seek(0)

        await message.answer_photo(
            BufferedInputFile(output_buffer.getvalue(), filename="processed.jpg"),
            caption=f"✅ *{effect_name}* qo'llandi!",
            parse_mode="Markdown"
        )
        await db_increment_stats(user_id, effect_name)
        await status_msg.delete()
    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Xatolik: {str(e)}")

# ─── Rasm haqida ──────────────────────────────────────────────────────────────
@router.message(F.text == "🖼 Rasm haqida")
async def photo_info(message: Message):
    user_id = message.from_user.id
    photo = user_last_photo.get(user_id)
    if not photo:
        await message.answer("❗ Avval rasm yuboring!")
        return
    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue()))
        size_kb = len(downloaded.getvalue()) // 1024
        await message.answer(
            f"🖼 *Rasm haqida*\n\n"
            f"📐 O'lchami: `{image.width} × {image.height}` px\n"
            f"🎨 Rejim: `{image.mode}`\n"
            f"📦 Hajmi: `{size_kb} KB`\n"
            f"📋 Format: `{image.format or 'JPEG'}`\n"
            f"📊 Nisbat: `{round(image.width/image.height, 2)}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {str(e)}")

# ─── Asosiy effektlar ─────────────────────────────────────────────────────────
@router.message(F.text == "⬛ Qora-oq")
async def bw_photo(message: Message):
    await apply_effect(message, "Qora-oq", lambda img: img.convert("L").convert("RGB"))

@router.message(F.text == "🟤 Sepiya")
async def sepia_photo(message: Message):
    def effect(img):
        img = img.convert("RGB")
        pixels = img.load()
        for i in range(img.width):
            for j in range(img.height):
                r, g, b = pixels[i, j]
                pixels[i, j] = (
                    min(255, int(r * 0.393 + g * 0.769 + b * 0.189)),
                    min(255, int(r * 0.349 + g * 0.686 + b * 0.168)),
                    min(255, int(r * 0.272 + g * 0.534 + b * 0.131)),
                )
        return img
    await apply_effect(message, "Sepiya", effect)

@router.message(F.text == "🔄 Negativ")
async def negative_photo(message: Message):
    def effect(img):
        img = img.convert("RGB")
        pixels = img.load()
        for i in range(img.width):
            for j in range(img.height):
                r, g, b = pixels[i, j]
                pixels[i, j] = (255 - r, 255 - g, 255 - b)
        return img
    await apply_effect(message, "Negativ", effect)

@router.message(F.text == "🌫 Xiralashtirish")
async def blur_photo(message: Message):
    await apply_effect(message, "Xiralashtirish", lambda img: img.filter(ImageFilter.GaussianBlur(radius=5)))

@router.message(F.text == "☀️ Yorqinlik")
async def brightness_photo(message: Message):
    await apply_effect(message, "Yorqinlikni oshirish", lambda img: ImageEnhance.Brightness(img).enhance(1.8))

@router.message(F.text == "🎨 Kontrast")
async def contrast_photo(message: Message):
    await apply_effect(message, "Kontrastni oshirish", lambda img: ImageEnhance.Contrast(img).enhance(2.0))

@router.message(F.text == "🔃 90° Aylantirish")
async def rotate_photo(message: Message):
    await apply_effect(message, "90° Aylantirish", lambda img: img.rotate(-90, expand=True))

@router.message(F.text == "🔍 Aniqlik")
async def sharpen_photo(message: Message):
    await apply_effect(message, "Aniqlik", lambda img: img.filter(ImageFilter.SHARPEN))

@router.message(F.text == "🟦 Piksellashtirish")
async def pixelate_photo(message: Message):
    def effect(img):
        small = img.resize((img.width // 10, img.height // 10), Image.NEAREST)
        return small.resize((img.width, img.height), Image.NEAREST)
    await apply_effect(message, "Piksellashtirish", effect)

# ─── Flip ─────────────────────────────────────────────────────────────────────
@router.message(F.text == "↔️ Gorizontal Flip")
async def flip_h(message: Message):
    await apply_effect(message, "Gorizontal Flip", lambda img: ImageOps.mirror(img))

@router.message(F.text == "↕️ Vertikal Flip")
async def flip_v(message: Message):
    await apply_effect(message, "Vertikal Flip", lambda img: ImageOps.flip(img))

# ─── Rang to'yinishi ──────────────────────────────────────────────────────────
@router.message(F.text == "🌈 Rang to'yinishi")
async def saturation_photo(message: Message):
    await apply_effect(message, "Rang to'yinishi", lambda img: ImageEnhance.Color(img.convert("RGB")).enhance(2.0))

# ─── Ramka ────────────────────────────────────────────────────────────────────
@router.message(F.text == "🖼 Ramka qo'shish")
async def add_frame(message: Message):
    def effect(img):
        img = img.convert("RGB")
        border = max(img.width, img.height) // 25
        framed = ImageOps.expand(img, border=border, fill=(255, 255, 255))
        outer = ImageOps.expand(framed, border=border // 3, fill=(180, 140, 100))
        return outer
    await apply_effect(message, "Ramka", effect)

# ─── Markazdan kesish ─────────────────────────────────────────────────────────
@router.message(F.text == "✂️ Markazdan kesish")
async def center_crop(message: Message):
    def effect(img):
        img = img.convert("RGB")
        side = min(img.width, img.height)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        return img.crop((left, top, left + side, top + side))
    await apply_effect(message, "Markazdan kesish", effect)

# ─── Siqish ───────────────────────────────────────────────────────────────────
@router.message(F.text == "🗜 Siqish")
async def compress_photo(message: Message):
    user_id = message.from_user.id
    photo = user_last_photo.get(user_id)
    if not photo:
        await message.answer("❗ Avval rasm yuboring!")
        return
    status_msg = await message.answer("⏳ Rasm siqilmoqda...")
    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue())).convert("RGB")
        compressed = image.resize((image.width // 2, image.height // 2), Image.LANCZOS)
        out = io.BytesIO()
        compressed.save(out, format="JPEG", quality=40)
        out.seek(0)
        orig_kb = len(downloaded.getvalue()) // 1024
        new_kb = len(out.getvalue()) // 1024
        await message.answer_photo(
            BufferedInputFile(out.getvalue(), filename="compressed.jpg"),
            caption=f"🗜 Siqildi!\n📦 Oldin: {orig_kb} KB\n📉 Hozir: {new_kb} KB"
        )
        await db_increment_stats(user_id, "Siqish")
        await status_msg.delete()
    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Xatolik: {str(e)}")

# ─── Watermark ────────────────────────────────────────────────────────────────
@router.message(F.text == "💧 Watermark")
async def watermark_start(message: Message, state: FSMContext):
    if not user_last_photo.get(message.from_user.id):
        await message.answer("❗ Avval rasm yuboring!")
        return
    await state.set_state(WatermarkState.waiting_for_text)
    await message.answer("✏️ Watermark matni kiriting (masalan: © Mening kompaniyam):")

@router.message(WatermarkState.waiting_for_text)
async def watermark_apply(message: Message, state: FSMContext):
    wm_text = message.text
    await state.clear()

    user_id = message.from_user.id
    photo = user_last_photo.get(user_id)
    if not photo:
        await message.answer("❗ Rasm topilmadi.")
        return

    status_msg = await message.answer("⏳ Watermark qo'shilmoqda...")
    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue())).convert("RGBA")

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font_size = max(image.width, image.height) // 20
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), wm_text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = image.width - tw - image.width // 30
        y = image.height - th - image.height // 30

        draw.text((x + 2, y + 2), wm_text, font=font, fill=(0, 0, 0, 100))
        draw.text((x, y), wm_text, font=font, fill=(255, 255, 255, 180))

        result = Image.alpha_composite(image, overlay).convert("RGB")
        out = io.BytesIO()
        result.save(out, format="JPEG", quality=95)
        out.seek(0)

        await message.answer_photo(
            BufferedInputFile(out.getvalue(), filename="watermarked.jpg"),
            caption=f"💧 Watermark qo'shildi: *{wm_text}*",
            parse_mode="Markdown"
        )
        await db_increment_stats(user_id, "Watermark")
        await status_msg.delete()
    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Xatolik: {str(e)}")

# ─── Razmer o'zgartirish ──────────────────────────────────────────────────────
@router.message(F.text == "📐 Razmer o'zgartirish")
async def resize_menu(message: Message):
    if not user_last_photo.get(message.from_user.id):
        await message.answer("❗ Avval rasm yuboring!")
        return
    await message.answer(
        "📐 *Standart razmerlar*\n\nSosial tarmoq va professional razmerlardan birini tanlang:",
        reply_markup=get_size_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("size:"))
async def size_callback(callback, state: FSMContext):
    size_name = callback.data[5:]
    user_id = callback.from_user.id

    if size_name == "custom":
        await state.set_state(ResizeState.waiting_for_size)
        await callback.message.answer(
            "✏️ O'z razmeringizni kiriting.\n"
            "Format: `kenglik yuksalik`\n"
            "Masalan: `1920 1080`",
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    if size_name not in PHOTO_SIZES:
        await callback.answer("Noma'lum razmer!", show_alert=True)
        return

    target_w, target_h = PHOTO_SIZES[size_name]
    photo = user_last_photo.get(user_id)
    if not photo:
        await callback.answer("Rasm topilmadi!", show_alert=True)
        return

    await callback.answer()
    status_msg = await callback.message.answer(f"⏳ {size_name} razmerga o'zgartirilmoqda...")

    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue())).convert("RGB")

        # Letterbox usuli — nisbatni saqlagan holda to'ldirish
        image.thumbnail((target_w, target_h), Image.LANCZOS)
        background = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        offset = ((target_w - image.width) // 2, (target_h - image.height) // 2)
        background.paste(image, offset)

        out = io.BytesIO()
        background.save(out, format="JPEG", quality=95)
        out.seek(0)

        await callback.message.answer_photo(
            BufferedInputFile(out.getvalue(), filename="resized.jpg"),
            caption=f"📐 *{size_name}*\n✅ `{target_w} × {target_h}` px",
            parse_mode="Markdown"
        )
        await db_increment_stats(user_id, f"Razmer: {size_name}")
        await status_msg.delete()
    except Exception as e:
        await status_msg.delete()
        await callback.message.answer(f"❌ Xatolik: {str(e)}")

@router.message(ResizeState.waiting_for_size)
async def custom_resize(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split()
        if len(parts) != 2:
            raise ValueError
        target_w, target_h = int(parts[0]), int(parts[1])
        if target_w <= 0 or target_h <= 0 or target_w > 10000 or target_h > 10000:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Masalan: `1920 1080`", parse_mode="Markdown")
        return

    await state.clear()
    user_id = message.from_user.id
    photo = user_last_photo.get(user_id)
    if not photo:
        await message.answer("❗ Rasm topilmadi.")
        return

    status_msg = await message.answer(f"⏳ {target_w}×{target_h} razmerga o'zgartirilmoqda...")
    try:
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        image = Image.open(io.BytesIO(downloaded.getvalue())).convert("RGB")
        resized = image.resize((target_w, target_h), Image.LANCZOS)
        out = io.BytesIO()
        resized.save(out, format="JPEG", quality=95)
        out.seek(0)
        await message.answer_photo(
            BufferedInputFile(out.getvalue(), filename="resized.jpg"),
            caption=f"📐 Custom razmer: `{target_w} × {target_h}` px",
            parse_mode="Markdown"
        )
        await db_increment_stats(user_id, f"Custom razmer {target_w}x{target_h}")
        await status_msg.delete()
    except Exception as e:
        await status_msg.delete()
        await message.answer(f"❌ Xatolik: {str(e)}")

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    dp.include_router(router)
    logger.info("Bot ishga tushmoqda...")
    try:
        await db_get_or_create_user(0, "system", "System check")
        logger.info("✅ MongoDB ulanishi muvaffaqiyatli!")
    except Exception as e:
        logger.error(f"❌ MongoDB xatosi: {e}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())