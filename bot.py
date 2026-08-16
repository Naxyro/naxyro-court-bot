"""
==============================================================================
🏛️ СИСТЕМА СУДЕБНОГО КОНТРОЛЯ | Специально для проекта RMRP
🧑‍💻 Разработчик Naxyro
==============================================================================
"""

import discord
from discord.ext import commands, tasks
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# ==================== НАСТРОЙКИ И КОНФИГУРАЦИЯ ====================

BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА"  
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "ССЫЛКА_НА_ВАШУ_ТАБЛИЦУ"

SERVER_CHANNELS = {
    "Арбат": 1529573516670664918,
    "Тверской": 1529573558987128913,
    "Рублевка": 1529573614511325355,
    "Патрики": 1529573478309822667,
    "Кутузовский": 1529573656932651078
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
sheet = gc.open_by_url(SPREADSHEET_URL)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== ИЕРАРХИЯ И СПИСКИ ДОСТУПОВ ====================

MANAGEMENT_ROLES = [
    "Председатель Верховного Суда", "Зам. ПВС", "Заместитель ПВС",
    "Секретарь Президиума", "Высшая квалификационная коллегия судей", "ВККС", "Председатель ВККС"
]

HIGH_JUDGE_ROLES = ["Верховный Судья", "ВС"]
LIMITED_ACCESS_ROLES = ["Московский городской судья", "МГС", "Судья МГС"]

SERVERS = ["Арбат", "Тверской", "Рублевка", "Патрики", "Кутузовский"]
SERVER_CHOICES = [discord.app_commands.Choice(name=s, value=s) for s in SERVERS]

CATEGORY_CHOICES = [
    discord.app_commands.Choice(name="Гражданское судопроизводство", value="Гражданское судопроизводство"),
    discord.app_commands.Choice(name="Уголовное судопроизводство", value="Уголовное судопроизводство"),
    discord.app_commands.Choice(name="Административное судопроизводство", value="Административное судопроизводство"),
    discord.app_commands.Choice(name="Адм. судопроизводство по адм. делам", value="Адм. судопроизводство по адм. делам"),
    discord.app_commands.Choice(name="Апелляция", value="Апелляция"),
    discord.app_commands.Choice(name="Кассация (Президиум)", value="Кассация (Президиум)")
]

# ==================== ТЕХНИЧЕСКИЕ ФУНКЦИИ ====================

def check_user_role_level(interaction: discord.Interaction) -> str:
    user_roles = [role.name.lower() for role in interaction.user.roles]
    management = [r.lower() for r in MANAGEMENT_ROLES]
    high_judge = [r.lower() for r in HIGH_JUDGE_ROLES]
    limited = [r.lower() for r in LIMITED_ACCESS_ROLES]
    
    if any(role in management for role in user_roles): return "MANAGEMENT"
    elif any(role in high_judge for role in user_roles): return "HIGH_JUDGE"
    elif any(role in limited for role in user_roles): return "LIMITED"
    return "NONE"

def get_server_name(user_id: int, choice: discord.app_commands.Choice[str] = None) -> str:
    if choice and choice.value != "Все": return choice.value
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        user_id_str = str(user_id)
        for row in rows[2:]:
            if len(row) >= 8 and row[1].strip() == user_id_str:
                return row[7].strip()
    except Exception: pass
    return None

def resolve_judge_info(guild: discord.Guild, judge_member: discord.Member = None, judge_text: str = None) -> tuple[str, discord.Member]:
    target_member = judge_member
    display_name = ""
    try:
        ws_members = sheet.worksheet("Состав")
        rows = ws_members.get_all_values()
    except: rows = []

    if target_member:
        user_id_str = str(target_member.id)
        for row in rows[2:]:
            if len(row) >= 2 and row[1].strip() == user_id_str:
                display_name = row[0].strip()
                break
        if not display_name: display_name = target_member.display_name
        return display_name, target_member

    if judge_text:
        judge_text_clean = judge_text.strip()
        if judge_text_clean.startswith("<@") and judge_text_clean.endswith(">"):
            clean_id = judge_text_clean.replace("<@", "").replace("!", "").replace(">", "").strip()
            if clean_id.isdigit():
                target_member = guild.get_member(int(clean_id))
                if target_member: return resolve_judge_info(guild, judge_member=target_member)

        for row in rows[2:]:
            if len(row) >= 2:
                db_fio = str(row[0]).strip()
                db_id = str(row[1]).strip()
                if judge_text_clean.lower() in db_fio.lower() or db_fio.lower() in judge_text_clean.lower():
                    display_name = db_fio
                    if db_id.isdigit(): target_member = guild.get_member(int(db_id))
                    break
        
        if not display_name: display_name = judge_text_clean
        if not target_member: target_member = discord.utils.get(guild.members, name=judge_text_clean)
        return display_name, target_member
    return "Неизвестный судья", None

def is_judge_of_case(guild: discord.Guild, user: discord.Member, case_number: str, server_name: str) -> bool:
    try:
        ws_cases = sheet.worksheet(f"Расп_{server_name}")
        rows = ws_cases.get_all_values()
        user_fio, _ = resolve_judge_info(guild, judge_member=user)
        for row in rows[1:]:
            if len(row) >= 2 and case_number.lower() in row[0].lower():
                if user_fio.lower() in row[1].lower() or str(user.id) in row[1]:
                    return True
        return False
    except: return False

def auto_sort_hearings(server_name: str):
    """Сортировка заседаний по хронологии дат и времени"""
    try:
        ws = sheet.worksheet(f"Зас_{server_name}")
        rows = ws.get_all_values()
        if len(rows) <= 2: return
        
        data = rows[1:]
        
        def parse_date(row):
            try:
                date_str = row[1].replace(" в ", " ").replace(" к ", " ").strip()
                return datetime.strptime(date_str, "%d.%m.%Y %H:%M")
            except:
                return datetime(2099, 1, 1)
                
        sorted_data = sorted(data, key=parse_date)
        ws.update(values=sorted_data, range_name=f"A2:D{len(rows)}")
    except Exception as e: 
        print(f"Ошибка автоматической сортировки: {e}")

def is_time_slot_taken(server_name: str, requested_time: str) -> tuple[bool, str]:
    """Проверяет, занято ли указанное время на конкретном сервере."""
    try:
        ws = sheet.worksheet(f"Зас_{server_name}")
        rows = ws.get_all_values()
        req_clean = requested_time.replace(" в ", " ").replace(" к ", " ").strip()
        for row in rows[1:]:
            if len(row) >= 2:
                exist_clean = row[1].replace(" в ", " ").replace(" к ", " ").strip()
                if req_clean == exist_clean:
                    return True, row[0]
        return False, ""
    except Exception:
        return False, ""

def auto_clean_past_hearings():
    """Архивация прошедших заседаний"""
    today = datetime.now().date()
    try:
        ws_archive = sheet.worksheet("Архив_Заседаний")
    except Exception:
        ws_archive = None

    for srv in SERVERS:
        try:
            ws = sheet.worksheet(f"Зас_{srv}")
            rows = ws.get_all_values()
            if len(rows) <= 1: continue
            
            rows_to_delete = []
            for idx, row in enumerate(rows[1:], start=2):
                if len(row) >= 2 and row[1]:
                    date_part = row[1].strip().split(" ")[0]
                    try:
                        h_date = datetime.strptime(date_part, "%d.%m.%Y").date()
                        if h_date < today: 
                            rows_to_delete.append(idx)
                            if ws_archive:
                                archive_row = row.copy()
                                archive_row.append(srv)
                                ws_archive.append_row(archive_row)
                    except: pass
            
            for r_idx in reversed(rows_to_delete):
                ws.delete_rows(r_idx)
        except Exception as e: 
            print(f"Ошибка архивации заседаний: {e}")

# ==================== КОМАНДЫ-ПОМОЩНИКИ ====================

@bot.command(name="sync")
async def force_sync(ctx):
    if ctx.author.guild_permissions.administrator:
        try:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ Успешно! Обновлено {len(synced)} команд.")
        except Exception as e: await ctx.send(f"❌ Ошибка: {e}")

@bot.command(name="clearsync")
async def clear_sync(ctx):
    if ctx.author.guild_permissions.administrator:
        try:
            bot.tree.clear_commands(guild=ctx.guild)
            await bot.tree.sync(guild=ctx.guild)
            await ctx.send("🧹 Локальные дубликаты удалены!")
        except Exception as e: await ctx.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="команды", description="Справочник и инструкция по использованию системы")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏛️ Путеводитель по судебной системе", 
        description="Ниже представлен полный список модулей и логика их работы:",
        color=discord.Color.dark_gold()
    )
    embed.add_field(
        name="🛡️ 1. Кадры и Дисциплина (Доступ: ВККС / Президиум)", 
        value="• `/добавить_судью` — внести нового сотрудника.\n"
              "• `/изменить_судью` — обновить данные.\n"
              "• `/удалить_судью` — исключить из состава.\n"
              "• `/выдать_пред` / `/снять_пред` — взыскания.\n"
              "• `/состав` — реестр судейского корпуса.", 
        inline=False
    )
    embed.add_field(
        name="⚖️ 2. Движение и учет дел", 
        value="• `/назначить_иск` — распределить дело.\n"
              "• `/принять_иск` — принять дело в производство.\n"
              "• `/мои_дела` — активные дела судьи.\n"
              "• `/переназначить_дело` — передать производство.\n"
              "• `/без_движения` — приостановить дело.\n"
              "• `/вердикт` — вынести решение (архивация).\n"
              "• `/очистить_архив` — очистка БД по датам.", 
        inline=False
    )
    embed.add_field(
        name="📅 3. Заседания и контроль сроков", 
        value="• `/назначить_заседание` — назначить слушание.\n"
              "• `/отменить_заседание` — снять с расписания.\n"
              "• `/заседания` — график ближайших судов.\n"
              "• `/проверить_дату` — доступность времени.", 
        inline=False
    )
    embed.add_field(
        name="📊 4. Мониторинг и статистика", 
        value="• `/статистика_общая` — сводный отчет.\n"
              "• `/статистика_личная` — карточка судьи.\n"
              "• `/статистика_пвс` — расширенный анализ ПВС.", 
        inline=False
    )
    embed.set_footer(text="Developed by Naxyro | RMRP")
    await interaction.response.send_message(embed=embed)

