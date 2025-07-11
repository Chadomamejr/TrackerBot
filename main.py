import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio
import pytz

# 環境変数をロード
load_dotenv()

JST = pytz.timezone('Asia/Tokyo')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix='!', intents=intents)

DATA_FILE = 'sleep_data.json'
user_messages = {}
auto_delete_tasks = {}
# ステータスクリアボタンの確認状態を保持するための辞書
clear_status_confirmations = {}

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"警告: {DATA_FILE} が破損しています。新しいファイルを作成します。")
                return {}
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_latest_sleep_info(user_id):
    data = load_data()
    user_data = data.get(str(user_id), {})

    is_sleeping = user_data.get('is_sleeping', False)

    last_sleep_start_str = None
    last_sleep_end_str = None
    average_sleep_minutes = 0

    sleep_records = user_data.get('sleep_records', [])

    # 200時間以上の異常な睡眠記録を除外
    valid_sleep_records = [
        record for record in sleep_records
        if record.get('duration_minutes', 0) < 200 * 60
    ]

    if valid_sleep_records:
        total_minutes = sum(record['duration_minutes'] for record in valid_sleep_records)
        average_sleep_minutes = total_minutes / len(valid_sleep_records)

        latest_record = valid_sleep_records[-1]
        last_sleep_start_str = latest_record.get('sleep_start')
        last_sleep_end_str = latest_record.get('sleep_end')

    # 150時間以上の睡眠状態の自動リセット
    if is_sleeping and 'sleep_start' in user_data:
        try:
            sleep_start_dt = datetime.fromisoformat(user_data['sleep_start']).astimezone(JST)
            current_time_jst = datetime.now(JST)
            duration_since_sleep_start = current_time_jst - sleep_start_dt

            if duration_since_sleep_start.total_seconds() > 150 * 3600:
                print(f"User {user_id} has been 'sleeping' for over 150 hours. Auto-waking them up.")
                sleep_record_auto_wake = {
                    'sleep_start': user_data['sleep_start'],
                    'sleep_end': current_time_jst.isoformat(),
                    'duration_minutes': int(duration_since_sleep_start.total_seconds() / 60)
                }
                user_data['sleep_records'].append(sleep_record_auto_wake)
                user_data['is_sleeping'] = False
                if 'sleep_start' in user_data:
                    del user_data['sleep_start']
                save_data(data)
                is_sleeping = False
                last_sleep_start_str = sleep_record_auto_wake['sleep_start']
                last_sleep_end_str = sleep_record_auto_wake['sleep_end']

                valid_records_after_auto = [
                    record for record in user_data['sleep_records']
                    if record.get('duration_minutes', 0) < 200 * 60
                ]
                if valid_records_after_auto:
                    total_minutes = sum(record['duration_minutes'] for record in valid_records_after_auto)
                    average_sleep_minutes = total_minutes / len(valid_records_after_auto)
        except ValueError as e:
            print(f"睡眠開始時刻の解析エラー for user {user_id}: {e}. データをリセットします。")
            if 'sleep_start' in user_data:
                del user_data['sleep_start']
            user_data['is_sleeping'] = False
            save_data(data)
            is_sleeping = False
            last_sleep_start_str = None
            last_sleep_end_str = None


    if is_sleeping and 'sleep_start' in user_data:
        last_sleep_start_str = user_data['sleep_start']

    # 200時間以上の起床中ステータスの自動リセット
    if not is_sleeping and 'sleep_end' in user_data:
        try:
            last_wake_up_dt = datetime.fromisoformat(user_data['sleep_end']).astimezone(JST)
            current_time_jst = datetime.now(JST)
            duration_since_last_wake_up = current_time_jst - last_wake_up_dt

            if duration_since_last_wake_up.total_seconds() > 200 * 3600:
                print(f"User {user_id} has been 'awake' for over 200 hours. Resetting their status.")
                last_sleep_start_str = None
                last_sleep_end_str = None
                if 'sleep_end' in user_data:
                    del user_data['sleep_end']
                save_data(data)
        except ValueError as e:
            print(f"起床終了時刻の解析エラー for user {user_id}: {e}. データをリセットします。")
            if 'sleep_end' in user_data:
                del user_data['sleep_end']
            last_sleep_start_str = None
            last_sleep_end_str = None
            save_data(data)

    return {
        'is_sleeping': is_sleeping,
        'last_sleep_start': last_sleep_start_str,
        'last_sleep_end': last_sleep_end_str,
        'average_sleep_minutes': average_sleep_minutes,
        'raw_user_data': user_data
    }

