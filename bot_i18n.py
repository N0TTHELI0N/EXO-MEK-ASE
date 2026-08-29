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
        "en": "Could not connect to the ARK server. Contact an admin.",
    },
    "nitrado_not_configured": {
        "ar": "Nitrado غير مُعد. استخدم `/set-nitrado-token`.",
        "en": "Nitrado is not configured. Use `/set-nitrado-token`.",
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
    "purchase_queued": {
        "ar": "تم شراء **{dino}** بالمستوى **{level}**! سيتم التسليم داخل اللعبة بواسطة الإدمن قريباً.",
        "en": "Purchased **{dino}** at level **{level}**! Delivery in-game by an admin will be arranged shortly.",
    },
    "pending_title": {
        "ar": "المشتريات المعلّقة",
        "en": "Pending Purchases",
    },
    "pending_empty": {
        "ar": "لا توجد مشتريات معلّقة.",
        "en": "No pending purchases.",
    },
    "pending_not_found": {
        "ar": "لم يتم العثور على هذا الشراء.",
        "en": "That purchase was not found.",
    },
    "purchase_spawn_failed": {
        "ar": "فشل تسليم الشراء **#{purchase_id}**. تأكد أن Nitrado مُعد وأنك داخل اللعبة.",
        "en": "Failed to deliver purchase **#{purchase_id}**. Make sure Nitrado is configured and you are in-game.",
    },
    "purchase_delivered": {
        "ar": "تم تسليم **{dino}** بالمستوى **{level}** (شراء **#{purchase_id}**).",
        "en": "Delivered **{dino}** at level **{level}** (purchase **#{purchase_id}**).",
    },
    "purchase_cancelled": {
        "ar": "تم إلغاء الشراء **#{purchase_id}** واسترداد **{amount}** نقطة.",
        "en": "Purchase **#{purchase_id}** cancelled and **{amount}** points refunded.",
    },
    "pending_embed": {
        "ar": "**{buyer}** اشترى **{dino}** بالمستوى {level} ({price} نقطة).\nاضغط تسليم عندما تكون بجانبه داخل اللعبة.\n`{blueprint}`",
        "en": "**{buyer}** bought **{dino}** at level {level} ({price} pts).\nClick **Deliver** when you are next to them in-game.\n`{blueprint}`",
    },
    "done_embed": {
        "ar": "**{buyer}** - {dino} Lvl {level} ({price} نقطة)\nتم التسليم بواسطة: {delivered_by}",
        "en": "**{buyer}** - {dino} Lvl {level} ({price} pts)\nDelivered by: {delivered_by}",
    },
    "custom_not_found": {
        "ar": "الأمر المخصص `{name}` غير موجود.",
        "en": "Custom command `{name}` not found.",
    },
    "custom_ran": {
        "ar": "تم تنفيذ:\n```{command}```",
        "en": "Executed:\n```{command}```",
    },
    "custom_empty": {
        "ar": "لا توجد أوامر مخصصة بعد.",
        "en": "No custom commands yet.",
    },
    "runner_disabled": {
        "ar": "مشغل الأوامر معطّل. فعّله من لوحة التحكم.",
        "en": "The command runner is disabled. Enable it from the dashboard.",
    },
    "forum_topic": {
        "ar": "سجل أوامر السيرفر - مصنف في ٤ أقسام",
        "en": "Server command log - categorized into 4 sections",
    },
    "forum_thread_intro": {
        "ar": "قسم **{label}** - تُعرض هنا الأوامر المسجلة.",
        "en": "**{label}** section - logged commands appear here.",
    },
    "shop_forum_topic": {
        "ar": "سجل متجر الديناصورات - التسليمات المكتملة والمعلقة",
        "en": "Dino shop log - completed and pending deliveries",
    },
    "shop_forum_thread_intro": {
        "ar": "قسم **{label}** - تظهر هنا حركة المتجر.",
        "en": "**{label}** section - shop activity appears here.",
    },
    "tribe_forum_topic": {
        "ar": "سجلات قبائل السيرفر - مشاركة لكل قبيلة",
        "en": "Server tribe logs - one post per tribe",
    },
    "tribe_forum_thread_intro": {
        "ar": "سجل أحداث قبيلة **{tribe}** - تظهر أحداثها هنا.",
        "en": "Tribe **{tribe}** event log - its events appear here.",
    },
    "tribe_forum_no_tribes": {
        "ar": "لا توجد قبائل بعد. أضف قبائل عبر /add-tribe-name وستُنشأ مشاركاتها تلقائيًا.",
        "en": "No tribes yet. Add tribes via /add-tribe-name and their posts will be created automatically.",
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