# ==================== БЛОК: КАДРЫ И ДИСЦИПЛИНА ====================

@bot.tree.command(name="добавить_судью", description="Внести нового судью в реестр состава")
@discord.app_commands.rename(fio="фио", user="пользователь", server="сервер", position="должность", qual_class="квалиф_класс", passport="номер_паспорта", app_date="дата_назначения")
@discord.app_commands.choices(server=SERVER_CHOICES)
async def add_judge(interaction: discord.Interaction, fio: str, user: discord.Member, server: discord.app_commands.Choice[str], position: str, qual_class: str = "Ожидает ЭКЗ", passport: str = "Нет данных", app_date: str = None):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        if not app_date: app_date = datetime.now().strftime("%d.%m.%Y")
        row_data = [fio.strip(), str(user.id), app_date, passport, "0/3 0/3", position.strip(), qual_class, server.value]
        ws.append_row(row_data)
        await interaction.followup.send(embed=discord.Embed(title="👤 Судья добавлен", description=f"**{fio}** [{server.value}] внесен в реестр.", color=discord.Color.green()))
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: `{e}`")

@bot.tree.command(name="изменить_судью", description="Редактировать данные действующего судьи")
@discord.app_commands.rename(user="пользователь", new_position="нов_должность", new_class="нов_квалиф_класс", new_server="нов_сервер", new_date="нов_дата", new_passport="нов_паспорт")
@discord.app_commands.choices(new_server=SERVER_CHOICES)
async def edit_judge(interaction: discord.Interaction, user: discord.Member, new_position: str = None, new_class: str = None, new_server: discord.app_commands.Choice[str] = None, new_date: str = None, new_passport: str = None):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        target_idx = None
        for idx, row in enumerate(rows[2:], start=3):
            if len(row) >= 2 and row[1].strip() == str(user.id):
                target_idx = idx
                break
        if not target_idx: return await interaction.followup.send(f"⚠️ Пользователь не найден.", ephemeral=True)

        if new_date: ws.update_cell(target_idx, 3, new_date)
        if new_passport: ws.update_cell(target_idx, 4, new_passport)
        if new_position: ws.update_cell(target_idx, 6, new_position)
        if new_class: ws.update_cell(target_idx, 7, new_class)
        if new_server: ws.update_cell(target_idx, 8, new_server.value)
        await interaction.followup.send(f"✅ Данные {user.mention} обновлены!")
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: `{e}`")