async def clear_previous_messages(user_id):
    if user_id in user_messages:
        # 進行中の自動削除タスクをキャンセル
        for msg in user_messages[user_id]:
            if msg.id in auto_delete_tasks:
                auto_delete_tasks[msg.id].cancel()
                del auto_delete_tasks[msg.id]
        
        for msg in user_messages[user_id]:
            try:
                await msg.delete()
            except discord.NotFound:
                pass # メッセージが既に削除されている場合は無視
            except discord.HTTPException as e:
                print(f"メッセージ削除中にHTTPエラーが発生しました: {e}")
                pass
        user_messages[user_id] = []

async def schedule_auto_delete(message, delay_minutes=2):
    async def delete_after_delay():
        await asyncio.sleep(delay_minutes * 60)
        try:
            await message.delete()
            # 削除後に user_messages と auto_delete_tasks からも削除
            for user_id_key, messages in user_messages.items():
                if message in messages:
                    messages.remove(message)
                    break
            if message.id in auto_delete_tasks:
                del auto_delete_tasks[message.id]
        except discord.NotFound:
            pass # メッセージが既に削除されている場合は無視
        except discord.HTTPException as e:
            print(f"自動削除中にHTTPエラーが発生しました: {e}")
            pass
        except asyncio.CancelledError:
            print(f"メッセージID {message.id} の自動削除タスクがキャンセルされました。")
            pass

    task = asyncio.create_task(delete_after_delay())
    auto_delete_tasks[message.id] = task
    return task

def add_user_message(user_id, message):
    if user_id not in user_messages:
        user_messages[user_id] = []
    user_messages[user_id].append(message)

