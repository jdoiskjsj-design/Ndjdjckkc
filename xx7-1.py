# -*- coding: utf-8 -*-
"""
صانع بوتات الميوزك
==================
بوت واحد (الصانع) ينشئ لكل مستخدم بوت ميوزك خاصًا به: يضع المستخدم توكن بوته ويسجّل حسابًا مساعدًا
(Telethon + PyTgCalls) فيشغّل البوت الأغاني والفيديو في المحادثات المرئية.

- لوحة المطور (داخل بوت الصانع): كل البوتات، الحقوق، قناة السورس، الاشتراك الإجباري، محرك الموسيقى...
- لوحة المالك (داخل بوت كل مستخدم): الحساب المساعد، الإعدادات، الحقوق، المجموعات، الإحصائيات...
- لا يحتاج اشتراكًا مدفوعًا.

التشغيل:   python music_maker.py
التحديث:   python music_maker.py --upgrade   (يحدّث المكتبات)

ضع توكن بوت الصانع في BOT_TOKEN (بوت جديد من BotFather، وليس توكن بوت المراقبة،
لأن تيليجرام لا يسمح بتشغيل بوتين بنفس التوكن).
"""
import importlib.util
import os
import subprocess
import sys

# ------------------------------------------------------------------ الإعدادات
BOT_TOKEN =  "8941543246:AAGzdCl4MIRB-ceW49oltsjbLDb7ImICzvw"
API_ID = " 31540159"
API_HASH =  "fd3ff16d17e43a5d50b1135ae8437408"
OWNER_ID =  8706836075
DEV_URL =  "https://t.me/x_7_v3"

CREDITS_DAYS = 3          # بعد كم يوم تعود حقوق المطور تلقائيًا
PAGE_SIZE = 8
REQUEST_GAP = 3           # ثواني بين طلبين من نفس المستخدم
NOTIFY_PACE = 0.05

REQUIRED = {"telethon": "telethon", "pytgcalls": "py-tgcalls", "aiohttp": "aiohttp", "tzdata": "tzdata",
            "yt_dlp": "yt-dlp[default]", "static_ffmpeg": "static-ffmpeg", "PIL": "pillow"}


def ensure_packages(upgrade=False):
    for module, package in REQUIRED.items():
        if not upgrade and importlib.util.find_spec(module):
            continue
        cmd = [sys.executable, "-m", "pip", "install", "-q", "-U", package]
        if subprocess.run(cmd, capture_output=True).returncode != 0:
            subprocess.run(cmd + ["--break-system-packages"], capture_output=True)


ensure_packages("--upgrade" in sys.argv)

import asyncio
import copy
import html
import io
import json
import logging
import math
import random
import re
import shutil
import time
import wave
from datetime import datetime, timedelta, timezone

import aiohttp
from urllib.parse import quote
from telethon import TelegramClient, functions, types, utils
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream

try:
    from pytgcalls.types import VideoQuality
except Exception:
    VideoQuality = None

try:
    from pytgcalls import filters as call_filters
except Exception:
    call_filters = None

try:
    from zoneinfo import ZoneInfo
    DAMASCUS = ZoneInfo("Asia/Damascus")
except Exception:
    DAMASCUS = timezone(timedelta(hours=3))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maker")

MUSIC_DIR = "music_cache"
COOKIES_FILE = "cookies.txt"
DB_FILE = "maker_db.json"
BACKUP_DIR = "maker_backups"
MEDIA_DIR = "media"

QUOTE_TEXTS = True        # True = كل نصوص البوتات تظهر بشكل مقتبس (blockquote) | False = نصوص عادية
DEFAULT_TPL = 9           # كليشة التشغيل الافتراضية (رقم 10 = لوحة التحكم الكاملة القديمة)

# ------------------------------------------------------------------ البيانات
DEFAULT_CFG = {                       # إعدادات كل بوت (يغيّرها مالكه)
    "access": "mixed",                # all | mixed | admins
    "max_min": 15, "queue_limit": 20, "volume": 100, "progress_sec": 10, "blur": 8,
    "video": True, "yt": True, "auto_leave": True,
    "panel_photo": "", "panel_gif": "", "stickers": [], "forced": [], "start_media": None,
    "tpl": DEFAULT_TPL,               # رقم كليشة التشغيل المطبّقة (0-9)
}

DEFAULT_DB = {
    "bots": {},          # {bot_id: سجل البوت}
    "devs": [], "refs": {}, "owners": {},
    "known": [],         # من فتح بوت الصانع
    "people": {},        # إحصائيات مستخدمي بوت الصانع
    "emoji": {},         # ايموجي مميز للأزرار والنصوص
    "g": {
        "open": True,                 # السماح بإنشاء بوتات جديدة
        "per_user": 1, "max_bots": 30,
        "credits_mode": "user",       # user = حقوق المستخدم | dev = حقوقي
        "dev_name": "المطور", "dev_url": DEV_URL, "updates_url": "", "source_url": "",
        "forced": [],                 # الاشتراك الإجباري في كل البوتات
        "max_min_cap": 60,            # سقف مدة المقطع لكل البوتات
        "welcome": "", "replies": [], "media": [], "panel_media": None, "tpl_media": {},
        "trial_on": True, "trial_days": 7, "ref_need": 5, "start_media": None,
        "yt": {"fallback": True, "proxy": "", "ipv4": True, "auto_update": True, "last_update": 0,
               "cache_mb": 2048, "fast_start": True},
    },
}


def deep_merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_db():
    data = copy.deepcopy(DEFAULT_DB)
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, encoding="utf-8") as f:
                deep_merge(data, json.load(f))
        except (OSError, ValueError) as e:
            log.error("ملف البيانات تالف (%s)، نسخة منه في %s.corrupt", e, DB_FILE)
            shutil.copy(DB_FILE, DB_FILE + ".corrupt")
    return data


db = load_db()
G = db["g"]


def gy():
    return G["yt"]


def save():
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DB_FILE)


_dirty = False


def save_soon():
    global _dirty
    _dirty = True


def flush():
    global _dirty
    if _dirty:
        _dirty = False
        save()


def backup_db():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    shutil.copy(DB_FILE, os.path.join(BACKUP_DIR, datetime.now(timezone.utc).strftime("db-%Y%m%d-%H%M.json")))
    for old in sorted(os.listdir(BACKUP_DIR))[:-10]:
        os.remove(os.path.join(BACKUP_DIR, old))


def new_bot_rec(token, info, owner):
    return {"id": info["id"], "token": token, "username": info.get("username", ""),
            "name": info.get("first_name", ""), "owner": owner, "created": time.time(),
            "enabled": True, "status": "new", "session": "", "mode_override": "",
            "credits": {}, "welcome": "", "cfg": copy.deepcopy(DEFAULT_CFG),
            "groups": {}, "people": {}, "known": [], "stats": {"plays": 0, "downloads": 0},
            "expires": time.time() + G["trial_days"] * 86400, "suspended": False, "warned": False}


def migrate():
    for rec in db["bots"].values():
        rec["cfg"] = {**copy.deepcopy(DEFAULT_CFG), **rec.get("cfg", {})}
        for key, default in (("groups", {}), ("people", {}), ("known", []), ("credits", {}),
                             ("stats", {"plays": 0, "downloads": 0}), ("mode_override", ""), ("welcome", ""),
                             ("session", ""), ("status", "new"), ("enabled", True), ("suspended", False),
                             ("warned", False), ("expires", time.time() + G["trial_days"] * 86400)):
            rec.setdefault(key, copy.deepcopy(default))
    save()


migrate()

# ------------------------------------------------------------------ أدوات عامة
CHILDREN = {}          # {bot_id: Child}
MAIN = None            # بوت الصانع
MAKER_USERNAME = ""    # يوزر بوت الصانع (لزر «اصنع بوتك» في كل البوتات)
HTTP = None


def now_ts():
    return time.time()


def is_dev(uid):
    return uid == OWNER_ID or uid in db["devs"]


def esc(value):
    return html.escape(str(value))


def mention(uid, name=None):
    if isinstance(uid, int) and uid < 0:
        return f"<b>{esc(name or uid)}</b>"
    return f'<a href="tg://user?id={uid}">{esc(name or uid)}</a>'


def fmt_ts(ts):
    if not ts:
        return "غير معروف"
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(DAMASCUS).strftime("%Y-%m-%d %I:%M %p")


def dur(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{hours} ساعة " if hours else "") + (f"{minutes} دقيقة " if minutes else "") + f"{secs} ثانية"


def short(err):
    """نص خطأ قصير نظيف (yt-dlp يضيف ألوان ANSI)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", str(err)).strip()[:200]


def fmt_secs(n):
    n = int(n or 0)
    h, rest = divmod(n, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def progress_bar(pos, total, width=16):
    if not total:
        return fmt_secs(pos)
    ratio = min(1.0, pos / total)
    i = min(width - 1, int(width * ratio))
    return ("▬" * i + "●" + "▬" * (width - 1 - i)
            + f"\n{fmt_secs(pos)} / {fmt_secs(total)}  ({int(ratio * 100)}%)")


def next_preset(options, current):
    return options[(options.index(current) + 1) % len(options)] if current in options else options[0]


async def run_blocking(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"})


def norm_ar(text):
    return re.sub(r"[\u064b-\u0652\u0640]", "", text).translate(_AR_MAP)


def tg_name(user):
    full = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return full or user.get("username") or str(user.get("id", ""))


def norm_link(text):
    """رابط تيليجرام من @name أو name أو رابط t.me. يرجع "" إن كان غير صالح."""
    text = text.strip()
    if re.fullmatch(r"@?[A-Za-z][\w]{3,31}", text):
        return "https://t.me/" + text.lstrip("@")
    if re.match(r"^(https?://)?(t|telegram)\.me/\S+$", text):
        return text if text.startswith("http") else "https://" + text
    return ""


def record_person(people, uid, name=None, username=None, bump=None, bot=False):
    """يسجل المستخدم في قاموس people ويزيد عدّاده. username: None لا تغيّر، "" بدون يوزر."""
    if not uid or uid < 0:
        return
    rec = people.setdefault(str(uid), {"first": now_ts(), "plays": 0, "dls": 0})
    if name:
        rec["name"] = name
    if username is not None:
        rec["un"] = username
    if bot:
        rec["bot"] = True
    rec["last"] = now_ts()
    if bump:
        rec[bump] = rec.get(bump, 0) + 1
    save_soon()


def people_view(people, page, cb, back, title="إحصائيات المستخدمين"):
    """صفحة إحصائيات: كل مستخدم مع يوزره وعدد طلباته. cb: بادئة callback للتنقل بين الصفحات."""
    items = sorted(people.items(),
                   key=lambda kv: (-(kv[1].get("plays", 0) + kv[1].get("dls", 0)), -kv[1].get("last", 0)))
    per = 8
    pages = max(1, math.ceil(len(items) / per))
    page = max(0, min(page, pages - 1))
    head = [f"<b>{title}</b>", "",
            f"المسجلون: <b>{len(items)}</b> | فتحوا البوت: <b>{sum(1 for _, r in items if r.get('bot'))}</b>",
            f"طلبات التشغيل: <b>{sum(r.get('plays', 0) for _, r in items)}</b> | "
            f"تحميلات يوت: <b>{sum(r.get('dls', 0) for _, r in items)}</b>",
            f"الصفحة {page + 1} من {pages}"]
    blocks = []
    for i, (uid, r) in enumerate(items[page * per:(page + 1) * per], page * per + 1):
        username = f"@{r['un']}" if r.get("un") else "بدون يوزر"
        blocks.append(f"<b>{i}.</b> {mention(int(uid), r.get('name'))} {esc(username)}\n"
                      f"الايدي: <code>{uid}</code> | طلبات: {r.get('plays', 0)} | تحميل: {r.get('dls', 0)}\n"
                      f"آخر نشاط: {fmt_ts(r.get('last'))}")
    text = "\n".join(head) + "\n\n" + ("\n\n".join(blocks) if blocks else "لا يوجد مستخدمون بعد.")
    nav = []
    if page > 0:
        nav.append(b("السابق", f"{cb}:{page - 1}", style="primary"))
    if page < pages - 1:
        nav.append(b("التالي", f"{cb}:{page + 1}", style="primary"))
    return text, back_kb([nav] if nav else None, back)


# ------------------------------------------------------------------ Bot API
TG_EMOJI = re.compile(r"<tg-emoji[^>]*>.*?</tg-emoji>\s?", re.S)


def has_icons(markup):
    try:
        return any("icon_custom_emoji_id" in btn for row in markup["inline_keyboard"] for btn in row)
    except (TypeError, KeyError):
        return False


def strip_icons(markup):
    return {"inline_keyboard": [[{k: v for k, v in btn.items() if k != "icon_custom_emoji_id"} for btn in row]
                                for row in markup["inline_keyboard"]]}


def wrap_quote(text):
    """يلفّ النص في اقتباس (blockquote) ولا يلفّه مرتين."""
    if not QUOTE_TEXTS or not isinstance(text, str) or not text.strip() or "<blockquote" in text:
        return text
    return f"<blockquote>{text}</blockquote>"


def quote_params(params):
    """كل رسالة أو تعليق وسائط بصيغة HTML يُعرض مقتبسًا."""
    if params.get("parse_mode") == "HTML":
        for name in ("text", "caption"):
            if isinstance(params.get(name), str):
                params[name] = wrap_quote(params[name])
    return params


class BotAPI:
    """نداءات Bot API لبوت واحد (توكنه). نستعمله للصانع ولكل بوت مصنوع."""

    def __init__(self, token):
        self.token = token

    async def _post(self, method, params, retry=True):
        try:
            async with HTTP.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params) as r:
                data = await r.json()
            wait = (data.get("parameters") or {}).get("retry_after")
            if not data.get("ok") and wait and retry:
                await asyncio.sleep(wait + 1)
                return await self._post(method, params, retry=False)
            if not data.get("ok") and method != "getUpdates":
                log.warning("%s: %s", method, data.get("description"))
            return data
        except Exception as e:
            log.warning("api %s: %s", method, e)
            return {"ok": False}

    async def __call__(self, method, **params):
        """إذا رُفضت الرسالة بسبب ايموجي مميز غير صالح نعيدها بدونه."""
        quote_params(params)
        data = await self._post(method, params)
        if data.get("ok"):
            return data
        changed = False
        if has_icons(params.get("reply_markup")):
            params["reply_markup"] = strip_icons(params["reply_markup"])
            changed = True
        for name in ("text", "caption"):
            if isinstance(params.get(name), str) and "<tg-emoji" in params[name]:
                params[name] = TG_EMOJI.sub("", params[name])
                changed = True
        return await self._post(method, params) if changed else data

    async def download(self, file_id):
        info = await self("getFile", file_id=file_id)
        if not info.get("ok"):
            return None
        try:
            async with HTTP.get(f"https://api.telegram.org/file/bot{self.token}/{info['result']['file_path']}") as r:
                return await r.read()
        except Exception as e:
            log.warning("download: %s", e)
            return None

    async def upload(self, method, field, data, filename, **params):
        quote_params(params)
        form = aiohttp.FormData()
        for key, value in params.items():
            if value is not None:
                form.add_field(key, value if isinstance(value, str) else json.dumps(value))
        form.add_field(field, data, filename=filename)
        try:
            async with HTTP.post(f"https://api.telegram.org/bot{self.token}/{method}", data=form,
                                 timeout=aiohttp.ClientTimeout(total=300)) as r:
                return await r.json()
        except Exception as e:
            log.warning("upload %s: %s", method, e)
            return {"ok": False}

    async def profile_photo(self, data):
        """تغيير صورة البوت الشخصية (setMyProfilePhoto)."""
        form = aiohttp.FormData()
        form.add_field("photo", json.dumps({"type": "static", "photo": "attach://pic"}))
        form.add_field("pic", data, filename="pic.jpg")
        try:
            async with HTTP.post(f"https://api.telegram.org/bot{self.token}/setMyProfilePhoto", data=form) as r:
                return await r.json()
        except Exception as e:
            log.warning("profile_photo: %s", e)
            return {"ok": False, "description": str(e)}


# ------------------------------------------------------------------ الأزرار والنصوص
BUTTON_SLOTS = {
    "*": "كل الأزرار", "us": "أزرار المستخدمين", "ow": "أزرار لوحة المالك", "dv": "أزرار لوحة المطور",
    "fs": "أزرار الاشتراك الإجباري", "mu_pause": "الميوزك: إيقاف مؤقت", "mu_resume": "الميوزك: استكمال",
    "mu_back": "الميوزك: عودة", "mu_fwd": "الميوزك: تقديم", "mu_skip": "الميوزك: تخطي",
    "mu_stop": "الميوزك: إيقاف", "mu_loop": "الميوزك: تكرار", "mu_queue": "الميوزك: الطابور",
    "mu_dev": "الميوزك: المطور", "mu_updates": "الميوزك: التحديثات", "mu_source": "الميوزك: السورس",
    "mu_close": "الميوزك: إغلاق اللوحة", "mu_make": "الميوزك: اصنع بوتك",
    "mu_add": "الميوزك: أضفني لمجموعتك",
}
TEXT_SLOTS = {"t:*": "كل الرسائل", "t:music": "رسائل الموسيقى", "t:start": "رسالة البداية",
              "t:owner": "لوحة المالك", "t:dev": "لوحة المطور", "t:guide": "طريقة الاستخدام"}
FIELD_SLOTS = {"f:*": "كل عناوين الحقول", "f:song": "حقل العنوان", "f:artist": "حقل القناة",
               "f:by": "حقل الطالب", "f:duration": "حقل المدة", "f:place": "حقل المكان"}
SLOT_NAMES = {**BUTTON_SLOTS, **TEXT_SLOTS, **FIELD_SLOTS}


def custom_emoji(eid):
    return f'<tg-emoji emoji-id="{eid}">&#8226;</tg-emoji>'


def deco(text, kind=None):
    eid = (kind and db["emoji"].get("t:" + kind)) or db["emoji"].get("t:*")
    return f"{custom_emoji(eid)} {text}" if eid else text


def field(slot, label, value):
    eid = db["emoji"].get("f:" + slot) or db["emoji"].get("f:*")
    return f"{custom_emoji(eid) + ' ' if eid else ''}{label}: {value}"


def b(text, data=None, url=None, style=None, k=None):
    """زر inline. style: primary أزرق | success أخضر | danger أحمر."""
    btn = {"text": text}
    if url:
        btn["url"] = url
    else:
        btn["callback_data"] = data
    if style:
        btn["style"] = style
    slot = k or (data.split(":")[0] if data else "us")
    eid = db["emoji"].get(slot) or db["emoji"].get("*")
    if eid:
        btn["icon_custom_emoji_id"] = str(eid)
    return btn


def kb(rows):
    return {"inline_keyboard": rows}


def back_kb(extra=None, to="home"):
    return kb((extra or []) + [[b("رجوع", to, style="primary"), b("✖", "x:close", style="danger")]])


# ------------------------------------------------------------------ الحقوق
def credits_mode(rec):
    return (rec.get("mode_override") if rec else "") or G["credits_mode"]


def effective_credits(rec):
    """الحقوق الظاهرة في البوت: حقوق المطور، أو حقوق المالك إن كان الوضع «حقوق المستخدم» ولم تنتهِ مدتها."""
    base = {"dev_name": G["dev_name"], "dev_url": G["dev_url"],
            "updates_url": G["updates_url"], "source_url": G["source_url"]}
    custom = (rec or {}).get("credits") or {}
    if rec and credits_mode(rec) == "user":
        for key in base:
            if custom.get(key):
                base[key] = custom[key]
    return base


def credits_days_left(rec):
    cr = rec.get("credits") or {}
    if not cr.get("set_at"):
        return None
    return max(0, math.ceil((cr["set_at"] + CREDITS_DAYS * 86400 - now_ts()) / 86400))


def make_button():
    """زر «اصنع بوتك» يدخل المستخدم إلى بوت الصانع مباشرة."""
    if not MAKER_USERNAME:
        return None
    return b("اصنع بوتك", url=f"https://t.me/{MAKER_USERNAME}?start=create", style="success", k="mu_make")


def credit_buttons(rec):
    """أزرار الحقوق: المطور وقناة التحديثات وقناة السورس (التي لها رابط)."""
    cr = effective_credits(rec)
    row = []
    if cr["dev_url"]:
        row.append(b(cr["dev_name"] or "المطور", url=cr["dev_url"], style="success", k="mu_dev"))
    if cr["updates_url"]:
        row.append(b("قناة التحديثات", url=cr["updates_url"], style="primary", k="mu_updates"))
    if cr["source_url"]:
        row.append(b("قناة السورس", url=cr["source_url"], style="primary", k="mu_source"))
    return row


# ------------------------------------------------------------------ الاشتراك الإجباري
_sub_cache = {}


def forced_channels(app=None):
    own = getattr(app, "cfg", {}).get("forced", []) if app is not None else []
    return list(G["forced"]) + list(own)


def sub_key(uid, app=None):
    return (uid, app.api.token if app is not None else "")


async def check_forced(uid, app=None):
    """قنوات الاشتراك الإجباري التي لم يشترك فيها المستخدم (قائمة فارغة = مسموح).
    الفحص يتم ببوت الصانع، فيجب أن يكون مشرفًا في تلك القنوات. إن تعذر الفحص لا نمنع المستخدم."""
    forced = forced_channels(app)
    if not forced or is_dev(uid) or MAIN is None:
        return []
    ckey = sub_key(uid, app)
    hit = _sub_cache.get(ckey)
    if hit and time.monotonic() - hit[1] < (300 if not hit[0] else 15):
        return hit[0]
    missing = []
    for ch in forced:
        own = bool(ch.get("own")) and app is not None
        if own and uid == app.rec["owner"]:
            continue
        api = app.api if own else MAIN.api
        d = await api("getChatMember", chat_id=ch["chat"], user_id=uid)
        if not d.get("ok"):
            ch["broken"] = True              # البوت ليس مشرفًا هناك: نتجاهل الفحص
            continue
        ch["broken"] = False
        status = d["result"].get("status")
        if status in ("left", "kicked") or (status == "restricted" and not d["result"].get("is_member")):
            missing.append(ch)
    _sub_cache[ckey] = (missing, time.monotonic())
    return missing


async def resolve_channel(api, m, text, bot_id):
    """يحلل إدخال المالك (يوزر/رابط/ايدي/رسالة محوّلة) إلى قناة. يرجع (قناة، خطأ)."""
    fwd = m.get("forward_from_chat") or (m.get("forward_origin") or {}).get("chat") or {}
    tokens = text.split()
    if fwd.get("id"):
        ref, rest = fwd["id"], []
    elif tokens:
        first, rest = tokens[0], tokens[1:]
        link = re.match(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z]\w{3,31})$", first)
        if link:
            ref = "@" + link.group(1)
        elif re.fullmatch(r"-?\d+", first):
            ref = int(first)
        else:
            ref = "@" + first.lstrip("@")
    else:
        return None, "أرسل يوزر القناة أو ايديها."
    info = await api("getChat", chat_id=ref)
    if not info.get("ok"):
        return None, "لم أجد هذه القناة. تأكد من الاسم وأن البوت مشرف فيها."
    ch = info["result"]
    link = rest[0] if rest else (f"https://t.me/{ch['username']}" if ch.get("username") else "")
    if not link:
        link = (await api("exportChatInviteLink", chat_id=ch["id"])).get("result") or ""
    if not link.startswith("http"):
        return None, "القناة خاصة: أرسل ايديها ثم رابط الدعوة بعده."
    member = await api("getChatMember", chat_id=ch["id"], user_id=bot_id)
    is_admin = member.get("ok") and member["result"].get("status") in ("administrator", "creator")
    return {"chat": ch["id"], "link": link, "title": ch.get("title") or ch.get("username"),
            "broken": not is_admin}, None


def forced_markup(missing):
    rows = [[b(ch.get("title") or "اشترك في القناة", url=ch["link"], style="primary", k="fs")] for ch in missing]
    rows.append([b("تحقق من الاشتراك", "fs:check", style="success", k="fs")])
    return kb(rows)


# ------------------------------------------------------------------ محرك الموسيقى (مشترك بين كل البوتات)
# البحث والتحميل والكاش وحماية يوتيوب عامة للجميع، ويتحكم بها المطور من لوحته.
_inflight = {}             # (id, نوع) -> مهمة تحميل جارية
_dl_gate = None
_search_cache = {}
_stream_cache = {}

# ------------------------------------------------------------------ تجهيز ffmpeg و yt-dlp
def ensure_ffmpeg():
    """يجهز ffmpeg و ffprobe تلقائيًا (حزمة static-ffmpeg) إن لم يكونا مثبتين في النظام."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception as e:
        log.warning("تعذر تجهيز ffmpeg تلقائيًا (%s). ثبّته يدويًا: apt install ffmpeg", e)
    return bool(shutil.which("ffmpeg"))


def ensure_js_runtime():
    """يوتيوب يحتاج بيئة جافاسكربت (deno أو node) مع yt-dlp الحديث. نحاول تثبيت deno إن لم نجد شيئًا."""
    import site
    import sysconfig
    extra = [sysconfig.get_path("scripts"), os.path.join(site.USER_BASE, "bin")]
    os.environ["PATH"] = os.pathsep.join([p for p in extra if p]) + os.pathsep + os.environ.get("PATH", "")
    if any(shutil.which(x) for x in ("deno", "node", "bun", "qjs")):
        return True
    marker = ".js_runtime_tried"
    if os.path.exists(marker):
        return bool(shutil.which("deno"))
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-U", "deno"]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        subprocess.run(cmd + ["--break-system-packages"], capture_output=True)
    open(marker, "w").close()
    ok = bool(shutil.which("deno"))
    if not ok:
        log.warning("لم أجد deno أو node. إن فشل التحميل من يوتيوب ثبّت أحدهما: https://deno.com")
    return ok


def ytdlp_version():
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return None


def _pip_upgrade_ytdlp():
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-U", "yt-dlp[default]"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        res = subprocess.run(cmd + ["--break-system-packages"], capture_output=True, text=True)
    for name in [k for k in sys.modules if k == "yt_dlp" or k.startswith("yt_dlp.")]:
        del sys.modules[name]      # ليُحمَّل الإصدار الجديد عند أول استخدام
    return res.returncode == 0, (res.stderr or res.stdout)[-200:]


# ------------------------------------------------------------------ البحث والتحميل
def _ydl_opts(**extra):
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20,
            "retries": 3, "fragment_retries": 3, "concurrent_fragment_downloads": 8}
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    proxies = proxy_list()
    if proxies:
        opts["proxy"] = random.choice(proxies)          # عند وجود أكثر من بروكسي نبدّل بينها
    elif gy()["ipv4"]:
        opts["source_address"] = "0.0.0.0"              # IPv4 فقط
    opts.update(extra)
    return opts