@bot.tree.command(name="удалить_судью", description="Исключить судью из реестра")
@discord.app_commands.rename(judge_fio_or_id="фио_или_id")
async def remove_judge(interaction: discord.Interaction, judge_fio_or_id: str):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        target_idx = None
        for idx, row in enumerate(rows[2:], start=3):
            if len(row) >= 2 and (judge_fio_or_id.lower() in row[0].lower() or judge_fio_or_id == row[1]):
                target_idx = idx
                break
        if target_idx:
            ws.delete_rows(target_idx)
            await interaction.followup.send(f"🚫 Судья исключен.")
        else: await interaction.followup.send(f"⚠️ Судья не найден.", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: `{e}`")

@bot.tree.command(name="выдать_пред", description="Выдать взыскание судье")
@discord.app_commands.rename(judge="судья", pred_type="тип_взыскания", reason="причина")
@discord.app_commands.choices(pred_type=[
    discord.app_commands.Choice(name="Предупреждение", value="warning"),
    discord.app_commands.Choice(name="Выговор", value="reprimand")
])
async def give_warning(interaction: discord.Interaction, judge: discord.Member, pred_type: discord.app_commands.Choice[str], reason: str):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        target_idx = None
        current_preds = "0/3 0/3"
        for idx, row in enumerate(rows[2:], start=3):
            if len(row) >= 5 and row[1].strip() == str(judge.id):
                target_idx = idx
                current_preds = row[4].strip()
                break
        if not target_idx: return await interaction.followup.send(f"⚠️ Судья не найден.", ephemeral=True)

        parts = current_preds.split(" ")
        g_num = int(parts[0].split("/")[0]) if len(parts) > 0 else 0
        s_num = int(parts[1].split("/")[0]) if len(parts) > 1 else 0

        if pred_type.value == "warning": g_num = min(g_num + 1, 3)
        else: s_num = min(s_num + 1, 3)

        new_preds = f"{g_num}/3 {s_num}/3"
        ws.update_cell(target_idx, 5, new_preds)

        embed = discord.Embed(title="⚠️ Взыскание", description=f"Судье {judge.mention} выдано взыскание.", color=discord.Color.red())
        embed.add_field(name="Счетчик", value=f"`{new_preds}`", inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="снять_пред", description="Снять взыскание с судьи")
@discord.app_commands.rename(judge="судья", pred_type="тип_взыскания")
@discord.app_commands.choices(pred_type=[
    discord.app_commands.Choice(name="Предупреждение", value="warning"),
    discord.app_commands.Choice(name="Выговор", value="reprimand")
])
async def remove_warning(interaction: discord.Interaction, judge: discord.Member, pred_type: discord.app_commands.Choice[str]):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        target_idx = None
        current_preds = "0/3 0/3"
        for idx, row in enumerate(rows[2:], start=3):
            if len(row) >= 5 and row[1].strip() == str(judge.id):
                target_idx = idx
                current_preds = row[4].strip()
                break
        if not target_idx: return await interaction.followup.send(f"⚠️ Судья не найден.", ephemeral=True)

        parts = current_preds.split(" ")
        g_num = int(parts[0].split("/")[0]) if len(parts) > 0 else 0
        s_num = int(parts[1].split("/")[0]) if len(parts) > 1 else 0

        if pred_type.value == "warning": g_num = max(g_num - 1, 0)
        else: s_num = max(s_num - 1, 0)

        new_preds = f"{g_num}/3 {s_num}/3"
        ws.update_cell(target_idx, 5, new_preds)
        await interaction.followup.send(f"✅ Взыскание снято. Новый баланс: `{new_preds}`")
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="состав", description="Вывести реестр судейского корпуса")
async def show_composition(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        ws = sheet.worksheet("Состав")
        rows = ws.get_all_values()
        if len(rows) <= 2: return await interaction.followup.send("📜 Реестр пуст.")
        
        embeds, current_embed, field_count = [], discord.Embed(title="🏛️ Реестр", color=discord.Color.gold()), 0
        
        for row in rows[2:]:
            if len(row) >= 8:
                if field_count == 25:
                    embeds.append(current_embed)
                    current_embed = discord.Embed(color=discord.Color.gold())
                    field_count = 0
                badge = "👑" if "верховн" in row[5].lower() else "⚖️"
                current_embed.add_field(
                    name=f"{badge} {row[0]} [{row[7]}]", 
                    value=f"Должность: {row[5]}\nПреды: `{row[4]}`\nID: `<@{row[1]}>`", 
                    inline=True
                )
                field_count += 1
                
        if field_count > 0: embeds.append(current_embed)
        await interaction.followup.send(embeds=embeds)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

# ==================== БЛОК: РЕГИСТРАЦИЯ ДЕЛ И ЗАСЕДАНИЙ ====================

@bot.tree.command(name="назначить_иск", description="Распределить новое дело на судью")
@discord.app_commands.rename(case_number="номер_дела", judge="судья", category="категория", target_server="сервер")
@discord.app_commands.choices(category=CATEGORY_CHOICES, target_server=SERVER_CHOICES)
async def assign_case(interaction: discord.Interaction, case_number: str, judge: discord.Member, category: discord.app_commands.Choice[str], target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level not in ["MANAGEMENT", "HIGH_JUDGE"]: 
        return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)

    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if not server: return await interaction.followup.send("❌ Укажите сервер вручную.", ephemeral=True)

        ws_cases = sheet.worksheet(f"Расп_{server}")
        judge_fio, target_member = resolve_judge_info(interaction.guild, judge_member=judge)
        ws_cases.append_row([case_number, judge_fio, category.value, datetime.now().strftime("%d.%m.%Y %H:%M"), "Ожидает принятия"])

        embed = discord.Embed(title=f"⚖️ Дело распределено [{server}]", color=discord.Color.blue())
        embed.add_field(name="Дело", value=f"`{case_number}`", inline=True)
        embed.add_field(name="Судья", value=f"**{judge_fio}**", inline=False)
        
        ping_msg = f"Уведомление: {target_member.mention}, на вас распределено дело!" if target_member else ""
        await interaction.followup.send(content=ping_msg, embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="принять_иск", description="Принять иск к производству и назначить заседание")
@discord.app_commands.rename(case_number="номер_дела", date_time="дата_и_время", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def accept_case(interaction: discord.Interaction, case_number: str, date_time: str, target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level == "NONE": return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if not server: return await interaction.followup.send("❌ Укажите сервер.", ephemeral=True)

        ws_cases = sheet.worksheet(f"Расп_{server}")
        rows_cases = ws_cases.get_all_values()
        
        assigned_judge, case_row_idx = None, None
        for idx, row in enumerate(rows_cases[1:], start=2):
            if len(row) >= 1 and case_number.lower() in row[0].lower():
                assigned_judge = row[1].strip() if len(row) > 1 else ""
                case_row_idx = idx
                break
                
        if not case_row_idx: return await interaction.followup.send(f"⚠️ Дело не найдено.", ephemeral=True)

        if role_level == "LIMITED":
            user_fio, _ = resolve_judge_info(interaction.guild, judge_member=interaction.user)
            if user_fio.lower() not in assigned_judge.lower() and str(interaction.user.id) not in assigned_judge:
                return await interaction.followup.send(f"❌ Это не ваше дело!", ephemeral=True)

        is_taken, taken_by_case = is_time_slot_taken(server, date_time)
        if is_taken:
            return await interaction.followup.send(f"❌ Зал занят делом **{taken_by_case}**.", ephemeral=True)

        ws_cases.update_cell(case_row_idx, 5, "Назначено заседание")
        ws_cases.update_cell(case_row_idx, 4, datetime.now().strftime("%d.%m.%Y %H:%M"))

        judge_fio, target_member = resolve_judge_info(interaction.guild, judge_text=assigned_judge)
        ws_hearings = sheet.worksheet(f"Зас_{server}")
        ws_hearings.append_row([case_number, date_time, assigned_judge, "Назначено"])
        auto_sort_hearings(server)

        embed = discord.Embed(title=f"✅ Иск принят [{server}]", color=discord.Color.green())
        embed.add_field(name="Дело", value=f"`{case_number}`", inline=True)
        embed.add_field(name="Время", value=f"`{date_time}`", inline=True)
        
        ping_msg = f"{target_member.mention}! Вы назначили заседание." if target_member else ""
        await interaction.followup.send(content="✅ Иск принят.", ephemeral=True)
        
        channel_id = SERVER_CHANNELS.get(server)
        if channel_id:
            announce_channel = bot.get_channel(channel_id)
            if announce_channel: await announce_channel.send(content=ping_msg, embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="назначить_заседание", description="Назначить повторное заседание")
@discord.app_commands.rename(case_number="номер_дела", date_time="дата_и_время", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def schedule_hearing(interaction: discord.Interaction, case_number: str, date_time: str, target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level == "NONE": return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)

    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if not server: return await interaction.followup.send("❌ Укажите сервер.", ephemeral=True)

        ws_cases = sheet.worksheet(f"Расп_{server}")
        rows_cases = ws_cases.get_all_values()
        
        assigned_judge, case_row_idx = None, None
        for idx, row in enumerate(rows_cases[1:], start=2):
            if len(row) >= 2 and case_number.lower() in row[0].lower():
                assigned_judge = row[1].strip()
                case_row_idx = idx
                break
                
        if not assigned_judge: return await interaction.followup.send(f"❌ Дело не найдено.", ephemeral=True)

        if role_level == "LIMITED":
            user_fio, _ = resolve_judge_info(interaction.guild, judge_member=interaction.user)
            if user_fio.lower() not in assigned_judge.lower() and str(interaction.user.id) not in assigned_judge:
                return await interaction.followup.send(f"❌ Не ваше дело!", ephemeral=True)

        is_taken, taken_by_case = is_time_slot_taken(server, date_time)
        if is_taken:
            return await interaction.followup.send(f"❌ Зал занят делом **{taken_by_case}**.", ephemeral=True)

        if case_row_idx: ws_cases.update_cell(case_row_idx, 5, "Назначено заседание")

        judge_fio, target_member = resolve_judge_info(interaction.guild, judge_text=assigned_judge)
        ws_hearings = sheet.worksheet(f"Зас_{server}")
        ws_hearings.append_row([case_number, date_time, assigned_judge, "Назначено"])
        auto_sort_hearings(server)

        embed = discord.Embed(title=f"📅 Заседание назначено [{server}]", color=discord.Color.gold())
        embed.add_field(name="Дело", value=f"`{case_number}`", inline=True)
        embed.add_field(name="Время", value=f"`{date_time}`", inline=True)
        
        ping_msg = f"{target_member.mention}! Повторное заседание назначено." if target_member else ""
        await interaction.followup.send(content="✅ Заседание внесено.", ephemeral=True)
        
        channel_id = SERVER_CHANNELS.get(server)
        if channel_id:
            announce_channel = bot.get_channel(channel_id)
            if announce_channel: await announce_channel.send(content=ping_msg, embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="мои_дела", description="Показать список активных дел")
async def my_cases(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        judge_fio, _ = resolve_judge_info(interaction.guild, judge_member=interaction.user)
        active_cases = []

        for srv in SERVERS:
            try:
                ws = sheet.worksheet(f"Расп_{srv}")
                records = ws.get_all_records()
                for r in records:
                    status = str(r.get("Статус дела", r.get("Статус", ""))).lower()
                    assigned = str(r.get("Назначенный судья", ""))
                    if (judge_fio.lower() in assigned.lower() or str(interaction.user.id) in assigned) and "рассмотрено" not in status:
                        r['Сервер'] = srv
                        active_cases.append(r)
            except: pass

        if not active_cases: return await interaction.followup.send("📂 Нет активных дел.", ephemeral=True)

        embed = discord.Embed(title=f"📂 Активные дела ({len(active_cases)})", color=discord.Color.blue())
        for c in active_cases:
            embed.add_field(name=f"⚖️ {c.get('Номер дела')} [{c.get('Сервер')}]", value=f"Статус: `{c.get('Статус дела', 'В производстве')}`\nДата: {c.get('Дата распределения')}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

@bot.tree.command(name="переназначить_дело", description="Передать дело другому судье")
@discord.app_commands.rename(case_number="номер_дела", new_judge="новый_судья", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def reassign_case(interaction: discord.Interaction, case_number: str, new_judge: discord.Member, target_server: discord.app_commands.Choice[str] = None):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Только руководство.", ephemeral=True)
    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        ws = sheet.worksheet(f"Расп_{server}")
        rows = ws.get_all_values()
        judge_fio, target_member = resolve_judge_info(interaction.guild, judge_member=new_judge)
        updated = False
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) >= 1 and case_number.lower() in row[0].lower():
                ws.update_cell(idx, 2, judge_fio)
                updated = True
                break
        if updated: 
            ping_msg = f"{target_member.mention}, передано дело!" if target_member else ""
            await interaction.followup.send(content=ping_msg, embed=discord.Embed(title="🔄 Передача", description=f"Дело **{case_number}** передано: **{judge_fio}**.", color=discord.Color.blue()))
        else: await interaction.followup.send(f"⚠️ Дело не найдено.", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="без_движения", description="Оставить иск без движения")
@discord.app_commands.rename(case_number="номер_дела", reason="причина", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def stay_case(interaction: discord.Interaction, case_number: str, reason: str, target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level == "NONE": return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if role_level == "LIMITED" and not is_judge_of_case(interaction.guild, interaction.user, case_number, server):
            return await interaction.followup.send(f"❌ Не ваше дело!", ephemeral=True)

        ws = sheet.worksheet(f"Расп_{server}")
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) >= 1 and case_number.lower() in row[0].lower():
                ws.update_cell(idx, 5, f"Без движения: {reason}")
                return await interaction.followup.send(embed=discord.Embed(title=f"⚠️ Без движения [{server}]", description=f"**{case_number}**\nПричина: {reason}", color=discord.Color.gold()))
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="вердикт", description="Вынести решение и отправить в архив")
@discord.app_commands.rename(case_number="номер_дела", verdict_type="итог", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def case_verdict(interaction: discord.Interaction, case_number: str, verdict_type: str, target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level == "NONE": return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if role_level == "LIMITED" and not is_judge_of_case(interaction.guild, interaction.user, case_number, server):
            return await interaction.followup.send(f"❌ Не ваше дело!", ephemeral=True)

        ws_cases = sheet.worksheet(f"Расп_{server}")
        rows_cases = ws_cases.get_all_values()
        target_row, target_idx = None, None
        
        for idx, row in enumerate(rows_cases[1:], start=2):
            if len(row) >= 1 and case_number.lower() in row[0].lower():
                target_row = row
                target_idx = idx
                break
                
        if not target_row: return await interaction.followup.send(f"⚠️ Дело не найдено.", ephemeral=True)

        try:
            ws_archive = sheet.worksheet("Архив")
            ws_archive.append_row([target_row[0], target_row[1], target_row[2] if len(target_row) > 2 else "Не указано", target_row[3] if len(target_row) > 3 else datetime.now().strftime("%d.%m.%Y"), verdict_type, server])
        except Exception as e: print(f"Ошибка архивации: {e}")

        ws_cases.delete_rows(target_idx)
        try:
            ws_hearings = sheet.worksheet(f"Зас_{server}")
            rows_h = ws_hearings.get_all_values()
            for h_idx, h_row in enumerate(rows_h[1:], start=2):
                if len(h_row) >= 1 and case_number.lower() in h_row[0].lower():
                    ws_hearings.delete_rows(h_idx)
                    break
        except: pass

        await interaction.followup.send(embed=discord.Embed(title=f"⚖️ АКТ [{server}]", description=f"Дело **{case_number}** в Архиве.\n**Итог:** {verdict_type}", color=discord.Color.green()))
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="отменить_заседание", description="Снять заседание с рассмотрения")
@discord.app_commands.rename(case_number="номер_дела", reason="причина", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def cancel_hearing(interaction: discord.Interaction, case_number: str, reason: str, target_server: discord.app_commands.Choice[str] = None):
    role_level = check_user_role_level(interaction)
    if role_level == "NONE": return await interaction.response.send_message("❌ Нет прав.", ephemeral=True)
    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        if role_level == "LIMITED" and not is_judge_of_case(interaction.guild, interaction.user, case_number, server):
            return await interaction.followup.send(f"❌ Не ваше дело!", ephemeral=True)

        ws = sheet.worksheet(f"Зас_{server}")
        rows = ws.get_all_values()
        target_idx = None
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) >= 1 and case_number.lower() in row[0].lower():
                target_idx = idx
                break
        if target_idx:
            ws.delete_rows(target_idx)
            await interaction.followup.send(f"⚠️ Заседание снято. Причина: {reason}")
        else: await interaction.followup.send(f"⚠️ Заседание не найдено.", ephemeral=True)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="проверить_дату", description="Проверить график на день")
@discord.app_commands.rename(target_date="дата", target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def check_date_schedule(interaction: discord.Interaction, target_date: str, target_server: discord.app_commands.Choice[str] = None):
    await interaction.response.defer()
    try:
        server = get_server_name(interaction.user.id, target_server)
        ws = sheet.worksheet(f"Зас_{server}")
        matches = [row for row in ws.get_all_values()[1:] if len(row) >= 3 and target_date in row[1]]
        if matches:
            msg = f"На **{target_date}** [{server}] назначено **{len(matches)}** заседаний:\n"
            for m in matches: msg += f"⚖️ {m[0]} ({m[1]}) — Судья: {m[2]}\n"
            await interaction.followup.send(msg)
        else: await interaction.followup.send(f"🟢 Дата `{target_date}` свободна!")
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="заседания", description="График ближайших заседаний")
@discord.app_commands.rename(target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def list_hearings(interaction: discord.Interaction, target_server: discord.app_commands.Choice[str] = None):
    await interaction.response.defer()
    try:
        auto_clean_past_hearings()
        server = get_server_name(interaction.user.id, target_server)
        rows = sheet.worksheet(f"Зас_{server}").get_all_values()
        if len(rows) <= 1: return await interaction.followup.send(f"📅 График свободен.")
        
        embed = discord.Embed(title=f"📅 График [{server}]", color=discord.Color.gold())
        for row in rows[1:]:
            if len(row) >= 3: embed.add_field(name=f"⚖️ Дело {row[0]}", value=f"Время: {row[1]}\nСудья: {row[2]}", inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="очистить_архив", description="Очистка архива за период")
@discord.app_commands.rename(start_date="начало", end_date="конец", target_server="сервер")
@discord.app_commands.choices(target_server=[discord.app_commands.Choice(name="Все серверы", value="Все")] + SERVER_CHOICES)
async def clear_archive_registry(interaction: discord.Interaction, start_date: str, end_date: str, target_server: discord.app_commands.Choice[str]):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Только Руководство.", ephemeral=True)
    await interaction.response.defer()
    try:
        start_dt = datetime.strptime(start_date.strip(), "%d.%m.%Y").date()
        end_dt = datetime.strptime(end_date.strip(), "%d.%m.%Y").date()
        ws = sheet.worksheet("Архив")
        rows = ws.get_all_values()
        
        rows_to_delete = []
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) >= 6:
                try:
                    row_date = datetime.strptime(row[3].strip().split(" ")[0], "%d.%m.%Y").date()
                    if start_dt <= row_date <= end_dt and (target_server.value == "Все" or row[5].strip() == target_server.value):
                        rows_to_delete.append(idx)
                except: pass
        
        for r_idx in reversed(rows_to_delete): ws.delete_rows(r_idx)
        await interaction.followup.send(f"🧹 Удалено **{len(rows_to_delete)}** дел.")
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

# ==================== СТАТИСТИКА ====================

@bot.tree.command(name="статистика_общая", description="Общий отчет по серверам")
@discord.app_commands.rename(target_server="сервер")
@discord.app_commands.choices(target_server=SERVER_CHOICES)
async def stats_general(interaction: discord.Interaction, target_server: discord.app_commands.Choice[str] = None):
    await interaction.response.defer()
    try:
        servers_to_check = [target_server.value] if target_server else SERVERS
        types_count, total_cases = {}, 0
        for srv in servers_to_check:
            try:
                for r in sheet.worksheet(f"Расп_{srv}").get_all_records():
                    total_cases += 1
                    pt = str(r.get("Тип процесса", "Прочее")).strip()
                    if pt: types_count[pt] = types_count.get(pt, 0) + 1
            except: pass
        
        embed = discord.Embed(title=f"📊 Отчет [{target_server.value if target_server else 'ВСЕ'}]", description=f"Активных дел: **{total_cases}**", color=discord.Color.blue())
        types_text = "".join([f"• {pt}: **{c}**\n" for pt, c in types_count.items()])
        embed.add_field(name="⚖️ По категориям", value=types_text if types_text else "Нет данных", inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="статистика_личная", description="Карточка судьи")
@discord.app_commands.rename(judge="судья")
async def stats_personal(interaction: discord.Interaction, judge: discord.Member = None):
    await interaction.response.defer()
    try:
        target = judge if judge else interaction.user
        judge_fio, _ = resolve_judge_info(interaction.guild, judge_member=target)
        cases = []
        for srv in SERVERS:
            try:
                for r in sheet.worksheet(f"Расп_{srv}").get_all_records():
                    if judge_fio.lower() in str(r.get("Назначенный судья", "")).lower() or str(target.id) in str(r.get("Назначенный судья", "")):
                        r['Сервер'] = srv
                        cases.append(r)
            except: pass
        embed = discord.Embed(title=f"👤 Статистика: {judge_fio}", description=f"В производстве: **{len(cases)}**", color=discord.Color.purple())
        for c in cases[-5:]: embed.add_field(name=f"Дело {c.get('Номер дела')} [{c.get('Сервер')}]", value=f"Статус: {c.get('Статус дела', c.get('Статус'))}", inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

@bot.tree.command(name="статистика_пвс", description="Расширенная статистика за период (ПВС/ВККС)")
@discord.app_commands.rename(judge="судья", start_date="начало", end_date="конец")
async def stats_advanced(interaction: discord.Interaction, judge: discord.Member, start_date: str, end_date: str):
    if check_user_role_level(interaction) != "MANAGEMENT": return await interaction.response.send_message("❌ Доступ только для Руководства.", ephemeral=True)
    await interaction.response.defer()
    try:
        start_dt = datetime.strptime(start_date.strip(), "%d.%m.%Y").date()
        end_dt = datetime.strptime(end_date.strip(), "%d.%m.%Y").date()
        judge_fio, _ = resolve_judge_info(interaction.guild, judge_member=judge)
        active_cases, closed_cases = 0, 0

        for srv in SERVERS:
            try:
                for row in sheet.worksheet(f"Расп_{srv}").get_all_values()[1:]:
                    if len(row) >= 4 and (judge_fio.lower() in row[1].lower() or str(judge.id) in row[1]):
                        try:
                            if start_dt <= datetime.strptime(row[3].replace(" в ", " ").replace(" к ", " ").strip().split(" ")[0], "%d.%m.%Y").date() <= end_dt: active_cases += 1
                        except: pass
            except: pass

        try:
            for row in sheet.worksheet("Архив").get_all_values()[1:]:
                if len(row) >= 4 and (judge_fio.lower() in row[1].lower() or str(judge.id) in row[1]):
                    try:
                        if start_dt <= datetime.strptime(row[3].replace(" в ", " ").replace(" к ", " ").strip().split(" ")[0], "%d.%m.%Y").date() <= end_dt: closed_cases += 1
                    except: pass
        except: pass

        embed = discord.Embed(title=f"📈 Отчет по судье (ПВС/ВККС)", description=f"Судья: **{judge_fio}**\nПериод: `{start_date}` — `{end_date}`", color=discord.Color.purple())
        embed.add_field(name="Всего дел в периоде", value=f"**{active_cases + closed_cases}**", inline=False)
        embed.add_field(name="В производстве", value=f"**{active_cases}**", inline=True)
        embed.add_field(name="Завершено", value=f"**{closed_cases}**", inline=True)
        await interaction.followup.send(embed=embed)
    except Exception as e: await interaction.followup.send(f"❌ Ошибка: {e}")

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

@tasks.loop(minutes=30)
async def check_deadlines_and_hearings():
    await bot.wait_until_ready()
    try:
        auto_clean_past_hearings()
        now = datetime.now()
        
        for srv in SERVERS:
            channel_id = SERVER_CHANNELS.get(srv)
            channel = bot.get_channel(channel_id) if channel_id else None
            if not channel: continue

            try:
                ws_h = sheet.worksheet(f"Зас_{srv}")
                for row in ws_h.get_all_values()[1:]:
                    if len(row) >= 3 and row[1]:
                        try:
                            clean_time = row[1].replace(" в ", " ").replace(" к ", " ").strip()
                            h_date = datetime.strptime(clean_time, "%d.%m.%Y %H:%M")
                            diff = h_date - now
                            if timedelta(minutes=0) < diff <= timedelta(minutes=30):
                                embed_h = discord.Embed(title=f"⏰ СКОРО ЗАСЕДАНИЕ [{srv}]", color=discord.Color.red())
                                embed_h.add_field(name=f"⚖️ Дело: {row[0]}", value=f"Время: {row[1]}\nСудья: {row[2]}", inline=False)
                                _, tm = resolve_judge_info(channel.guild, judge_text=row[2])
                                ping_str = f"Внимание, {tm.mention}! Заседание начнется менее чем через 30 минут!" if tm else ""
                                await channel.send(content=ping_str, embed=embed_h)
                        except: pass
            except: pass

            try:
                ws_c = sheet.worksheet(f"Расп_{srv}")
                for row in ws_c.get_all_values()[1:]:
                    if len(row) >= 5:
                        case_num, judge_raw, status, date_str = row[0], row[1], row[4].lower(), row[3].strip()
                        if "рассмотрено" in status or "назначено" in status or "движения" in status: continue
                        
                        try:
                            clean_date = date_str.replace(" в ", " ").replace(" к ", " ").strip()
                            case_date = datetime.strptime(clean_date, "%d.%m.%Y %H:%M")
                            diff = now - case_date
                            _, judge_mem = resolve_judge_info(channel.guild, judge_text=judge_raw)
                            if not judge_mem: continue

                            if "ожида" in status:
                                if diff > timedelta(hours=12) and diff <= timedelta(hours=12, minutes=30):
                                    await channel.send(content=f"⏳ {judge_mem.mention}, напоминание! Менее 12 часов на принятие дела **{case_num}** [{srv}].")
                                elif diff > timedelta(hours=24) and diff <= timedelta(hours=24, minutes=30):
                                    await channel.send(content=f"⚠️ {judge_mem.mention}, просрочка! Дело **{case_num}** [{srv}] не принято более 24 часов.")
                            else:
                                if diff > timedelta(hours=12) and diff <= timedelta(hours=12, minutes=30):
                                    await channel.send(content=f"⏳ {judge_mem.mention}, напоминание! Менее 12 часов на вынесение вердикта по делу **{case_num}** [{srv}].")
                                elif diff > timedelta(hours=24) and diff <= timedelta(hours=24, minutes=30):
                                    await channel.send(content=f"⏰ {judge_mem.mention}, просрочка! Дело **{case_num}** [{srv}] без вердикта более 24 часов!")
                        except: pass
            except: pass
    except Exception as e: print(f"Ошибка фонового контроля: {e}")

# ==================== ЗАПУСК ====================

@bot.event
async def on_ready():
    print(f"==============================================================================")
    print(f"⚖️ СИСТЕМА СУДЕБНОГО КОНТРОЛЯ | Проект: RMRP")
    print(f"🧑‍💻 Разработано Naxyro")
    print(f"🤖 Бот успешно подключен к серверу! (Имя: {bot.user.name}, ID: {bot.user.id})")
    print(f"==============================================================================")
    auto_clean_past_hearings()
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано команд: {len(synced)}")
    except Exception as e: print(f"Ошибка синхронизации: {e}")
    if not check_deadlines_and_hearings.is_running(): check_deadlines_and_hearings.start()

bot.run(BOT_TOKEN)