async def send_all_members_status(interaction: discord.Interaction, user_id_to_track: str):
    current_time_jst = datetime.now(JST)
    data = load_data()

    embed = discord.Embed(
        title='📊 ステータス',
        description='サーバーのメンバーの睡眠状況',
        color=0x99ffff,
        timestamp=current_time_jst
    )

    members = interaction.guild.members

    display_members = sorted([m for m in members if not m.bot and not m.system and str(m.id) in data], key=lambda m: m.display_name.lower())

    if not display_members:
        embed.description = "まだ睡眠記録があるメンバーがいません。「おやすみ」ボタンから記録を開始してください。"
    else:
        status_messages = []
        for member in display_members:
            member_info = get_user_latest_sleep_info(member.id)

            discord_status = member.status
            status_icon = "🟢" if discord_status == discord.Status.online else \
                          "🟠" if discord_status == discord.Status.idle else \
                          "🔴" if discord_status == discord.Status.dnd else \
                          "⚪"

            status_emoji = "😴" if member_info['is_sleeping'] else "☀️"
            status_text = "睡眠中" if member_info['is_sleeping'] else "起床中"

            time_since_status_change = ""
            if member_info['is_sleeping'] and 'sleep_start' in member_info['raw_user_data']:
                try:
                    sleep_start_dt = datetime.fromisoformat(member_info['raw_user_data']['sleep_start']).astimezone(JST)
                    duration = current_time_jst - sleep_start_dt
                    hours = int(duration.total_seconds() // 3600)
                    minutes = int((duration.total_seconds() % 3600) // 60)
                    time_since_status_change = f" ({hours}時間{minutes}分睡眠中)"
                except ValueError:
                    time_since_status_change = " (時刻データエラー)"
            elif not member_info['is_sleeping'] and 'sleep_end' in member_info['raw_user_data']:
                try:
                    last_wake_up_dt = datetime.fromisoformat(member_info['raw_user_data']['sleep_end']).astimezone(JST)
                    duration = current_time_jst - last_wake_up_dt
                    hours = int(duration.total_seconds() // 3600)
                    minutes = int((duration.total_seconds() % 3600) // 60)
                    if duration.total_seconds() < 200 * 3600: # 200時間以上の起床中は表示しない
                        time_since_status_change = f" ({hours}時間{minutes}分起床中)"
                except ValueError:
                    time_since_status_change = " (時刻データエラー)"

            last_sleep_start_display = "記録なし"
            if member_info['last_sleep_start']:
                try:
                    last_sleep_start_dt = datetime.fromisoformat(member_info['last_sleep_start']).astimezone(JST)
                    last_sleep_start_display = last_sleep_start_dt.strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    last_sleep_start_display = "日付形式エラー"

            last_sleep_end_display = "記録なし"
            if member_info['last_sleep_end']:
                try:
                    last_sleep_end_dt = datetime.fromisoformat(member_info['last_sleep_end']).astimezone(JST)
                    last_sleep_end_display = last_sleep_end_dt.strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    last_sleep_end_display = "日付形式エラー"

            avg_sleep_display = "記録なし"
            if member_info['average_sleep_minutes'] > 0:
                avg_hours = int(member_info['average_sleep_minutes'] // 60)
                avg_minutes = int(member_info['average_sleep_minutes'] % 60)
                avg_sleep_display = f"{avg_hours}時間{avg_minutes}分"

            status_messages.append(
                f"{member.mention} {status_emoji} **{status_text}** {time_since_status_change} {status_icon}\n"
                f"  最後に寝た時間: {last_sleep_start_display}\n"
                f"  最後に起きた時間: {last_sleep_end_display}\n"
                f"  平均睡眠時間: {avg_sleep_display}"
            )

        field_value = "\n\n".join(status_messages)

        # Embedのfield_valueは1024文字までなので分割
        if len(field_value) > 1024:
            chunks = []
            current_chunk = []
            current_chunk_len = 0
            for msg in status_messages:
                if current_chunk_len + len(msg) + 2 > 1024 and current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [msg]
                    current_chunk_len = len(msg) + 2
                else:
                    current_chunk.append(msg)
                    current_chunk_len += len(msg) + 2
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))

            for i, chunk in enumerate(chunks):
                embed.add_field(name=f'メンバーのステータス ({i+1}/{len(chunks)})', value=chunk, inline=False)
        else:
            embed.add_field(name='メンバーのステータス', value=field_value, inline=False)

    status_message_response = await interaction.followup.send(embed=embed)
    add_user_message(user_id_to_track, status_message_response) # <-- followup.sendはメッセージオブジェクトを直接返す


class SleepTrackerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='😴 おやすみ', style=discord.ButtonStyle.primary, custom_id='sleep_button')
    async def sleep_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_time_jst = datetime.now(JST)

        await clear_previous_messages(user_id)
        await interaction.response.defer() # 応答が遅延することをDiscordに伝える

        data = load_data()
        if user_id not in data:
            data[user_id] = {'sleep_records': []}

        if data[user_id].get('is_sleeping', False) and 'sleep_start' in data[user_id]:
            try:
                sleep_start_dt = datetime.fromisoformat(data[user_id]['sleep_start']).astimezone(JST)
                duration_since_sleep_start = current_time_jst - sleep_start_dt

                if duration_since_sleep_start.total_seconds() > 150 * 3600:
                    sleep_record_auto_wake = {
                        'sleep_start': data[user_id]['sleep_start'],
                        'sleep_end': current_time_jst.isoformat(),
                        'duration_minutes': int(duration_since_sleep_start.total_seconds() / 60)
                    }
                    data[user_id]['sleep_records'].append(sleep_record_auto_wake)
                    data[user_id]['is_sleeping'] = False
                    if 'sleep_start' in data[user_id]:
                        del data[user_id]['sleep_start']
                    save_data(data)

                    embed_auto_wake = discord.Embed(
                        title='⚠️ 自動起床処理',
                        description=f'{interaction.user.mention} さんは150時間以上睡眠中と判断されたため、自動的に起床状態になりました。\n再度「おやすみ」を押して睡眠を開始してください。',
                        color=0xffcc00
                    )
                    auto_wake_message = await interaction.followup.send(embed=embed_auto_wake)
                    add_user_message(user_id, auto_wake_message)
                    await schedule_auto_delete(auto_wake_message, 2)
                    return
            except ValueError as e:
                print(f"睡眠開始時刻の解析エラー (おやすみボタン) for user {user_id}: {e}. データをリセットします。")
                if 'sleep_start' in data[user_id]:
                    del data[user_id]['sleep_start']
                data[user_id]['is_sleeping'] = False
                save_data(data)
                embed_error = discord.Embed(
                    title='エラーが発生しました',
                    description='睡眠開始時刻のデータが破損しているため、ステータスをリセットしました。再度お試しください。',
                    color=0xff0000
                )
                error_message = await interaction.followup.send(embed=embed_error, ephemeral=True)
                add_user_message(user_id, error_message)
                return


        if data[user_id].get('is_sleeping', False):
            embed = discord.Embed(
                title='😴 すでに睡眠中です',
                description='先に「🌅 おはよう」で起床を記録してください',
                color=0xff9999
            )
            already_sleeping_message = await interaction.followup.send(embed=embed, ephemeral=True)
            add_user_message(user_id, already_sleeping_message)
            return

        data[user_id]['is_sleeping'] = True
        data[user_id]['sleep_start'] = current_time_jst.isoformat()
        save_data(data)

        # 全員ステータス表示は defer 後に followup.send で送る
        await send_all_members_status(interaction, user_id)

        embed = discord.Embed(
            title='😴 おやすみなさい！',
            description=f'{interaction.user.mention} の睡眠を記録開始しました',
            color=0x9999ff,
            timestamp=current_time_jst
        )
        embed.add_field(
            name='⏰ 自動削除',
            value='このメッセージは2分後に自動的に削除されます',
            inline=False
        )
        message = await interaction.followup.send(embed=embed) # <-- followup.sendはメッセージオブジェクトを直接返す
        add_user_message(user_id, message)
        await schedule_auto_delete(message, 2)

    @discord.ui.button(label='🌅 おはよう', style=discord.ButtonStyle.success, custom_id='wake_button')
    async def wake_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        current_time_jst = datetime.now(JST)

        await clear_previous_messages(user_id)
        await interaction.response.defer()

        data = load_data()
        if user_id not in data or not data[user_id].get('is_sleeping', False):
            embed = discord.Embed(
                title='🌅 睡眠記録がありません',
                description='先に「😴 おやすみ」で睡眠を開始してください',
                color=0xff9999
            )
            no_record_message = await interaction.followup.send(embed=embed, ephemeral=True)
            add_user_message(user_id, no_record_message)
            return

        sleep_start = None
        try:
            sleep_start = datetime.fromisoformat(data[user_id]['sleep_start']).astimezone(JST)
        except ValueError as e:
            print(f"睡眠開始時刻の解析エラー (おはようボタン) for user {user_id}: {e}. データをリセットします。")
            if 'sleep_start' in data[user_id]:
                del data[user_id]['sleep_start']
            data[user_id]['is_sleeping'] = False
            save_data(data)
            embed_error = discord.Embed(
                title='エラーが発生しました',
                description='睡眠開始時刻のデータが破損しているため、ステータスをリセットしました。再度お試しください。',
                color=0xff0000
            )
            error_message = await interaction.followup.send(embed=embed_error, ephemeral=True)
            add_user_message(user_id, error_message)
            return
        
        sleep_duration = current_time_jst - sleep_start

        sleep_record = {
            'sleep_start': data[user_id]['sleep_start'],
            'sleep_end': current_time_jst.isoformat(),
            'duration_minutes': int(sleep_duration.total_seconds() / 60)
        }

        data[user_id]['sleep_records'].append(sleep_record)
        data[user_id]['is_sleeping'] = False
        if 'sleep_start' in data[user_id]:
            del data[user_id]['sleep_start']
        data[user_id]['sleep_end'] = current_time_jst.isoformat()
        save_data(data)

        await send_all_members_status(interaction, user_id)

        hours = int(sleep_duration.total_seconds() // 3600)
        minutes = int((sleep_duration.total_seconds() % 3600) // 60)

        embed = discord.Embed(
            title='🌅 おはようございます！',
            description=f'{interaction.user.mention} さんの睡眠時間: **{hours}時間{minutes}分**',
            color=0xffff99,
            timestamp=current_time_jst
        )
        embed.add_field(name='就寝時刻', value=sleep_start.strftime('%Y-%m-%d %H:%M'), inline=True)
        embed.add_field(name='起床時刻', value=current_time_jst.strftime('%Y-%m-%d %H:%M'), inline=True)
        embed.add_field(
            name='⏰ 自動削除',
            value='このメッセージは2分後に自動的に削除されます',
            inline=False
        )
        message = await interaction.followup.send(embed=embed) # <-- followup.sendはメッセージオブジェクトを直接返す
        add_user_message(user_id, message)
        await schedule_auto_delete(message, 2)

    @discord.ui.button(label='📊 ステータス', style=discord.ButtonStyle.secondary, custom_id='stats_button')
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await clear_previous_messages(str(interaction.user.id))
        await interaction.response.defer()
        await send_all_members_status(interaction, str(interaction.user.id))

    @discord.ui.button(label='💀 自分のステータスをクリア', style=discord.ButtonStyle.danger, custom_id='clear_my_status_button')
    async def clear_my_status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = str(interaction.user.id)
        await clear_previous_messages(user_id)

        if user_id in clear_status_confirmations and clear_status_confirmations[user_id]:
            # 2回目のクリック：データをクリア
            data = load_data()
            if user_id in data:
                del data[user_id] # ユーザーの全データを削除
                save_data(data)

                embed = discord.Embed(
                    title='✅ ステータスがクリアされました',
                    description=f'{interaction.user.mention} さんのすべての睡眠データが削除されました。',
                    color=0x00ff00
                )
                response_message = await interaction.response.send_message(embed=embed)
                response_message_obj = await interaction.original_response() # <-- ここでメッセージオブジェクトを取得
            else:
                embed = discord.Embed(
                    title='ℹ️ 睡眠データがありません',
                    description=f'{interaction.user.mention} さんにはクリアする睡眠データがありません。',
                    color=0x00aaff
                )
                response_message = await interaction.response.send_message(embed=embed)
                response_message_obj = await interaction.original_response() # <-- ここでメッセージオブジェクトを取得

            del clear_status_confirmations[user_id] # 確認状態をリセット
            add_user_message(user_id, response_message_obj) # <-- 修正
            await schedule_auto_delete(response_message_obj, 5) # 5秒後に削除 # <-- 修正
        else:
            # 1回目のクリック：確認を求める
            clear_status_confirmations[user_id] = True
            embed = discord.Embed(
                title='⚠️ ステータスクリアの確認',
                description=f'{interaction.user.mention} さんの**すべての睡眠データを削除**します。\n本当に削除する場合は、**もう一度**「💀 自分のステータスをクリア」ボタンを押してください。',
                color=0xffcc00
            )
            # ephemeral メッセージの場合も original_response を使う
            response_message_interaction = await interaction.response.send_message(embed=embed, ephemeral=True)
            response_message_obj = await interaction.original_response() # <-- ephemeral でもメッセージオブジェクトを取得
            add_user_message(user_id, response_message_obj) # <-- 修正

            # 10秒後に確認状態をリセットするタスク
            async def reset_confirmation():
                await asyncio.sleep(10)
                if user_id in clear_status_confirmations and clear_status_confirmations[user_id]:
                    del clear_status_confirmations[user_id]
                    print(f"User {user_id}'s clear status confirmation timed out.")
            asyncio.create_task(reset_confirmation())


@bot.event
async def on_ready():
    print(f'{bot.user} がログインしました！')
    print(f'ボットID: {bot.user.id}')
    print('新機能: タイムゾーン修正、オンライン/オフライン連携、自動就寝/起床、異常データ自動削除機能が追加されました')

    try:
        # スラッシュコマンドの同期
        synced = await bot.tree.sync()
        print(f'{len(synced)}個のコマンドを同期しました。')
    except Exception as e:
        print(f'コマンド同期中にエラーが発生しました: {e}')

    # Viewを永続化するためにadd_viewを呼び出す
    bot.add_view(SleepTrackerView())

@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    # Bot自身、システムユーザー、またはステータスが変わらない場合は無視
    if after.bot or after.system or before.status == after.status:
        return

    user_id = str(after.id)
    data = load_data()

    # ユーザーデータがない場合は処理しない
    if user_id not in data:
        return

    user_data = data[user_id]
    current_time_jst = datetime.now(JST)

    # オフラインになった場合
    if before.status != discord.Status.offline and after.status == discord.Status.offline:
        if not user_data.get('is_sleeping', False): # 既に睡眠中でない場合のみ
            print(f"User {after.display_name} went offline. Auto-sleeping them.")
            user_data['is_sleeping'] = True
            user_data['sleep_start'] = current_time_jst.isoformat()
            save_data(data)

    # オンラインになった場合 (またはオフラインから他のステータスに変わった場合)
    elif before.status == discord.Status.offline and after.status != discord.Status.offline:
        if user_data.get('is_sleeping', False) and 'sleep_start' in user_data:
            try:
                sleep_start_dt = datetime.fromisoformat(user_data['sleep_start']).astimezone(JST)
                current_sleep_duration_minutes = (current_time_jst - sleep_start_dt).total_seconds() / 60

                member_info = get_user_latest_sleep_info(user_id)
                average_sleep_minutes = member_info['average_sleep_minutes']

                # 平均睡眠時間の前後1時間以内であれば自動起床
                # ただし、平均睡眠時間が0（記録なし）の場合はこの条件をスキップ
                if average_sleep_minutes > 0:
                    lower_bound = (average_sleep_minutes - 60)
                    upper_bound = (average_sleep_minutes + 60)

                    if lower_bound <= current_sleep_duration_minutes <= upper_bound:
                        print(f"User {after.display_name} went online. Auto-waking them based on average sleep time.")
                        sleep_record_auto_wake = {
                            'sleep_start': user_data['sleep_start'],
                            'sleep_end': current_time_jst.isoformat(),
                            'duration_minutes': int(current_sleep_duration_minutes)
                        }
                        user_data['sleep_records'].append(sleep_record_auto_wake)
                        user_data['is_sleeping'] = False
                        if 'sleep_start' in user_data:
                            del user_data['sleep_start']
                        user_data['sleep_end'] = current_time_jst.isoformat()
                        save_data(data)
                elif current_sleep_duration_minutes >= 60: # 平均がない場合でも1時間以上寝てたら自動起床
                    print(f"User {after.display_name} went online. Auto-waking them after 1h+ sleep (no avg).")
                    sleep_record_auto_wake = {
                        'sleep_start': user_data['sleep_start'],
                        'sleep_end': current_time_jst.isoformat(),
                        'duration_minutes': int(current_sleep_duration_minutes)
                    }
                    user_data['sleep_records'].append(sleep_record_auto_wake)
                    user_data['is_sleeping'] = False
                    if 'sleep_start' in user_data:
                        del user_data['sleep_start']
                    user_data['sleep_end'] = current_time_jst.isoformat()
                    save_data(data)
            except ValueError as e:
                print(f"睡眠開始時刻の解析エラー (on_presence_update) for user {user_id}: {e}. データをリセットします。")
                if 'sleep_start' in user_data:
                    del user_data['sleep_start']
                user_data['is_sleeping'] = False
                save_data(data)


@bot.tree.command(name='start', description='睡眠トラッカーを開始します。')
async def start_tracker_slash(interaction: discord.Interaction):
    user_id = str(interaction.user.id)

    embed = discord.Embed(
        title='💤 AutomatonTrackerV2💤',
        description='ボタンをクリックして睡眠を記録しよう‼️‼️',
        color=0xccccff
    )

    embed.add_field(
        name='🐻使い方🐻',
        value='😴 **おやすみ** - 睡眠開始を記録（ログは2分後自動で削除）\n🌅 **おはよう** - 起床を記録（ログは2分後自動で削除）\n📊 **ステータス** - 全員の睡眠ステータスを表示\n💀 **自分のステータスをクリア** - 自分の睡眠データをすべて削除（2回押しで確定）',
        inline=False
    )

    embed.set_footer(text='tungtungtungsahurat3am')

    view = SleepTrackerView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name='setstatus', description='プレイヤーの睡眠ステータスを変更します。')
@app_commands.describe(member='ステータスを変更するユーザー', status='設定するステータス (sleep または wake)')
@app_commands.checks.has_permissions(administrator=True)
@app_commands.checks.has_role('Automaton') # ロール名を適宜調整してください
async def set_status_slash(interaction: discord.Interaction, member: discord.Member, status: str):
    user_id = str(member.id)
    current_time_jst = datetime.now(JST)
    data = load_data()

    if user_id not in data:
        data[user_id] = {'sleep_records': []}

    status_lower = status.lower()

    if status_lower == 'sleep':
        if data[user_id].get('is_sleeping', False):
            await interaction.response.send_message(f'{member.mention} は既に睡眠中です。', ephemeral=True)
            return

        data[user_id]['is_sleeping'] = True
        data[user_id]['sleep_start'] = current_time_jst.isoformat()
        save_data(data)
        embed = discord.Embed(
            title='✅ ステータス変更',
            description=f'{member.mention} のステータスを **睡眠中** に設定しました。',
            color=0x9999ff
        )
        await interaction.response.send_message(embed=embed)

    elif status_lower == 'wake':
        if not data[user_id].get('is_sleeping', False):
            await interaction.response.send_message(f'{member.mention} は既に起床中です。または睡眠記録がありません。', ephemeral=True)
            return

        # sleep_startがデータに存在する場合のみ睡眠記録を作成
        if 'sleep_start' in data[user_id]:
            try:
                sleep_start = datetime.fromisoformat(data[user_id]['sleep_start']).astimezone(JST)
                sleep_duration = current_time_jst - sleep_start

                sleep_record = {
                    'sleep_start': data[user_id]['sleep_start'],
                    'sleep_end': current_time_jst.isoformat(),
                    'duration_minutes': int(sleep_duration.total_seconds() / 60)
                }
                data[user_id]['sleep_records'].append(sleep_record)
            except ValueError as e:
                print(f"睡眠開始時刻の解析エラー (setstatus コマンド) for user {user_id}: {e}. 記録をスキップします。")
                # エラーが発生してもステータスは変更する
                pass
            
        data[user_id]['is_sleeping'] = False
        if 'sleep_start' in data[user_id]:
            del data[user_id]['sleep_start']
        data[user_id]['sleep_end'] = current_time_jst.isoformat()
        save_data(data)

        embed = discord.Embed(
            title='✅ ステータス変更',
            description=f'{member.mention} のステータスを **起床中** に設定しました。',
            color=0xffff99
        )
        await interaction.response.send_message(embed=embed)

    else:
        await interaction.response.send_message('無効なステータスです。「sleep」または「wake」を指定してください。', ephemeral=True)

@set_status_slash.error
async def set_status_slash_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message('このコマンドを実行する権限がありません。「管理者」権限が必要です。', ephemeral=True)
    elif isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(f'このコマンドを実行する権限がありません。「{error.missing_role}」ロールが必要です。', ephemeral=True)
    else:
        await interaction.response.send_message(f'エラーが発生しました: {error}', ephemeral=True)

if __name__ == '__main__':
    TOKEN = os.getenv ('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print('エラー: DISCORD_BOT_TOKEN環境変数が設定されていません')
        print('Discord Developer Portalでボットを作成し、トークンを取得してください')
        print('また、ボットのOAuth2 URL設定で、GUILD_MEMBERS および PRESENCE インテントを有効にするのを忘れないでください。')
    else:
        try:
            bot.run(TOKEN)
        except discord.errors.PrivilegedIntentsRequired as e:
            print(f"インテントエラー: {e}")
            print("GUILD_MEMBERS または PRESENCE インテントが有効になっていません。Discord Developer Portalでボットの設定を確認し、'Privileged Gateway Intents' の下にある 'SERVER MEMBERS INTENT' と 'PRESENCE INTENT' をONにしてください。")
        except Exception as e:
            print(f"ボットの起動中にエラーが発生しました: {e}")
