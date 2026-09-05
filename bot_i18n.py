# bot_i18n.py
# Bilingual translation support (Arabic / English)

import time

import guild_settings

STRINGS = {
    "admin_only": {
        "ar": "للإدمن فقط.",
        "en": "Admin only.",
    },
    "user_banned_from_bot": {
        "ar": "❌ أنت محظور من استخدام هذا البوت.",
        "en": "❌ You are banned from using this bot.",
    },
    "license_gate_required": {
        "ar": "❌ هذا السيرفر ليس لديه رخصة صالحة. فعّلها بأمر /set-license.",
        "en": "❌ This server has no valid license. Activate one with /set-license.",
    },
    "automod_profanity_deleted": {
        "ar": "تم حذف رسالتك لاحتوائها على كلمة ممنوعة.",
        "en": "Your message was deleted for containing a banned word.",
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
    "license_key_format_invalid": {
        "ar": "❌ صيغة مفتاح الرخصة غير صالحة.",
        "en": "❌ Invalid license key format.",
    },
    "license_key_mismatch": {
        "ar": "❌ مفتاح الرخصة هذا لا يطابق الرخصة الصادرة لهذا السيرفر، أو أنه منتهي.",
        "en": "❌ This license key does not match the license issued for this server, or it has expired.",
    },
    "license_verified_unlimited": {
        "ar": "♾️ تم التحقق من الرخصة (غير محدودة).",
        "en": "♾️ License verified (unlimited).",
    },
    "license_verified_until": {
        "ar": "✅ تم التحقق من الرخصة. نشطة حتى {expiry}.",
        "en": "✅ License verified. Active until {expiry}.",
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
    "backup_title": {
        "ar": "📦 نسخ Nitrado الاحتياطية",
        "en": "📦 Nitrado Backups",
    },
    "top_players_title": {
        "ar": "🏆 أفضل اللاعبين",
        "en": "🏆 Top Players",
    },
    "server_restarted_whitelist": {
        "ar": "🔄 تمت إعادة تشغيل السيرفر. تم تحديث الوايت ليست الساعة {time} UTC.",
        "en": "🔄 Server restarted. Whitelist updated at {time} UTC.",
    },
    "whitelist_path_set": {
        "ar": "✅ تم تعيين مجلد الوايت ليست إلى:\n`{path}`",
        "en": "✅ Whitelist directory set to:\n`{path}`",
    },
    "whitelist_title": {
        "ar": "📋 الوايت ليست",
        "en": "📋 Whitelist",
    },
    "whitelist_status_active_word": {
        "ar": "نشط",
        "en": "active",
    },
    "whitelist_status_pending_word": {
        "ar": "معلق",
        "en": "pending",
    },
    "whitelist_none_linked": {
        "ar": "لا يوجد لاعبون مرتبطون.",
        "en": "No linked players.",
    },
    "wl_status_body": {
        "ar": "**PSN:** `{psn}`\n**الحالة:** {status}",
        "en": "**PSN:** `{psn}`\n**Status:** {status}",
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
    "playtime_no_data": {
        "ar": "لا توجد بيانات تتبع بعد. يبدأ تتبع وقت اللعب من لحظة تفعيل البوت على السيرفر.",
        "en": "No tracking data yet. Playtime starts accumulating once the bot is live on the server.",
    },
    "playtime_tracking_note": {
        "ar": "يتم تتبع الوقت من لحظة تفعيل البوت (لا يوجد سجل سابق من Nitrado).",
        "en": "Tracked from when the bot went live (Nitrado provides no history).",
    },

    # ── admin ────────────────────────────────────────────────
    "nitrado_token_saved": {
        "ar": "✅ تم حفظ رمز Nitrado.",
        "en": "✅ Nitrado API token saved.",
    },
    "log_channel_set": {
        "ar": "✅ تم تعيين قناة السجل إلى {channel}",
        "en": "✅ Log channel set to {channel}",
    },
    "user_banned": {
        "ar": "✅ تم حظر {user} من البوت.",
        "en": "✅ {user} banned from the bot.",
    },
    "no_guilds": {
        "ar": "لا توجد سيرفرات.",
        "en": "No guilds.",
    },
    "commands_synced": {
        "ar": "✅ تمت المزامنة: {count} أمرًا.",
        "en": "✅ Synced {count} commands.",
    },
    "sync_failed": {
        "ar": "❌ فشلت المزامنة: {error}",
        "en": "❌ Sync failed: {error}",
    },
    "bot_owner_only": {
        "ar": "❌ مطور البوت فقط.",
        "en": "❌ Bot owner only.",
    },
    "no_command_permissions": {
        "ar": "📋 لا توجد صلاحيات أوامر مكونة.\nكل الأوامر تستخدم صلاحيات ديسكورد الافتراضية.",
        "en": "📋 No command permissions configured.\nAll commands use default Discord permissions.",
    },
    "command_permissions_title": {
        "ar": "**صلاحيات الأوامر**",
        "en": "**Command Permissions**",
    },
    "command_permission_removed": {
        "ar": "✅ لم يعد بإمكان {role} استخدام `/{command}`.",
        "en": "✅ Role {role} can no longer use `/{command}`.",
    },
    "command_permissions_cleared": {
        "ar": "✅ تمت إعادة `/{command}` إلى الصلاحيات الافتراضية.",
        "en": "✅ `/{command}` reset to default permissions.",
    },
    "automod_list_footer": {
        "ar": "الإجمالي: {count} كلمة مخصصة",
        "en": "Total: {count} custom words",
    },

    # ── cluster ──────────────────────────────────────────────
    "cluster_alpha_set": {
        "ar": "⭐ تم تعيين القبيلة الأساسية للكلستر **{cluster}** إلى **{tribe}**{channel}.",
        "en": "⭐ Alpha tribe for cluster **{cluster}** set to **{tribe}**{channel}.",
    },
    "cluster_empty": {
        "ar": "لا توجد كلسترات بعد.",
        "en": "No clusters configured yet.",
    },
    "cluster_alpha_title": {
        "ar": "قبائل الكلستر",
        "en": "Cluster Alphas",
    },
    "cluster_removed": {
        "ar": "✅ تمت إزالة الكلستر #{cluster_id}.",
        "en": "✅ Cluster #{cluster_id} removed.",
    },
    "cluster_not_found": {
        "ar": "❌ الكلستر #{cluster_id} غير موجود.",
        "en": "❌ Cluster #{cluster_id} not found.",
    },
    "cluster_status_title": {
        "ar": "حالة الكلستر",
        "en": "Cluster Status",
    },
    "cluster_active_count": {
        "ar": "🌐 الكلسترات النشطة: **{count}**",
        "en": "🌐 Active clusters: **{count}**",
    },

    # ── leaderboard ──────────────────────────────────────────
    "leaderboard_title": {
        "ar": "🏆 لوحة المتصدرين",
        "en": "🏆 Leaderboard",
    },
    "leaderboard_setup": {
        "ar": "✅ سيتم تحديث لوحة المتصدرين تلقائيًا في {channel} كل {interval} دقيقة.",
        "en": "✅ Leaderboard will auto-update in {channel} every {interval} min.",
    },
    "tribe_owner_set": {
        "ar": "✅ {member} هو الآن مالك **{tribe}**.",
        "en": "✅ {member} is now the owner of **{tribe}**.",
    },
    "tribe_points_added": {
        "ar": "✅ تمت إضافة **{amount}** إلى **{tribe}**. الرصيد الجديد: **{balance}**.",
        "en": "✅ Added **{amount}** to **{tribe}**. New balance: **{balance}**.",
    },
    "tribe_points_removed": {
        "ar": "✅ تم خصم **{amount}** من **{tribe}**. الرصيد الجديد: **{balance}**.",
        "en": "✅ Removed **{amount}** from **{tribe}**. New balance: **{balance}**.",
    },

    # ── staff ────────────────────────────────────────────────
    "staff_payment_recorded": {
        "ar": "💳 تم تسجيل **{currency} {amount:,.2f}** لـ {member} (*{role}*, {payment_type}). رقم الدفعة `#{payment_id}`.",
        "en": "💳 Recorded **{currency} {amount:,.2f}** for {member} (*{role}*, {payment_type}). Payment ID `#{payment_id}`.",
    },
    "staff_no_payments": {
        "ar": "لا توجد دفعات موظفين.",
        "en": "No staff payments found.",
    },
    "staff_payments_title": {
        "ar": "دفعات الموظفين",
        "en": "Staff Payments",
    },
    "staff_payment_status_set": {
        "ar": "✅ تم تحديث الدفعة #{payment_id} إلى **{status}**.",
        "en": "✅ Payment #{payment_id} marked **{status}**.",
    },
    "staff_payment_not_found": {
        "ar": "❌ الدفعة #{payment_id} غير موجودة.",
        "en": "❌ Payment #{payment_id} not found.",
    },
    "staff_payment_deleted": {
        "ar": "🗑️ تم حذف الدفعة #{payment_id}.",
        "en": "🗑️ Payment #{payment_id} deleted.",
    },

    # ── whitelist ────────────────────────────────────────────
    "whitelist_path_set": {
        "ar": "✅ تم تعيين مجلد الوايت ليست إلى:\n`{path}`",
        "en": "✅ Whitelist directory set to:\n`{path}`",
    },
    "no_linked_players": {
        "ar": "لا يوجد لاعبون مربوطون.",
        "en": "No linked players.",
    },
    "whitelist_title": {
        "ar": "📋 الوايت ليست",
        "en": "📋 Whitelist",
    },
    "restart_whitelist_updated": {
        "ar": "🔄 تمت إعادة تشغيل السيرفر. تم تحديث الوايت ليست الساعة {time} UTC.",
        "en": "🔄 Server restarted. Whitelist updated at {time} UTC.",
    },

    # ── tribelog ─────────────────────────────────────────────
    "tribe_empty_name": {
        "ar": "❌ اسم القبيلة فارغ.",
        "en": "❌ Empty tribe name.",
    },
    "tribe_name_added": {
        "ar": "✅ تمت إضافة **{name}** لقائمة المراقبة.",
        "en": "✅ **{name}** added to monitoring list.",
    },
    "tribelog_toggled": {
        "ar": "✅ مراقبة سجلات القبائل **{status}**.",
        "en": "✅ Tribe log monitoring **{status}**.",
    },
    "tribelog_channel_set": {
        "ar": "✅ تم تعيين قناة سجلات القبائل إلى {channel}",
        "en": "✅ Tribe log channel set to {channel}",
    },
    "tribelog_source_set": {
        "ar": "✅ تم تعيين مصدر سجلات القبائل إلى **{source}**.",
        "en": "✅ Tribe log source set to **{source}**.",
    },
    "tribelog_config_saved": {
        "ar": "✅ تم حفظ إعدادات Nitrado لسجلات القبائل.",
        "en": "✅ Tribe log Nitrado config saved.",
    },
    "tribelog_forum_ready": {
        "ar": "✅ فوروم سجلات القبائل جاهز.\nالفوروم: {forum}\nالقبائل المراقبة ({count}):\n{lines}",
        "en": "✅ Tribe-logs forum ready.\nForum: {forum}\nMonitored tribes ({count}):\n{lines}",
    },
    "tribelog_config_title": {
        "ar": "📋 إعدادات سجلات القبائل",
        "en": "📋 Tribe Log Config",
    },

    # ── moderation ───────────────────────────────────────────
    "warning_msg": {
        "ar": "⚠️ تم تحذير **{player}**. السبب: {reason}\nالتحذيرات النشطة: **{count}/{threshold}**",
        "en": "⚠️ **{player}** warned. Reason: {reason}\nActive warnings: **{count}/{threshold}**",
    },
    "tempwarn_msg": {
        "ar": "⚠️ تم تحذير **{player}** مؤقتًا لمدة **{hours}h**. السبب: {reason}\nالتحذيرات النشطة: **{count}/{threshold}**",
        "en": "⚠️ **{player}** temp-warned for **{hours}h**. Reason: {reason}\nActive warnings: **{count}/{threshold}**",
    },
    "no_warnings": {
        "ar": "لا توجد تحذيرات لـ **{player}**.",
        "en": "No warnings found for **{player}**.",
    },
    "warnings_cleared": {
        "ar": "✅ تم مسح جميع تحذيرات **{player}**.",
        "en": "✅ All warnings cleared for **{player}**.",
    },
    "warning_removed": {
        "ar": "✅ تمت إزالة التحذير #{warning_id}.",
        "en": "✅ Warning #{warning_id} removed.",
    },
    "warnings_title": {
        "ar": "تحذيرات {player}",
        "en": "Warnings for {player}",
    },
    "no_punishments": {
        "ar": "لا توجد عقوبات لـ **{player}**.",
        "en": "No punishments found for **{player}**.",
    },
    "punishment_banned": {
        "ar": "🔨 تم حظر **{player}**.",
        "en": "🔨 **{player}** banned.",
    },
    "punishment_tempbanned": {
        "ar": "🔨 تم حظر **{player}** مؤقتًا لمدة **{hours}h**.",
        "en": "🔨 **{player}** temp-banned for **{hours}h**.",
    },
    "ban_failed": {
        "ar": "❌ فشل حظر **{player}** (خطأ في الأمر)",
        "en": "❌ Failed to ban **{player}** (command error)",
    },
    "ips_banned_count": {
        "ar": "📡 تم حظر {count} عنوان IP.",
        "en": "📡 Banned {count} IP address(es).",
    },
    "no_ips_to_ban": {
        "ar": "ℹ️ لا توجد عناوين IP مسجلة لحظرها (أضف عناوين IP في تبويب مكافحة الإساءة باللوحة).",
        "en": "ℹ️ No recorded IPs to ban (add IPs in dashboard Anti-Abuse tab).",
    },
    "wipe_done": {
        "ar": "🗑️ تم **{wipe}** لـ **{player}**.",
        "en": "🗑️ **{player}** {wipe} done.",
    },
    "punishment_history_title": {
        "ar": "سجل العقوبات: {player}",
        "en": "Punishment History: {player}",
    },
    "blacklisted": {
        "ar": "⛔ تم وضع **{player}** في القائمة السوداء.",
        "en": "⛔ **{player}** blacklisted.",
    },
    "already_blacklisted": {
        "ar": "ℹ️ **{player}** موجود بالفعل في القائمة السوداء.",
        "en": "ℹ️ **{player}** is already blacklisted.",
    },
    "unblacklisted": {
        "ar": "✅ تمت إزالة **{player}** من القائمة السوداء ({count} سجل{suffix}).",
        "en": "✅ **{player}** removed from blacklist ({count} record{suffix}).",
    },
    "unban_failed_note": {
        "ar": "\n`UnBan` فشل (السيرفر غير قابل للوصول / غير مُعد) — السجل ما زال محذوفًا.",
        "en": "\n`UnBan` failed (server not reachable / not configured) — record still removed.",
    },
    "no_blacklists": {
        "ar": "لا يوجد لاعبون في القائمة السوداء.",
        "en": "No players are blacklisted.",
    },
    "blacklisted_title": {
        "ar": "اللاعبون في القائمة السوداء",
        "en": "Blacklisted Players",
    },
    "warning_threshold_set": {
        "ar": "✅ تم تعيين حد التحذيرات إلى **{count}**.",
        "en": "✅ Warning threshold set to **{count}**.",
    },
    "auto_punishment_set": {
        "ar": "✅ تم تعيين العقوبة التلقائية إلى **{type}**.",
        "en": "✅ Auto-punishment set to **{type}**.",
    },
    "auto_tempban_duration_set": {
        "ar": "✅ تم تعيين مدة الحظر التلقائي إلى **{hours}h**.",
        "en": "✅ Auto-tempban duration set to **{hours}h**.",
    },
    "tempwarn_expiry_set": {
        "ar": "✅ تم تعيين صلاحية التحذير المؤقت الافتراضية إلى **{hours}h**.",
        "en": "✅ Default tempwarn expiry set to **{hours}h**.",
    },
    "punishment_log_set": {
        "ar": "✅ تم تعيين قناة سجل العقوبات إلى {channel}",
        "en": "✅ Punishment log channel set to {channel}",
    },
    "tribe_member_added": {
        "ar": "✅ تمت إضافة **{player}** إلى قبيلة **{tribe}**.",
        "en": "✅ **{player}** added to tribe **{tribe}**.",
    },
    "server_status_title": {
        "ar": "🖥️ حالة السيرفر",
        "en": "🖥️ Server Status",
    },
    "field_status": {
        "ar": "الحالة",
        "en": "Status",
    },
    "field_players": {
        "ar": "اللاعبون",
        "en": "Players",
    },
    "field_player_list": {
        "ar": "قائمة اللاعبين",
        "en": "Player List",
    },
    "server_status_error": {
        "ar": "❌ خطأ في جلب الحالة: `{error}`",
        "en": "❌ Error fetching status: `{error}`",
    },
    "server_restart_triggered": {
        "ar": "🔄 تم تشغيل إعادة تشغيل السيرفر.",
        "en": "🔄 Server restart triggered.",
    },
    "server_restart_failed": {
        "ar": "❌ فشل تشغيل إعادة التشغيل.",
        "en": "❌ Failed to trigger restart.",
    },
    "server_stop_triggered": {
        "ar": "⏹️ تم تشغيل إيقاف السيرفر.",
        "en": "⏹️ Server stop triggered.",
    },
    "server_stop_failed": {
        "ar": "❌ فشل تشغيل الإيقاف.",
        "en": "❌ Failed to trigger stop.",
    },
    "auto_banned": {
        "ar": "🔨 تم الحظر التلقائي لـ **{player}**.",
        "en": "🔨 **{player}** auto-banned.",
    },
    "auto_ban_failed": {
        "ar": "❌ فشل الحظر التلقائي.",
        "en": "❌ Auto-ban failed.",
    },
    "auto_tempbanned": {
        "ar": "🔨 تم الحظر التلقائي المؤقت لـ **{player}** لمدة **{hours}h**.",
        "en": "🔨 **{player}** auto temp-banned for **{hours}h**.",
    },
    "auto_tempban_failed": {
        "ar": "❌ فشل الحظر التلقائي المؤقت.",
        "en": "❌ Auto-tempban failed.",
    },
    "auto_wipe_done": {
        "ar": "🗑️ **{player}** تم {wipe} تلقائيًا.",
        "en": "🗑️ **{player}** auto-{wipe}.",
    },
    "auto_unbanned": {
        "ar": "✅ تم إلغاء حظر **{player}** تلقائيًا (انتهت مدة الحظر المؤقت).",
        "en": "✅ **{player}** automatically unbanned (tempban expired).",
    },

    # ── player_ops ───────────────────────────────────────────
    "player_online": {
        "ar": "🟢 متصل",
        "en": "🟢 Online",
    },
    "player_offline": {
        "ar": "🔴 غير متصل",
        "en": "🔴 Offline",
    },
    "player_unknown": {
        "ar": "⚪ غير معروف",
        "en": "⚪ Unknown",
    },
    "field_in_game_status": {
        "ar": "الحالة داخل اللعبة",
        "en": "In-game status",
    },
    "field_tribe": {
        "ar": "القبيلة",
        "en": "Tribe",
    },
    "field_active_warnings": {
        "ar": "التحذيرات النشطة",
        "en": "Active warnings",
    },
    "field_player_id": {
        "ar": "معرف اللاعب",
        "en": "Player ID",
    },
    "field_ping": {
        "ar": "البنق",
        "en": "Ping",
    },
    "field_punishments": {
        "ar": "العقوبات ({count})",
        "en": "Punishments ({count})",
    },
    "field_recorded_ips": {
        "ar": "عناوين IP المسجلة",
        "en": "Recorded IPs",
    },
    "field_discord_account": {
        "ar": "حساب ديسكورد",
        "en": "Discord account",
    },
    "no_alts_detected": {
        "ar": "✅ لا توجد حسابات بديلة مكتشفة لـ **{player}**. (أضف المزيد من بيانات IP على اللوحة لتحسين الاكتشاف)",
        "en": "✅ No alt accounts detected for **{player}**. (Add more IP data on the dashboard to improve detection)",
    },
    "alts_detected": {
        "ar": "⚠️ حسابات بديلة محتملة لـ **{player}** (عنوان IP مشترك):",
        "en": "⚠️ Possible alt account(s) for **{player}** (shared IP):",
    },
    "alt_banned": {
        "ar": "⛔ محظور",
        "en": "⛔ banned",
    },
    "alt_clean": {
        "ar": "✅ نظيف",
        "en": "✅ clean",
    },
    "no_ip_bans": {
        "ar": "لا توجد عناوين IP محظورة.",
        "en": "No IP addresses are banned.",
    },
    "banned_ips_title": {
        "ar": "عناوين IP المحظورة",
        "en": "Banned IPs",
    },
    "ip_banned": {
        "ar": "📡 تم حظر IP **{ip}**.",
        "en": "📡 IP **{ip}** banned.",
    },
    "ip_already_banned": {
        "ar": "ℹ️ IP **{ip}** كان محظورًا بالفعل.",
        "en": "ℹ️ IP **{ip}** was already banned.",
    },
    "ip_linked_account_kicked": {
        "ar": "\n🔨 تم طرد/حظر الحساب المرتبط **{player}** داخل اللعبة.",
        "en": "\n🔨 Kicked/banned linked account **{player}** in-game.",
    },
    "ip_unbanned": {
        "ar": "✅ تم إلغاء حظر IP **{ip}**.",
        "en": "✅ IP **{ip}** unbanned.",
    },
    "ip_not_banned": {
        "ar": "ℹ️ IP **{ip}** غير موجود في قائمة الحظر.",
        "en": "ℹ️ IP **{ip}** was not in the ban list.",
    },
    "ip_recorded": {
        "ar": "✅ تم تسجيل IP **{ip}** لـ **{player}**.",
        "en": "✅ IP **{ip}** recorded for **{player}**.",
    },
    "footer_premium_license": {
        "ar": "الميزات المميزة تتطلب رخصة صالحة.",
        "en": "Basic premium features require a valid license.",
    },
    "none_value": {
        "ar": "لا شيء",
        "en": "None",
    },

    # ── anti_abuse ───────────────────────────────────────────
    "no_admin_actions": {
        "ar": "لا توجد إجراءات إدارية مسجلة بعد.",
        "en": "No admin actions logged yet.",
    },
    "audit_log_title": {
        "ar": "🛡️ سجل تدقيق مكافحة الإساءة",
        "en": "🛡️ Anti-Abuse Audit Log",
    },
    "ip_harvest_toggled": {
        "ar": "📡 الجمع التلقائي لعناوين IP **{state}**.",
        "en": "📡 Automatic IP harvesting **{state}**.",
    },
    "anti_abuse_title": {
        "ar": "🛡️ مكافحة الإساءة",
        "en": "🛡️ Anti-Abuse",
    },
    "auto_ip_harvest": {
        "ar": "**جمع IP التلقائي:** {state}",
        "en": "**Auto IP harvesting:** {state}",
    },
    "admin_actions_logged": {
        "ar": "**الإجراءات الإدارية المسجلة:** {count}",
        "en": "**Admin actions logged:** {count}",
    },
    "ip_records_count": {
        "ar": "**سجلات IP:** {count}",
        "en": "**IP records:** {count}",
    },
    "ip_bans_count": {
        "ar": "**حظر IP:** {count}",
        "en": "**IP bans:** {count}",
    },
    "auto_ban_alts": {
        "ar": "**الحظر التلقائي للحسابات البديلة:** {state} (الحد: {threshold})",
        "en": "**Auto-ban alts:** {state} (threshold: {threshold})",
    },
    "on_state": {
        "ar": "✅ مفعّل",
        "en": "✅ On",
    },
    "off_state": {
        "ar": "❌ معطّل",
        "en": "❌ Off",
    },
    "alt_detected_title": {
        "ar": "🚨 تم اكتشاف حساب بديل محتمل",
        "en": "🚨 Possible Alt Account Detected",
    },
    "alt_detected_body": {
        "ar": "**{player}** دخل من IP `{ip}` وهو مرتبط أيضًا بـ **{alt}**.\n\nربما نفس الشخص يلعب بحساب بديل.",
        "en": "**{player}** joined from IP `{ip}` which is also linked to **{alt}**.\n\nPossibly the same person playing on an alt account.",
    },
    "alt_detected_footer": {
        "ar": "الاكتشاف التلقائي لمكافحة الإساءة",
        "en": "Anti-Abuse auto-detection",
    },
    "auto_ban_msg": {
        "ar": "🔨 **حظر تلقائي:** تم حظر `{player}` نهائيًا لعودته بحسابات بديلة (مرتبط بـ {alts}).",
        "en": "🔨 **Auto-ban:** `{player}` permanently banned for returning on alt account(s) (linked to {alts}).",
    },

    # ── chat_bridge ──────────────────────────────────────────
    "chat_bridge_toggled": {
        "ar": "✅ جسر شات اللعبة **{state}**.",
        "en": "✅ In-game chat bridge **{state}**.",
    },
    "chat_log_channel_set": {
        "ar": "✅ تم تعيين قناة سجل الشات أحادي الاتجاه إلى {channel}",
        "en": "✅ One-way chat log channel set to {channel}",
    },
    "relay_channel_set": {
        "ar": "✅ تم تعيين قناة الترحيل ثنائية الاتجاه إلى {channel}",
        "en": "✅ Two-way relay channel set to {channel}",
    },
    "chat_bridge_state": {
        "ar": "⚙️ جسر الشات: داخل اللعبة→ديسكورد: **{relay_out}**، ديسكورد→اللعبة: **{relay_in}**",
        "en": "⚙️ Chat bridge: in→discord: **{relay_out}**, discord→game: **{relay_in}**",
    },
    "chat_bridge_sent": {
        "ar": "✅ تم إرسال الرسالة إلى شات اللعبة.",
        "en": "✅ Message sent into game chat.",
    },
    "chat_bridge_failed": {
        "ar": "❌ فشل — السيرفر غير قابل للوصول.",
        "en": "❌ Failed — server not reachable.",
    },
    "chat_bridge_title": {
        "ar": "💬 جسر الشات",
        "en": "💬 Chat Bridge",
    },
    "no_auto_triggers": {
        "ar": "لا توجد مشغلات كشف تلقائي بعد.",
        "en": "No auto-detection triggers yet.",
    },
    "trigger_added": {
        "ar": "✅ تمت إضافة المشغل **{word}** → **{punishment}**{suffix}.",
        "en": "✅ Trigger **{word}** added → **{punishment}**{suffix}.",
    },
    "trigger_removed": {
        "ar": "✅ تمت إزالة المشغل **{word}**.",
        "en": "✅ Removed trigger **{word}**.",
    },
    "trigger_not_found": {
        "ar": "❌ المشغل **{word}** غير موجود.",
        "en": "❌ Trigger **{word}** not found.",
    },
    "triggers_title": {
        "ar": "مشغلات شات اللعبة",
        "en": "In-Game Chat Triggers",
    },
    "trigger_toggled": {
        "ar": "✅ القاعدة #{word_id} **{state}**.",
        "en": "✅ Rule #{word_id} **{state}**.",
    },
    "triggers_cleared": {
        "ar": "🗑️ تمت إزالة جميع مشغلات شات اللعبة.",
        "en": "🗑️ All in-game chat triggers removed.",
    },
    "cooldown_set": {
        "ar": "⏱️ تم تعيين فترة تباطؤ العقوبة التلقائية إلى **{minutes}** دقيقة.",
        "en": "⏱️ Auto-punishment cooldown set to **{minutes}** minutes.",
    },
    "hours_suffix": {
        "ar": " ({hours}h)",
        "en": " ({hours}h)",
    },
    "enabled_word": {
        "ar": "مفعّل",
        "en": "enabled",
    },
    "disabled_word": {
        "ar": "معطّل",
        "en": "disabled",
    },
    "chat_forward_line": {
        "ar": "💬 **{channel}** · **{player}**: {message}",
        "en": "💬 **{channel}** · **{player}**: {message}",
    },
    "auto_warned_chat": {
        "ar": "⚠️ **{player}** تم **تحذيره** تلقائيًا ({reason})",
        "en": "⚠️ **{player}** auto-**warned** ({reason})",
    },
    "auto_blacklisted_chat": {
        "ar": "⛔ **{player}** تمت **قائمته السوداء** تلقائيًا ({reason})",
        "en": "⛔ **{player}** auto-**blacklisted** ({reason})",
    },
    "auto_tempbanned_chat": {
        "ar": "🔨 **{player}** تم **حظره مؤقتًا** تلقائيًا لمدة {hours}h ({reason})",
        "en": "🔨 **{player}** auto **temp-banned** for {hours}h ({reason})",
    },
    "auto_banned_chat": {
        "ar": "🔨 **{player}** تم **حظره** تلقائيًا ({reason})",
        "en": "🔨 **{player}** auto-**banned** ({reason})",
    },
    "status_enabled_field": {
        "ar": "**مفعّل:** {state}",
        "en": "**Enabled:** {state}",
    },
    "status_log_channel_field": {
        "ar": "**قناة السجل:** {channel}",
        "en": "**Log channel:** {channel}",
    },
    "status_log_channel_not_set": {
        "ar": "**قناة السجل:** غير معيّنة",
        "en": "**Log channel:** not set",
    },
    "status_relay_channel_field": {
        "ar": "**قناة الترحيل:** {channel}",
        "en": "**Relay channel:** {channel}",
    },
    "status_relay_channel_not_set": {
        "ar": "**قناة الترحيل:** غير معيّنة",
        "en": "**Relay channel:** not set",
    },
    "status_relay_out_field": {
        "ar": "**اللعبة→ديسكورد (relay_out):** {state}",
        "en": "**In→Discord (relay_out):** {state}",
    },
    "status_relay_in_field": {
        "ar": "**ديسكورد→اللعبة (relay_in):** {state}",
        "en": "**Discord→Game (relay_in):** {state}",
    },
    "deliver_button_label": {
        "ar": "تسليم",
        "en": "Deliver",
    },
    "cancel_button_label": {
        "ar": "إلغاء",
        "en": "Cancel",
    },
    "pending_embed_title": {
        "ar": "#{purchase_id} · {dino} مستوى {level}",
        "en": "#{purchase_id} · {dino} Lvl {level}",
    },
    "purchase_footer": {
        "ar": "شراء #{purchase_id}",
        "en": "Purchase #{purchase_id}",
    },
    "done_embed_title": {
        "ar": "✅ {dino} مستوى {level}",
        "en": "✅ {dino} Lvl {level}",
    },
    "shop_dino_line": {
        "ar": "**{name}** — مستوى {min}-{max} — {price} نقطة",
        "en": "**{name}** — Lvl {min}-{max} — {price} pts",
    },

    # ── shop ─────────────────────────────────────────────────
    "dino_added": {
        "ar": "✅ تمت إضافة **{name}** إلى المتجر.",
        "en": "✅ **{name}** added to the shop.",
    },
    "dino_removed": {
        "ar": "✅ تمت إزالة **{name}** من المتجر.",
        "en": "✅ **{name}** removed from the shop.",
    },
    "shop_dinos_title": {
        "ar": "🦕 داينوات المتجر",
        "en": "🦕 Shop Dinosaurs",
    },
    "shop_channels_set": {
        "ar": "✅ التسليمات المعلقة → {pending_channel}\n✅ التسليمات المكتملة → {done_channel}",
        "en": "✅ Pending deliveries → {pending_channel}\n✅ Delivered purchases → {done_channel}",
    },
    "min_level_set": {
        "ar": "✅ تم تعيين الحد الأدنى للمستوى إلى **{level}** لهذا السيرفر.",
        "en": "✅ Minimum level set to **{level}** for this server.",
    },

    # ── custom commands ──────────────────────────────────────
    "command_disabled": {
        "ar": "❌ هذا الأمر معطّل.",
        "en": "❌ This command is disabled.",
    },
    "invalid_command_name": {
        "ar": "❌ اسم الأمر غير صالح.",
        "en": "❌ Invalid command name.",
    },
    "custom_created": {
        "ar": "✅ تم إنشاء الأمر المخصص `/{name}`.\nاستخدم `/custom name:{name}` لتشغيله.",
        "en": "✅ Custom command `/{name}` created.\nUse `/custom name:{name}` to run it.",
    },
    "custom_deleted": {
        "ar": "✅ تم حذف الأمر المخصص `/{name}`.",
        "en": "✅ Custom command `/{name}` deleted.",
    },
    "custom_not_found": {
        "ar": "❌ الأمر المخصص `/{name}` غير موجود.",
        "en": "❌ Custom command `/{name}` not found.",
    },
    "custom_commands_title": {
        "ar": "⚙️ الأوامر المخصصة",
        "en": "⚙️ Custom Commands",
    },
    "custom_permission_denied": {
        "ar": "❌ لا تملك صلاحية استخدام هذا الأمر.",
        "en": "❌ You don't have permission to use this command.",
    },
    "custom_disabled_suffix": {
        "ar": " (معطّل)",
        "en": " (disabled)",
    },
    "forum_log_title": {
        "ar": "{emoji} {label}",
        "en": "{emoji} {label}",
    },
    "forum_log_body": {
        "ar": "**{who}** نفّذ:\n```{cmd}```",
        "en": "**{who}** ran:\n```{cmd}```",
    },
    "shop_delivery_done_title": {
        "ar": "✅ تم التسليم",
        "en": "✅ Delivery Done",
    },
    "shop_delivery_done_body": {
        "ar": "استلم **{buyer}** **{dino}** (مستوى {level})",
        "en": "**{buyer}** received **{dino}** (Lvl {level})",
    },
    "shop_delivery_cancelled_title": {
        "ar": "❌ تم الإلغاء",
        "en": "❌ Delivery Cancelled",
    },
    "shop_delivery_cancelled_body": {
        "ar": "أُلغي **{dino}** لـ **{buyer}** (استرداد {price})",
        "en": "**{buyer}** - **{dino}** cancelled (refund {price})",
    },
    "shop_purchase_queued_title": {
        "ar": "⏳ شراء معلق",
        "en": "⏳ Purchase Queued",
    },
    "shop_purchase_queued_body": {
        "ar": "طلب **{buyer}** **{dino}** (مستوى {level}, {price} نقطة)",
        "en": "**{buyer}** ordered **{dino}** (Lvl {level}, {price} pts)",
    },
    "automod_log_alert": {
        "ar": "🚨 **تنبيه الأتمود**\n```\n{line}\n```",
        "en": "🚨 **Automod Alert**\n```\n{line}\n```",
    },
    "forum_error": {
        "ar": "❌ تعذر إنشاء الفوروم: {error}",
        "en": "❌ Could not create forum: {error}",
    },
    "forums_partial": {
        "ar": "⚠️ تم إنشاء {created}/4 مواضيع فقط. المفقود: {missing}.{errors} أعد تشغيل الأمر للمحاولة.",
        "en": "⚠️ Only {created}/4 threads were created. Missing: {missing}.{errors} Run the command again to retry.",
    },
    "forum_ready": {
        "ar": "✅ فوروم سجل السيرفر جاهز.\nالفوروم: {forum}\nالمواضيع: 🦖 <#{thread_dino}> · 🎁 <#{thread_gfi}> · 🧍 <#{thread_player}> · 🎮 <#{thread_gcm}>",
        "en": "✅ Server-log forum ready.\nForum: {forum}\nThreads: 🦖 <#{thread_dino}> · 🎁 <#{thread_gfi}> · 🧍 <#{thread_player}> · 🎮 <#{thread_gcm}>",
    },
    "shop_forum_partial": {
        "ar": "⚠️ تعذر إنشاء جميع مواضيع المتجر. المفقود: {missing}.{errors} أعد تشغيل الأمر للمحاولة.",
        "en": "⚠️ Could not create all shop threads. Missing: {missing}.{errors} Run the command again to retry.",
    },
    "shop_forum_ready": {
        "ar": "✅ فوروم سجل المتجر جاهز.\nالفوروم: {forum}\nالمواضيع: ✅ <#{thread_done}> · ⏳ <#{thread_pending}>",
        "en": "✅ Shop-logs forum ready.\nForum: {forum}\nThreads: ✅ <#{thread_done}> · ⏳ <#{thread_pending}>",
    },

    # ── automod ──────────────────────────────────────────────
    "automod_alert": {
        "ar": "🚨 تنبيه الأتمود",
        "en": "🚨 Automod Alert",
    },
    "automod_muted_spam": {
        "ar": "🔇 {user} تم كتمه لمدة {minutes} دقيقة (سبام).",
        "en": "🔇 {user} muted for {minutes} min (spam).",
    },

    # ── help / info (dropdown help) ──────────────────────────
    "help_welcome_title": {
        "ar": "🤖 مرحبًا في بوت إكسو ميك!",
        "en": "🤖 Welcome to Exo-Mek Bot!",
    },
    "help_welcome_desc": {
        "ar": "بوت إدارة متكامل لسيرفرات **ARK: Survival Evolved**.\nاختر فئة من القائمة أدناه لاستعراض الأوامر.",
        "en": "All-in-one management bot for **ARK: Survival Evolved**.\nPick a category from the dropdown below to browse commands.",
    },
    "help_about_label": {
        "ar": "ℹ️ عن البوت",
        "en": "ℹ️ About",
    },
    "help_about_desc": {
        "ar": "نبذة عن البوت + روابط",
        "en": "Info about the bot + links",
    },
    "help_setup_label": {
        "ar": "⚙️ الإعداد",
        "en": "⚙️ Setup",
    },
    "help_setup_desc": {
        "ar": "كيفية إعداد البوت",
        "en": "How to set up the bot",
    },
    "help_placeholder": {
        "ar": "اختر قسمًا…",
        "en": "Choose a section…",
    },
    "help_about_field_desc": {
        "ar": "الوصف",
        "en": "Description",
    },
    "help_about_field_links": {
        "ar": "روابط مفيدة",
        "en": "Useful links",
    },
    "help_about_field_how": {
        "ar": "الإعداد السريع",
        "en": "Quick start",
    },
    "help_about_body": {
        "ar": "**إكسو ميك** هو بوت إدارة شامل لسيرفرات ARK: Survival Evolved يشمل:\n\n• إدارة اللاعبين والعقوبات والوايت ليست والـ IP\n• متجر داينوات بنظام نقاط\n• لوحة متصدرين وسجلات قبائل\n• مراقبة الشات والأتمود ومكافحة الإساءة\n• نسخ احتياطي وتحكم بالسيرفر عبر Nitrado\n• لوحة تحكم ويب كاملة\n\nاللغة الحالية: {lang_name} — غيّرها بأمر `/set-language`.",
        "en": "**Exo-Mek** is an all-in-one management bot for ARK: Survival Evolved servers featuring:\n\n• Player management, punishments, whitelist and IP tools\n• Dino shop with a points system\n• Leaderboard and tribe logs\n• Chat monitoring, automod and anti-abuse\n• Backups and server control via Nitrado\n• Full web dashboard\n\nCurrent language: {lang_name} — change it with `/set-language`.",
    },
    "help_about_dashboard": {
        "ar": "لوحة التحكم",
        "en": "Dashboard",
    },
    "help_about_invite": {
        "ar": "إضافة البوت",
        "en": "Invite Bot",
    },
    "help_about_dashboard_url": {
        "ar": "لوحة تحكم الويب لإدارة كل شيء من متصفحك — من السيرفرات والأوامر إلى اللاعبين والدفعات.",
        "en": "Web dashboard for managing everything from your browser — from servers and commands to players and payments.",
    },
    "help_about_invite_url": {
        "ar": "ادعُ البوت إلى سيرفرك للبدء.",
        "en": "Invite the bot to your server to get started.",
    },
    "help_setup_body": {
        "ar": "**كيف تبدأ خلال 5 دقائق:**\n\n1. **أضف البوت** إلى سيرفرك (زر الإضافة من قسم «عن البوت»).\n2. **ادخل إلى لوحة التحكم** واختر سيرفرك — دع البوت للوصول إلى سيرفرك.\n3. **فعّل رخصة سيرفرك** بأمر `/set-license` مع المفتاح الصادر لك.\n4. **اربط سيرفر الآرك**: بأمر `/set-nitrado-token` ضع رمز Nitrado ورقم الخدمة.\n5. من **لوحة التحكم**: أعطِ البوت الصلاحيات، اختر اللغة، واضبط القنوات والإعدادات.\n6. استمتع! استخدم `/help` لاستعراض كل الأوامر حسب الفئة.\n\n{license_hint}",
        "en": "**Get started in 5 minutes:**\n\n1. **Invite the bot** to your server (Invite button in the About section).\n2. **Open the dashboard** and pick your server — make sure the bot can access it.\n3. **Activate your server license** with `/set-license` using the key you received.\n4. **Link your ARK server**: use `/set-nitrado-token` with your Nitrado API token and service ID.\n5. From the **dashboard**: grant bot permissions, pick the language, and configure channels & settings.\n6. Enjoy! Use `/help` anytime to browse commands by category.\n\n{license_hint}",
    },
    "help_license_active": {
        "ar": "✓ رخصة سيرفرك **نشطة**.",
        "en": "✓ Your server license is **active**.",
    },
    "help_license_inactive": {
        "ar": "⚠ لا توجد رخصة نشطة — استخدم `/set-license` لتفعيل سيرفرك.",
        "en": "⚠ No active license — use `/set-license` to activate your server.",
    },
    "help_category_header": {
        "ar": "📖 أوامر: {label}",
        "en": "📖 Commands: {label}",
    },
    "help_footer_hint": {
        "ar": "اختر فئة من القائمة لعرض أوامرها",
        "en": "Pick a category from the dropdown to see its commands",
    },
    "help_no_description": {
        "ar": "لا يوجد وصف",
        "en": "No description",
    },
    "help_category_empty": {
        "ar": "لا توجد أوامر في هذا التصنيف",
        "en": "No commands in this category.",
    },
}

DEFAULT_LANGUAGE = "ar"

# Small TTL cache for content overrides so we don't hit the DB on every
# bot message. Owner edits show up within a few seconds on every server.
_OVERRIDE_CACHE = {}
_OVERRIDE_CACHE_TTL = 5.0


def _get_override(key: str, lang: str):
    now = time.time()
    entry = _OVERRIDE_CACHE.get(key)
    if entry and now - entry[0] < _OVERRIDE_CACHE_TTL:
        return entry[1].get(lang)
    value = guild_settings.get_content_override(key, lang)
    _OVERRIDE_CACHE[key] = (now, {lang: value})
    return value


def t(guild_id: int, key: str, **kwargs) -> str:
    lang = guild_settings.get_setting(guild_id, "bot_language", DEFAULT_LANGUAGE)
    override = _get_override(key, lang)
    translations = STRINGS.get(key, {})
    if override:
        text = override
    else:
        text = translations.get(lang, translations.get(DEFAULT_LANGUAGE, key))
    try:
        return text.format_map(_SafeDict(kwargs))
    except (KeyError, IndexError, ValueError):
        return text


class _SafeDict(dict):
    """A dict that returns '{key}' for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return '{' + key + '}'