def proxy_list():
    return [x for x in re.split(r"[\s,]+", gy()["proxy"].strip()) if x]


class YtBlocked(Exception):
    """يوتيوب يحجب السيرفر مؤقتًا: لا نكرر الطلبات حتى لا يزيد الحجب."""


_yt = {"until": 0.0, "count": 0, "reason": ""}
BLOCK_HINTS = ("sign in to confirm", "not a bot", "429", "too many requests", "po token",
               "http error 403", "forbidden")


def is_block_error(err):
    msg = short(err).lower()
    return any(h in msg for h in BLOCK_HINTS)


def friendly(err):
    """نص خطأ للمستخدم لا يذكر يوتيوب ولا الحجب."""
    if isinstance(err, YtBlocked) or is_block_error(err):
        return "تعذر جلب هذا المقطع الآن، جرّب مقطعًا آخر أو أعد المحاولة بعد قليل"
    return short(err)


def yt_blocked():
    return time.time() < _yt["until"]


def yt_mark_blocked(err):
    _yt["count"] += 1
    minutes = min(45, 3 * 2 ** (_yt["count"] - 1))      # 15 ثم 30 ثم 60 ثم 120 دقيقة
    _yt["until"] = time.time() + minutes * 60
    _yt["reason"] = short(err)[:90]
    log.warning("يوتيوب يحجب السيرفر، نتوقف عنه %s دقيقة: %s", minutes, _yt["reason"])


def yt_mark_ok():
    _yt.update(until=0.0, count=0, reason="")


def yt_status_line():
    if not yt_blocked():
        return "سليم"
    until = fmt_ts(_yt["until"])
    return f"محجوب مؤقتًا حتى {until} ({esc(_yt['reason'])})"


def _yt_probe():
    """اختبار سريع: هل يعطينا يوتيوب صيغ فيديو معروف؟"""
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts(skip_download=True)) as y:
        info = y.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
    count = len((info or {}).get("formats") or [])
    if not count:
        raise RuntimeError("لم يرجع يوتيوب أي صيغة")
    return count


def safe_id(info):
    ie = str(info.get("ie_key") or info.get("extractor_key") or "yt").lower()
    return re.sub(r"[^\w.-]", "_", f"{ie}_{info['id']}")[:90]


def norm_info(entry):
    if not entry or not entry.get("id"):
        return None
    vid = str(entry["id"])
    url = entry.get("webpage_url") or entry.get("url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    return {"id": safe_id(entry), "title": entry.get("title") or "بدون عنوان",
            "dur": int(entry.get("duration") or 0), "url": url,
            "uploader": entry.get("uploader") or entry.get("channel") or "",
            "live": bool(entry.get("is_live")) or entry.get("live_status") == "is_live"}


def _flat_search(prefix, query):
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist", skip_download=True)) as y:
        res = y.extract_info(f"{prefix}{query}", download=False)
    return [x for x in (norm_info(e) for e in (res or {}).get("entries") or []) if x]


def _search_blocking(query):
    import yt_dlp
    if re.match(r"https?://", query):
        with yt_dlp.YoutubeDL(_ydl_opts(skip_download=True)) as y:
            info = y.extract_info(query, download=False)
        if info and info.get("entries"):
            info = next(iter(info["entries"]), None)
        return [x for x in [norm_info(info)] if x]
    found, err = [], None
    if yt_blocked():
        err = YtBlocked("يوتيوب يحجب السيرفر مؤقتًا")
    else:
        try:
            found = _flat_search("ytsearch3:", query)
        except Exception as e:
            err = e
            if is_block_error(e):
                yt_mark_blocked(e)
    if not found and gy()["fallback"]:       # يوتيوب لا يرد: نبحث في ساوندكلاود (لا يحتاج كوكيز)
        found = _flat_search("scsearch3:", query)
    if not found and err:
        raise err
    return found


def _soundcloud_alt(title, dur):
    """بديل للمقطع من ساوندكلاود بنفس العنوان تقريبًا وبمدة قريبة."""
    for info in _flat_search("scsearch5:", title):
        if not dur or not info["dur"] or abs(info["dur"] - dur) <= 90:
            return info
    return None




async def search(query):
    """بحث مع ذاكرة قصيرة: تكرار نفس الطلب خلال 10 دقائق فوري."""
    key = norm_ar(query).lower().strip()
    hit = _search_cache.get(key)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    results = await run_blocking(_search_blocking, query)
    if len(_search_cache) > 200:
        _search_cache.clear()
    _search_cache[key] = (time.monotonic(), results)
    return results


def pick_result(results, max_seconds):
    """أول نتيجة صالحة: ليست بثًا مباشرًا ولا أطول من الحد المسموح."""
    if not results:
        raise ValueError("لم أجد نتائج")
    for r in results:
        if not r["live"] and (r["dur"] == 0 or r["dur"] <= max_seconds):
            return r
    if all(r["live"] for r in results):
        raise ValueError("النتائج بثوث مباشرة ولا يمكن تشغيلها")
    raise ValueError(f"كل النتائج أطول من الحد المسموح ({max_seconds // 60} دقيقة)")


def find_cached(sid, kind):
    prefix = f"{sid}.{kind}."
    best = None
    try:
        for name in os.listdir(MUSIC_DIR):
            rest = name[len(prefix):]
            if not name.startswith(prefix) or re.match(r"^f\d+[.-]", rest):
                continue
            if name.endswith((".part", ".ytdl", ".temp")):
                continue
            path = os.path.join(MUSIC_DIR, name)
            if os.path.getsize(path) > 0 and (best is None or os.path.getmtime(path) > os.path.getmtime(best)):
                best = path
    except OSError:
        pass
    return best


# عملاء يوتيوب نجربهم بالترتيب عند الفشل بدون كوكيز (الأسماء تتغير مع تحديثات yt-dlp)
YT_CLIENT_TRIES = (None, ["tv", "mweb"])


def _download_once(url, sid, kind, clients):
    import yt_dlp
    out = os.path.join(MUSIC_DIR, f"{sid}.{kind}.%(ext)s")
    if kind == "v":
        opts = _ydl_opts(format="b[height<=480][ext=mp4]/bv*[height<=480]+ba/b[height<=480]/b", outtmpl=out,
                         merge_output_format="mp4")
    else:
        opts = _ydl_opts(format="bestaudio[abr<=?100]/bestaudio/best", outtmpl=out)
    if clients:
        opts["extractor_args"] = {"youtube": {"player_client": clients}}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
    done = ((info or {}).get("requested_downloads") or [{}])[0].get("filepath")
    if not done or not os.path.exists(done):
        done = find_cached(sid, kind)
    if not done:
        raise RuntimeError("اكتمل التحميل لكن الملف غير موجود")
    return done


def _download_blocking(url, sid, kind):
    youtube = "youtube.com" in url or "youtu.be" in url
    if youtube and yt_blocked():
        raise YtBlocked("يوتيوب يحجب السيرفر مؤقتًا، جرّب بعد قليل")
    tries = YT_CLIENT_TRIES if youtube else (None,)
    last, blocks = None, 0
    for clients in tries:
        try:
            path = _download_once(url, sid, kind, clients)
            if youtube:
                yt_mark_ok()
            return path
        except Exception as e:
            last = e
            blocks += is_block_error(e)
    if youtube and blocks == len(tries):
        yt_mark_blocked(last)
    raise last



def protected_paths():
    keep = set()
    for child in CHILDREN.values():
        for p in child.players.values():
            for t in ([p.current] if p.current else []) + p.queue:
                if t.path:
                    keep.add(t.path)
    return keep


def trim_cache():
    """يحذف الأقدم استخدامًا حتى يرجع حجم الكاش تحت الحد الذي حدده المطور."""
    limit = gy()["cache_mb"] * 1024 * 1024
    keep = protected_paths()
    files = []
    for name in os.listdir(MUSIC_DIR):
        path = os.path.join(MUSIC_DIR, name)
        if os.path.isfile(path):
            st = os.stat(path)
            files.append((st.st_mtime, st.st_size, path))
    total = sum(f[1] for f in files)
    for _, size, path in sorted(files):
        if total <= limit:
            break
        if path not in keep:
            try:
                os.remove(path)
                total -= size
            except OSError:
                pass


def cache_size():
    try:
        return sum(os.path.getsize(os.path.join(MUSIC_DIR, f)) for f in os.listdir(MUSIC_DIR))
    except OSError:
        return 0


def is_youtube(url):
    return "youtube.com" in url or "youtu.be" in url


async def _fallback_download(track, err):
    """يوتيوب فشل (غالبًا حجب السيرفر بدون كوكيز): الصوت فقط، ثم نسخة من ساوندكلاود."""
    if not is_youtube(track.url):
        raise err
    log.info("فشل تحميل يوتيوب (%s) نجرب البدائل", short(err))
    if track.video:
        try:
            path = await run_blocking(_download_blocking, track.url, track.id, "a")
            track.video, track.fallback = False, "audio"
            return path
        except Exception:
            pass
    alt = await run_blocking(_soundcloud_alt, track.title, track.dur)
    if not alt:
        raise err
    path = await run_blocking(_download_blocking, alt["url"], alt["id"], "a")
    track.id, track.url, track.video, track.fallback = alt["id"], alt["url"], False, "soundcloud"
    return path


async def _download_task(track, kind):
    global _dl_gate
    if _dl_gate is None:
        _dl_gate = asyncio.Semaphore(3)
    async with _dl_gate:
        try:
            path = await run_blocking(_download_blocking, track.url, track.id, kind)
        except Exception as err:
            if not gy()["fallback"]:
                raise
            path = await _fallback_download(track, err)
    await run_blocking(trim_cache)
    return path


async def fetch(track):
    """مسار الملف من الكاش أو بعد تحميله. الطلبات المتزامنة لنفس المقطع تنتظر تحميلًا واحدًا."""
    kind = "v" if track.video else "a"
    cached = find_cached(track.id, kind)
    if cached:
        return cached
    key = (track.id, kind)
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_download_task(track, kind))
        _inflight[key] = task
        task.add_done_callback(lambda _t, k=key: _inflight.pop(k, None))
    return await asyncio.shield(task)


async def prefetch(track):
    try:
        track.path = await fetch(track)
    except Exception as e:
        log.info("prefetch: %s", short(e))


# ------------------------------------------------------------------ المقطع والمشغّل

FALLBACK_NOTES = {"audio": "تعذر تحميل الفيديو من يوتيوب فشغّلت الصوت فقط.",
                  "soundcloud": "يوتيوب حجب التحميل من السيرفر فشغّلت نسخة من ساوندكلاود."}


class Track:
    def __init__(self, info, video, by):
        self.id = info["id"]
        self.title = info["title"]
        self.dur = info["dur"]
        self.url = info["url"]
        self.uploader = info["uploader"]
        self.video = video
        self.by = by             # (ايدي، اسم) من طلبه
        self.path = None
        self.resolving = None    # مهمة استخراج رابط البث (تبدأ مبكرًا لتسريع التشغيل)
        self.fallback = None     # "audio" أو "soundcloud" إذا استُخدم بديل
        self.live = False        # يُبَثّ مباشرة من الرابط أثناء تحميله في الخلفية



COMMANDS = {
    "شغل": "play", "play": "play", "يوت": "yt", "yt": "yt",
    "تخطي": "skip", "skip": "skip", "وقف": "pause", "pause": "pause",
    "استكمال": "resume", "كمل": "resume", "resume": "resume",
    "انهاء": "stop", "ايقاف": "stop", "stop": "stop",
    "تكرار": "loop", "loop": "loop", "قائمة": "queue", "الطابور": "queue", "queue": "queue",
    "الان": "now", "now": "now", "تقديم": "fwd", "رجوع": "back", "عودة": "back",
    "صوت": "volume", "volume": "volume",
}
VIDEO_SUFFIXES = ("مع الفيديو", "مع فيديو", "بالفيديو", "فيديو", "video")


def parse_video_flag(rest):
    """يفصل كلمة «مع الفيديو» عن اسم الأغنية. يرجع (الاسم، فيديو؟)."""
    low = norm_ar(rest)
    for word in VIDEO_SUFFIXES:
        if low.endswith(" " + word) or low == word:
            cut = low[:len(low) - len(word)].strip()
            return (rest[:len(cut)].strip() if len(low) == len(rest) else cut), True
        if low.startswith(word + " "):
            cut = low[len(word):].strip()
            return (rest[len(rest) - len(cut):].strip() if len(low) == len(rest) else cut), True
    return rest, False



def _read_file(path):
    with open(path, "rb") as f:
        return f.read()


def _media_file_id(result, kind):
    if kind == "photo":
        return result["photo"][-1]["file_id"]
    return (result.get(kind) or {}).get("file_id")


def _blur_image(path, radius):
    from PIL import Image, ImageFilter
    img = Image.open(path).convert("RGB")
    img.thumbnail((1280, 1280))
    if radius:
        img = img.filter(ImageFilter.GaussianBlur(radius))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()




# ------------------------------------------------------------------ البدء السريع: البث من الرابط أثناء التحميل
def _resolve_blocking(url):
    """رابط الصوت المباشر بلا تحميل. يرجع None إن لم يكن رابطًا بسيطًا يصلح للبث."""
    import yt_dlp
    if is_youtube(url) and yt_blocked():
        return None
    with yt_dlp.YoutubeDL(_ydl_opts(format="bestaudio[abr<=?100]/bestaudio", skip_download=True)) as y:
        info = y.extract_info(url, download=False)
    if not info or not info.get("url") or info.get("fragments"):
        return None
    if str(info.get("protocol", "")).startswith(("m3u8", "http_dash", "dash", "rtmp")):
        return None
    return {"url": info["url"], "headers": dict(info.get("http_headers") or {})}


async def resolve_stream(track):
    hit = _stream_cache.get(track.id)
    if hit and time.monotonic() - hit[0] < 1800:
        return hit[1]
    try:
        src = await run_blocking(_resolve_blocking, track.url)
    except Exception as e:
        if is_block_error(e):
            yt_mark_blocked(e)
        log.info("resolve: %s", short(e))
        return None
    if src:
        if len(_stream_cache) > 200:
            _stream_cache.clear()
        _stream_cache[track.id] = (time.monotonic(), src)
    return src


def _warm_yt():
    """يحمّل yt-dlp ومستخرجاته مسبقًا، فلا يتأخر أول طلب بعد التشغيل."""
    import yt_dlp
    yt_dlp.YoutubeDL(_ydl_opts(skip_download=True)).close()


# ------------------------------------------------------------------ قاعدة مشتركة لبوت الصانع والبوتات المصنوعة
class Ctx:
    """سياق ضغطة زر: من ضغط، وأين، وعلى ماذا."""

    def __init__(self, app, q):
        msg = q.get("message") or {}
        self.app, self.qid = app, q["id"]
        self.user = q["from"]
        self.uid = self.user["id"]
        self.chat = (msg.get("chat") or {}).get("id")
        self.mid = msg.get("message_id")
        self.reply_mid = (msg.get("reply_to_message") or {}).get("message_id")
        self.editable = not any(k in msg for k in ("photo", "animation", "video", "document"))
        self.data = q.get("data") or ""
        self.parts = self.data.split(":")
        self.act = self.parts[0]
        self.sub = self.parts[1] if len(self.parts) > 1 else ""

    async def screen(self, text, markup=None, kind=None):
        await self.app.show(self.chat, text, markup, self.mid, kind=kind, editable=self.editable)

    async def toast(self, text=None, alert=False):
        params = {"callback_query_id": self.qid}
        if text:
            params.update(text=text, show_alert=alert)
        await self.app.api("answerCallbackQuery", **params)


