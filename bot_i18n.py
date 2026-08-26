# bot_i18n.py
# Bilingual translation support (Arabic / English)

import guild_settings

STRINGS = {
    "admin_only": {
        "ar": "للإدمن فقط.",
        "en": "Admin only.",
    },
    "help_text_updated": {
        "ar": "تم تحديث نص المساعدة لـ **{key}**.",
        "en": "Help text for **{key}** updated.",
    },
    "no_permission": {
        "ar": "ما عندك صلاحية تستخدم هذا الأمر.",
        "en": "You don't have permission to use this command.",
    },
    "error_generic": {
        "ar": "حدث خطأ. حاول مرة ثانية.",
        "en": "An error occurred. Please try again.",
    },
    "rcon_failed": {
        "ar": "تعذر الاتصال بسيرفر الآرك. تواصل مع الإدمن.",
        "en": "Could not connect to the ARK server (RCON). Contact an admin.",
    },
    "sftp_not_configured": {
        "ar": "SFTP غير مُعد.",
        "en": "SFTP is not configured.",
    },
    "license_invalid": {
        "ar": "الرخصة غير صالحة أو منتهية.",
        "en": "Invalid or expired license.",
    },
    "balance_msg": {
        "ar": "رصيدك الحالي: **{points}** نقطة.",
        "en": "Your current balance: **{points}** points.",
    },
    "shop_empty": {
        "ar": "لا توجد داينوات متاحة في المتجر بعد.",
        "en": "No dinosaurs available in the shop yet.",
    },
    "dino_not_available": {
        "ar": "هذا الداينو غير متاح بالمتجر.",
        "en": "This dinosaur is not available in the shop.",
    },
    "level_not_allowed": {
        "ar": "المستوى لازم يكون بين **{min_level}** و **{max_level}**.",
        "en": "Level must be between **{min_level}** and **{max_level}**.",
    },
    "insufficient_points": {
        "ar": "تحتاج **{price}** نقطة بس عندك **{current}** بس.",
        "en": "You need **{price}** points but you only have **{current}**.",
    },
    "purchase_rcon_failed": {
        "ar": "فشل الاتصال بالسيرفر. حاول مرة ثانية.",
        "en": "Failed to connect to the server. Please try again later.",
    },
    "purchase_success": {
        "ar": "تم شراء ورسبنة **{dino}** بالمستوى **{level}** بنجاح!",
        "en": "Successfully purchased and spawned **{dino}** at level **{level}**!",
    },
    "points_added": {
        "ar": "تم إضافة **{amount}** نقطة. الرصيد الجديد: **{balance}**.",
        "en": "**{amount}** points added. New balance: **{balance}**.",
    },
    "points_removed": {
        "ar": "تم خصم **{amount}** نقطة. الرصيد الجديد: **{balance}**.",
        "en": "**{amount}** points removed. New balance: **{balance}**.",
    },
    "whitelist_added": {
        "ar": "تمت إضافة **{gamertag}** للوايت ليست.",
        "en": "**{gamertag}** has been added to the whitelist.",
    },
    "whitelist_removed": {
        "ar": "تمت إزالة **{gamertag}** من الوايت ليست.",
        "en": "**{gamertag}** has been removed from the whitelist.",
    },
    "whitelist_not_found": {
        "ar": "هذا العضو غير مسجل بالوايت ليست.",
        "en": "This member is not in the whitelist.",
    },
    "linkpsn_success": {
        "ar": "تم ربط **{gamertag}** مع {member}. سيتم إضافتهم للوايت ليست عند إعادة التشغيل.",
        "en": "Linked **{gamertag}** to {member}. They will be added to the whitelist on next restart.",
    },
    "unlinkpsn_success": {
        "ar": "تم فصل PSN عن {member}.",
        "en": "Unlinked PSN from {member}.",
    },
    "wl_not_registered": {
        "ar": "{member} غير مسجل بنظام الوايت ليست.",
        "en": "{member} is not registered in the whitelist system.",
    },
    "whitelist_pending_restart": {
        "ar": "في انتظار إعادة التشغيل",
        "en": "Pending restart",
    },
    "whitelist_active": {
        "ar": "نشط",
        "en": "Active",
    },
    "restart_scheduled": {
        "ar": "تم جدولة إعادة تشغيل السيرفر الساعة **{time}** UTC.",
        "en": "Server restart scheduled for **{time}** UTC.",
    },
    "restart_failed": {
        "ar": "فشل في جدولة إعادة تشغيل السيرفر.",
        "en": "Failed to schedule server restart.",
    },
    "backup_created": {
        "ar": "تم إنشاء النسخة الاحتياطية: **{name}**",
        "en": "Backup created: **{name}**",
    },
    "backup_restored": {
        "ar": "تمت استعادة النسخة الاحتياطية **{name}**.",
        "en": "Backup **{name}** restored.",
    },
    "backup_list_empty": {
        "ar": "لا توجد نسخ احتياطية.",
        "en": "No backups found.",
    },
    "backup_failed": {
        "ar": "فشلت عملية النسخ الاحتياطي.",
        "en": "Backup operation failed.",
    },
    "tribelog_no_entries": {
        "ar": "لا توجد سجلات قبيلة.",
        "en": "No tribe log entries found.",
    },
    "help_title": {
        "ar": "دليل الأوامر",
        "en": "Command Help",
    },
    "help_description": {
        "ar": "الأوامر المتاحة:",
        "en": "Here are the available commands:",
    },
    "automod_word_added": {
        "ar": "تمت إضافة الكلمة `{word}` لمراقبة الأتمود.",
        "en": "Word `{word}` added to automod monitoring.",
    },
    "automod_word_removed": {
        "ar": "تمت إزالة الكلمة `{word}` من مراقبة الأتمود.",
        "en": "Word `{word}` removed from automod monitoring.",
    },
    "automod_word_not_found": {
        "ar": "الكلمة `{word}` غير موجودة.",
        "en": "Word `{word}` not found.",
    },
    "automod_words_empty": {
        "ar": "لا توجد كلمات مخصصة بعد.\nالكلمات الافتراضية لا تزال نشطة.",
        "en": "No custom words added yet.\nDefault words are still active.",
    },
    "automod_words_cleared": {
        "ar": "تم مسح جميع الكلمات المخصصة.",
        "en": "All custom automod words cleared.",
    },
    "language_set": {
        "ar": "تم تغيير اللغة إلى **{lang_name}**.",
        "en": "Language set to **{lang_name}**.",
    },
}

DEFAULT_LANGUAGE = "ar"


def t(guild_id: int, key: str, **kwargs) -> str:
    lang = guild_settings.get_setting(guild_id, "bot_language", DEFAULT_LANGUAGE)
    translations = STRINGS.get(key, {})
    text = translations.get(lang, translations.get(DEFAULT_LANGUAGE, key))
    try:
        return text.format_map(_SafeDict(kwargs))
    except (KeyError, IndexError, ValueError):
        return text


class _SafeDict(dict):
    """A dict that returns '{key}' for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return '{' + key + '}'
