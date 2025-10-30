# -----------------------------------------------------------------------------
# 🔹 المتطلبات (يجب تثبيتها)
# pip install python-telegram-bot httpx python-dotenv
# -----------------------------------------------------------------------------

import os
import datetime
import asyncio  # لاستخدام time.sleep غير المتزامن
import httpx    # بديل requests غير المتزامن
from zoneinfo import ZoneInfo  # لمعالجة التوقيت بدقة (يتطلب بايثون 3.9+)
from dotenv import load_dotenv # لتحميل التوكن من ملف .env
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import logging

# إعداد تسجيل الأخطاء (Logging) لمتابعة ما يحدث
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# تحميل المتغيرات من ملف .env
load_dotenv()

# 🔹 توكن البوت (يتم جلبه الآن من ملف .env)
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("لم يتم العثور على BOT_TOKEN! تأكد من وجود ملف .env")
    exit() # إيقاف التشغيل إذا لم يتم العثور على التوكن

# 🔹 ملف التخزين
DOMAINS_FILE = "domains.txt"


# 🟢 دالة لإضافة دومينات (أصبحت async)
async def add_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # التأكد من أن الرسالة موجودة
    if not update.message or not update.message.text:
        return

    domains_text = update.message.text.replace("/adddomains", "").strip()
    domains = [d.strip() for d in domains_text.split("\n") if d.strip()]

    if not domains:
        await update.message.reply_text("⚠️ أرسل لائحة الدومينات بعد الأمر /adddomains")
        return

    # عملية الكتابة في الملف سريعة، لا داعي لتعقيدها بـ aiofiles
    try:
        with open(DOMAINS_FILE, "a") as f:
            for domain in domains:
                f.write(domain + "\n")
        
        await update.message.reply_text(f"✅ تمت إضافة {len(domains)} دومين(ات) بنجاح!")
    except Exception as e:
        logger.error(f"Error writing to domains file: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء حفظ الدومينات.")


# 🕒 دالة لتحويل التوقيت من UTC إلى توقيت المغرب (بشكل دقيق)
def convert_to_morocco_time(utc_time_str: str) -> str:
    try:
        # إزالة 'Z' واستبدالها بـ +00:00 ليتوافق مع ISO format
        if utc_time_str.endswith("Z"):
            utc_time_str = utc_time_str[:-1] + "+00:00"

        # قراءة الوقت بصيغة ISO
        utc_time = datetime.datetime.fromisoformat(utc_time_str)
        
        # التأكد من أن الوقت المستلم هو UTC (أحياناً لا يتم تحديده)
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=datetime.timezone.utc)

        # تحديد التوقيت المحلي للمغرب (الدار البيضاء)
        morocco_tz = ZoneInfo("Africa/Casablanca")
        
        # التحويل إلى توقيت المغرب
        morocco_time = utc_time.astimezone(morocco_tz)
        
        return morocco_time.strftime("%Y-%m-%d %H:%M:%S")
        
    except (ValueError, TypeError, ImportError) as e:
        logger.error(f"Error converting time: {e} for input {utc_time_str}")
        return "؟ توقيت غير معروف" # رسالة احتياطية


# 🔍 دالة للتحقق من تواريخ انتهاء الدومينات (أصبحت async وتستخدم httpx)
async def check_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not os.path.exists(DOMAINS_FILE):
        await update.message.reply_text("🚫 ما كاين حتى دومين فالقائمة.")
        return

    try:
        with open(DOMAINS_FILE, "r") as f:
            domains = [d.strip() for d in f.readlines() if d.strip()]
    except Exception as e:
        logger.error(f"Error reading domains file: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء قراءة قائمة الدومينات.")
        return

    if not domains:
        await update.message.reply_text("📭 اللائحة خاوية.")
        return
    
    await update.message.reply_text("🔍 جاري فحص الدومينات... المرجو الانتظار.")

    results = []
    # نستخدم httpx.AsyncClient للطلبات غير المتزامنة
    async with httpx.AsyncClient() as client:
        for domain in domains:
            url = f"https://rdap.verisign.com/com/v1/domain/{domain}"
            try:
                r = await client.get(url, timeout=10)
                r.raise_for_status() # يطلق خطأ إذا كان الـ status code هو 4xx أو 5xx

                data = r.json()
                expiration = next(
                    (e["eventDate"] for e in data.get("events", []) if e["eventAction"] == "expiration"), None
                )
                
                if expiration:
                    maroc_time = convert_to_morocco_time(expiration)
                    results.append(f"🌐 {domain} → ⏰ {maroc_time}")
                else:
                    results.append(f"⚠️ {domain} : ما كاينش تاريخ انتهاء.")
            
            except httpx.HTTPStatusError as e:
                logger.warning(f"RDAP API error for {domain}: {e}")
                results.append(f"❌ {domain}: خطأ فـ RDAP API (Status: {e.response.status_code}).")
            except httpx.RequestError as e:
                logger.error(f"Network error for {domain}: {e}")
                results.append(f"⚠️ {domain}: خطأ في الشبكة.")
            except Exception as e:
                logger.error(f"Generic error for {domain}: {e}")
                results.append(f"⚠️ {domain}: {str(e)}")

            # نستخدم asyncio.sleep بدلاً من time.sleep
            await asyncio.sleep(1) # باش ماندوزوش بزاف الطلبات دفعة وحدة

    message = "\n".join(results)
    await update.message.reply_text(message if message else "😕 ما كاين حتى نتيجة.")


# 🧾 دالة تعرض جميع الدومينات المسجلة (أصبحت async)
async def list_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
        
    if not os.path.exists(DOMAINS_FILE):
        await update.message.reply_text("🚫 ما كاين حتى دومين فالقائمة.")
        return

    try:
        with open(DOMAINS_FILE, "r") as f:
            domains = [d.strip() for d in f.readlines() if d.strip()]

        if domains:
            await update.message.reply_text("📋 اللائحة ديال الدومينات:\n" + "\n".join(domains))
        else:
            await update.message.reply_text("📭 اللائحة خاوية.")
    except Exception as e:
        logger.error(f"Error reading domains file for list_domains: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء عرض اللائحة.")


# 🗑️ دالة لمسح اللائحة (أصبحت async)
async def clear_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
        
    if os.path.exists(DOMAINS_FILE):
        try:
            os.remove(DOMAINS_FILE)
            await update.message.reply_text("🧹 تم مسح جميع الدومينات.")
        except OSError as e:
            logger.error(f"Error removing domains file: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء مسح الملف.")
    else:
        await update.message.reply_text("⚠️ ما كاين حتى ملف أصلاً.")


# 🚀 إعداد البوت (بالطريقة الجديدة)
def main():
    logger.info("Building application...")
    application = Application.builder().token(BOT_TOKEN).build()

    # إضافة الأوامر
    application.add_handler(CommandHandler("adddomains", add_domains))
    application.add_handler(CommandHandler("checkdomains", check_domains))
    application.add_handler(CommandHandler("listdomains", list_domains))
    application.add_handler(CommandHandler("cleardomains", clear_domains))

    logger.info("Bot is starting polling...")
    # تشغيل البوت
    application.run_polling()


if __name__ == "__main__":
    main()