class App:
    """يجمع ما يتشاركه بوت الصانع وكل بوت مصنوع: الاستقبال، عرض الشاشات، الاشتراك الإجباري."""
    allowed = ["message", "callback_query"]

    def __init__(self, token):
        self.api = BotAPI(token)
        self.states = {}                 # user_id -> خطوة الإدخال الحالية
        self.tasks = set()
        self.running = False
        self.offset = 0
        self.gate_notice = {}

    def spawn(self, coro):
        task = asyncio.ensure_future(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def reset_state(self, uid):
        self.states.pop(uid, None)

    async def show(self, chat, text, markup=None, old=None, kind=None, editable=True, photo=None):
        """يعرض شاشة: نعدّل الرسالة القديمة في مكانها إن أمكن، وإلا نرسل جديدة ثم نحذف القديمة."""
        text = deco(text, kind)
        page = dict(chat_id=chat, parse_mode="HTML", reply_markup=markup)
        if old and editable and not photo:
            d = await self.api("editMessageText", message_id=old, text=text, disable_web_page_preview=True, **page)
            if d.get("ok") or "not modified" in str(d.get("description", "")):
                return
        sent = {"ok": False}
        if photo and len(text) < 1000:
            sent = await self.api("sendPhoto", photo=photo, caption=text, **page)
        if not sent.get("ok"):
            sent = await self.api("sendMessage", text=text, disable_web_page_preview=True, **page)
        if sent.get("ok") and old:
            await self.api("deleteMessage", chat_id=chat, message_id=old)

    async def poll(self):
        while self.running:
            try:
                d = await self.api("getUpdates", offset=self.offset, timeout=50, allowed_updates=self.allowed)
                if not d.get("ok"):
                    code = d.get("error_code")
                    if code == 401:
                        await self.on_dead()
                        return
                    await asyncio.sleep(10 if code == 409 else 3)
                    continue
                for update in d.get("result", []):
                    self.offset = update["update_id"] + 1
                    self.spawn(self.dispatch(update))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("poll: %s", e)
                await asyncio.sleep(3)

    async def dispatch(self, update):
        try:
            if "message" in update:
                await self.on_message(update["message"])
            elif "callback_query" in update:
                await self.on_callback(update["callback_query"])
            elif "my_chat_member" in update:
                await self.on_member(update["my_chat_member"])
            elif "managed_bot" in update:
                await self.on_managed(update["managed_bot"])
        except Exception as e:
            log.exception("dispatch: %s", e)

    async def on_dead(self):
        pass

    async def on_member(self, upd):
        pass

    async def on_managed(self, upd):
        pass

    async def cb_close(self, c):
        """زر ✖: يحذف الرسالة (اللوحة) نهائيًا."""
        await c.toast()
        await self.api("deleteMessage", chat_id=c.chat, message_id=c.mid)

    async def gate(self, uid, chat, reply_to=None):
        """الاشتراك الإجباري: يرجع True إن كان مسموحًا، وإلا يرسل رسالة بالقنوات المطلوبة."""
        missing = await check_forced(uid, self)
        if not missing:
            return True
        key, now = (chat, uid), time.monotonic()
        if now - self.gate_notice.get(key, 0) > 30:
            self.gate_notice[key] = now
            params = dict(chat_id=chat, parse_mode="HTML", reply_markup=forced_markup(missing),
                          text=deco("<b>اشترك أولًا لاستخدام البوت</b>\nاشترك في القنوات التالية ثم اضغط "
                                    "«تحقق من الاشتراك».", "start"))
            if reply_to:
                params.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
            await self.api("sendMessage", **params)
        return False

    async def cb_fs(self, c):
        _sub_cache.pop(sub_key(c.uid, self), None)
        if await check_forced(c.uid, self):
            await c.toast("لم تشترك بعد في كل القنوات", alert=True)
            return
        await c.toast("تم التحقق، أهلًا بك")
        await self.after_subscribed(c)

    async def after_subscribed(self, c):
        pass


async def broadcast(api, targets, src_chat, src_mid, report_chat):
    sent = failed = 0
    started = time.time()
    for target in targets:
        args = dict(chat_id=target, from_chat_id=src_chat, message_id=src_mid)
        d = await api("copyMessage", **args)
        if not d.get("ok"):
            wait = (d.get("parameters") or {}).get("retry_after")
            if wait:
                await asyncio.sleep(wait + 1)
                d = await api("copyMessage", **args)
        sent += 1 if d.get("ok") else 0
        failed += 0 if d.get("ok") else 1
        await asyncio.sleep(0.05)
    await api("sendMessage", chat_id=report_chat, parse_mode="HTML",
              text=("<b>تقرير الإذاعة</b>\n\n"
                    f"المستهدفون: <b>{len(targets)}</b>\nوصلت: <b>{sent}</b>\n"
                    f"فشلت (حظروا البوت): <b>{failed}</b>\nالمدة: {dur(time.time() - started)}"))


# ------------------------------------------------------------------ المشغّل والرسائل المؤقتة
# ------------------------------------------------------------------ كليشات التشغيل
# كل كليشة: شكل النص + أزرارها. رموز الأزرار: pause resume stop skip back fwd loop queue close (تحكم)
# و dev chn add (روابط). الألوان: BLUE أزرق | GREEN أخضر | RED أحمر. الأخيرة (classic) هي اللوحة القديمة.
# صورة/GIF كل كليشة يضعها المطور من: لوحة المطور ← كليشات التشغيل.
BLUE, GREEN, RED = "primary", "success", "danger"
TPL_ACTS = {"pause": "mu_pause", "resume": "mu_resume", "stop": "mu_stop", "skip": "mu_skip", "back": "mu_back",
            "fwd": "mu_fwd", "loop": "mu_loop", "queue": "mu_queue", "close": "mu_close"}

TEMPLATES = [
    {"name": "جاري تشغيل الان", "head": "⌯ جاري تشغيل الان", "bullet": "⌯ ", "sep": " : ",
     "labels": ("الآغنيه", "المدة", "بواسطة"),
     "rows": [[("stop", "STOP", BLUE), ("resume", "RESUME", BLUE), ("pause", "PAUSE", BLUE)],
              [("dev", "DEV", BLUE), ("chn", "CHN", BLUE)],
              [("close", "- CLOSE", RED)]]},
    {"name": "قيد التشغيل الآن", "head": "▶️ قيـد التشغيل الآن", "bullet": "★ ", "sep": " › ",
     "labels": ("الاسم", "المدة", "بواسطة"),
     "rows": [[("pause", "ايقاف", BLUE), ("stop", "انهاء", BLUE), ("resume", "استئناف", BLUE)],
              [("dev", "المطور", BLUE), ("chn", "قناة البوت", BLUE)],
              [("close", "اغلاق", RED)]]},
    {"name": "تم تشغيل الاغنيه", "head": "- تـم تشغيـل الآغنيه ♪", "bullet": "", "sep": " ـ ",
     "labels": ("الآغنيه", "المده", "المستخدم"),
     "rows": [[("stop", "STP", BLUE), ("resume", "RESUME", BLUE), ("pause", "PAUSE", BLUE)],
              [("dev", "DEV", BLUE), ("skip", "SKP", RED), ("chn", "CHN", BLUE)],
              [("add", "- ADD ME TO GROUP", GREEN)],
              [("close", "- CLS ✗", RED)]]},
    {"name": "START PLAYING NOW", "head": "START PLAYING NOW .. 📡", "bullet": "", "sep": " : ",
     "labels": ("TITLE", "DURATION", "REQUESTED BY"),
     "rows": [[("stop", "STOP ■", BLUE), ("resume", "RESUME ►", BLUE), ("pause", "PAUSE ♪", BLUE)],
              [("dev", "DEVELOPER", BLUE), ("chn", "CHANNEL", BLUE)],
              [("add", "ADD ME YOUR GROUP", BLUE)],
              [("close", "CLOSE", RED)]]},
    {"name": "تشغيل الآن", "head": "🎧 تشغيل الآن", "bullet": "• ", "sep": ": ",
     "labels": ("العنوان", "المدة", "الطالب"),
     "rows": [[("pause", "إيقاف مؤقت", BLUE), ("resume", "استكمال", GREEN)],
              [("skip", "تخطي", BLUE), ("stop", "إيقاف", RED)],
              [("dev", "المطور", BLUE), ("chn", "القناة", BLUE)],
              [("close", "إغلاق", RED)]]},
    {"name": "NOW PLAYING", "head": "🎧 NOW PLAYING", "bullet": "• ", "sep": " ➜ ",
     "labels": ("Title", "Time", "By"),
     "rows": [[("pause", "⏸ PAUSE", BLUE), ("resume", "▶ RESUME", GREEN)],
              [("skip", "⏭ SKIP", BLUE), ("stop", "⏹ END", RED)],
              [("dev", "DEV", BLUE), ("chn", "CHANNEL", BLUE)],
              [("add", "+ ADD TO GROUP", GREEN)],
              [("close", "CLOSE", RED)]]},
    {"name": "جاري التشغيل (أيقونات)", "head": "「 جاري التشغيل 」", "bullet": "✦ ", "sep": " ⇜ ",
     "labels": ("الاسم", "المدة", "الطلب"),
     "rows": [[("pause", "⏸", BLUE), ("resume", "▶", GREEN), ("skip", "⏭", BLUE), ("stop", "⏹", RED)],
              [("dev", "المطور", BLUE), ("chn", "القناة", BLUE)],
              [("close", "إغلاق", RED)]]},
    {"name": "عربي | English", "head": "♪ NOW PLAYING | تشغيل الآن", "bullet": "◈ ", "sep": " : ",
     "labels": ("Song | الاسم", "Time | المدة", "By | الطالب"),
     "rows": [[("stop", "STOP | إيقاف", RED), ("resume", "RESUME | استكمال", GREEN)],
              [("pause", "PAUSE | مؤقت", BLUE), ("skip", "SKIP | تخطي", BLUE)],
              [("dev", "DEV | المطور", BLUE), ("chn", "CH | القناة", BLUE)],
              [("close", "CLOSE | إغلاق", RED)]]},
    {"name": "تحكم موسّع", "head": "◉ لوحة التحكم | يعمل الآن", "bullet": "⌯ ", "sep": ": ",
     "labels": ("العنوان", "المدة", "الطالب"),
     "rows": [[("back", "⏪ 10", BLUE), ("pause", "⏸", BLUE), ("fwd", "10 ⏩", BLUE)],
              [("skip", "⏭ تخطي", BLUE), ("stop", "⏹ إيقاف", RED)],
              [("loop", "🔁 تكرار", BLUE), ("queue", "📜 الطابور", BLUE)],
              [("dev", "المطور", BLUE), ("chn", "القناة", BLUE)],
              [("close", "✖ إغلاق", RED)]]},
    {"name": "الافتراضية (تحكم كامل)", "classic": True},
]


def tpl_field(slot, bullet, label, sep, value):
    """سطر حقل في الكليشة. إن وضع المطور ايموجي مميزًا لهذا الحقل حلّ محل الرمز."""
    eid = db["emoji"].get("f:" + slot) or db["emoji"].get("f:*")
    mark = custom_emoji(eid) + " " if eid else bullet
    return f"{mark}{label}{sep}{value}"


def tpl_text(idx, d):
    """نص الكليشة رقم idx من بيانات التشغيل d."""
    t = TEMPLATES[idx]
    song, length, by = t["labels"]
    lines = [t["head"], "",
             tpl_field("song", t["bullet"], song, t["sep"], esc(d["title"])),
             tpl_field("duration", t["bullet"], length, t["sep"], d["dur"]),
             tpl_field("by", t["bullet"], by, t["sep"], d["by"]), ""]
    if d["paused"]:
        lines.append("⏸ متوقف مؤقتًا")
    lines.append(d["bar"])
    if d["queue"]:
        lines.append(f"في الانتظار: {d['queue']}")
    if d["loop"]:
        lines.append("التكرار: مفعّل")
    return "\n".join(lines)


def tpl_button(child, tok, label, style, cid, loop, preview):
    if tok in TPL_ACTS:
        if tok == "loop" and loop:
            label, style = label + " ✓", GREEN
        return b(label, "ow:tpn" if preview else f"mu:{tok}:{cid}", style=style, k=TPL_ACTS[tok])
    cr = effective_credits(child.rec)
    if tok == "dev":
        return b(label, url=cr["dev_url"], style=style, k="mu_dev") if cr["dev_url"] else None
    if tok == "chn":
        url = cr["updates_url"] or cr["source_url"]
        return b(label, url=url, style=style, k="mu_updates") if url else None
    if tok == "add" and child.username:
        url = f"https://t.me/{child.username}?startgroup=true&admin=manage_video_chats+invite_users+delete_messages"
        return b(label, url=url, style=style, k="mu_add")
    return None


def tpl_markup(child, idx, cid, loop=False, preview=False):
    """أزرار الكليشة. في المعاينة تكون أزرار التحكم بلا أثر."""
    rows = []
    for row in TEMPLATES[idx]["rows"]:
        btns = [x for x in (tpl_button(child, tok, label, style, cid, loop, preview)
                            for tok, label, style in row) if x]
        if btns:
            rows.append(btns)
    mk = make_button()
    if mk:
        rows.append([mk])
    return kb(rows)


class Player:
    """حالة التشغيل في مجموعة واحدة."""

    def __init__(self, child, cid):
        self.child, self.cid = child, cid
        self.queue, self.current = [], None
        self.loop = self.paused = self.busy = False
        self.lock = asyncio.Lock()
        self.base, self.t0 = 0.0, None        # الموضع بالثواني عند آخر بداية أو استئناف
        self.started_at = self.last_edit = 0.0
        self.panels = []                      # [(chat_id, message_id, هل هي صورة)]
        self.volume = child.cfg["volume"]

    def position(self):
        if self.current is None:
            return 0
        run = time.monotonic() - self.t0 if (self.t0 is not None and not self.paused) else 0
        pos = self.base + run
        return min(pos, self.current.dur) if self.current.dur else pos


class Sent:
    """رسالة أرسلها البوت (نصية أو ملصق) يمكن تعديلها أو حذفها."""

    def __init__(self, child, chat, mid, sticker=False, reply_to=None):
        self.child, self.chat, self.mid = child, chat, mid
        self.sticker, self.reply_to = sticker, reply_to

    async def edit(self, text):
        if self.sticker:                       # الملصق لا يُعدَّل: نحذفه ونرسل النص مكانه
            await self.delete()
            new = await self.child.say(self.chat, text, self.reply_to)
            self.mid, self.sticker = new.mid, False
        elif self.mid:
            await self.child.api("editMessageText", chat_id=self.chat, message_id=self.mid,
                                 text=deco(text, "music"), parse_mode="HTML", disable_web_page_preview=True)

    async def progress(self, text):
        """تحديث حالة أثناء العمل: الملصق يبقى ظاهرًا ولا يُستبدل بنص."""
        if not self.sticker:
            await self.edit(text)

    async def delete(self):
        if self.mid:
            await self.child.api("deleteMessage", chat_id=self.chat, message_id=self.mid)


PRESETS = {"max_min": [5, 10, 15, 30, 60, 120], "queue_limit": [5, 10, 20, 50], "volume": [50, 100, 150, 200],
           "progress_sec": [5, 10, 15, 30], "blur": [0, 4, 8, 14, 22]}
ACCESS_MODES = {"all": "الجميع", "mixed": "الطلب للجميع والتحكم للمشرفين", "admins": "المشرفون فقط"}

USER_GUIDE = (
    "<b>طريقة الاستخدام</b>\n\n"
    "1. أضف البوت إلى مجموعتك واجعله مشرفًا (صلاحية دعوة المستخدمين وإدارة المحادثات المرئية).\n"
    "2. اكتب في المجموعة:\n"
    "- <code>شغل اسم الأغنية</code>: تشغيلها في المحادثة المرئية (تُفتح تلقائيًا إن لم تكن قائمة).\n"
    "- <code>شغل اسم الأغنية مع الفيديو</code>: بالصورة والصوت.\n"
    "- <code>يوت اسم الأغنية</code>: تحميلها وإرسالها كملف صوتي.\n"
    "3. التحكم: تخطي، وقف (إيقاف مؤقت)، استكمال، ايقاف (إيقاف الموسيقى)، تكرار، قائمة، الان، "
    "تقديم 30، رجوع 30، صوت 80.\n"
    "4. عند بدء التشغيل تظهر لوحة أزرار مع شريط تقدم يتحدث تلقائيًا."
)

OWNER_GUIDE = (
    "<b>دليل مالك البوت</b>\n\n"
    "1. <b>الحساب المساعد</b>: سجّل حسابًا (يفضل حساب مخصص) برقمه والكود. هو الذي يدخل المحادثات المرئية.\n"
    "2. أضف البوت إلى مجموعتك واجعله مشرفًا، أو عطّل «Group Privacy» من BotFather ليرى أوامر الأعضاء. "
    "يدخل الحساب المساعد المجموعة تلقائيًا عند أول طلب (البوت يحتاج صلاحية دعوة المستخدمين).\n"
    "3. <b>الإعدادات</b>: الصلاحيات، أقصى مدة، الطابور، الصوت، الفيديو، أمر يوت، المغادرة التلقائية.\n"
    "4. <b>الحقوق</b>: حسب إعداد المطور قد تستطيع وضع حقوقك (المطور وقناة التحديثات وقناة السورس). "
    "تعود حقوق المطور تلقائيًا بعد 7 أيام.\n"
    "5. <b>المجموعات</b>: تشغيل الميوزك أو إيقافه في كل مجموعة.\n"
    "6. <b>كليشات التشغيل</b> لاختيار شكل لوحة التشغيل، و<b>ملصق الانتظار</b> و<b>صورة اللوحة</b> (مع التشويش) و<b>رسالة الترحيب</b> و<b>الإذاعة</b> و<b>الإحصائيات</b>."
)




# ------------------------------------------------------------------ لوحة المالك
PANELS_DIR = "panels"
INFO_FIELDS = {"name": ("اسم البوت", 64), "desc": ("وصف البوت", 512), "about": ("النبذة", 120),
               "photo": ("صورة البوت", 0)}
CREDIT_FIELDS = {"dev_name": "اسم زر المطور", "dev_url": "رابط المطور",
                 "updates_url": "قناة التحديثات", "source_url": "قناة السورس"}


class OwnerPanel:
    """لوحة مالك البوت المصنوع: كل ما يخص بوته، يظهر له وحده (وللمطور) داخل بوته."""

    # ---------------- الرئيسية
    def owner_text(self):
        r = self.rec
        mode, days = credits_mode(r), credits_days_left(r)
        if mode == "dev":
            credits_line = "حقوق المطور (مقفلة)"
        elif r["credits"] and days is not None:
            credits_line = f"حقوقك مفعّلة، وتعود حقوق المطور بعد {days} يوم"
        else:
            credits_line = "حقوق المطور (يمكنك تغييرها)"
        playing = sum(1 for p in self.players.values() if p.current)
        return ("<b>لوحة مالك البوت</b>\n\n"
                f"البوت: @{esc(self.username)} ({esc(r['name'])})\n"
                f"الحساب المساعد: {self.account_line()}\n"
                f"المجموعات: <b>{len(r['groups'])}</b> | المستخدمون: <b>{len(r['people'])}</b>\n"
                f"التشغيلات: <b>{r['stats']['plays']}</b> | التحميلات: <b>{r['stats']['downloads']}</b>\n"
                f"يشتغل الآن في: <b>{playing}</b> مجموعة\n"
                f"الحقوق: {credits_line}" + trial_info(r))

    def owner_kb(self):
        rows = [
            [b("الحساب المساعد", "ow:acc", style="success"), b("الإعدادات", "ow:set", style="primary")],
            [b("المجموعات", "ow:grp:0", style="primary"), b("الإحصائيات", "ow:st:0", style="primary")],
            [b("الحقوق", "ow:cr", style="primary"), b("معلومات البوت", "ow:info", style="primary")],
            [b("الاشتراك الإجباري", "ow:ofs", style="primary"), b("إذاعة", "ow:bc", style="primary")],
            [b("وسائط الانتظار", "ow:stk", style="success"), b("صورة/GIF اللوحة", "ow:ph", style="success")],
            [b("كليشات التشغيل", "ow:tpl", style="success"), b("واجهة المستخدم", "us:home", style="primary")],
            [b("رسالة الترحيب", "ow:wel", style="primary"), b("صورة /start", "ow:ssm", style="success")],
            [b("دليل المالك", "ow:guide", style="primary"), b("رابط الدعوة", "ow:ref", style="success")],
            [b("✖", "x:close", style="danger")],
        ]
        return kb(rows)

    async def cb_home(self, c):
        await c.screen(self.owner_text(), self.owner_kb(), kind="owner")

    async def cb_owner_guide(self, c):
        await c.screen(OWNER_GUIDE, back_kb(None, "ow:home"), kind="guide")

    # ---------------- الحساب المساعد
    async def cb_acc(self, c):
        text = ("<b>الحساب المساعد</b>\n\n"
                f"الحالة: {self.account_line()}\n\n"
                "هذا الحساب هو الذي يدخل المحادثات المرئية ويشغّل الصوت والفيديو. "
                "يفضل حساب مخصص لا تستعمله في أمور أخرى.")
        if self.rec["session"]:
            rows = [[b("تسجيل خروج", "ow:logout", style="danger")]]
        else:
            rows = [[b("تسجيل الدخول", "ow:login", style="success")]]
        await c.screen(text, back_kb(rows, "ow:home"), kind="owner")

    async def cb_login(self, c):
        if self.rec["session"]:
            await self.cb_acc(c)
            return
        self.states[c.uid] = {"step": "phone"}
        await c.screen("أرسل رقم الحساب المساعد مع رمز الدولة:\nمثال: <code>+9647700000000</code>",
                       back_kb(None, "ow:acc"))

    async def cb_logout(self, c):
        await self.stop_userbot()
        self.rec["session"] = ""
        save()
        await self.cb_acc(c)

    async def step_phone(self, m, chat, uid, text, st):
        back = back_kb(None, "ow:acc")
        old = self.logins.pop(uid, None)
        if old:
            await old["c"].disconnect()
        phone = text.replace(" ", "")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except Exception as e:
            await client.disconnect()
            self.states.pop(uid, None)
            await self.show(chat, f"فشل إرسال الكود: <code>{esc(short(e))}</code>", back)
            return
        self.logins[uid] = {"c": client, "phone": phone, "hash": sent.phone_code_hash}
        self.states[uid] = {"step": "code"}
        await self.show(chat, "وصل كود التحقق على الحساب.\n\nأرسله <b>بينه شرطات</b> مثل: <code>1-2-3-4-5</code>\n"
                              "(تيليجرام يلغي الكود إذا أرسلته متصلًا)", back)

    async def step_login(self, m, chat, uid, text, st):
        login = self.logins.get(uid)
        if not login:
            self.states.pop(uid, None)
            return
        back = back_kb(None, "ow:acc")
        await self.api("deleteMessage", chat_id=chat, message_id=m["message_id"])    # فيه الكود أو كلمة المرور
        try:
            if st["step"] == "code":
                await login["c"].sign_in(login["phone"], re.sub(r"\D", "", text), phone_code_hash=login["hash"])
            else:
                await login["c"].sign_in(password=text)
        except SessionPasswordNeededError:
            self.states[uid] = {"step": "password"}
            await self.show(chat, "الحساب عليه تحقق بخطوتين، أرسل كلمة المرور:", back)
            return
        except Exception as e:
            await self.show(chat, f"خطأ: <code>{esc(short(e))}</code>\nحاول مرة أخرى.", back)
            return
        self.rec["session"] = login["c"].session.save()
        save()
        await login["c"].disconnect()
        self.logins.pop(uid, None)
        self.states.pop(uid, None)
        started = await self.start_userbot()
        await self.show(chat, "تم تسجيل الدخول وتشغيل الحساب المساعد." if started else "تم الحفظ لكن تعذر التشغيل.")
        await self.show(chat, self.owner_text(), self.owner_kb(), kind="owner")

    # ---------------- الإعدادات
    def settings_view(self):
        cfg = self.cfg
        on = lambda flag: "شغّال" if flag else "متوقف"
        text = ("<b>الإعدادات</b>\n\n"
                f"الصلاحيات: {ACCESS_MODES[cfg['access']]}\n"
                f"أقصى مدة للمقطع: {min(cfg['max_min'], G['max_min_cap'])} دقيقة (سقف المطور {G['max_min_cap']})\n"
                f"الطابور: {cfg['queue_limit']} | الصوت: {cfg['volume']}% | تحديث التقدم: {cfg['progress_sec']} ث\n"
                f"الفيديو: {on(cfg['video'])} | أمر يوت: {on(cfg['yt'])}\n"
                f"المغادرة التلقائية بعد انتهاء الطابور: {on(cfg['auto_leave'])}\n"
                f"تشويش صورة اللوحة: {cfg['blur']}")

        def flag(label, key):
            return b(f"{label}: {on(cfg[key])}", f"ow:tg:{key}", style="success" if cfg[key] else "danger")
        rows = [
            [b("الصلاحيات", "ow:tg:access", style="primary"),
             b(f"أقصى مدة: {min(cfg['max_min'], G['max_min_cap'])} د", "ow:tg:max_min", style="primary")],
            [b(f"الطابور: {cfg['queue_limit']}", "ow:tg:queue_limit", style="primary"),
             b(f"الصوت: {cfg['volume']}%", "ow:tg:volume", style="primary")],
            [b(f"تحديث التقدم: {cfg['progress_sec']} ث", "ow:tg:progress_sec", style="primary"),
             b(f"تشويش الصورة: {cfg['blur']}", "ow:tg:blur", style="primary")],
            [flag("الفيديو", "video"), flag("أمر يوت", "yt")],
            [flag("المغادرة التلقائية", "auto_leave")],
        ]
        return text, back_kb(rows, "ow:home")

    async def cb_settings(self, c, note=""):
        text, markup = self.settings_view()
        await c.screen(note + text, markup, kind="owner")

    async def cb_toggle(self, c):
        key, cfg, note = c.parts[2] if len(c.parts) > 2 else "", self.cfg, ""
        if key == "access":
            keys = list(ACCESS_MODES)
            cfg["access"] = keys[(keys.index(cfg["access"]) + 1) % len(keys)]
        elif key == "max_min":
            options = [x for x in PRESETS["max_min"] if x <= G["max_min_cap"]] or [G["max_min_cap"]]
            cfg["max_min"] = next_preset(options, min(cfg["max_min"], G["max_min_cap"]))
        elif key in ("queue_limit", "volume", "progress_sec", "blur"):
            cfg[key] = next_preset(PRESETS[key], cfg[key])
            if key == "blur" and os.path.exists(self.panel_src()):
                done = await self.rebuild_panel_photo(c.chat)
                note = "تم تطبيق التشويش على الصورة.\n\n" if done else "تعذر تطبيق التشويش على الصورة.\n\n"
        elif key in ("video", "yt", "auto_leave"):
            cfg[key] = not cfg[key]
        save()
        await self.cb_settings(c, note)

    # ---------------- المجموعات
    async def cb_groups(self, c):
        page = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else 0
        items = sorted(self.rec["groups"].items(), key=lambda kv: kv[1]["title"].lower())
        pages = max(1, math.ceil(len(items) / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        rows = [[b(("مطفأ: " if g["off"] else "شغّال: ") + g["title"][:26], f"ow:gt:{cid}:{page}",
                   style="danger" if g["off"] else "success")]
                for cid, g in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
        nav = []
        if page > 0:
            nav.append(b("السابق", f"ow:grp:{page - 1}", style="primary"))
        if page < pages - 1:
            nav.append(b("التالي", f"ow:grp:{page + 1}", style="primary"))
        if nav:
            rows.append(nav)
        text = (f"<b>المجموعات</b>\nالعدد: <b>{len(items)}</b> | الصفحة {page + 1} من {pages}\n"
                "اضغط على المجموعة لتشغيل الميوزك فيها أو إيقافه.")
        if not items:
            text += "\n\nلا توجد مجموعات بعد. أضف البوت إلى مجموعتك."
        await c.screen(text, back_kb(rows, "ow:home"), kind="owner")

    async def cb_group_toggle(self, c):
        cid, page = c.parts[2], c.parts[3] if len(c.parts) > 3 else "0"
        g = self.rec["groups"].get(cid)
        if g:
            g["off"] = not g["off"]
            save()
            if g["off"]:
                await self.music_stop(int(cid))
        c.parts = ["ow", "grp", page]
        await self.cb_groups(c)

    # ---------------- الإحصائيات
    async def cb_stats(self, c):
        page = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else 0
        text, markup = people_view(self.rec["people"], page, "ow:st", "ow:home", "إحصائيات مستخدمي بوتك")
        await c.screen(text, markup, kind="owner")

    # ---------------- الحقوق
    def credits_view(self):
        r = self.rec
        mode, cr, days = credits_mode(r), effective_credits(r), credits_days_left(r)
        lines = ["<b>الحقوق</b>", "",
                 "الوضع: " + ("حقوق المطور (مقفلة، لا يمكن تغييرها)" if mode == "dev"
                              else "حقوق المستخدم (يمكنك تغييرها)"), "",
                 f"اسم زر المطور: {esc(cr['dev_name'] or 'غير محدد')}",
                 f"رابط المطور: {esc(cr['dev_url'] or 'غير محدد')}",
                 f"قناة التحديثات: {esc(cr['updates_url'] or 'غير محددة')}",
                 f"قناة السورس: {esc(cr['source_url'] or 'غير محددة')}"]
        rows = []
        if mode == "user":
            lines += ["", "تعود حقوق المطور تلقائيًا بعد 7 أيام من أول تعديل تجريه."]
            if r["credits"] and days is not None:
                lines.append(f"المتبقي حتى عودتها: <b>{days}</b> يوم")
            rows = [[b("اسم زر المطور", "ow:crf:dev_name", style="primary"),
                     b("رابط المطور", "ow:crf:dev_url", style="primary")],
                    [b("قناة التحديثات", "ow:crf:updates_url", style="primary"),
                     b("قناة السورس", "ow:crf:source_url", style="primary")]]
        return "\n".join(lines), back_kb(rows, "ow:home")

    async def cb_credits(self, c):
        text, markup = self.credits_view()
        await c.screen(text, markup, kind="owner")

    async def cb_credit_field(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        if credits_mode(self.rec) != "user" or key not in CREDIT_FIELDS:
            await self.cb_credits(c)
            return
        self.states[c.uid] = {"step": "crf", "field": key}
        hint = "اسمًا قصيرًا" if key == "dev_name" else "رابط تيليجرام (@name أو https://t.me/...)"
        await c.screen(f"أرسل {hint} لـ«{CREDIT_FIELDS[key]}».\nأرسل 0 لإعادته لقيمة المطور.", back_kb(None, "ow:cr"))

    async def step_credit(self, m, chat, uid, text, st):
        key, back = st["field"], back_kb(None, "ow:cr")
        if credits_mode(self.rec) != "user":
            self.states.pop(uid, None)
            return
        if text == "0":
            self.rec["credits"].pop(key, None)
        elif key == "dev_name":
            if not 1 <= len(text) <= 20:
                await self.show(chat, "الاسم من 1 إلى 20 حرفًا.", back)
                return
            self.rec["credits"][key] = text
        else:
            link = norm_link(text)
            if not link:
                await self.show(chat, "الرابط يجب أن يكون لتيليجرام: @name أو https://t.me/...", back)
                return
            self.rec["credits"][key] = link
        if any(k in self.rec["credits"] for k in CREDIT_FIELDS):
            self.rec["credits"].setdefault("set_at", now_ts())     # المهلة تبدأ من أول تعديل ولا تتجدد
        else:
            self.rec["credits"] = {}
        save()
        self.states.pop(uid, None)
        text_, markup = self.credits_view()
        await self.show(chat, "تم الحفظ.\n\n" + text_, markup, kind="owner")


    # ---------------- الملصق والصورة والترحيب
    async def cb_stk(self, c):
        self.states[c.uid] = {"step": "stk"}
        await c.screen("أرسل ملصقًا أو صورة أو GIF ليردّ به البوت أثناء البحث والتحميل بدل رسالة «جاري البحث».\n"
                       f"يمكنك إرسال عدة ملصقات (حتى 10) ويختار البوت منها عشوائيًا. المضاف الآن: "
                       f"<b>{len(self.cfg['stickers'])}</b>\nأرسل 0 لمسح الملصقات.", back_kb(None, "ow:home"))

    async def step_sticker(self, m, chat, uid, text, st):
        back, stickers = back_kb(None, "ow:home"), self.cfg["stickers"]
        if text == "0":
            stickers.clear()
            save()
            self.states.pop(uid, None)
            await self.show(chat, "تم مسح الملصقات.", back)
            return
        if m.get("sticker"):
            item = {"t": "sticker", "id": m["sticker"]["file_id"]}
        elif m.get("animation"):
            item = {"t": "animation", "id": m["animation"]["file_id"]}
        elif m.get("photo"):
            item = {"t": "photo", "id": m["photo"][-1]["file_id"]}
        else:
            await self.show(chat, "أرسل ملصقًا أو صورة أو GIF، أو 0 للمسح.", back)
            return
        known = [x if isinstance(x, str) else x["id"] for x in stickers]
        if item["id"] not in known:
            if len(stickers) >= 10:
                await self.show(chat, "وصلت للحد الأقصى (10). أرسل 0 لمسحها أولًا.", back)
                return
            stickers.append(item)
            save()
        await self.show(chat, f"تمت الإضافة. عدد الملصقات: <b>{len(stickers)}</b>\nأرسل ملصقًا آخر أو ارجع.", back)

    def panel_src(self):
        os.makedirs(PANELS_DIR, exist_ok=True)
        return os.path.join(PANELS_DIR, f"{self.rec['id']}.jpg")

    async def rebuild_panel_photo(self, chat):
        """يطبّق التشويش على الصورة الأصلية ويرفعها مرة واحدة ليأخذ file_id نعيد استعماله مع كل لوحة."""
        if not os.path.exists(self.panel_src()):
            return False
        try:
            data = await run_blocking(_blur_image, self.panel_src(), self.cfg["blur"])
        except Exception as e:
            log.warning("blur: %s", e)
            return False
        d = await self.api.upload("sendPhoto", "photo", data, "panel.jpg", chat_id=chat)
        if not d.get("ok"):
            return False
        self.cfg["panel_photo"] = d["result"]["photo"][-1]["file_id"]
        save()
        await self.api("deleteMessage", chat_id=chat, message_id=d["result"]["message_id"])
        return True

    async def cb_ph(self, c):
        self.states[c.uid] = {"step": "ph"}
        await c.screen("أرسل الصورة أو الـ GIF الذي يظهر في لوحة التشغيل.\n"
                       f"تُطبَّق عليها درجة التشويش الحالية ({self.cfg['blur']}) ويمكنك تغييرها من الإعدادات "
                       "(0 = بدون تشويش).\nأرسل 0 لإزالة الصورة.", back_kb(None, "ow:home"))

    async def step_photo(self, m, chat, uid, text, st):
        back = back_kb(None, "ow:home")
        if text == "0":
            if os.path.exists(self.panel_src()):
                os.remove(self.panel_src())
            self.cfg["panel_photo"] = ""
            self.cfg["panel_gif"] = ""
            save()
            self.states.pop(uid, None)
            await self.show(chat, "تمت إزالة صورة اللوحة.", back)
            return
        if m.get("animation"):
            if os.path.exists(self.panel_src()):
                os.remove(self.panel_src())
            self.cfg["panel_gif"], self.cfg["panel_photo"] = m["animation"]["file_id"], ""
            save()
            self.states.pop(uid, None)
            await self.show(chat, "تم حفظ الـ GIF وسيظهر في لوحة التشغيل.", back)
            return
        if not m.get("photo"):
            await self.show(chat, "أرسل صورة أو GIF (وليس ملفًا)، أو 0 للإزالة.", back)
            return
        raw = await self.api.download(m["photo"][-1]["file_id"])
        if not raw:
            await self.show(chat, "تعذر جلب الصورة من تيليجرام.", back)
            return
        with open(self.panel_src(), "wb") as f:
            f.write(raw)
        self.states.pop(uid, None)
        self.cfg["panel_gif"] = ""
        done = await self.rebuild_panel_photo(chat)
        await self.show(chat, "تم حفظ صورة اللوحة وتطبيق التشويش عليها." if done
                        else "تعذر معالجة الصورة (تأكد أن مكتبة pillow مثبتة).", back)

    async def cb_wel(self, c):
        self.states[c.uid] = {"step": "wel"}
        await c.screen("أرسل نص رسالة الترحيب التي يراها المستخدمون عند /start (حتى 700 حرف).\n"
                       "أرسل 0 للعودة للنص الافتراضي.", back_kb(None, "ow:home"))

    async def step_welcome(self, m, chat, uid, text, st):
        back = back_kb(None, "ow:home")
        if text != "0" and not 1 <= len(text) <= 700:
            await self.show(chat, "النص من 1 إلى 700 حرف.", back)
            return
        self.rec["welcome"] = "" if text == "0" else esc(text)
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم حفظ رسالة الترحيب.", back)

    # ---------------- كليشات التشغيل
    def tpl_nav(self, idx):
        n = len(TEMPLATES)
        done = idx == self.tpl_current()
        return kb([[b("السابق", f"ow:tpl:{(idx - 1) % n}", style="primary"),
                    b(f"{idx + 1}/{n}", "ow:tpn", style="primary"),
                    b("التالي", f"ow:tpl:{(idx + 1) % n}", style="primary")],
                   [b("✓ الكليشة الحالية" if done else "تطبيق", f"ow:tplok:{idx}", style="success")],
                   [b("رجوع", "ow:tplx", style="primary")]])

    async def drop_tpl_view(self, c):
        """يحذف رسالة المعاينة ورسالة التنقل المفتوحتين."""
        for mid in {c.reply_mid, self.tpl_views.pop(c.uid, None), c.mid} - {None}:
            await self.api("deleteMessage", chat_id=c.chat, message_id=mid)

    @staticmethod
    def tpl_arg(c, default):
        try:
            idx = int(c.parts[2])
        except (IndexError, ValueError):
            idx = default
        return max(0, min(idx, len(TEMPLATES) - 1))

    async def cb_tpl(self, c):
        """معاينة كليشة: رسالة بصورتها وأزرارها، وتحتها رسالة السابق/التالي/تطبيق."""
        idx = self.tpl_arg(c, self.tpl_current())
        await self.drop_tpl_view(c)
        res = await self.send_with_media(c.chat, self.render_text(idx, self.tpl_sample(c.user)),
                                         self.render_kb(idx, 0, preview=True), tpl=idx, preview=True)
        extra = {}
        if res:
            self.tpl_views[c.uid] = res[0]
            extra = dict(reply_to_message_id=res[0], allow_sending_without_reply=True)
        await self.api("sendMessage", chat_id=c.chat, text="هل تريد تعيين هذه الكليشه؟", parse_mode="HTML",
                       reply_markup=self.tpl_nav(idx), **extra)

    async def cb_tpl_ok(self, c):
        idx = self.tpl_arg(c, self.tpl_current())
        self.cfg["tpl"] = idx
        save()
        await self.api("editMessageText", chat_id=c.chat, message_id=c.mid, parse_mode="HTML",
                       text=f"تم تعيين الكليشه <b>{idx + 1}</b> بنجاح ✓\nتظهر في التشغيلات الجديدة.",
                       reply_markup=self.tpl_nav(idx))

    async def cb_tpl_back(self, c):
        await self.drop_tpl_view(c)
        await self.show(c.chat, self.owner_text(), self.owner_kb(), kind="owner")

    async def cb_noop(self, c):
        pass

    # ---------------- الإذاعة
    async def cb_bc(self, c):
        self.states[c.uid] = {"step": "bc"}
        await c.screen(f"<b>الإذاعة</b>\n\nأرسل الرسالة التي تريد إرسالها إلى مستخدمي بوتك "
                       f"(<b>{len(self.rec['known'])}</b> مستخدم)، بأي تنسيق.", back_kb(None, "ow:home"))

    async def step_bc(self, m, chat, uid, text, st):
        self.states[uid] = {"step": "bcconfirm", "mid": m["message_id"], "chat": chat}
        await self.show(chat, f"<b>تأكيد الإذاعة</b>\n\nعدد المستلمين: <b>{len(self.bc_targets())}</b>\n"
                              "سيُرسل لهم نفس رسالتك أعلاه كما هي. هل تؤكد؟",
                        back_kb([[b("تأكيد الإرسال", "ow:bcgo", style="success")]], "ow:home"))

    def bc_targets(self):
        return [u for u in self.rec["known"] if u != self.rec["owner"]]

    async def cb_bcgo(self, c):
        st = self.states.get(c.uid)
        if not st or st.get("step") != "bcconfirm":
            return
        if self.bc_busy:
            await c.screen("هناك إذاعة قيد الإرسال الآن، انتظر انتهاءها.", back_kb(None, "ow:home"))
            return
        targets = self.bc_targets()
        self.states.pop(c.uid, None)
        await c.screen(f"بدأت الإذاعة إلى <b>{len(targets)}</b> مستخدم، وسيصلك تقرير عند الانتهاء.",
                       back_kb(None, "ow:home"))

        async def run():
            self.bc_busy = True
            try:
                await broadcast(self.api, targets, st["chat"], st["mid"], c.chat)
            finally:
                self.bc_busy = False
        self.spawn(run())

    # ---------------- صورة /start
    async def cb_ssm(self, c):
        self.states[c.uid] = {"step": "ssm"}
        await c.screen("أرسل الصورة أو الـ GIF الذي يظهر مع رسالة /start في بوتك.\nأرسل 0 لإزالته.",
                       back_kb(None, "ow:home"))

    async def step_start_media(self, m, chat, uid, text, st):
        back = back_kb(None, "ow:home")
        if text == "0":
            self.cfg["start_media"] = None
        elif m.get("animation"):
            self.cfg["start_media"] = {"t": "animation", "id": m["animation"]["file_id"]}
        elif m.get("photo"):
            self.cfg["start_media"] = {"t": "photo", "id": m["photo"][-1]["file_id"]}
        else:
            await self.show(chat, "أرسل صورة أو GIF، أو 0 للإزالة.", back)
            return
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم الحفظ." if self.cfg["start_media"] else "تمت الإزالة.", back)

    async def send_start(self, chat, uid=None):
        """رسالة /start: بصورة أو GIF المالك إن وُجدت. المالك يراها كالمستخدمين مع زر «لوحة المالك»."""
        m = self.cfg.get("start_media")
        greet = "<b>أهلًا بك مطوري العزيز</b>\n\n" if uid and is_dev(uid) else ""
        body, markup = greet + self.start_text(), self.start_kb(uid)
        text = deco(body, "start")
        if m and len(text) <= 1000:
            method = "sendPhoto" if m["t"] == "photo" else "sendAnimation"
            d = await self.api(method, chat_id=chat, **{m["t"]: m["id"]}, caption=text, parse_mode="HTML",
                               reply_markup=markup)
            if d.get("ok"):
                return
        await self.show(chat, body, markup, kind="start")

    # ---------------- رابط الدعوة
    async def cb_ref(self, c):
        owner = self.rec["owner"]
        text = ("<b>رابط الدعوة</b>\n\n"
                f"مدة التشغيل {G['trial_days']} أيام وتتجدد تلقائيًا عند دعوة <b>{G['ref_need']}</b> أعضاء جدد "
                f"إلى صانع البوتات عبر رابطك:\n<code>{ref_link(owner)}</code>\n\n"
                f"المدعوون الآن: <b>{owner_refs(owner)}</b> من {G['ref_need']}"
                + trial_info(self.rec))
        await c.screen(text, back_kb([[b("مشاركة الرابط", url=share_url(owner), style="success")]], "ow:home"),
                       kind="owner")

    # ---------------- معلومات البوت
    async def cb_info(self, c):
        text = ("<b>معلومات البوت</b>\n\n"
                f"الاسم الحالي: {esc(self.rec['name'])}\n"
                "غيّر اسم بوتك ووصفه ونبذته وصورته الشخصية، وتظهر للمستخدمين فورًا.")
        rows = [[b("تغيير الاسم", "ow:inf:name", style="primary"), b("تغيير الوصف", "ow:inf:desc", style="primary")],
                [b("تغيير النبذة", "ow:inf:about", style="primary"), b("تغيير الصورة", "ow:inf:photo", style="primary")]]
        await c.screen(text, back_kb(rows, "ow:home"), kind="owner")

    async def cb_info_field(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        if key not in INFO_FIELDS:
            await self.cb_info(c)
            return
        self.states[c.uid] = {"step": "inf", "field": key}
        label, limit = INFO_FIELDS[key]
        if key == "photo":
            hint = "أرسل الصورة الجديدة."
        else:
            hint = f"أرسل {label} الجديد (حتى {limit} حرفًا)." + ("" if key == "name" else "\nأرسل 0 لإزالته.")
        await c.screen(f"<b>{label}</b>\n\n{hint}", back_kb(None, "ow:info"))

    async def step_info(self, m, chat, uid, text, st):
        key, back = st["field"], back_kb(None, "ow:info")
        if key == "photo":
            if not m.get("photo"):
                await self.show(chat, "أرسل صورة (وليس ملفًا).", back)
                return
            raw = await self.api.download(m["photo"][-1]["file_id"])
            if not raw:
                await self.show(chat, "تعذر جلب الصورة من تيليجرام.", back)
                return
            d = await self.api.profile_photo(raw)
        else:
            label, limit = INFO_FIELDS[key]
            clear = text == "0" and key != "name"
            if not clear and not 1 <= len(text) <= limit:
                await self.show(chat, f"النص من 1 إلى {limit} حرفًا.", back)
                return
            method = {"name": "setMyName", "desc": "setMyDescription", "about": "setMyShortDescription"}[key]
            param = {"name": "name", "desc": "description", "about": "short_description"}[key]
            d = await self.api(method, **{param: "" if clear else text})
            if d.get("ok") and key == "name":
                self.rec["name"] = text
                save()
        if not d.get("ok"):
            await self.show(chat, f"تعذر التحديث:\n<code>{esc(short(d.get('description') or 'خطأ'))}</code>", back)
            return
        self.states.pop(uid, None)
        await self.show(chat, "تم التحديث.", back)

    # ---------------- الاشتراك الإجباري الخاص بالبوت
    def ofs_view(self):
        own = self.cfg["forced"]
        lines = ["<b>الاشتراك الإجباري في بوتك</b>", "",
                 "أضف حتى 3 قنوات يشترك فيها المستخدمون قبل استخدام بوتك. "
                 "يجب أن يكون <b>بوتك</b> مشرفًا في القناة ليفحص الاشتراك.",
                 f"قنوات المطور الإجبارية (ثابتة ولا تُحذف): <b>{len(G['forced'])}</b>", ""]
        rows = []
        for i, ch in enumerate(own):
            warn = " (البوت ليس مشرفًا هناك)" if ch.get("broken") else ""
            lines.append(f"{i + 1}. {esc(ch.get('title') or ch['chat'])}{warn}")
            rows.append([b(f"حذف: {(ch.get('title') or str(ch['chat']))[:24]}", f"ow:ofsdel:{i}", style="danger")])
        if not own:
            lines.append("لا توجد قنوات مضافة.")
        if len(own) < 3:
            rows.insert(0, [b("إضافة قناة", "ow:ofsadd", style="success")])
        return "\n".join(lines), back_kb(rows, "ow:home")

    async def cb_ofs(self, c):
        text, markup = self.ofs_view()
        await c.screen(text, markup, kind="owner")

    async def cb_ofsadd(self, c):
        self.states[c.uid] = {"step": "ofs_add"}
        await c.screen("أرسل يوزر القناة (<code>@name</code>) أو رابطها، أو حوّل رسالة منها.\n"
                       "للقناة الخاصة أرسل ايديها ثم رابط الدعوة بعده بمسافة.\nتأكد أن بوتك مشرف فيها.",
                       back_kb(None, "ow:ofs"))

    async def step_ofs_add(self, m, chat, uid, text, st):
        back = back_kb(None, "ow:ofs")
        if len(self.cfg["forced"]) >= 3:
            self.states.pop(uid, None)
            await self.show(chat, "الحد الأقصى 3 قنوات.", back)
            return
        ch, err = await resolve_channel(self.api, m, text, self.rec["id"])
        if err:
            await self.show(chat, err, back)
            return
        ch["own"] = True
        self.cfg["forced"].append(ch)
        save()
        _sub_cache.clear()
        self.states.pop(uid, None)
        text_, markup = self.ofs_view()
        await self.show(chat, ("تمت الإضافة.\n\n" if not ch["broken"]
                               else "تمت الإضافة، لكن بوتك ليس مشرفًا فيها فلن يعمل الفحص.\n\n") + text_,
                        markup, kind="owner")

    async def cb_ofsdel(self, c):
        idx = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else -1
        if 0 <= idx < len(self.cfg["forced"]):
            self.cfg["forced"].pop(idx)
            save()
            _sub_cache.clear()
        await self.cb_ofs(c)


# ------------------------------------------------------------------ البوت المصنوع
class Child(OwnerPanel, App):
    allowed = ["message", "callback_query", "my_chat_member"]

    def __init__(self, rec):
        super().__init__(rec["token"])
        self.rec, self.cfg = rec, rec["cfg"]
        self.username = rec.get("username", "")
        self.players = {}                # chat_id -> Player
        self.in_call = set()             # المجموعات التي يوجد فيها الحساب المساعد في مكالمة
        self.joined = set()              # المجموعات التي دخلها الحساب المساعد
        self.ub = self.calls = self.me = None
        self.logins = {}
        self.leave_tasks = {}
        self.admin_cache = {}
        self.last_request = {}
        self.bc_busy = False
        self.media_ids = {}
        self.tpl_views = {}              # uid -> رسالة معاينة الكليشة المفتوحة
        self.steps = {
            "phone": self.step_phone, "code": self.step_login, "password": self.step_login,
            "stk": self.step_sticker, "ph": self.step_photo, "wel": self.step_welcome,
            "bc": self.step_bc, "crf": self.step_credit, "ofs_add": self.step_ofs_add, "inf": self.step_info, "ssm": self.step_start_media,
        }
        self.routes = {
            "home": self.cb_home, "acc": self.cb_acc, "login": self.cb_login, "logout": self.cb_logout,
            "set": self.cb_settings, "tg": self.cb_toggle, "grp": self.cb_groups, "gt": self.cb_group_toggle,
            "st": self.cb_stats, "cr": self.cb_credits, "crf": self.cb_credit_field,
            "stk": self.cb_stk, "ph": self.cb_ph, "wel": self.cb_wel, "bc": self.cb_bc, "bcgo": self.cb_bcgo,
            "guide": self.cb_owner_guide, "info": self.cb_info, "inf": self.cb_info_field,
            "ofs": self.cb_ofs, "ofsadd": self.cb_ofsadd, "ofsdel": self.cb_ofsdel, "ref": self.cb_ref, "ssm": self.cb_ssm,
            "tpl": self.cb_tpl, "tplok": self.cb_tpl_ok, "tplx": self.cb_tpl_back, "tpn": self.cb_noop,
        }

    # ---------------- دورة الحياة
    async def start(self):
        me = await self.api("getMe")
        if not me.get("ok"):
            self.rec["status"] = "token_invalid"
            save()
            return False
        info = me["result"]
        self.username = info.get("username", "")
        self.rec.update(username=self.username, name=info.get("first_name", ""), status="running")
        self.running = True
        if self.rec["session"]:
            await self.start_userbot()
        self.spawn(self.poll())
        save_soon()
        return True

    async def stop(self):
        self.running = False
        for task in list(self.tasks) + list(self.leave_tasks.values()):
            task.cancel()
        self.leave_tasks.clear()
        await self.stop_userbot()

    async def on_dead(self):
        """التوكن لم يعد صالحًا (حُذف أو أُعيد توليده)."""
        self.running = False
        await MAIN.api("sendMessage", chat_id=self.rec["owner"], parse_mode="HTML",
                       text=f"تم حذف البوت <b>@{esc(self.username)}</b> من تيليجرام (أو أُعيد توليد توكنه)، "
                            "فحُذف من الصانع تلقائيًا. يمكنك إنشاء بوت جديد في أي وقت.")
        asyncio.ensure_future(delete_bot(self.rec["id"]))

    def is_owner(self, uid):
        return uid == self.rec["owner"] or is_dev(uid)

    def remember(self, user, bot=False):
        uid = user.get("id")
        if bot and uid not in self.rec["known"]:
            self.rec["known"].append(uid)
        record_person(self.rec["people"], uid, tg_name(user), user.get("username") or "", bot=bot)

    def group_rec(self, chat):
        key = str(chat["id"])
        g = self.rec["groups"].get(key)
        if g is None:
            g = self.rec["groups"][key] = {"title": chat.get("title") or key, "username": chat.get("username"),
                                           "added": now_ts(), "off": False}
            save_soon()
        elif chat.get("title") and g["title"] != chat["title"]:
            g["title"], g["username"] = chat["title"], chat.get("username")
        return g

    def title_of(self, cid):
        g = self.rec["groups"].get(str(cid))
        return g["title"] if g else str(cid)

    def cap_seconds(self):
        return min(self.cfg["max_min"], G["max_min_cap"]) * 60

    # ---------------- الحساب المساعد
    async def start_userbot(self):
        await self.stop_userbot()
        if not self.rec["session"]:
            return False
        try:
            ub = TelegramClient(StringSession(self.rec["session"]), API_ID, API_HASH)
            await ub.connect()
            if not await ub.is_user_authorized():
                self.rec["session"] = ""
                save()
                await ub.disconnect()
                return False
            self.ub, self.me = ub, await ub.get_me()
            calls = PyTgCalls(ub)
            if call_filters:
                try:
                    @calls.on_update(call_filters.stream_end)
                    async def _ended(_, update):
                        await self.on_stream_end(update.chat_id)
                except Exception as e:
                    log.warning("stream_end: %s", e)
                try:
                    from pytgcalls.types import ChatUpdate
                    closed = (ChatUpdate.Status.CLOSED_VOICE_CHAT | ChatUpdate.Status.KICKED
                              | ChatUpdate.Status.LEFT_GROUP)

                    @calls.on_update(call_filters.chat_update(closed))
                    async def _closed(_, update):
                        await self.on_call_closed(update.chat_id)
                except Exception as e:
                    log.info("chat_update غير متوفر: %s", e)
            await calls.start()
            self.calls = calls
            self.spawn(self.warm_up(ub))
            return True
        except Exception as e:
            log.exception("start_userbot @%s: %s", self.username, e)
            self.ub = self.calls = None
            return False

    async def warm_up(self, client):
        try:
            async for _ in client.iter_dialogs(limit=300):
                pass
        except Exception as e:
            log.info("warm_up: %s", e)

    async def stop_userbot(self):
        for cid in list(self.in_call):
            try:
                await self.calls.leave_call(cid)
            except Exception:
                pass
        self.in_call.clear()
        self.players.clear()
        self.joined.clear()
        if self.ub:
            try:
                await self.ub.disconnect()
            except Exception:
                pass
        self.ub = self.calls = self.me = None

    def account_line(self):
        if self.me:
            user = f"@{self.me.username}" if getattr(self.me, "username", None) else "بدون يوزر"
            return f"متصل: {esc(utils.get_display_name(self.me))} ({esc(user)})"
        return "غير مسجل" if not self.rec["session"] else "مسجل لكن غير متصل"

    async def ensure_assistant(self, chat):
        """يتأكد أن الحساب المساعد داخل المجموعة، وإلا يدخلها (باليوزر أو برابط دعوة يصنعه البوت)."""
        cid = chat["id"]
        if cid in self.joined:
            return True
        try:
            await self.ub.get_permissions(cid, "me")
            self.joined.add(cid)
            return True
        except Exception:
            pass
        for attempt in range(2):
            try:
                if chat.get("username"):
                    await self.ub(functions.channels.JoinChannelRequest(chat["username"]))
                else:
                    link = (await self.api("exportChatInviteLink", chat_id=cid)).get("result") or ""
                    if not link:
                        return False
                    await self.ub(functions.messages.ImportChatInviteRequest(link.rsplit("/", 1)[-1].lstrip("+")))
                self.joined.add(cid)
                return True
            except Exception as e:
                name = type(e).__name__
                if "AlreadyParticipant" in name:
                    self.joined.add(cid)
                    return True
                if attempt == 0 and "Banned" in name and self.me:        # محظور من المجموعة: نرفع الحظر ونعيد
                    await self.api("unbanChatMember", chat_id=cid, user_id=self.me.id, only_if_banned=True)
                    continue
                log.warning("assistant join %s: %s", cid, short(e))
                return False
        return False

    async def get_call(self, cid):
        entity = await self.ub.get_entity(cid)
        if isinstance(entity, types.Channel):
            full = await self.ub(functions.channels.GetFullChannelRequest(entity))
        else:
            full = await self.ub(functions.messages.GetFullChatRequest(chat_id=entity.id))
        return full.full_chat.call

    async def prepare_chat(self, chat):
        """يدخل الحساب المساعد المجموعة ويفحص وجود محادثة مرئية (بالتوازي مع البحث). يرجع (دخل؟، توجد محادثة؟)."""
        if not await self.ensure_assistant(chat):
            return False, False
        try:
            return True, bool(await self.get_call(chat["id"]))
        except Exception:
            return True, False

    async def ensure_call(self, cid):
        """يتأكد من وجود محادثة مرئية في المجموعة، ويفتحها إن لم توجد (يحتاج الحساب المساعد صلاحية)."""
        try:
            if await self.get_call(cid):
                return True
            peer = await self.ub.get_input_entity(cid)
            await self.ub(functions.phone.CreateGroupCallRequest(peer=peer, random_id=random.randint(1, 2 ** 31 - 1)))
            await asyncio.sleep(1)
            return True
        except Exception as e:
            log.info("ensure_call %s: %s", cid, short(e))
            return False

    # ---------------- الرسائل
    async def say(self, cid, text, reply_to=None):
        params = dict(chat_id=cid, text=deco(text, "music"), parse_mode="HTML", disable_web_page_preview=True)
        if reply_to:
            params.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
        d = await self.api("sendMessage", **params)
        return Sent(self, cid, d["result"]["message_id"] if d.get("ok") else 0)

    async def send_item(self, chat, item, caption=None, markup=None, reply_to=None):
        """يرسل وسيطة (ملصق/صورة/GIF) من file_id أو من ملف محفوظ (ويخزّن file_id). يرجع الرسالة أو None."""
        kind = item["t"]
        method = {"photo": "sendPhoto", "animation": "sendAnimation", "sticker": "sendSticker"}[kind]
        params = {"chat_id": chat}
        if caption and kind != "sticker":
            params.update(caption=caption, parse_mode="HTML")
        if markup:
            params["reply_markup"] = markup
        if reply_to:
            params.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
        path = item.get("path")
        fid = item.get("id") or (self.media_ids.get(path) if path else None)
        d = {"ok": False}
        if fid:
            d = await self.api(method, **{kind: fid}, **params)
        if not d.get("ok") and path and os.path.exists(path):
            data = await run_blocking(_read_file, path)
            d = await self.api.upload(method, kind, data, os.path.basename(path), **params)
            if d.get("ok"):
                new_id = _media_file_id(d["result"], kind)
                if new_id:
                    self.media_ids[path] = new_id
        return d["result"] if d.get("ok") else None

    async def send_reply(self, cid, reply, reply_to):
        if reply["t"] == "text":
            await self.say(cid, reply["text"], reply_to)
        else:
            cap = deco(reply["text"], "music") if reply.get("text") else None
            await self.send_item(cid, reply, caption=cap, reply_to=reply_to)

    async def say_status(self, cid, text, reply_to=None):
        """رد أثناء البحث والتحميل: ملصق/صورة/GIF (للمالك أو للمطور)، وإلا رسالة نصية."""
        pool = self.cfg["stickers"] or G["media"]
        if pool:
            item = random.choice(pool)
            if isinstance(item, str):
                item = {"t": "sticker", "id": item}
            res = await self.send_item(cid, item, reply_to=reply_to)
            if res:
                return Sent(self, cid, res["message_id"], sticker=True, reply_to=reply_to)
        return await self.say(cid, text, reply_to)

    # ---------------- الاستقبال
    async def on_message(self, m):
        if m["chat"]["type"] == "private":
            await self.private_message(m)
        else:
            await self.group_message(m)

    async def on_callback(self, q):
        c = Ctx(self, q)
        self.remember(c.user, bot=bool(c.chat and c.chat > 0))
        if c.act == "mu":                              # أزرار لوحة التشغيل: الصلاحية تُفحص داخلها
            await self.cb_music(c)
        elif c.act == "fs":
            await self.cb_fs(c)
        elif c.act == "x":
            await self.cb_close(c)
        elif c.act == "us":
            await c.toast()
            if c.sub == "guide":
                await c.screen(USER_GUIDE, back_kb(None, "us:home"), kind="guide")
            else:
                await c.screen(self.start_text(), self.start_kb(c.uid), kind="start")
        elif c.act == "ow":
            if not self.is_owner(c.uid):
                await c.toast("هذه اللوحة لمالك البوت فقط", alert=True)
                return
            await c.toast()
            if self.rec.get("suspended") and not is_dev(c.uid):
                await c.screen(suspended_text(self.rec), suspended_kb(self.rec), kind="owner")
                return
            if c.sub not in ("crf", "login", "stk", "ph", "wel", "bc"):
                await self.reset_state(c.uid)
            route = self.routes.get(c.sub)
            if route:
                await route(c)

    async def reset_state(self, uid):
        self.states.pop(uid, None)
        pending = self.logins.pop(uid, None)
        if pending:
            await pending["c"].disconnect()

    async def after_subscribed(self, c):
        await c.screen(self.start_text(), self.start_kb(c.uid), kind="start")

    async def on_member(self, upd):
        chat = upd["chat"]
        if chat.get("type") == "private":
            return
        old = (upd.get("old_chat_member") or {}).get("status")
        new = (upd.get("new_chat_member") or {}).get("status")
        cid = chat["id"]
        if new in ("member", "administrator") and old in ("left", "kicked", None):
            self.group_rec(chat)
            save_soon()
            adder = upd.get("from") or {}
            greet = "<b>أهلًا بك مطوري العزيز</b>\n" if is_dev(adder.get("id", 0)) else ""
            await self.api("sendMessage", chat_id=cid, parse_mode="HTML",
                           text=deco(greet + "<b>أهلًا بكم</b>\nاجعلوني مشرفًا (دعوة المستخدمين وإدارة المحادثات المرئية) "
                                     "ثم اكتبوا: <code>شغل اسم الأغنية</code>", "start"),
                           reply_markup=kb([credit_buttons(self.rec)] if credit_buttons(self.rec) else []))
            link = f"https://t.me/{chat['username']}" if chat.get("username") else ""
            if not link:
                link = (await self.api("exportChatInviteLink", chat_id=cid)).get("result") or ""
            who = mention(adder["id"], tg_name(adder)) if adder.get("id") else "غير معروف"
            await self.api("sendMessage", chat_id=self.rec["owner"], parse_mode="HTML",
                           text=("<b>تمت إضافة البوت إلى مجموعة جديدة</b>\n\n"
                                 f"المجموعة: <b>{esc(chat.get('title', cid))}</b>\n"
                                 f"الايدي: <code>{cid}</code>\nأضافه: {who}"),
                           reply_markup=kb([[b("دخول المجموعة", url=link, style="success")]] if link else []))
        elif new in ("left", "kicked"):
            self.rec["groups"].pop(str(cid), None)
            await self.on_call_closed(cid)
            self.joined.discard(cid)
            save_soon()

    # ---------------- الخاص
    def start_text(self):
        return self.rec["welcome"] or (
            f"<b>أهلًا بك في {esc(self.rec['name'])}</b>\n\nبوت لتشغيل الأغاني والفيديو في المحادثات المرئية.\n"
            "أضفني إلى مجموعتك واجعلني مشرفًا، ثم اكتب: <code>شغل اسم الأغنية</code>")

    def start_kb(self, uid=None):
        add = f"https://t.me/{self.username}?startgroup=true&admin=manage_video_chats+invite_users+delete_messages"
        rows = [[b("أضفني إلى مجموعتك", url=add, style="success")],
                [b("طريقة الاستخدام", "us:guide", style="primary")]]
        if uid and self.is_owner(uid):
            rows.insert(0, [b("لوحة المالك", "ow:home", style="success")])
        if credit_buttons(self.rec):
            rows.append(credit_buttons(self.rec))
        if make_button():
            rows.append([make_button()])
        rows.append([b("✖", "x:close", style="danger")])
        return kb(rows)

    async def private_message(self, m):
        chat, user = m["chat"]["id"], m.get("from") or {}
        uid, text = user.get("id"), (m.get("text") or "").strip()
        if not uid:
            return
        self.remember(user, bot=True)
        if text.split("@")[0] == "/id":
            await self.api("sendMessage", chat_id=chat, parse_mode="HTML", text=f"ايديك: <code>{uid}</code>")
            return
        if self.rec.get("suspended") and not is_dev(uid):
            if self.is_owner(uid):
                await self.show(chat, suspended_text(self.rec), suspended_kb(self.rec), kind="owner")
            else:
                await self.show(chat, "<b>هذا البوت متوقف مؤقتًا.</b>", None, kind="start")
            return
        if text.startswith("/start") or text == "/panel":
            await self.reset_state(uid)
            if not await self.gate(uid, chat):
                return
            if text == "/panel" and self.is_owner(uid):
                greet = "<b>أهلًا بك مطوري العزيز</b>\n\n" if is_dev(uid) else ""
                await self.show(chat, greet + self.owner_text(), self.owner_kb(), kind="owner")
            else:
                await self.send_start(chat, uid)
            return
        st = self.states.get(uid)
        handler = self.steps.get(st["step"]) if st else None
        if handler and self.is_owner(uid):
            await handler(m, chat, uid, text, st)
        elif text.startswith("/"):
            await self.show(chat, self.start_text(), self.start_kb(uid), kind="start")

    # ---------------- أوامر المجموعة
    async def group_message(self, m):
        chat, user = m["chat"], m.get("from") or {}
        cid, uid = chat["id"], user.get("id")
        text = (m.get("text") or "").strip()
        if (not uid or not text or len(text) > 300 or user.get("is_bot") or not self.rec["enabled"]
                or self.rec.get("suspended")):
            return
        if G["replies"]:                                 # ردود المطور التلقائية (كلمة -> رد)
            rkey = norm_ar(text.lower()).strip()
            reply = next((r for r in G["replies"] if r["k"] == rkey), None)
            if reply:
                if self.group_rec(chat).get("off"):
                    return
                now = time.monotonic()
                if now - self.last_request.get((cid, "rp", rkey), 0) > 10:
                    self.last_request[(cid, "rp", rkey)] = now
                    await self.send_reply(cid, reply, m["message_id"])
                return
        first, _, rest = text.partition(" ")
        cmd = first.lstrip("/!.#")
        if "@" in cmd:
            cmd, _, target = cmd.partition("@")
            if target.lower() != self.username.lower():
                return                                   # الأمر موجّه لبوت آخر
        action = COMMANDS.get(norm_ar(cmd).lower())
        if action is None:
            return
        group = self.group_rec(chat)
        if group.get("off"):
            return
        rest, reply_to = rest.strip(), m["message_id"]
        name, username = tg_name(user), user.get("username") or ""

        if action in ("play", "yt"):
            if not rest or (action == "yt" and not self.cfg["yt"]):
                return
            if not await self.can_request(uid, cid):
                return
            now = time.monotonic()
            if now - self.last_request.get((cid, uid), 0) < REQUEST_GAP:
                return
            self.last_request[(cid, uid)] = now
            if not await self.gate(uid, cid, reply_to):
                return
            if not self.calls:
                await self.say(cid, "الحساب المساعد غير مسجل في هذا البوت. على مالك البوت تسجيله من لوحة المالك.",
                               reply_to)
                return
            record_person(self.rec["people"], uid, name, username, bump="dls" if action == "yt" else "plays")
            if action == "yt":
                await self.music_download(chat, reply_to, rest, uid)
                return
            query, video = parse_video_flag(rest)
            video = video and self.cfg["video"]
            if query:
                await self.music_request(chat, reply_to, query, video, (uid, name))
            return

        p = self.players.get(cid)
        if p is None or p.current is None:
            return                                       # «تخطي» وأمثالها تُتجاهل إن لم يكن هناك تشغيل
        if not await self.can_control(uid, cid):
            now = time.monotonic()
            if now - self.last_request.get((cid, uid, "deny"), 0) > 15:
                self.last_request[(cid, uid, "deny")] = now
                await self.say(cid, "التحكم بالموسيقى للمشرفين فقط", reply_to)
            return
        number = int(re.sub(r"\D", "", rest) or 0) or None
        result = await self.music_action(p, action, number)
        if result:
            await self.say(cid, esc(result), reply_to)

    # ---------------- الصلاحيات
    async def is_chat_admin(self, uid, cid):
        key, now = (cid, uid), time.monotonic()
        hit = self.admin_cache.get(key)
        if hit and now - hit[1] < 60:
            return hit[0]
        d = await self.api("getChatMember", chat_id=cid, user_id=uid)
        ok = d.get("ok") and d["result"].get("status") in ("creator", "administrator")
        self.admin_cache[key] = (ok, now)
        return ok

    async def can_control(self, uid, cid):
        if self.cfg["access"] == "all" or self.is_owner(uid):
            return True
        return await self.is_chat_admin(uid, cid)

    async def can_request(self, uid, cid):
        if self.cfg["access"] in ("all", "mixed"):
            return True
        return await self.can_control(uid, cid)

    # ---------------- التشغيل
    def player(self, cid):
        if cid not in self.players:
            self.players[cid] = Player(self, cid)
        return self.players[cid]

    async def pytg(self, names, *args):
        """ينادي أول دالة موجودة في PyTgCalls من بين الأسماء (تختلف أسماؤها بين الإصدارات)."""
        for name in names:
            fn = getattr(self.calls, name, None)
            if fn:
                return await fn(*args)
        raise RuntimeError("هذه الميزة غير متوفرة في إصدار المكتبة المثبّت")

    async def start_stream(self, p, seek=0, source=None, headers=None):
        """يبدأ بث المقطع من الملف المحمّل، أو من رابط مباشر (source) للبدء السريع."""
        t = p.current
        extra = {"ffmpeg_parameters": f"-ss {int(seek)}"} if seek else {}
        if headers:
            extra["headers"] = headers
        quality = getattr(VideoQuality, "SD_480p", None) if VideoQuality else None
        if t.video and quality:
            stream = MediaStream(source or t.path, audio_parameters=AudioQuality.HIGH,
                                 video_parameters=quality, **extra)
        else:
            stream = MediaStream(source or t.path, audio_parameters=AudioQuality.HIGH,
                                 video_flags=MediaStream.Flags.IGNORE, **extra)
        await self.calls.play(p.cid, stream)
        self.in_call.add(p.cid)
        p.base, p.t0, p.paused = float(seek), time.monotonic(), False
        p.started_at = time.monotonic()
        try:
            if t.path:
                os.utime(t.path, None)
        except OSError:
            pass
        if p.volume != 100:
            try:
                await self.pytg(("change_volume_call", "change_volume"), p.cid, p.volume)
            except Exception as e:
                log.info("volume: %s", e)

    def cancel_leave(self, cid):
        task = self.leave_tasks.pop(cid, None)
        if task:
            task.cancel()

    async def leave(self, cid):
        self.cancel_leave(cid)
        if cid in self.in_call:
            try:
                await self.calls.leave_call(cid)
            except Exception:
                pass
            self.in_call.discard(cid)

    def schedule_leave(self, cid, delay=5):
        """بعد انتهاء التشغيل ينتظر الحساب المساعد 5 ثواني ثم يغادر المحادثة المرئية (إن فعّل المالك ذلك)."""
        self.cancel_leave(cid)
        if not self.cfg["auto_leave"]:
            return

        async def later():
            await asyncio.sleep(delay)
            p = self.players.get(cid)
            if p is None or (p.current is None and not p.queue):
                self.leave_tasks.pop(cid, None)
                await self.leave(cid)
        self.leave_tasks[cid] = asyncio.ensure_future(later())

    async def play_next(self, p, skip=False):
        """يبدأ المقطع التالي من الطابور (أو يعيد الحالي إن كان التكرار مفعّلًا). True إن بدأ تشغيل شيء."""
        async with p.lock:
            p.busy = True
            self.cancel_leave(p.cid)
            try:
                while True:
                    prev = p.current
                    if prev is not None and p.loop and not skip:
                        nxt = prev
                    elif p.queue:
                        nxt = p.queue.pop(0)
                    else:
                        nxt = None
                    skip = False
                    if nxt is None:
                        p.current = None
                        p.base, p.t0, p.paused = 0.0, None, False
                        await self.panel_finish(p, "انتهى التشغيل")
                        self.schedule_leave(p.cid)
                        return False
                    p.current = nxt
                    try:
                        nxt.live = False
                        if not nxt.path or not os.path.exists(nxt.path):
                            if not await self.try_fast_start(p, nxt):
                                nxt.path = await fetch(nxt)
                                await self.start_stream(p, 0)
                        else:
                            await self.start_stream(p, 0)
                    except Exception as e:
                        log.warning("play %s: %s", p.cid, e)
                        p.current = None
                        await self.say(p.cid, f"تعذر تشغيل <b>{esc(nxt.title)}</b>:\n<code>{esc(friendly(e))}</code>")
                        continue
                    self.rec["stats"]["plays"] += 1
                    save_soon()
                    nxt.fallback = None          # التحويل لبديل يتم بصمت دون إشعار المستخدم
                    await self.panel_show(p, fresh=True)
                    if p.queue:
                        self.spawn(prefetch(p.queue[0]))
                    return True
            finally:
                p.busy = False

    async def try_fast_start(self, p, t):
        """الصوت فقط: يبدأ البث من الرابط المباشر فورًا ويحمّل الملف في الخلفية (للتقديم والإعادة).
        يرجع False إن لم ينجح فنعود للتحميل الكامل."""
        if t.video or not gy()["fast_start"] or find_cached(t.id, "a"):
            return False
        try:
            fut = t.resolving or asyncio.ensure_future(resolve_stream(t))
            src = await asyncio.wait_for(asyncio.shield(fut), 10)
            if not src:
                return False
            await self.start_stream(p, 0, src["url"], src["headers"])
            t.live = True
            self.spawn(self.cache_in_background(t))
            return True
        except Exception as e:
            t.live = False
            log.info("البدء السريع فشل: %s", short(e))
            return False

    async def cache_in_background(self, t):
        await prefetch(t)

    async def music_stop(self, cid, note="تم إيقاف الموسيقى"):
        p = self.players.get(cid)
        if not p:
            return
        async with p.lock:
            p.queue.clear()
            p.current, p.loop = None, False
            p.base, p.t0, p.paused = 0.0, None, False
            await self.panel_finish(p, note)
        await self.leave(cid) if self.cfg["auto_leave"] else None

    async def stop_all(self):
        count = 0
        for cid, p in list(self.players.items()):
            if p.current or p.queue:
                await self.music_stop(cid)
                count += 1
        return count

    async def on_call_closed(self, cid):
        """انتهت المحادثة المرئية أو طُرد الحساب المساعد: نمسح المشغّل."""
        p = self.players.pop(cid, None)
        self.in_call.discard(cid)
        self.cancel_leave(cid)
        if p and (p.current or p.queue):
            p.queue.clear()
            p.current = None
            await self.panel_finish(p, "انتهت المحادثة المرئية")

    async def on_stream_end(self, cid):
        p = self.players.get(cid)
        if p is None or p.current is None:
            return
        if p.busy or time.monotonic() - p.started_at < 1.5:
            return                                       # حدث مكرر (صوت وصورة) أو ناتج عن تبديلنا للمقطع
        t = p.current
        if t.live and p.position() < 6:                  # انقطع البث المباشر مبكرًا: نكمل من الملف المحمّل
            t.live = False
            async with p.lock:
                p.busy = True
                try:
                    t.path = await fetch(t)
                    await self.start_stream(p, 0)
                    return
                except Exception as e:
                    log.warning("fallback download %s: %s", p.cid, short(e))
                finally:
                    p.busy = False
        await self.play_next(p)

    # ---------------- اللوحة
    # ---------------- لوحة التشغيل (الكليشات)
    def tpl_current(self):
        idx = self.cfg.get("tpl", DEFAULT_TPL)
        return idx if isinstance(idx, int) and 0 <= idx < len(TEMPLATES) else DEFAULT_TPL

    def tpl_data(self, p):
        t = p.current
        return {"title": t.title, "uploader": t.uploader, "dur": fmt_secs(t.dur) if t.dur else "غير معروفة",
                "by": mention(*t.by), "place": self.title_of(p.cid), "paused": p.paused,
                "bar": progress_bar(p.position(), t.dur), "queue": len(p.queue), "loop": p.loop,
                "video": t.video}

    @staticmethod
    def tpl_sample(user):
        """بيانات تجريبية لمعاينة الكليشة عند المالك."""
        return {"title": "اسم الاغنية هنا", "uploader": "اسم القناة", "dur": "03:45",
                "by": mention(user.get("id"), tg_name(user)), "place": "اسم المجموعة", "paused": False,
                "bar": progress_bar(95, 225), "queue": 0, "loop": False, "video": False}

    def classic_text(self, d):
        lines = [f"<b>{'تشغيل فيديو' if d['video'] else 'تشغيل موسيقى'}</b>", "",
                 field("song", "العنوان", f"<b>{esc(d['title'])}</b>")]
        if d["uploader"]:
            lines.append(field("artist", "القناة", esc(d["uploader"])))
        lines += [field("duration", "المدة", d["dur"]),
                  field("by", "الطالب", d["by"]),
                  field("place", "المكان", esc(d["place"])),
                  f"الحالة: {'متوقف مؤقتًا' if d['paused'] else 'يعمل الآن'}",
                  d["bar"]]
        if d["queue"]:
            lines.append(f"في الانتظار: <b>{d['queue']}</b>")
        if d["loop"]:
            lines.append("التكرار: مفعّل")
        return "\n".join(lines)

    def classic_kb(self, cid, loop=False, preview=False):
        def mb(label, act, style, slot):
            return b(label, "ow:tpn" if preview else f"mu:{act}:{cid}", style=style, k=slot)
        rows = [
            [mb("إيقاف مؤقتًا", "pause", "danger", "mu_pause"), mb("استكمال البث", "resume", "success", "mu_resume")],
            [mb("عودة 10 ثواني", "back", "primary", "mu_back"), mb("تقديم 10 ثواني", "fwd", "primary", "mu_fwd")],
            [mb("تخطي", "skip", "primary", "mu_skip"), mb("إيقاف الموسيقى", "stop", "danger", "mu_stop")],
            [mb("التكرار: مفعّل" if loop else "تكرار", "loop", "success" if loop else "primary", "mu_loop"),
             mb("الطابور", "queue", "primary", "mu_queue"), mb("✖", "close", "danger", "mu_close")],
        ]
        if credit_buttons(self.rec):
            rows.append(credit_buttons(self.rec))
        if make_button():
            rows.append([make_button()])
        return kb(rows)

    def render_text(self, idx, d):
        return self.classic_text(d) if TEMPLATES[idx].get("classic") else tpl_text(idx, d)

    def render_kb(self, idx, cid, loop=False, preview=False):
        if TEMPLATES[idx].get("classic"):
            return self.classic_kb(cid, loop, preview)
        return tpl_markup(self, idx, cid, loop, preview)

    def panel_text(self, p):
        return self.render_text(self.tpl_current(), self.tpl_data(p))

    def panel_kb(self, p):
        return self.render_kb(self.tpl_current(), p.cid, p.loop)

    async def send_with_media(self, cid, text, markup, tpl=None, preview=False):
        """يرسل النص مع صورة أو GIF ويرجع (message_id، هل بوسائط) أو None.
        الأولوية في اللوحة الحقيقية: وسائط المالك الخاصة ← وسائط الكليشة (من المطور) ← وسائط المطور العامة.
        وفي المعاينة تتقدم وسائط الكليشة."""
        if len(text) <= 1000:
            tm = G["tpl_media"].get(str(tpl)) if tpl is not None else None
            glob = G.get("panel_media")
            tm = tm if tm and os.path.exists(tm["path"]) else None
            glob = glob if glob and os.path.exists(glob["path"]) else None
            gif, photo = self.cfg.get("panel_gif"), self.cfg.get("panel_photo")
            tries = []
            if preview and tm:
                tries.append(("item", tm))
            if gif:
                tries.append(("animation", gif))
            elif photo:
                tries.append(("photo", photo))
            if tm and not preview:
                tries.append(("item", tm))
            if glob:
                tries.append(("item", glob))
            for kind, src in tries:
                if kind == "item":
                    res = await self.send_item(cid, src, caption=text, markup=markup)
                    if res:
                        return res["message_id"], True
                    continue
                d = await self.api("sendAnimation" if kind == "animation" else "sendPhoto", chat_id=cid,
                                   **{kind: src}, caption=text, parse_mode="HTML", reply_markup=markup)
                if d.get("ok"):
                    return d["result"]["message_id"], True
        d = await self.api("sendMessage", chat_id=cid, text=text, parse_mode="HTML", reply_markup=markup,
                           disable_web_page_preview=True)
        return (d["result"]["message_id"], False) if d.get("ok") else None

    async def panel_send(self, cid, text, markup):
        res = await self.send_with_media(cid, text, markup, tpl=self.tpl_current())
        return (cid, res[0], res[1]) if res else None

    async def panel_edit(self, entry, text, markup):
        chat, mid, is_photo = entry
        if is_photo:
            d = await self.api("editMessageCaption", chat_id=chat, message_id=mid, caption=text,
                               parse_mode="HTML", reply_markup=markup)
        else:
            d = await self.api("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
                               reply_markup=markup, disable_web_page_preview=True)
        return bool(d.get("ok")) or "not modified" in str(d.get("description", ""))

    async def panel_show(self, p, fresh=False, resend=True):
        """fresh: لوحة جديدة (عند بدء مقطع). وإلا نعدّل الموجودة. resend=False: تعديل فقط (شريط التقدم)."""
        if p.current is None:
            return
        text, markup = deco(self.panel_text(p), "music"), self.panel_kb(p)
        if fresh:
            for chat, mid, _ in p.panels:
                await self.api("deleteMessage", chat_id=chat, message_id=mid)
            p.panels = []
        p.panels = [e for e in p.panels if await self.panel_edit(e, text, markup)]
        p.last_edit = time.monotonic()
        if p.panels or not resend:
            return
        entry = await self.panel_send(p.cid, text, markup)
        if entry:
            p.panels.append(entry)

    async def panel_finish(self, p, note):
        text = deco(f"<b>{esc(note)}</b>", "music")
        for chat, mid, is_photo in p.panels:
            if is_photo:
                await self.api("editMessageCaption", chat_id=chat, message_id=mid, caption=text,
                               parse_mode="HTML", reply_markup=kb([]))
            else:
                await self.api("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
                               reply_markup=kb([]))
        p.panels = []

    @staticmethod
    def queue_text(p, limit=10):
        lines = [f"<b>الآن:</b> {esc(p.current.title)}"]
        for i, t in enumerate(p.queue[:limit], 1):
            lines.append(f"{i}. {esc(t.title)} ({fmt_secs(t.dur)})")
        if len(p.queue) > limit:
            lines.append(f"... و{len(p.queue) - limit} أخرى")
        if len(lines) == 1:
            lines.append("الطابور فارغ")
        return "\n".join(lines)

    async def seek_to(self, p, target):
        t = p.current
        if not t.path:
            t.path = await fetch(t)                      # البث المباشر لم يكتمل تحميله: ننتظره
        target = max(0, min(target, t.dur - 2)) if t.dur else max(0, target)
        await self.start_stream(p, target)

    async def music_action(self, p, act, arg=None):
        """ينفّذ إجراء تحكم ويرجع نص النتيجة (يظهر كتنبيه للزر أو كرد على الأمر)."""
        if p.current is None:
            return "لا يوجد تشغيل الآن"
        if p.busy:
            return "جاري تحضير المقطع، حاول بعد لحظات"
        try:
            if act == "pause":
                if p.paused:
                    return "التشغيل متوقف مؤقتًا بالفعل"
                await self.pytg(("pause", "pause_stream"), p.cid)
                p.base, p.t0, p.paused = p.position(), None, True
                await self.panel_show(p)
                return "تم الإيقاف المؤقت"
            if act == "resume":
                if not p.paused:
                    return "التشغيل يعمل بالفعل"
                await self.pytg(("resume", "resume_stream"), p.cid)
                p.t0, p.paused = time.monotonic(), False
                await self.panel_show(p)
                return "تم استكمال البث"
            if act in ("fwd", "back"):
                step = arg if arg else 10
                await self.seek_to(p, p.position() + (step if act == "fwd" else -step))
                await self.panel_show(p)
                unit = "ثواني" if 3 <= step <= 10 else "ثانية"
                return f"{'تقديم' if act == 'fwd' else 'عودة'} {step} {unit}"
            if act == "skip":
                more = bool(p.queue)
                await self.play_next(p, skip=True)
                return "تم التخطي" if more else "لا يوجد مقطع تالٍ، انتهى التشغيل"
            if act == "stop":
                await self.music_stop(p.cid)
                return "تم إيقاف الموسيقى"
            if act == "loop":
                p.loop = not p.loop
                await self.panel_show(p)
                return "التكرار مفعّل" if p.loop else "التكرار متوقف"
            if act == "queue":
                return html.unescape(re.sub(r"<[^>]+>", "", self.queue_text(p, 5)))[:190]
            if act == "now":
                await self.panel_show(p, fresh=True)
                return ""
            if act == "close":
                for chat, mid, _ in p.panels:
                    await self.api("deleteMessage", chat_id=chat, message_id=mid)
                p.panels = []
                return "تم إغلاق اللوحة"
            if act == "volume":
                if arg is None:
                    return f"الصوت الحالي {p.volume}%"
                p.volume = max(1, min(200, arg))
                await self.pytg(("change_volume_call", "change_volume"), p.cid, p.volume)
                return f"تم ضبط الصوت على {p.volume}%"
        except Exception as e:
            log.warning("music_action %s: %s", act, e)
            return f"تعذر التنفيذ: {short(e)}"[:190]
        return ""

    async def cb_music(self, c):
        """أزرار لوحة التشغيل. تصل من أي شخص، فنتحقق من صلاحيته هنا."""
        if self.rec.get("suspended"):
            await c.toast("البوت متوقف مؤقتًا", alert=True)
            return
        try:
            act, cid = c.parts[1], int(c.parts[2])
        except (IndexError, ValueError):
            await c.toast()
            return
        p = self.players.get(cid)
        if p is None or p.current is None:
            await c.toast("انتهى التشغيل", alert=True)
            return
        if not await self.can_control(c.uid, cid):
            await c.toast("التحكم للمشرفين فقط", alert=True)
            return
        result = await self.music_action(p, act)
        await c.toast(result[:190] or None, alert=(act == "queue"))

    # ---------------- الطلبات
    async def music_request(self, chat, reply_to, query, video, by):
        cid = chat["id"]
        # الملصق والبحث ودخول الحساب المساعد يبدؤون معًا بدل الانتظار واحدًا بعد الآخر
        status_task = asyncio.ensure_future(self.say_status(cid, f"جاري البحث عن: <b>{esc(query[:80])}</b>", reply_to))
        search_task = asyncio.ensure_future(search(query))
        prep_task = asyncio.ensure_future(self.prepare_chat(chat))
        status = await status_task
        try:
            info, err = pick_result(await search_task, self.cap_seconds()), None
        except Exception as e:
            info, err = None, e
        track = None
        if info:
            track = Track(info, video, by)
            if not video and gy()["fast_start"]:
                track.resolving = asyncio.ensure_future(resolve_stream(track))   # يبدأ أثناء دخول الحساب المساعد
        assisted, has_call = await prep_task
        if err:
            await status.edit(f"تعذر العثور على نتيجة:\n<code>{esc(friendly(err))}</code>")
            return
        if not assisted:
            await status.edit("تعذر دخول الحساب المساعد إلى المجموعة.\nاجعل البوت مشرفًا بصلاحية دعوة المستخدمين، "
                              "أو أضف الحساب المساعد يدويًا.")
            return
        p = self.player(cid)
        if len(p.queue) >= self.cfg["queue_limit"]:
            await status.edit(f"الطابور ممتلئ ({self.cfg['queue_limit']} مقطع)")
            return
        if not has_call and not await self.ensure_call(cid):
            await status.edit("لا توجد محادثة مرئية، وتعذر فتحها.\n"
                              "ابدأ محادثة مرئية في المجموعة، أو امنح الحساب المساعد صلاحية إدارة المحادثات المرئية.")
            return
        idle = p.current is None and not p.busy and not p.queue    # بدون await بين الفحص والإضافة
        p.queue.append(track)
        if not idle:
            await status.edit(f"أُضيف إلى الطابور (رقم {len(p.queue)}): <b>{esc(track.title)}</b>")
            self.spawn(prefetch(track))
            if p.current:
                await self.panel_show(p)
            return
        self.spawn(status.progress(f"جاري التحميل: <b>{esc(track.title)}</b>"))
        await self.play_next(p)
        await status.delete()

    async def music_download(self, chat, reply_to, query, uid):
        cid = chat["id"]
        status = await self.say_status(cid, f"جاري البحث والتحميل: <b>{esc(query[:80])}</b>", reply_to)
        try:
            info = pick_result(await search(query), self.cap_seconds())
            path = await fetch(Track(info, False, (uid, "")))
            with open(path, "rb") as f:
                data = f.read()
            if len(data) > 49 * 1024 * 1024:
                raise RuntimeError("الملف أكبر من حد تيليجرام للبوتات (50 ميجا)")
            d = await self.api.upload("sendAudio", "audio", data, os.path.basename(path), chat_id=cid,
                                      caption=f"<b>{esc(info['title'])}</b>\nالمدة: {fmt_secs(info['dur'])}",
                                      parse_mode="HTML", title=info["title"][:60], performer=info["uploader"][:60],
                                      duration=info["dur"] or None, reply_to_message_id=reply_to,
                                      allow_sending_without_reply="true")
            if not d.get("ok"):
                raise RuntimeError(d.get("description") or "فشل رفع الملف")
            self.rec["stats"]["downloads"] += 1
            save_soon()
            await status.delete()
        except Exception as e:
            log.warning("yt %s: %s", cid, e)
            await status.edit(f"تعذر التحميل:\n<code>{esc(friendly(e))}</code>")


# ------------------------------------------------------------------ إدارة البوتات المصنوعة
async def start_bot(rec):
    old = CHILDREN.get(rec["id"])
    if old:
        await old.stop()
    child = Child(rec)
    CHILDREN[rec["id"]] = child
    return await child.start()


async def stop_bot(bot_id):
    child = CHILDREN.get(bot_id)
    if child:
        await child.stop()


async def delete_bot(bot_id):
    child = CHILDREN.pop(bot_id, None)
    if child:
        await child.stop()
    db["bots"].pop(str(bot_id), None)
    save()
    try:
        os.remove(os.path.join(PANELS_DIR, f"{bot_id}.jpg"))
    except OSError:
        pass


def bot_status(rec):
    child = CHILDREN.get(rec["id"])
    if rec.get("status") == "token_invalid":
        return "التوكن غير صالح"
    if rec.get("suspended"):
        return "موقوف (انتهت المدة)"
    if not rec.get("enabled", True):
        return "متوقف"
    return "شغّال" if child and child.running else "يبدأ..."


def owner_tag(uid):
    person = db["people"].get(str(uid), {})
    return f"{mention(uid, person.get('name'))} {('@' + esc(person['un'])) if person.get('un') else ''}".strip()


def on_off(flag):
    return "شغّال" if flag else "متوقف"


FACTORY_GUIDE = (
    "<b>طريقة صنع بوت ميوزك</b>\n\n"
    "1. اضغط «صنع بوت» ثم «صنع بوت مجاني».\n"
    "2. افتح @BotFather وأرسل <code>/newbot</code> واختر اسمًا ويوزرًا، ثم انسخ التوكن وأرسله هنا.\n"
    "3. افتح بوتك الجديد وأرسل <code>/start</code> فتظهر لوحة المالك.\n"
    "4. من «الحساب المساعد» سجّل حسابًا برقمه ثم الكود (بينه شرطات 1-2-3-4-5).\n"
    "5. أضف البوت إلى مجموعتك واجعله مشرفًا، ثم اكتب فيها: <code>شغل اسم الأغنية</code>.\n\n"
    "من لوحة المالك تتحكم بكل شيء: الإعدادات، المجموعات، الحقوق، ملصق الانتظار، صورة اللوحة، "
    "الإذاعة، والإحصائيات."
)


# ------------------------------------------------------------------ بوت الصانع
class Factory(App):
    allowed = ["message", "callback_query", "managed_bot"]

    def __init__(self):
        super().__init__(BOT_TOKEN)
        self.username, self.bot_id, self.bc_busy = "", 0, False
        self.pending_ref = {}
        self.start_fid = {}
        self.steps = {
            "create_token": self.step_create, "fs_add": self.step_fs_add, "cr_field": self.step_cr_field,
            "eng_proxy": self.step_proxy, "eng_cookies": self.step_cookies, "cfg_welcome": self.step_welcome,
            "bc": self.step_bc, "emoji": self.step_emoji, "adddev": self.step_adddev, "deldev": self.step_deldev,
            "rp_key": self.step_rp_key, "rp_body": self.step_rp_body, "md_add": self.step_md_add,
            "pm_set": self.step_pm_set, "ss_set": self.step_ss_set, "tm_set": self.step_tm_set,
        }
        self.dev_only_steps = set(self.steps) - {"create_token"}
        self.us_routes = {
            "home": self.cb_us_home, "create": self.cb_create, "free": self.cb_free, "paid": self.cb_paid,
            "mine": self.cb_mine, "mb": self.cb_mybot, "bdel": self.cb_mybot_del, "bdelok": self.cb_mybot_delok,
            "guide": self.cb_us_guide, "inst": self.cb_instant,
        }
        self.dv_routes = {
            "home": self.cb_dv_home, "bots": self.cb_bots, "bot": self.cb_bot, "bt": self.cb_bot_toggle,
            "br": self.cb_bot_restart, "bx": self.cb_bot_extend, "bm": self.cb_bot_mode, "bz": self.cb_bot_credits_reset,
            "bd": self.cb_bot_delete, "bdok": self.cb_bot_delete_ok,
            "cr": self.cb_credits, "crm": self.cb_credits_mode, "crf": self.cb_credits_field, "crz": self.cb_credits_zero,
            "fs": self.cb_forced, "fsadd": self.cb_forced_add, "fsdel": self.cb_forced_del,
            "eng": self.cb_engine, "engt": self.cb_engine_flag, "engc": self.cb_engine_cycle, "engp": self.cb_engine_proxy,
            "engk": self.cb_engine_cookies, "engu": self.cb_engine_update, "engy": self.cb_engine_check,
            "engr": self.cb_engine_reset, "engx": self.cb_engine_clear,
            "cfg": self.cb_config, "cfgo": self.cb_config_open, "cfgc": self.cb_config_cycle, "cfgw": self.cb_config_welcome,
            "st": self.cb_stats, "bc": self.cb_bc, "bct": self.cb_bc_target, "bcgo": self.cb_bc_go,
            "emoji": self.cb_emoji, "txtem": self.cb_txtem, "emk": self.cb_emk, "emojiclear": self.cb_emoji_clear,
            "txtclear": self.cb_txt_clear, "preview": self.cb_preview,
            "adddev": self.cb_adddev, "deldev": self.cb_deldev,
            "rp": self.cb_rp, "rpadd": self.cb_rpadd, "rpdel": self.cb_rpdel,
            "md": self.cb_md, "mdadd": self.cb_mdadd, "mdclr": self.cb_mdclr, "pmset": self.cb_pmset,
            "pmclr": self.cb_pmclr, "ssset": self.cb_ss_set, "ssclr": self.cb_ss_clr,
            "tm": self.cb_tm, "tms": self.cb_tm_pick, "tmx": self.cb_tm_clear,
        }

    async def start(self):
        global MAKER_USERNAME
        me = await self.api("getMe")
        if not me.get("ok"):
            sys.exit("توكن بوت الصانع غير صالح. تأكد من BOT_TOKEN.")
        self.username, self.bot_id = me["result"]["username"], me["result"]["id"]
        MAKER_USERNAME = self.username
        self.running = True
        self.spawn(self.poll())

    def remember(self, user):
        uid = user.get("id")
        if uid not in db["known"]:
            db["known"].append(uid)
        record_person(db["people"], uid, tg_name(user), user.get("username") or "", bot=True)

    # ---------------- الرسائل
    async def on_message(self, m):
        if m["chat"]["type"] != "private":
            return
        chat, user = m["chat"]["id"], m.get("from") or {}
        uid, text = user.get("id"), (m.get("text") or "").strip()
        if not uid:
            return
        is_new = uid not in db["known"]
        self.remember(user)
        if text.split("@")[0] == "/id":
            await self.api("sendMessage", chat_id=chat, parse_mode="HTML",
                           text=f"ايديك: <code>{uid}</code>\nمطور: {'نعم' if is_dev(uid) else 'لا'}"
                                f" (OWNER_ID الحالي: <code>{OWNER_ID}</code>)")
            return
        if text.startswith("/start") or text == "/panel":
            await self.reset_state(uid)
            payload = text.partition(" ")[2].strip()
            if payload.startswith("ref_") and payload[4:].isdigit() and is_new:
                inviter = int(payload[4:])
                if inviter != uid and str(uid) not in db["refs"]:
                    self.pending_ref[uid] = inviter
            if not await self.gate(uid, chat):
                return
            await self.apply_ref(uid)
            if text.partition(" ")[2].strip() == "create":
                await self.show_create(chat)
            elif is_dev(uid):
                await self.show(chat, "<b>أهلًا بك مطوري العزيز</b>\n\n" + self.dv_text(), self.dv_kb(uid), kind="dev")
            else:
                await self.send_home(chat, uid)
            return
        st = self.states.get(uid)
        step = st["step"] if st else None
        if step in self.steps and (step not in self.dev_only_steps or is_dev(uid)):
            await self.steps[step](m, chat, uid, text, st)
        elif text.startswith("/"):
            await self.show(chat, self.home_text(), self.home_kb(uid), kind="start")

    async def on_callback(self, q):
        c = Ctx(self, q)
        self.remember(c.user)
        if c.act == "x":
            await self.cb_close(c)
        elif c.act == "fs":
            await self.cb_fs(c)
        elif c.act == "us":
            await c.toast()
            await self.reset_state(c.uid)
            route = self.us_routes.get(c.sub)
            if route:
                await route(c)
        elif c.act == "dv":
            if not is_dev(c.uid):
                await c.toast("هذه اللوحة للمطور فقط", alert=True)
                return
            await c.toast()
            await self.reset_state(c.uid)
            route = self.dv_routes.get(c.sub)
            if route:
                await route(c)

    async def after_subscribed(self, c):
        await self.apply_ref(c.uid)
        await c.screen(self.home_text(), self.home_kb(c.uid), kind="start")

    # ---------------- شاشات المستخدمين
    def home_text(self):
        return G["welcome"] or ("<b>صانع بوتات الميوزك</b>\n\n"
                                "أنشئ بوت ميوزك خاصًا بك يشغّل الأغاني والفيديو في المحادثات المرئية، "
                                "مع لوحة تحكم كاملة لك.\nاضغط «صنع بوت» لتبدأ.")

    def home_kb(self, uid):
        rows = [[b("صنع بوت", "us:create", style="success"), b("بوتاتي", "us:mine", style="primary")],
                [b("طريقة الاستخدام", "us:guide", style="primary")]]
        if credit_buttons(None):
            rows.append(credit_buttons(None))
        if is_dev(uid):
            rows.append([b("لوحة المطور", "dv:home", style="success")])
        rows.append([b("✖", "x:close", style="danger")])
        return kb(rows)

    async def cb_us_home(self, c):
        await c.screen(self.home_text(), self.home_kb(c.uid), kind="start")

    async def cb_us_guide(self, c):
        await c.screen(FACTORY_GUIDE, back_kb(None, "us:home"), kind="guide")

    def create_menu(self):
        text = ("<b>صنع بوت ميوزك</b>\n\nاختر نوع البوت:\n"
                "- <b>مجاني</b>: بوت ميوزك كامل بلوحة مالك خاصة بك.\n"
                "- <b>مدفوع</b>: يُنصَّب لك من المطور بمزايا إضافية.\n"
                "- <b>فوري</b>: ينشأ بضغطة واحدة بدون BotFather ولا توكن (بحقوق المطور).")
        rows = [[b("إنشاء بوت فوري", "us:inst", style="success")],
                [b("صنع بوت مجاني", "us:free", style="success"), b("صنع بوت مدفوع", "us:paid", style="primary")],
                [b("طريقة الاستخدام", "us:guide", style="primary")]]
        return text, back_kb(rows, "us:home")

    async def show_create(self, chat):
        text, markup = self.create_menu()
        await self.show(chat, text, markup, kind="start")

    async def apply_ref(self, uid):
        """يحتسب دعوة جديدة لصاحب الرابط، ويعيد تشغيل بوته الموقوف إذا اكتمل العدد."""
        inviter = self.pending_ref.pop(uid, None)
        if not inviter or str(uid) in db["refs"]:
            return
        db["refs"][str(uid)] = inviter
        db["owners"].setdefault(str(inviter), {"refs": 0})["refs"] += 1
        save()
        revived = 0
        for rec in [r for r in db["bots"].values() if r["owner"] == inviter and r.get("suspended")]:
            if consume_refs(inviter):
                await revive(rec)
                revived += 1
        if not revived:
            await self.api("sendMessage", chat_id=inviter, parse_mode="HTML",
                           text=f"انضم عضو جديد عبر رابطك. المدعوون: <b>{owner_refs(inviter)}</b> من {G['ref_need']}")

    async def cb_instant(self, c):
        back = back_kb(None, "us:create")
        if not G["open"] and not is_dev(c.uid):
            await c.screen("إنشاء البوتات مغلق حاليًا. حاول لاحقًا.", back)
            return
        if not is_dev(c.uid) and len(self.mine_of(c.uid)) >= G["per_user"]:
            await c.screen(f"وصلت للحد المسموح ({G['per_user']} بوت لكل مستخدم). يمكنك حذف بوت من «بوتاتي».",
                           back_kb([[b("بوتاتي", "us:mine", style="primary")]], "us:create"))
            return
        if len(db["bots"]) >= G["max_bots"] and not is_dev(c.uid):
            await c.screen("امتلأ العدد الأقصى للبوتات على هذا الصانع. تواصل مع المطور.", back)
            return
        suffix = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=6))
        link = f"https://t.me/newbot/{self.username}/music_{suffix}_bot?name={quote('بوت ميوزك')}"
        await c.screen("<b>إنشاء بوت فوري</b>\n\nاضغط الزر وستظهر نافذة إنشاء البوت من تيليجرام: عدّل الاسم واليوزر "
                       "إن أردت ثم اضغط «إنشاء».\nيُضاف البوت إلى حسابك هنا تلقائيًا بدون توكن، وتظهر فيه حقوق المطور في البداية ويمكنك تغييرها من لوحة المالك.\n"
                       "بعدها افتحه وأرسل <code>/start</code>.",
                       back_kb([[b("إنشاء بوتي الآن", url=link, style="success")]], "us:create"), kind="start")

    async def on_managed(self, upd):
        """بوت أُنشئ عبر الإنشاء الفوري: نجلب توكنه ونشغّله باسم من أنشأه."""
        user, bot = upd.get("user") or {}, upd.get("bot") or {}
        uid, bid = user.get("id"), bot.get("id")
        if not uid or not bid:
            return
        self.remember(user)
        d = await self.api("getManagedBotToken", user_id=bid)
        token = d.get("result") if d.get("ok") else None
        if not isinstance(token, str):
            await self.api("sendMessage", chat_id=uid, text="تعذر جلب توكن البوت الجديد. أنشئه يدويًا من «صنع بوت مجاني».")
            return
        rec = db["bots"].get(str(bid))
        if rec:
            rec["token"] = token
        else:
            if not is_dev(uid) and (not G["open"] or len(self.mine_of(uid)) >= G["per_user"]
                                    or len(db["bots"]) >= G["max_bots"]):
                await self.api("sendMessage", chat_id=uid, text="لا يمكن تفعيل البوت: وصلت للحد المسموح.")
                return
            rec = new_bot_rec(token, bot, uid)
            rec["instant"] = True
            db["bots"][str(bid)] = rec
        save()
        started = await start_bot(rec)
        link = f"https://t.me/{rec['username']}?start=owner"
        await self.api("sendMessage", chat_id=uid, parse_mode="HTML",
                       text=deco(f"<b>تم إنشاء بوتك @{esc(rec['username'])}</b>\n\n"
                                 "1. افتح البوت وأرسل <code>/start</code> فتظهر لوحة المالك.\n"
                                 "2. سجّل «الحساب المساعد» من اللوحة.\n"
                                 "3. أضف البوت إلى مجموعتك واجعله مشرفًا."
                                 + ("" if started else "\n\nتعذر تشغيله الآن، راجع المطور."), "start"),
                       reply_markup=kb([[b("فتح بوتي", url=link, style="success")]]))

    async def cb_create(self, c):
        text, markup = self.create_menu()
        await c.screen(text, markup, kind="start")

    async def cb_paid(self, c):
        rows = [[b("مراسلة المطور", url=G["dev_url"] or DEV_URL, style="success", k="mu_dev")],
                [b("طريقة الاستخدام", "us:guide", style="primary")]]
        await c.screen("<b>البوت المدفوع</b>\n\nيُنصَّب لك من المطور بمزايا إضافية وصلاحيات أوسع.\n"
                       "للحصول عليه تواصل مع المطور.", back_kb(rows, "us:create"), kind="start")

    def mine_of(self, uid):
        return [r for r in db["bots"].values() if r["owner"] == uid]

    async def cb_free(self, c):
        back = back_kb(None, "us:create")
        if not G["open"] and not is_dev(c.uid):
            await c.screen("إنشاء البوتات مغلق حاليًا. حاول لاحقًا.", back)
            return
        if not is_dev(c.uid) and len(self.mine_of(c.uid)) >= G["per_user"]:
            await c.screen(f"وصلت للحد المسموح ({G['per_user']} بوت لكل مستخدم). يمكنك حذف بوت من «بوتاتي».",
                           back_kb([[b("بوتاتي", "us:mine", style="primary")]], "us:create"))
            return
        if len(db["bots"]) >= G["max_bots"] and not is_dev(c.uid):
            await c.screen("امتلأ العدد الأقصى للبوتات على هذا الصانع. تواصل مع المطور.", back)
            return
        self.states[c.uid] = {"step": "create_token"}
        await c.screen("<b>صنع بوت مجاني</b>\n\nافتح @BotFather وأرسل <code>/newbot</code>، اختر اسمًا ويوزرًا، "
                       "ثم انسخ التوكن وأرسله هنا.\nسأحذف رسالتك فور قراءتها حفاظًا على التوكن.", back)

    async def step_create(self, m, chat, uid, text, st):
        back = back_kb(None, "us:create")
        await self.api("deleteMessage", chat_id=chat, message_id=m["message_id"])    # فيها التوكن
        token = text.strip()
        if not re.fullmatch(r"\d{6,}:[\w-]{30,}", token):
            await self.show(chat, "هذا ليس توكن بوت. انسخه من @BotFather كما هو وأرسله.", back)
            return
        if token == BOT_TOKEN or any(r["token"] == token for r in db["bots"].values()):
            await self.show(chat, "هذا التوكن مستخدم مسبقًا.", back)
            return
        me = await BotAPI(token)("getMe")
        if not me.get("ok"):
            await self.show(chat, "التوكن غير صالح أو أُعيد توليده. تحقق منه في @BotFather.", back)
            return
        if str(me["result"]["id"]) in db["bots"]:
            await self.show(chat, "هذا البوت مصنوع مسبقًا.", back)
            return
        if not is_dev(uid) and (len(self.mine_of(uid)) >= G["per_user"] or len(db["bots"]) >= G["max_bots"]):
            await self.show(chat, "لا يمكن إنشاء بوت جديد الآن (وصلت للحد المسموح).", back)
            return
        rec = new_bot_rec(token, me["result"], uid)
        db["bots"][str(rec["id"])] = rec
        save()
        self.states.pop(uid, None)
        started = await start_bot(rec)
        link = f"https://t.me/{rec['username']}?start=owner"
        await self.show(chat, f"<b>تم إنشاء بوتك @{esc(rec['username'])}</b>\n\n"
                              "1. افتح البوت وأرسل <code>/start</code> فتظهر لوحة المالك.\n"
                              "2. سجّل «الحساب المساعد» من اللوحة.\n"
                              "3. أضف البوت إلى مجموعتك واجعله مشرفًا." + ("" if started else "\n\nتعذر تشغيله الآن، راجع المطور."),
                        kb([[b("فتح بوتي", url=link, style="success")], [b("بوتاتي", "us:mine", style="primary")]]),
                        kind="start")

    async def cb_mine(self, c):
        mine = self.mine_of(c.uid)
        rows = [[b(f"@{r['username']} - {bot_status(r)}", f"us:mb:{r['id']}", style="primary")] for r in mine]
        rows.append([b("صنع بوت", "us:create", style="success")])
        await c.screen("<b>بوتاتي</b>\n" + ("اضغط على البوت لعرض تفاصيله." if mine else "لا توجد بوتات بعد."),
                       back_kb(rows, "us:home"), kind="start")

    def own_bot(self, c):
        rec = db["bots"].get(c.parts[2]) if len(c.parts) > 2 else None
        return rec if rec and (rec["owner"] == c.uid or is_dev(c.uid)) else None

    async def cb_mybot(self, c):
        rec = self.own_bot(c)
        if not rec:
            await self.cb_mine(c)
            return
        text = (f"<b>@{esc(rec['username'])}</b> ({esc(rec['name'])})\n\n"
                f"الحالة: {bot_status(rec)}\nالمجموعات: <b>{len(rec['groups'])}</b> | "
                f"المستخدمون: <b>{len(rec['people'])}</b> | التشغيلات: <b>{rec['stats']['plays']}</b>\n"
                f"أُنشئ: {fmt_ts(rec['created'])}" + trial_info(rec))
        rows = [[b("فتح لوحة المالك", url=f"https://t.me/{rec['username']}?start=owner", style="success")],
                [b("رابط الدعوة (تمديد المدة)", url=share_url(rec["owner"]), style="primary")],
                [b("حذف البوت", f"us:bdel:{rec['id']}", style="danger")]]
        await c.screen(text, back_kb(rows, "us:mine"), kind="start")

    async def cb_mybot_del(self, c):
        rec = self.own_bot(c)
        if rec:
            await c.screen(f"حذف البوت <b>@{esc(rec['username'])}</b> نهائيًا؟",
                           kb([[b("تأكيد الحذف", f"us:bdelok:{rec['id']}", style="danger"),
                                b("إلغاء", f"us:mb:{rec['id']}", style="primary")]]))

    async def cb_mybot_delok(self, c):
        rec = self.own_bot(c)
        if rec:
            await delete_bot(rec["id"])
        await self.cb_mine(c)

    # ---------------- لوحة المطور
    def dv_text(self):
        bots = list(db["bots"].values())
        running = sum(1 for r in bots if bot_status(r) == "شغّال")
        plays = sum(r["stats"]["plays"] for r in bots)
        mode = "حقوق المستخدم" if G["credits_mode"] == "user" else "حقوقي"
        return ("<b>لوحة المطور</b>\n\n"
                f"البوتات: <b>{len(bots)}</b> (شغّالة {running}) | الملاك: <b>{len({r['owner'] for r in bots})}</b>\n"
                f"مستخدمو الصانع: <b>{len(db['known'])}</b>\n"
                f"إجمالي التشغيلات: <b>{plays}</b>\n"
                f"الحقوق: <b>{mode}</b> | الاشتراك الإجباري: <b>{len(G['forced'])}</b> قناة\n"
                f"إنشاء البوتات: <b>{'مفتوح' if G['open'] else 'مغلق'}</b> | المطورون: <b>{len(db['devs']) + 1}</b>")

    def dv_kb(self, uid):
        rows = [
            [b("البوتات", "dv:bots:0", style="primary"), b("الحقوق وقناة السورس", "dv:cr", style="primary")],
            [b("الاشتراك الإجباري", "dv:fs", style="primary"), b("محرك الموسيقى", "dv:eng", style="primary")],
            [b("إعدادات الصانع", "dv:cfg", style="primary"), b("الإحصائيات", "dv:st:0", style="primary")],
            [b("إذاعة", "dv:bc", style="success")],
            [b("ايموجي الأزرار", "dv:emoji", style="primary"), b("ملصقات النصوص", "dv:txtem", style="primary")],
            [b("الردود", "dv:rp", style="primary"), b("وسائط البوتات (صور/GIF)", "dv:md", style="primary")],
            [b("كليشات التشغيل (صورة/GIF لكل كليشة)", "dv:tm", style="success")],
        ]
        if uid == OWNER_ID:
            rows.append([b("إضافة مطور", "dv:adddev", style="success"), b("حذف مطور", "dv:deldev", style="danger")])
        rows.append([b("واجهة المستخدم", "us:home", style="primary"), b("✖", "x:close", style="danger")])
        return kb(rows)

    async def cb_dv_home(self, c):
        await c.screen(self.dv_text(), self.dv_kb(c.uid), kind="dev")

    # ---- البوتات
    async def cb_bots(self, c):
        page = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else 0
        bots = sorted(db["bots"].values(), key=lambda r: -r["created"])
        pages = max(1, math.ceil(len(bots) / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        rows = [[b(f"@{r['username']} | {bot_status(r)}", f"dv:bot:{r['id']}",
                   style="success" if bot_status(r) == "شغّال" else "danger")]
                for r in bots[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
        nav = []
        if page > 0:
            nav.append(b("السابق", f"dv:bots:{page - 1}", style="primary"))
        if page < pages - 1:
            nav.append(b("التالي", f"dv:bots:{page + 1}", style="primary"))
        if nav:
            rows.append(nav)
        await c.screen(f"<b>كل البوتات</b>\nالعدد: <b>{len(bots)}</b> | الصفحة {page + 1} من {pages}"
                       + ("" if bots else "\n\nلا توجد بوتات بعد."), back_kb(rows, "dv:home"), kind="dev")

    def bot_of(self, c):
        return db["bots"].get(c.parts[2]) if len(c.parts) > 2 else None

    async def cb_bot(self, c):
        rec = self.bot_of(c)
        if not rec:
            await self.cb_bots(c)
            return
        child = CHILDREN.get(rec["id"])
        mode, days = credits_mode(rec), credits_days_left(rec)
        override = {"": "افتراضي", "dev": "حقوقي", "user": "حقوق المستخدم"}[rec["mode_override"]]
        text = (f"<b>@{esc(rec['username'])}</b> ({esc(rec['name'])})\n\n"
                f"المالك: {owner_tag(rec['owner'])}\nالايدي: <code>{rec['id']}</code>\n"
                f"الحالة: <b>{bot_status(rec)}</b>\n"
                f"الحساب المساعد: {child.account_line() if child else 'غير متصل'}\n"
                f"المجموعات: <b>{len(rec['groups'])}</b> | المستخدمون: <b>{len(rec['people'])}</b>\n"
                f"التشغيلات: <b>{rec['stats']['plays']}</b> | التحميلات: <b>{rec['stats']['downloads']}</b>\n"
                f"أُنشئ: {fmt_ts(rec['created'])}\n"
                f"الحقوق: وضع البوت «{override}» (الفعلي: {'حقوق المستخدم' if mode == 'user' else 'حقوقي'})"
                + (f"\nحقوق مخصصة من المالك تعود بعد {days} يوم" if rec["credits"] and days is not None else ""))
        rid = rec["id"]
        rows = [[b("تشغيل" if not rec["enabled"] else "إيقاف", f"dv:bt:{rid}",
                   style="success" if not rec["enabled"] else "danger"), b("إعادة تشغيل", f"dv:br:{rid}", style="primary")],
                [b(f"وضع الحقوق: {override}", f"dv:bm:{rid}", style="primary"),
                 b("إعادة حقوقي له", f"dv:bz:{rid}", style="primary")],
                [b("تمديد المدة الآن", f"dv:bx:{rid}", style="success")],
                [b("فتح البوت", url=f"https://t.me/{rec['username']}?start=owner", style="success", k="mu_dev"),
                 b("حذف", f"dv:bd:{rid}", style="danger")]]
        await c.screen(text, back_kb(rows, "dv:bots:0"), kind="dev")

    async def cb_bot_toggle(self, c):
        rec = self.bot_of(c)
        if rec:
            rec["enabled"] = not rec["enabled"]
            save()
            await (start_bot(rec) if rec["enabled"] else stop_bot(rec["id"]))
            if not rec["enabled"]:
                rec["status"] = "stopped"
        await self.cb_bot(c)

    async def cb_bot_extend(self, c):
        rec = self.bot_of(c)
        if rec:
            await revive(rec)
        await self.cb_bot(c)

    async def cb_bot_restart(self, c):
        rec = self.bot_of(c)
        if rec:
            rec["enabled"] = True
            await start_bot(rec)
        await self.cb_bot(c)

    async def cb_bot_mode(self, c):
        rec = self.bot_of(c)
        if rec:
            order = ["", "dev", "user"]
            rec["mode_override"] = order[(order.index(rec["mode_override"]) + 1) % 3]
            save()
        await self.cb_bot(c)

    async def cb_bot_credits_reset(self, c):
        rec = self.bot_of(c)
        if rec:
            rec["credits"] = {}
            save()
        await self.cb_bot(c)

    async def cb_bot_delete(self, c):
        rec = self.bot_of(c)
        if rec:
            await c.screen(f"حذف البوت <b>@{esc(rec['username'])}</b> نهائيًا؟",
                           kb([[b("تأكيد الحذف", f"dv:bdok:{rec['id']}", style="danger"),
                                b("إلغاء", f"dv:bot:{rec['id']}", style="primary")]]))

    async def cb_bot_delete_ok(self, c):
        rec = self.bot_of(c)
        if rec:
            await delete_bot(rec["id"])
        c.parts = ["dv", "bots", "0"]
        await self.cb_bots(c)

    # ---- الحقوق وقناة السورس
    def credits_text(self):
        mode = "حقوق المستخدم" if G["credits_mode"] == "user" else "حقوقي (مقفلة على كل البوتات)"
        return ("<b>الحقوق وقناة السورس</b>\n\n"
                f"الوضع الافتراضي: <b>{mode}</b>\n"
                f"اسم زر المطور: {esc(G['dev_name'] or 'غير محدد')}\n"
                f"رابط المطور: {esc(G['dev_url'] or 'غير محدد')}\n"
                f"قناة التحديثات: {esc(G['updates_url'] or 'غير محددة')}\n"
                f"قناة السورس: {esc(G['source_url'] or 'غير محددة')}\n\n"
                "هذه الأزرار تظهر في لوحة التشغيل ورسائل البداية لكل البوتات.\n"
                "- <b>حقوق المستخدم</b>: يستطيع كل مالك تغيير حقوق بوته من لوحته، وتعود حقوقك له تلقائيًا بعد "
                f"{CREDITS_DAYS} أيام من أول تعديل.\n"
                "- <b>حقوقي</b>: تظهر حقوقك فقط ولا يستطيع أحد تغييرها.\n"
                "يمكنك تحديد وضع مختلف لبوت معين من صفحته.")

    def credits_kb(self):
        mode = G["credits_mode"] == "user"
        return back_kb([
            [b("الوضع: حقوق المستخدم" if mode else "الوضع: حقوقي", "dv:crm", style="success" if mode else "danger")],
            [b("اسم زر المطور", "dv:crf:dev_name", style="primary"), b("رابط المطور", "dv:crf:dev_url", style="primary")],
            [b("قناة التحديثات", "dv:crf:updates_url", style="primary"),
             b("إضافة قناة السورس", "dv:crf:source_url", style="success")],
            [b("إعادة حقوقي لكل البوتات الآن", "dv:crz", style="danger")],
        ], "dv:home")

    async def cb_credits(self, c):
        await c.screen(self.credits_text(), self.credits_kb(), kind="dev")

    async def cb_credits_mode(self, c):
        G["credits_mode"] = "dev" if G["credits_mode"] == "user" else "user"
        save()
        await self.cb_credits(c)

    async def cb_credits_field(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        if key not in CREDIT_FIELDS:
            await self.cb_credits(c)
            return
        self.states[c.uid] = {"step": "cr_field", "field": key}
        hint = "اسمًا قصيرًا" if key == "dev_name" else "رابط تيليجرام (@name أو https://t.me/...)"
        await c.screen(f"أرسل {hint} لـ«{CREDIT_FIELDS[key]}».\nأرسل 0 لإزالته.", back_kb(None, "dv:cr"))

    async def step_cr_field(self, m, chat, uid, text, st):
        key, back = st["field"], back_kb(None, "dv:cr")
        if text == "0":
            G[key] = ""
        elif key == "dev_name":
            if not 1 <= len(text) <= 20:
                await self.show(chat, "الاسم من 1 إلى 20 حرفًا.", back)
                return
            G[key] = text
        else:
            link = norm_link(text)
            if not link:
                await self.show(chat, "الرابط يجب أن يكون لتيليجرام: @name أو https://t.me/...", back)
                return
            G[key] = link
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم الحفظ.\n\n" + self.credits_text(), self.credits_kb(), kind="dev")

    async def cb_credits_zero(self, c):
        for rec in db["bots"].values():
            rec["credits"] = {}
        save()
        await self.cb_credits(c)

    # ---- الاشتراك الإجباري
    def forced_view(self):
        lines = ["<b>الاشتراك الإجباري</b>", "",
                 "يُطلب من كل مستخدم الاشتراك في هذه القنوات قبل استخدام بوت الصانع وكل البوتات المصنوعة.",
                 "يجب أن يكون بوت الصانع مشرفًا في كل قناة ليتمكن من فحص الاشتراك.", ""]
        rows = []
        for i, ch in enumerate(G["forced"]):
            warn = " (البوت ليس مشرفًا هناك)" if ch.get("broken") else ""
            lines.append(f"{i + 1}. {esc(ch.get('title') or ch['chat'])}{warn}")
            rows.append([b(f"حذف: {(ch.get('title') or str(ch['chat']))[:24]}", f"dv:fsdel:{i}", style="danger")])
        if not G["forced"]:
            lines.append("لا توجد قنوات مضافة.")
        rows.insert(0, [b("إضافة قناة", "dv:fsadd", style="success")])
        return "\n".join(lines), back_kb(rows, "dv:home")

    async def cb_forced(self, c):
        text, markup = self.forced_view()
        await c.screen(text, markup, kind="dev")

    async def cb_forced_add(self, c):
        self.states[c.uid] = {"step": "fs_add"}
        await c.screen("أرسل يوزر القناة (<code>@name</code>) أو رابطها، أو حوّل رسالة منها.\n"
                       "للقناة الخاصة أرسل ايديها ثم رابط الدعوة بعده بمسافة.\n"
                       "تأكد أن بوت الصانع مشرف فيها.", back_kb(None, "dv:fs"))

    async def step_fs_add(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:fs")
        fwd = m.get("forward_from_chat") or (m.get("forward_origin") or {}).get("chat") or {}
        tokens = text.split()
        if fwd.get("id"):
            ref, rest = fwd["id"], tokens
        elif tokens:
            first, rest = tokens[0], tokens[1:]
            link = re.match(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z]\w{3,31})$", first)
            if link:
                ref = "@" + link.group(1)
            elif re.fullmatch(r"-?\d+", first):
                ref = int(first)
            else:
                ref = "@" + first.lstrip("@")
        else:
            await self.show(chat, "أرسل يوزر القناة أو ايديها.", back)
            return
        info = await self.api("getChat", chat_id=ref)
        if not info.get("ok"):
            await self.show(chat, "لم أجد هذه القناة. تأكد من الاسم وأن البوت عضو فيها.", back)
            return
        ch = info["result"]
        link = rest[0] if rest else (f"https://t.me/{ch['username']}" if ch.get("username") else "")
        if not link:
            link = (await self.api("exportChatInviteLink", chat_id=ch["id"])).get("result") or ""
        if not link.startswith("http"):
            await self.show(chat, "القناة خاصة: أرسل ايديها ثم رابط الدعوة بعده.", back)
            return
        member = await self.api("getChatMember", chat_id=ch["id"], user_id=self.bot_id)
        is_admin = member.get("ok") and member["result"].get("status") in ("administrator", "creator")
        G["forced"].append({"chat": ch["id"], "link": link, "title": ch.get("title") or ch.get("username"),
                            "broken": not is_admin})
        save()
        _sub_cache.clear()
        self.states.pop(uid, None)
        text_, markup = self.forced_view()
        await self.show(chat, ("تمت الإضافة.\n" if is_admin else "تمت الإضافة، لكن بوت الصانع ليس مشرفًا فيها فلن يعمل الفحص.\n")
                        + "\n" + text_, markup, kind="dev")

    async def cb_forced_del(self, c):
        idx = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else -1
        if 0 <= idx < len(G["forced"]):
            G["forced"].pop(idx)
            save()
            _sub_cache.clear()
        await self.cb_forced(c)

    # ---- محرك الموسيقى
    def engine_view(self):
        y, version = gy(), ytdlp_version()
        text = ("<b>محرك الموسيقى (مشترك لكل البوتات)</b>\n\n"
                f"يوتيوب: {yt_status_line()}\n"
                f"بديل ساوندكلاود: {on_off(y['fallback'])} | بروكسي: {len(proxy_list()) or 'لا'} | "
                f"IPv4 فقط: {on_off(y['ipv4'])}\n"
                f"البدء السريع (بث من الرابط): {on_off(y['fast_start'])} | تحديث yt-dlp تلقائي: {on_off(y['auto_update'])}\n"
                f"سقف مدة المقطع لكل البوتات: {G['max_min_cap']} دقيقة\n"
                f"الكاش: {cache_size() // (1024 * 1024)} من {y['cache_mb']} ميجا\n"
                f"ffmpeg: {'جاهز' if shutil.which('ffmpeg') else 'غير موجود'} | yt-dlp: {version or 'غير مثبت'} | "
                f"الكوكيز: {'مستخدمة' if os.path.exists(COOKIES_FILE) else 'غير مستخدمة (اختياري)'}")

        def flag(label, key):
            return b(f"{label}: {on_off(y[key])}", f"dv:engt:{key}", style="success" if y[key] else "danger")
        rows = [
            [b("فحص يوتيوب", "dv:engy", style="primary"), b("إعادة المحاولة الآن", "dv:engr", style="success")],
            [flag("بديل ساوندكلاود", "fallback"), flag("IPv4 فقط", "ipv4")],
            [flag("البدء السريع", "fast_start"), flag("تحديث تلقائي", "auto_update")],
            [b(f"سقف المدة: {G['max_min_cap']} د", "dv:engc:cap", style="primary"),
             b(f"الكاش: {y['cache_mb']} ميجا", "dv:engc:cache", style="primary")],
            [b("بروكسي", "dv:engp", style="primary"), b("رفع الكوكيز (اختياري)", "dv:engk", style="primary")],
            [b("تحديث yt-dlp", "dv:engu", style="success"), b("مسح الكاش", "dv:engx", style="danger")],
        ]
        return text, back_kb(rows, "dv:home")

    async def cb_engine(self, c, note=""):
        text, markup = self.engine_view()
        await c.screen(note + text, markup, kind="dev")

    async def cb_engine_flag(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        if key in ("fallback", "ipv4", "fast_start", "auto_update"):
            gy()[key] = not gy()[key]
            save()
        await self.cb_engine(c)

    async def cb_engine_cycle(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        if key == "cap":
            G["max_min_cap"] = next_preset([15, 30, 60, 120], G["max_min_cap"])
        elif key == "cache":
            gy()["cache_mb"] = next_preset([512, 1024, 2048, 5120, 10240], gy()["cache_mb"])
        save()
        await self.cb_engine(c)

    async def cb_engine_proxy(self, c):
        self.states[c.uid] = {"step": "eng_proxy"}
        await c.screen("أرسل عنوان البروكسي مثل <code>http://user:pass@host:port</code> "
                       "أو <code>socks5://host:port</code>.\nيمكنك إرسال عدة بروكسيات (بينها مسافة أو سطر جديد) "
                       "ويبدّل البوت بينها.\nيفيد إذا كان يوتيوب يحجب ايبي السيرفر. أرسل 0 لإزالته.",
                       back_kb(None, "dv:eng"))

    async def step_proxy(self, m, chat, uid, text, st):
        items = [x for x in re.split(r"[\s,]+", text.strip()) if x]
        if text.strip() != "0" and (not items or not all(re.match(r"^(https?|socks[45]h?)://\S+$", x) for x in items)):
            await self.show(chat, "الصيغة غير صحيحة. مثال: <code>http://user:pass@host:port</code>",
                            back_kb(None, "dv:eng"))
            return
        clear = text.strip() == "0"
        gy()["proxy"] = "" if clear else " ".join(items)
        save()
        self.states.pop(uid, None)
        await self.api("deleteMessage", chat_id=chat, message_id=m["message_id"])    # فيه بيانات دخول
        text_, markup = self.engine_view()
        await self.show(chat, ("تمت إزالة البروكسي.\n\n" if clear else f"تم حفظ {len(items)} بروكسي.\n\n") + text_,
                        markup, kind="dev")

    async def cb_engine_cookies(self, c):
        self.states[c.uid] = {"step": "eng_cookies"}
        await c.screen("أرسل ملف <code>cookies.txt</code> (صيغة Netscape) المصدَّر من متصفح مسجّل الدخول في يوتيوب.\n"
                       "احذف رسالتك بعد الإرسال لأن الكوكيز حساسة. أرسل 0 لحذف الكوكيز الحالية.",
                       back_kb(None, "dv:eng"))

    async def step_cookies(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:eng")
        if text == "0":
            if os.path.exists(COOKIES_FILE):
                os.remove(COOKIES_FILE)
            self.states.pop(uid, None)
            await self.show(chat, "تم حذف الكوكيز.", back)
            return
        doc = m.get("document")
        raw = await self.api.download(doc["file_id"]) if doc else None
        body = (raw or b"").decode("utf-8", "ignore")
        if "\t" not in body:
            await self.show(chat, "أرسل ملف cookies.txt بصيغة Netscape (أعمدة مفصولة بـ Tab)، أو 0 للحذف.", back)
            return
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            f.write(body)
        self.states.pop(uid, None)
        await self.api("deleteMessage", chat_id=chat, message_id=m["message_id"])
        await self.show(chat, "تم حفظ الكوكيز وحذفت رسالتك.", back)

    async def cb_engine_update(self, c):
        await c.screen("جاري تحديث yt-dlp...", None)
        ok, tail = await run_blocking(_pip_upgrade_ytdlp)
        if ok:
            yt_mark_ok()
        await self.cb_engine(c, f"تم التحديث. الإصدار الآن: {ytdlp_version()}\n\n" if ok
                             else f"فشل التحديث:\n<code>{esc(tail)}</code>\n\n")

    async def cb_engine_check(self, c):
        await c.screen("جاري فحص يوتيوب...", None)
        try:
            count = await run_blocking(_yt_probe)
            yt_mark_ok()
            note = f"يوتيوب يعمل من هذا السيرفر ({count} صيغة).\n\n"
        except Exception as e:
            if is_block_error(e):
                yt_mark_blocked(e)
            note = f"يوتيوب لا يعمل الآن:\n<code>{esc(short(e))}</code>\n\n"
        await self.cb_engine(c, note)

    async def cb_engine_reset(self, c):
        yt_mark_ok()
        await self.cb_engine(c, "أُعيد فتح يوتيوب، وسيُجرَّب عند الطلب القادم.\n\n")

    async def cb_engine_clear(self, c):
        keep = protected_paths()
        for name in os.listdir(MUSIC_DIR):
            path = os.path.join(MUSIC_DIR, name)
            if os.path.isfile(path) and path not in keep:
                os.remove(path)
        await self.cb_engine(c, "تم مسح الكاش.\n\n")

    # ---- إعدادات الصانع
    def config_view(self):
        text = ("<b>إعدادات الصانع</b>\n\n"
                f"إنشاء البوتات: <b>{'مفتوح' if G['open'] else 'مغلق'}</b>\n"
                f"بوتات لكل مستخدم: <b>{G['per_user']}</b> | الحد الأقصى للبوتات: <b>{G['max_bots']}</b>\n"
                f"رسالة الترحيب: {'مخصصة' if G['welcome'] else 'الافتراضية'}\n\n"
                "كل بوت مصنوع يستهلك ذاكرة ومعالجًا (حساب مساعد واتصال صوتي)، فاضبط الحد الأقصى بحسب سيرفرك.")
        rows = [[b("الإنشاء: مفتوح" if G["open"] else "الإنشاء: مغلق", "dv:cfgo",
                   style="success" if G["open"] else "danger")],
                [b(f"بوتات لكل مستخدم: {G['per_user']}", "dv:cfgc:per_user", style="primary"),
                 b(f"الحد الأقصى: {G['max_bots']}", "dv:cfgc:max_bots", style="primary")],
                [b("مدة التشغيل: مفعّلة" if G["trial_on"] else "مدة التشغيل: معطّلة", "dv:cfgc:trial_on",
                   style="success" if G["trial_on"] else "danger")],
                [b(f"المدة: {G['trial_days']} يوم", "dv:cfgc:trial_days", style="primary"),
                 b(f"المدعوون المطلوبون: {G['ref_need']}", "dv:cfgc:ref_need", style="primary")],
                [b("رسالة الترحيب", "dv:cfgw", style="primary")]]
        return text, back_kb(rows, "dv:home")

    async def cb_config(self, c):
        text, markup = self.config_view()
        await c.screen(text, markup, kind="dev")

    async def cb_config_open(self, c):
        G["open"] = not G["open"]
        save()
        await self.cb_config(c)

    async def cb_config_cycle(self, c):
        key = c.parts[2] if len(c.parts) > 2 else ""
        presets = {"per_user": [1, 2, 3, 5, 10], "max_bots": [10, 30, 50, 100, 200],
                   "trial_days": [3, 7, 14, 30], "ref_need": [1, 3, 5, 10]}
        if key == "trial_on":
            G["trial_on"] = not G["trial_on"]
            save()
        elif key in presets:
            G[key] = next_preset(presets[key], G[key])
            save()
        await self.cb_config(c)

    async def cb_config_welcome(self, c):
        self.states[c.uid] = {"step": "cfg_welcome"}
        await c.screen("أرسل نص رسالة الترحيب في بوت الصانع (حتى 700 حرف). أرسل 0 للنص الافتراضي.",
                       back_kb(None, "dv:cfg"))

    async def step_welcome(self, m, chat, uid, text, st):
        if text != "0" and not 1 <= len(text) <= 700:
            await self.show(chat, "النص من 1 إلى 700 حرف.", back_kb(None, "dv:cfg"))
            return
        G["welcome"] = "" if text == "0" else esc(text)
        save()
        self.states.pop(uid, None)
        text_, markup = self.config_view()
        await self.show(chat, "تم الحفظ.\n\n" + text_, markup, kind="dev")

    # ---- الردود والوسائط (لكل البوتات)
    async def save_media(self, m, allowed):
        """يحفظ ملصقًا أو صورة أو GIF من الرسالة على القرص (file_id خاص بكل بوت فلا نخزّنه). يرجع {'t','path'}."""
        if m.get("sticker") and "sticker" in allowed:
            st = m["sticker"]
            kind, fid = "sticker", st["file_id"]
            ext = "tgs" if st.get("is_animated") else "webm" if st.get("is_video") else "webp"
        elif m.get("animation") and "animation" in allowed:
            kind, fid, ext = "animation", m["animation"]["file_id"], "mp4"
        elif m.get("photo") and "photo" in allowed:
            kind, fid, ext = "photo", m["photo"][-1]["file_id"], "jpg"
        else:
            return None
        raw = await self.api.download(fid)
        if not raw:
            return None
        os.makedirs(MEDIA_DIR, exist_ok=True)
        path = os.path.join(MEDIA_DIR, f"{int(time.time() * 1000)}_{random.randint(100, 999)}.{ext}")
        with open(path, "wb") as f:
            f.write(raw)
        return {"t": kind, "path": path}

    @staticmethod
    def drop_file(item):
        try:
            if item and item.get("path"):
                os.remove(item["path"])
        except OSError:
            pass

    REPLY_KINDS = {"text": "نص", "photo": "صورة", "animation": "GIF", "sticker": "ملصق"}

    def replies_view(self):
        items = G["replies"]
        lines = ["<b>الردود</b>", "",
                 "ردود تلقائية تجيب بها كل البوتات في المجموعات عندما يكتب أحدهم الكلمة نفسها بالضبط. "
                 "الرد نص أو صورة أو GIF أو ملصق.", ""]
        rows = [[b("إضافة رد", "dv:rpadd", style="success")]]
        for i, r in enumerate(items):
            lines.append(f"{i + 1}. <code>{esc(r['k'])}</code> ← {self.REPLY_KINDS[r['t']]}")
            rows.append([b(f"حذف: {r['k'][:24]}", f"dv:rpdel:{i}", style="danger")])
        if not items:
            lines.append("لا توجد ردود.")
        return "\n".join(lines), back_kb(rows, "dv:home")

    async def cb_rp(self, c):
        text, markup = self.replies_view()
        await c.screen(text, markup, kind="dev")

    async def cb_rpadd(self, c):
        if len(G["replies"]) >= 50:
            await c.screen("وصلت للحد الأقصى (50 ردًا).", back_kb(None, "dv:rp"))
            return
        self.states[c.uid] = {"step": "rp_key"}
        await c.screen("أرسل الكلمة أو الجملة التي تُشغّل الرد (تطابق تام).", back_kb(None, "dv:rp"))

    async def step_rp_key(self, m, chat, uid, text, st):
        key = norm_ar(text.lower()).strip()
        if not 1 <= len(key) <= 40:
            await self.show(chat, "الكلمة من 1 إلى 40 حرفًا.", back_kb(None, "dv:rp"))
            return
        self.states[uid] = {"step": "rp_body", "key": key}
        await self.show(chat, "الآن أرسل الرد: نصًا، أو صورة / GIF / ملصقًا (يمكن إضافة تعليق للصورة والـ GIF).",
                        back_kb(None, "dv:rp"))

    async def step_rp_body(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:rp")
        caption = (m.get("caption") or "").strip()
        item = await self.save_media(m, ("sticker", "animation", "photo"))
        if item:
            item["text"] = esc(caption)[:900]
        elif text:
            item = {"t": "text", "path": "", "text": esc(text)[:3500]}
        else:
            await self.show(chat, "أرسل نصًا أو صورة أو GIF أو ملصقًا.", back)
            return
        item["k"] = st["key"]
        G["replies"].append(item)
        save()
        self.states.pop(uid, None)
        text_, markup = self.replies_view()
        await self.show(chat, "تمت إضافة الرد.\n\n" + text_, markup, kind="dev")

    async def cb_rpdel(self, c):
        idx = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else -1
        if 0 <= idx < len(G["replies"]):
            self.drop_file(G["replies"].pop(idx))
            save()
        await self.cb_rp(c)

    def media_view(self):
        pm = G.get("panel_media")
        kinds = {"photo": "صورة", "animation": "GIF"}
        text = ("<b>وسائط البوتات</b>\n\n"
                f"وسائط الانتظار (صور/GIF/ملصقات تظهر أثناء البحث والتحميل): <b>{len(G['media'])}</b>\n"
                f"وسائط لوحة التشغيل: <b>{kinds.get(pm['t']) if pm else 'لا يوجد'}</b>\n\n"
                f"صورة رسالة /start في بوت الصانع: <b>{'مفعّلة' if G.get('start_media') else 'لا يوجد'}</b>\n"
                "تُستعمل وسائط الانتظار واللوحة في البوتات التي لم يضف مالكها وسائط خاصة به.")
        rows = [[b("صورة/GIF رسالة /start", "dv:ssset", style="success"), b("إزالتها", "dv:ssclr", style="danger")],
                [b("إضافة وسائط الانتظار", "dv:mdadd", style="success"), b("مسحها", "dv:mdclr", style="danger")],
                [b("تعيين صورة/GIF اللوحة", "dv:pmset", style="success"), b("إزالتها", "dv:pmclr", style="danger")],
                [b("كليشات التشغيل (صورة/GIF لكل كليشة)", "dv:tm", style="success")]]
        return text, back_kb(rows, "dv:home")

    async def cb_md(self, c):
        text, markup = self.media_view()
        await c.screen(text, markup, kind="dev")

    async def cb_mdadd(self, c):
        self.states[c.uid] = {"step": "md_add"}
        await c.screen("أرسل ملصقًا أو صورة أو GIF (حتى 10، أرسلها واحدة بعد أخرى).", back_kb(None, "dv:md"))

    async def step_md_add(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:md")
        if len(G["media"]) >= 10:
            await self.show(chat, "وصلت للحد الأقصى (10). امسحها أولًا.", back)
            return
        item = await self.save_media(m, ("sticker", "animation", "photo"))
        if not item:
            await self.show(chat, "أرسل ملصقًا أو صورة أو GIF.", back)
            return
        G["media"].append(item)
        save()
        await self.show(chat, f"تمت الإضافة. العدد: <b>{len(G['media'])}</b>\nأرسل غيرها أو ارجع.", back)

    async def cb_mdclr(self, c):
        for item in G["media"]:
            self.drop_file(item)
        G["media"] = []
        save()
        await self.cb_md(c)

    async def cb_pmset(self, c):
        self.states[c.uid] = {"step": "pm_set"}
        await c.screen("أرسل الصورة أو الـ GIF الذي يظهر في لوحة التشغيل لكل البوتات.", back_kb(None, "dv:md"))

    async def step_pm_set(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:md")
        item = await self.save_media(m, ("animation", "photo"))
        if not item:
            await self.show(chat, "أرسل صورة أو GIF.", back)
            return
        self.drop_file(G.get("panel_media"))
        G["panel_media"] = item
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم تعيين وسائط لوحة التشغيل.", back)

    async def cb_ss_set(self, c):
        self.states[c.uid] = {"step": "ss_set"}
        await c.screen("أرسل الصورة أو الـ GIF الذي يظهر مع رسالة /start في بوت الصانع.", back_kb(None, "dv:md"))

    async def step_ss_set(self, m, chat, uid, text, st):
        back = back_kb(None, "dv:md")
        item = await self.save_media(m, ("animation", "photo"))
        if not item:
            await self.show(chat, "أرسل صورة أو GIF.", back)
            return
        self.drop_file(G.get("start_media"))
        G["start_media"] = item
        self.start_fid.clear()
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم تعيين صورة /start.", back)

    async def cb_ss_clr(self, c):
        self.drop_file(G.get("start_media"))
        G["start_media"] = None
        self.start_fid.clear()
        save()
        await self.cb_md(c)

    async def send_home(self, chat, uid):
        """رسالة /start في الصانع: بصورة أو GIF المطور إن وُجدت."""
        text, markup = deco(self.home_text(), "start"), self.home_kb(uid)
        item = G.get("start_media")
        if item and os.path.exists(item["path"]) and len(text) <= 1000:
            kind = item["t"]
            method = "sendPhoto" if kind == "photo" else "sendAnimation"
            params = dict(chat_id=chat, caption=text, parse_mode="HTML", reply_markup=markup)
            d = {"ok": False}
            fid = self.start_fid.get(item["path"])
            if fid:
                d = await self.api(method, **{kind: fid}, **params)
            if not d.get("ok"):
                data = await run_blocking(_read_file, item["path"])
                d = await self.api.upload(method, kind, data, os.path.basename(item["path"]), **params)
                if d.get("ok"):
                    new = _media_file_id(d["result"], kind)
                    if new:
                        self.start_fid[item["path"]] = new
            if d.get("ok"):
                return
        await self.show(chat, self.home_text(), markup, kind="start")

    async def cb_pmclr(self, c):
        self.drop_file(G.get("panel_media"))
        G["panel_media"] = None
        save()
        await self.cb_md(c)

    # ---- كليشات التشغيل: صورة أو GIF لكل كليشة
    def tm_view(self):
        media = G["tpl_media"]
        kinds = {"photo": "صورة", "animation": "GIF"}
        lines = ["<b>كليشات التشغيل</b>", "",
                 "اختر رقم الكليشة ثم أرسل صورتها أو الـ GIF الخاص بها. تظهر مع لوحة التشغيل في كل بوت "
                 "طبّق مالكه هذه الكليشة (إلا إذا وضع المالك صورة خاصة به). المالك يعاينها من لوحته ← كليشات التشغيل.", ""]
        for i, t in enumerate(TEMPLATES):
            item = media.get(str(i))
            lines.append(f"{i + 1}. {esc(t['name'])}: <b>{kinds.get(item['t']) if item else 'بدون'}</b>")
        rows, row = [], []
        for i in range(len(TEMPLATES)):
            has = str(i) in media
            row.append(b(f"{i + 1} ✓" if has else str(i + 1), f"dv:tms:{i}", style="success" if has else "primary"))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([b("مسح كل الوسائط", "dv:tmx", style="danger")])
        return "\n".join(lines), back_kb(rows, "dv:md")

    async def cb_tm(self, c):
        text, markup = self.tm_view()
        await c.screen(text, markup, kind="dev")

    async def cb_tm_pick(self, c):
        try:
            i = max(0, min(int(c.parts[2]), len(TEMPLATES) - 1))
        except (IndexError, ValueError):
            i = 0
        self.states[c.uid] = {"step": "tm_set", "i": i}
        await c.screen(f"أرسل صورة أو GIF للكليشة <b>{i + 1}</b> ({esc(TEMPLATES[i]['name'])}).\n"
                       "أرسل 0 لإزالة وسائطها.", back_kb(None, "dv:tm"))

    async def step_tm_set(self, m, chat, uid, text, st):
        i, back = st.get("i", 0), back_kb(None, "dv:tm")
        if text == "0":
            self.drop_file(G["tpl_media"].pop(str(i), None))
            save()
            self.states.pop(uid, None)
            note = f"تمت إزالة وسائط الكليشة {i + 1}."
        else:
            item = await self.save_media(m, ("animation", "photo"))
            if not item:
                await self.show(chat, "أرسل صورة أو GIF (وليس ملفًا)، أو 0 للإزالة.", back)
                return
            self.drop_file(G["tpl_media"].get(str(i)))
            G["tpl_media"][str(i)] = item
            save()
            self.states.pop(uid, None)
            note = f"تم حفظ وسائط الكليشة {i + 1}."
        text_, markup = self.tm_view()
        await self.show(chat, note + "\n\n" + text_, markup, kind="dev")

    async def cb_tm_clear(self, c):
        for item in G["tpl_media"].values():
            self.drop_file(item)
        G["tpl_media"] = {}
        save()
        await self.cb_tm(c)

    # ---- الإحصائيات
    async def cb_stats(self, c):
        page = int(c.parts[2]) if len(c.parts) > 2 and c.parts[2].isdigit() else 0
        text, markup = people_view(db["people"], page, "dv:st", "dv:home", "إحصائيات مستخدمي الصانع")
        bots = list(db["bots"].values())
        extra = (f"\n\n<b>كل البوتات</b>\nالبوتات: {len(bots)} | مستخدمو البوتات: "
                 f"{sum(len(r['people']) for r in bots)} | تشغيلات: {sum(r['stats']['plays'] for r in bots)} | "
                 f"تحميلات: {sum(r['stats']['downloads'] for r in bots)}")
        await c.screen(text + extra, markup, kind="dev")

    # ---- الإذاعة
    async def cb_bc(self, c):
        rows = [[b(f"مستخدمو الصانع ({len(db['known'])})", "dv:bct:users", style="primary")],
                [b(f"ملاك البوتات ({len({r['owner'] for r in db['bots'].values()})})", "dv:bct:owners", style="primary")]]
        await c.screen("<b>الإذاعة</b>\n\nاختر الفئة:", back_kb(rows, "dv:home"), kind="dev")

    def bc_targets(self, kind):
        ids = set(db["known"]) if kind == "users" else {r["owner"] for r in db["bots"].values()}
        ids.discard(OWNER_ID)
        return sorted(ids)

    async def cb_bc_target(self, c):
        kind = c.parts[2] if len(c.parts) > 2 else ""
        if kind in ("users", "owners"):
            self.states[c.uid] = {"step": "bc", "to": kind}
            await c.screen("أرسل الآن الرسالة التي تريد إذاعتها (نص أو صورة أو فيديو أو ملف، بأي تنسيق).",
                           back_kb(None, "dv:bc"))

    async def step_bc(self, m, chat, uid, text, st):
        self.states[uid] = {"step": "bcconfirm", "to": st["to"], "mid": m["message_id"], "chat": chat}
        await self.show(chat, f"<b>تأكيد الإذاعة</b>\n\nالمستلمون: <b>{len(self.bc_targets(st['to']))}</b>\n"
                              "سيُرسل لهم نفس رسالتك أعلاه كما هي. هل تؤكد؟",
                        back_kb([[b("تأكيد الإرسال", "dv:bcgo", style="success")]], "dv:home"))

    async def cb_bc_go(self, c):
        st = self.states.get(c.uid)
        if not st or st.get("step") != "bcconfirm":
            return
        if self.bc_busy:
            await c.screen("هناك إذاعة قيد الإرسال الآن، انتظر انتهاءها.", back_kb(None, "dv:home"))
            return
        targets = self.bc_targets(st["to"])
        self.states.pop(c.uid, None)
        await c.screen(f"بدأت الإذاعة إلى <b>{len(targets)}</b> مستخدم، وسيصلك تقرير عند الانتهاء.",
                       back_kb(None, "dv:home"))

        async def run():
            self.bc_busy = True
            try:
                await broadcast(self.api, targets, st["chat"], st["mid"], c.chat)
            finally:
                self.bc_busy = False
        self.spawn(run())

    # ---- الايموجي المميز
    @staticmethod
    def slot_pairs(slots):
        items = list(slots.items())
        return [[b(label, f"dv:emk:{key}", k=key, style="primary") for key, label in items[i:i + 2]]
                for i in range(0, len(items), 2)]

    @staticmethod
    def applied_lines(keys):
        return "\n".join(f"- {SLOT_NAMES.get(k, k)}: <code>{db['emoji'][k]}</code>" for k in keys) or "لا يوجد"

    async def cb_emoji(self, c):
        keys = [k for k in db["emoji"] if not k.startswith(("t:", "f:"))]
        rows = self.slot_pairs(BUTTON_SLOTS) + [[b("حذف ايموجي الأزرار", "dv:emojiclear", style="danger")]]
        await c.screen("<b>ايموجي الأزرار</b>\n\nاختر الزر ثم أرسل الايموجي المميز نفسه ويظهر قبل نص الزر فورًا.\n"
                       "أرسل 0 لإزالته. «كل الأزرار» يطبَّق على أي زر ليس له ايموجي خاص.\n\n"
                       f"المطبّق حاليًا:\n{self.applied_lines(keys)}", back_kb(rows, "dv:home"), kind="dev")

    async def cb_txtem(self, c):
        keys = [k for k in db["emoji"] if k.startswith(("t:", "f:"))]
        rows = self.slot_pairs(TEXT_SLOTS) + self.slot_pairs(FIELD_SLOTS)
        rows.append([b("معاينة", "dv:preview", style="success"), b("حذف ملصقات النصوص", "dv:txtclear", style="danger")])
        await c.screen("<b>ملصقات النصوص</b>\n\nملصقات مميزة تظهر داخل رسائل كل البوتات: في أول الرسالة حسب نوعها، "
                       "أو قبل عنوان الحقل (العنوان، القناة، الطالب...).\nاختر الخانة ثم أرسل الايموجي المميز نفسه، "
                       f"أو 0 لإزالته.\n\nالمطبّق حاليًا:\n{self.applied_lines(keys)}", back_kb(rows, "dv:home"), kind="dev")

    async def cb_emk(self, c):
        key = c.data.split(":", 2)[2]
        self.states[c.uid] = {"step": "emoji", "key": key}
        back = "dv:txtem" if key.startswith(("t:", "f:")) else "dv:emoji"
        await c.screen(f"أرسل الآن الايموجي المميز نفسه لـ: <b>{esc(SLOT_NAMES.get(key, key))}</b>\n"
                       "(أو رقمه)، وأرسل 0 لإزالته.", back_kb(None, back))

    async def step_emoji(self, m, chat, uid, text, st):
        key = st["key"]
        is_text = key.startswith(("t:", "f:"))
        back = "dv:txtem" if is_text else "dv:emoji"
        found = [e.get("custom_emoji_id") for e in (m.get("entities") or []) if e.get("type") == "custom_emoji"]
        eid = "0" if text == "0" else (found[0] if found else re.sub(r"\D", "", text))
        if not eid:
            await self.show(chat, "أرسل الايموجي المميز نفسه (أو رقمه)، أو 0 لإزالته.", back_kb(None, back))
            return
        if int(eid) == 0:
            db["emoji"].pop(key, None)
        else:
            db["emoji"][key] = str(eid)
        save()
        self.states.pop(uid, None)
        await self.show(chat, "تم التطبيق فورًا. ارجع للقائمة لرؤية الحالة.", back_kb(None, back))

    async def cb_emoji_clear(self, c):
        db["emoji"] = {k: v for k, v in db["emoji"].items() if k.startswith(("t:", "f:"))}
        save()
        await self.cb_emoji(c)

    async def cb_txt_clear(self, c):
        db["emoji"] = {k: v for k, v in db["emoji"].items() if not k.startswith(("t:", "f:"))}
        save()
        await self.cb_txtem(c)

    async def cb_preview(self, c):
        text = ("<b>تشغيل موسيقى</b>\n\n" + field("song", "العنوان", "<b>اسم الأغنية</b>") + "\n"
                + field("artist", "القناة", "اسم القناة") + "\n" + field("duration", "المدة", "03:45") + "\n"
                + field("by", "الطالب", "اسم المستخدم") + "\n" + progress_bar(95, 225))
        await self.api("sendMessage", chat_id=c.chat, text=deco(text, "music"), parse_mode="HTML")

    # ---- المطورون
    async def cb_adddev(self, c):
        if c.uid != OWNER_ID:
            return
        self.states[c.uid] = {"step": "adddev"}
        await c.screen("<b>إضافة مطور</b>\n\nأرسل ايدي الشخص أو حوّل رسالة منه.", back_kb(None, "dv:home"))

    async def cb_deldev(self, c):
        if c.uid != OWNER_ID:
            return
        self.states[c.uid] = {"step": "deldev"}
        lines = "\n".join(f"- <code>{d}</code>" for d in db["devs"]) or "لا يوجد"
        await c.screen(f"<b>حذف مطور</b>\n\nأرسل ايدي المطور.\n\nالمطورون:\n{lines}", back_kb(None, "dv:home"))

    @staticmethod
    def target_of(m, text):
        fwd = (m.get("forward_from") or {}).get("id") or ((m.get("forward_origin") or {}).get("sender_user") or {}).get("id")
        digits = re.sub(r"\D", "", text)
        return fwd or (int(digits) if digits else None)

    async def step_adddev(self, m, chat, uid, text, st):
        target = self.target_of(m, text)
        if uid != OWNER_ID or not target:
            await self.show(chat, "أرسل الايدي (أرقام) أو حوّل رسالة منه.", back_kb(None, "dv:home"))
            return
        self.states.pop(uid, None)
        if target == OWNER_ID or target in db["devs"]:
            msg = "هذا الشخص مطور بالفعل."
        else:
            db["devs"].append(target)
            save()
            msg = f"تمت إضافة المطور <code>{target}</code>"
            await self.api("sendMessage", chat_id=target, text="تمت إضافتك كمطور في صانع البوتات. أرسل /start.")
        await self.show(chat, msg, back_kb(None, "dv:home"))

    async def step_deldev(self, m, chat, uid, text, st):
        target = self.target_of(m, text)
        if uid != OWNER_ID or not target:
            await self.show(chat, "أرسل الايدي (أرقام) أو حوّل رسالة منه.", back_kb(None, "dv:home"))
            return
        self.states.pop(uid, None)
        if target == OWNER_ID:
            msg = "المطور الأساسي لا يمكن حذفه."
        elif target in db["devs"]:
            db["devs"].remove(target)
            save()
            msg = f"تم حذف المطور <code>{target}</code>"
        else:
            msg = "هذا الايدي ليس مطورًا."
        await self.show(chat, msg, back_kb(None, "dv:home"))


# ------------------------------------------------------------------ مهام الخلفية
async def music_ticker():
    """يحدّث شريط التقدم في لوحات التشغيل الجارية (تعديل فقط، دون إعادة إرسال)."""
    while True:
        await asyncio.sleep(2)
        try:
            now = time.monotonic()
            for child in list(CHILDREN.values()):
                for p in list(child.players.values()):
                    if p.current is None or p.paused or p.busy or not p.panels:
                        continue
                    if now - p.last_edit >= child.cfg["progress_sec"]:
                        await child.panel_show(p, resend=False)
        except Exception as e:
            log.warning("ticker: %s", e)


async def credits_tick():
    """يعيد حقوق المطور لكل بوت مرّ على تخصيص مالكه لها 7 أيام، ويخبر المالك."""
    now = now_ts()
    for rec in list(db["bots"].values()):
        cr = rec.get("credits") or {}
        if cr and now - cr.get("set_at", now) >= CREDITS_DAYS * 86400:
            rec["credits"] = {}
            save()
            child = CHILDREN.get(rec["id"])
            api = child.api if child else MAIN.api
            await api("sendMessage", chat_id=rec["owner"], parse_mode="HTML",
                      text=f"عادت حقوق المطور في بوتك <b>@{esc(rec['username'])}</b> بعد انتهاء "
                           f"{CREDITS_DAYS} أيام. يمكنك تخصيصها من جديد من «الحقوق» في لوحة المالك.")


def ref_link(uid):
    return f"https://t.me/{MAKER_USERNAME}?start=ref_{uid}"


def share_url(uid):
    return "https://t.me/share/url?url=" + quote(ref_link(uid)) + "&text=" + quote("أنشئ بوت ميوزك خاص بك مجانًا")


def owner_refs(uid):
    return db["owners"].get(str(uid), {}).get("refs", 0)


def days_left_trial(rec):
    return max(0, math.ceil((rec["expires"] - now_ts()) / 86400))


def trial_info(rec):
    if not G["trial_on"] or is_dev(rec["owner"]):
        return ""
    if rec.get("suspended"):
        return "\nالحالة: موقوف (انتهت المدة)، ادعُ أعضاء لإعادة تشغيله"
    return (f"\nباقٍ على التشغيل: <b>{days_left_trial(rec)}</b> يوم | "
            f"رصيد الدعوات: <b>{owner_refs(rec['owner'])}/{G['ref_need']}</b>")


def suspended_text(rec):
    return ("<b>تم إيقاف بوتك مؤقتًا</b>\n"
            f"@{esc(rec['username'])}\n\n"
            f"انتهت مدة التشغيل ({G['trial_days']} أيام). لإعادة تشغيله تلقائيًا ادعُ <b>{G['ref_need']}</b> أعضاء جدد "
            f"إلى صانع البوتات عبر رابطك الخاص:\n<code>{ref_link(rec['owner'])}</code>\n\n"
            f"المدعوون الآن: <b>{owner_refs(rec['owner'])}</b> من {G['ref_need']}\n"
            "يُحتسب العضو إذا كان جديدًا في الصانع وفتح الرابط وبدأ البوت (وأتمّ الاشتراك الإجباري إن وُجد).")


def suspended_kb(rec):
    return kb([[b("مشاركة رابط الدعوة", url=share_url(rec["owner"]), style="success")]])


def consume_refs(uid):
    o = db["owners"].setdefault(str(uid), {"refs": 0})
    if o["refs"] >= G["ref_need"]:
        o["refs"] -= G["ref_need"]
        return True
    return False


async def revive(rec, note=True):
    rec["suspended"], rec["warned"] = False, False
    rec["expires"] = now_ts() + G["trial_days"] * 86400
    save()
    if note:
        await MAIN.api("sendMessage", chat_id=rec["owner"], parse_mode="HTML",
                       text=f"تم تشغيل بوتك <b>@{esc(rec['username'])}</b> من جديد لمدة {G['trial_days']} أيام.")


async def suspend(rec):
    rec["suspended"] = True
    save()
    child = CHILDREN.get(rec["id"])
    if child:
        await child.stop_all()
    await MAIN.api("sendMessage", chat_id=rec["owner"], parse_mode="HTML",
                   text=suspended_text(rec), reply_markup=suspended_kb(rec))


async def trial_tick():
    if not G["trial_on"]:
        for rec in list(db["bots"].values()):
            if rec.get("suspended"):
                await revive(rec, note=False)
        return
    now = now_ts()
    for rec in list(db["bots"].values()):
        if is_dev(rec["owner"]) or rec.get("suspended") or not rec.get("enabled", True):
            continue
        left = rec["expires"] - now
        if left <= 0:
            if consume_refs(rec["owner"]):
                await revive(rec)
            else:
                await suspend(rec)
        elif left < 86400 and not rec.get("warned"):
            rec["warned"] = True
            save()
            await MAIN.api("sendMessage", chat_id=rec["owner"], parse_mode="HTML",
                           text=f"سينتهي تشغيل بوتك <b>@{esc(rec['username'])}</b> خلال أقل من يوم.\n"
                                f"لتمديده ادعُ {G['ref_need']} أعضاء جدد عبر رابطك:\n<code>{ref_link(rec['owner'])}</code>",
                           reply_markup=suspended_kb(rec))


async def trial_loop():
    await asyncio.sleep(90)
    while True:
        try:
            await trial_tick()
        except Exception as e:
            log.warning("trial_loop: %s", e)
        await asyncio.sleep(600)


async def credits_loop():
    await asyncio.sleep(60)
    while True:
        try:
            await credits_tick()
        except Exception as e:
            log.warning("credits_loop: %s", e)
        await asyncio.sleep(3600)


async def ytdlp_autoupdate():
    """yt-dlp يتعطل كلما غيّر يوتيوب شيئًا، فنحدّثه كل 24 ساعة (يمكن إيقافه من لوحة المطور)."""
    await asyncio.sleep(120)
    while True:
        y = gy()
        try:
            if y["auto_update"] and time.time() - y["last_update"] > 24 * 3600:
                ok, tail = await run_blocking(_pip_upgrade_ytdlp)
                y["last_update"] = time.time()
                save()
                if ok:
                    yt_mark_ok()
                    log.info("تم تحديث yt-dlp إلى %s", ytdlp_version())
                else:
                    log.warning("فشل تحديث yt-dlp: %s", tail)
        except Exception as e:
            log.warning("autoupdate: %s", e)
        await asyncio.sleep(3600)


async def housekeeping():
    last_backup = time.monotonic()
    while True:
        await asyncio.sleep(10)
        try:
            flush()
            if time.monotonic() - last_backup > 6 * 3600:
                last_backup = time.monotonic()
                backup_db()
        except Exception as e:
            log.warning("housekeeping: %s", e)


async def delayed_start(rec, delay):
    await asyncio.sleep(delay)
    try:
        await start_bot(rec)
    except Exception as e:
        log.exception("start %s: %s", rec.get("username"), e)


async def warm_yt():
    try:
        await run_blocking(_warm_yt)
    except Exception as e:
        log.info("warm: %s", e)


async def main():
    global HTTP, MAIN
    if not BOT_TOKEN:
        sys.exit("ضع توكن بوت الصانع في BOT_TOKEN (بوت جديد من BotFather) ثم أعد التشغيل.")
    HTTP = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0), timeout=aiohttp.ClientTimeout(total=70))
    os.makedirs(MUSIC_DIR, exist_ok=True)
    await run_blocking(ensure_ffmpeg)
    await run_blocking(ensure_js_runtime)
    MAIN = Factory()
    await MAIN.start()
    for coro in (music_ticker(), credits_loop(), trial_loop(), ytdlp_autoupdate(), housekeeping(), warm_yt()):
        asyncio.ensure_future(coro)
    for i, rec in enumerate(list(db["bots"].values())):
        if rec.get("enabled", True):
            asyncio.ensure_future(delayed_start(rec, i * 1.5))
    log.info("صانع البوتات يعمل: @%s | البوتات: %s | OWNER_ID=%s", MAIN.username, len(db["bots"]), OWNER_ID)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        flush()