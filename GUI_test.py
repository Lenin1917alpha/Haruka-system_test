# GUI_test.py (修正版)

import pygame
import sys
import csv
import os
import requests # type: ignore
import io
import time
import threading
import wave
import multiprocessing
from datetime import datetime, time as dt_time # datetime と time をインポート

# グローバル変数（表示する行とアナウンス用情報）
display_rows = []
announcement_info = None
announcement_lock = threading.Lock() # アナウンス情報更新用のロック

def load_timetable(filepath):
    """timetable.csvから時刻表データを読み込み、ETDでソートして返す"""
    timetable = []
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file, skipinitialspace=True)
            for row in reader:
                try:
                    # ETDをtimeオブジェクトに変換して追加
                    row['ETD_time'] = datetime.strptime(row['ETD'], '%H:%M').time()
                    timetable.append(row)
                except ValueError:
                    print(f"警告: 行 {row} の ETD フォーマット '{row.get('ETD', '')}' が無効です。スキップします。")
                except KeyError:
                    print(f"警告: 行 {row} に ETD キーがありません。スキップします。")
    except FileNotFoundError:
        print(f"エラー: ファイル '{filepath}' が見つかりません。")
        sys.exit()
    except Exception as e:
        print(f"エラー: ファイル '{filepath}' の読み込み中にエラーが発生しました: {e}")
        sys.exit()

    # ETD時刻でソート
    timetable.sort(key=lambda x: x.get('ETD_time', dt_time.max)) # ETD_timeがない場合は最後に回す
    return timetable

def update_display_rows(timetable):
    """現在時刻に基づいて表示する次の2件の行を更新する"""
    global display_rows, announcement_info
    now_time = datetime.now().time()

    # 現在時刻以降の便をフィルタリング
    future_timetable = [row for row in timetable if row.get('ETD_time', dt_time.min) >= now_time]

    # フィルタリングされたリストから最大2件を取得
    new_display_rows = future_timetable[:2]

    # グローバル変数を更新 (ロックを使用)
    with announcement_lock:
        # アナウンス対象を先にチェック・更新
        if new_display_rows:
            # announcement_info が None または ETD が異なる場合のみ更新
            if announcement_info is None or announcement_info['ETD'] != new_display_rows[0]['ETD']:
                 announcement_info = new_display_rows[0].copy() # 変更があった場合のみ更新
                 print(f"アナウンス対象が変更されました: {announcement_info['ETD']}発") # デバッグ用
        else:
            # 未来の便がない場合、アナウンス対象をNoneに
            if announcement_info is not None:
                print("アナウンス対象がなくなりました。") # デバッグ用
            announcement_info = None

        # 表示行を更新
        display_rows = new_display_rows


def create_stop_info(row):
    """停車駅情報から案内文を生成する"""
    if not row: # rowがNoneや空の場合
        return "本日のバスは終了しました。"

    stops = []
    ways = []
    # 各停車地のキーが存在するか確認してからアクセス
    if row.get('echizen_takefu') == '1': stops.append("越前たけふ駅")
    else: ways.append("越前たけふ駅")
    if row.get('hoyama(1)') == '1': stops.append("帆山町")
    else: ways.append("帆山町")
    if row.get('kunitaka(1)') == '1': stops.append("国高")
    else: ways.append("国高")
    if row.get('takefu') == '1': stops.append("武生駅")
    else: ways.append("武生駅")
    if row.get('kunitaka(2)') == '1': stops.append("国高")
    else: ways.append("国高")
    if row.get('hoyama(2)') == '1': stops.append("帆山町")
    else: ways.append("帆山町")
    if row.get('jindai') == '0': ways.append("仁愛大学") # 終点が仁愛大学の場合

    destination_text = "終点：仁愛大学" if row.get('destination') == '0' else "終点：武生駅"

    #停車・通過の重複削除
    ways = list(filter(lambda x: x not in stops, ways))
    ways = list(dict.fromkeys(ways)) # 重複削除

    if stops:
        stop_info = "停車駅は、" + "、".join(stops) + "、" + destination_text + "です。"
        if ways:
             stop_info += "　" + "、".join(ways) + "には停車しません。ご注意ください。"
    else:
        stop_info = destination_text + "です。" # 直行便の場合など

    return stop_info

def voicevox_api_request(text, speaker=10006):
    """Voicevox APIにリクエストを送信し、音声データを取得する"""
    base_url = "http://localhost:50121" #ポート番号を修正
    params_create_audio_query = {
        "text": text,
        "speaker": speaker
    }
    try:
        response_create_audio_query = requests.post(
            f"{base_url}/audio_query",
            params=params_create_audio_query,
            timeout=10 # タイムアウト設定
        )
        response_create_audio_query.raise_for_status()
        audio_query = response_create_audio_query.json()

        params_synthesis = {
            "speaker": speaker,
            "enable_interrogative_upspeak": True
        }
        response_synthesis = requests.post(
            f"{base_url}/synthesis",
            params=params_synthesis,
            json=audio_query,
            timeout=30 # 合成は時間がかかる場合があるので長めに
        )
        response_synthesis.raise_for_status()
        return response_synthesis.content
    except requests.exceptions.RequestException as e:
        print(f"Voicevox APIリクエスト中にエラーが発生しました: {e}")
        return None
    except Exception as e:
        print(f"Voicevox処理中に予期せぬエラーが発生しました: {e}")
        return None


def play_voice(voice_data):
    """音声データを再生する (Soundオブジェクトを使用)"""
    if not voice_data:
        print("音声データがありません。再生をスキップします。")
        return False # 再生失敗を示す
    try:
        sound = pygame.mixer.Sound(io.BytesIO(voice_data))
        channel = sound.play()
        if channel:
            # 再生終了を待つ
            while channel.get_busy():
                pygame.time.Clock().tick(10) # CPU負荷を抑えつつ待機
            return True # 再生成功
        else:
            print("音声再生チャンネルの取得に失敗しました。")
            return False
    except pygame.error as e:
        print(f"音声の読み込みまたは再生中にPygameエラーが発生しました: {e}")
        return False
    except Exception as e:
        print(f"音声再生中に予期せぬエラーが発生しました: {e}")
        return False


def play_announcement(announcement):
    """アナウンスを再生する"""
    if not announcement:
        return
    try:
        # アナウンスを生成
        print(f"アナウンス生成中: {announcement[:30]}...") # 長いので一部表示
        voice_data = voicevox_api_request(announcement)
        if not voice_data:
             print("アナウンス音声の生成に失敗しました。")
             return

        # チャイム音を再生 (Soundオブジェクトを使用)
        try:
            # チャイムファイルのパスを取得
            script_dir = os.path.dirname(__file__)
            chime_path = os.path.join(script_dir, "sounds", "4point_chime.wav")
            if not os.path.exists(chime_path):
                print(f"警告: チャイムファイルが見つかりません: {chime_path}")
            else:
                chime_sound = pygame.mixer.Sound(chime_path)
                chime_channel = chime_sound.play() # 再生に使用したチャンネルを取得
                if chime_channel:
                    # チャイムの再生終了を待つ
                    while chime_channel.get_busy():
                        pygame.time.Clock().tick(10)
                else:
                    print("チャイムの再生チャンネルを取得できませんでした。")
                    pygame.time.wait(1000) # とりあえず1秒待つ
        except pygame.error as e:
            print(f"チャイム音の読み込みまたは再生に失敗しました: {e}")
            pygame.time.wait(1000) # エラーでも少し待つ

        # アナウンスを再生
        print("アナウンス再生中...")
        play_voice(voice_data)
        print("アナウンス再生完了。")

    except Exception as e:
        print(f"アナウンス再生処理全体でエラーが発生しました: {e}")

def announcement_loop():
    """アナウンスをループ再生する (60秒ごとに繰り返し)"""
    global announcement_info
    announced_end_message = False # 終了アナウンス済みフラグ

    while True:
        current_announcement_info = None
        # ロックを取得して安全にアナウンス情報を読み取る
        with announcement_lock:
            if announcement_info:
                current_announcement_info = announcement_info.copy() # 念のためコピー

        if current_announcement_info:
            # 便が変わったかどうかのチェックをせず、常にアナウンスを試みる
            current_time_str = current_announcement_info['ETD']
            print(f"アナウンス対象: {current_time_str}発 (60秒ごとに再生)") # ログメッセージ変更

            stop_info = create_stop_info(current_announcement_info)
            time_parts = current_announcement_info['ETD'].split(":")
            time_text = time_parts[0] + "時" + time_parts[1] + "分"
            destination_text = "仁愛大学" if current_announcement_info['destination'] == '0' else "武生駅"
            platform_text = current_announcement_info.get('platform', '未定')
            announcement = f"次に、仁愛大学から発車します、{time_text}発、無料シャトルバス、{destination_text}行きは、{platform_text}番乗り場から、発車します。乗車位置で、1列に並んで、お待ちください。{stop_info}"

            play_announcement(announcement)
            announced_end_message = False # アナウンスしたので終了フラグ解除

            # アナウンス後に60秒待つ
            time.sleep(60)

        else:
            # アナウンス対象がない場合（終バス後など）
            if not announced_end_message: # 終了アナウンスを一度だけ行う
                 print("アナウンス対象なし。終了アナウンスを再生します。")
                 play_announcement("本日のシャトルバスの運行は終了しました。")
                 announced_end_message = True
            # 終バス後も60秒ごとにチェック
            time.sleep(60)


def main():
    pygame.init()
    # より安定する可能性のあるパラメータでmixerを初期化
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        print("Pygame mixer initialized successfully.")
    except pygame.error as e:
        print(f"Pygame mixer initialization failed: {e}")
        pygame.quit()
        sys.exit()


    # ウィンドウサイズ
    screen_width, screen_height = 1600, 900
    screen = pygame.display.set_mode((screen_width, screen_height))
    pygame.display.set_caption("発車案内サンプル")

    # フォント設定 (環境に合わせてパスを修正してください)
    try:
        # Windowsの場合の一般的なパス例
        font_path_bold = "C:/Windows/Fonts/meiryob.ttc" # Meiryo Bold
        font_path_regular = "C:/Windows/Fonts/meiryo.ttc" # Meiryo Regular
        # もし上記で見つからない場合、游ゴシックなどを試す
        # font_path_bold = "C:/Windows/Fonts/YuGothB.ttc" # Yu Gothic Bold
        # font_path_regular = "C:/Windows/Fonts/YuGothR.ttc" # Yu Gothic Regular

        # フォントが存在するか確認
        if not os.path.exists(font_path_bold):
             print(f"警告: フォントファイルが見つかりません: {font_path_bold}")
             font_path_bold = None # Noneにしてデフォルトフォントを使う
        if not os.path.exists(font_path_regular):
             print(f"警告: フォントファイルが見つかりません: {font_path_regular}")
             font_path_regular = None

        font_title = pygame.font.Font(font_path_bold, 45)
        font_text = pygame.font.Font(font_path_bold, 48)
        font_expo = pygame.font.Font(font_path_regular, 28)
        font_scroll = pygame.font.Font(font_path_regular, 28)
        print("Fonts loaded successfully.")

    except Exception as e:
        print(f"フォントの読み込みに失敗しました: {e}")
        # フォールバックとしてデフォルトフォントを使用
        font_title = pygame.font.Font(None, 55)
        font_text = pygame.font.Font(None, 60)
        font_expo = pygame.font.Font(None, 40)
        font_scroll = pygame.font.Font(None, 35)
        print("Using default fonts.")

    # フォントの高さを取得 (スクロール位置計算用)
    font_expo_height = font_expo.get_height()
    font_scroll_height = font_scroll.get_height()

    # 背景色
    background_color = (0, 0, 0)  # 黒

    #タイトル
    title_surface = font_title.render("シャトルバス発車案内（武生駅・越前たけふ駅・国高・帆山町）", True, (255, 255, 255))  #白
    title_rect = title_surface.get_rect(center=(screen_width // 2, 43))

    #背景設定
    bg1 = pygame.Rect(0, 0, screen_width, 130)
    bg2 = pygame.Rect(0, 80, screen_width, 10)
    bg3 = pygame.Rect(0, 510, screen_width, 10)

    #図形設定
    rect1 = pygame.Rect(30, 165, 190, 80)
    rect2 = pygame.Rect(30, 560, 190, 80)

    #固定テキスト (位置調整)
    expo_text0_1 = font_expo.render("J-TraIV", True, (255, 255, 255))
    expo_text0_2 = font_expo.render("発車時刻", True, (255, 255, 255))
    expo_text0_3 = font_expo.render("行き先", True, (255, 255, 255))
    expo_text0_4 = font_expo.render("台数", True, (255, 255, 255))
    expo_text0_5 = font_expo.render("乗り場", True, (255, 255, 255))
    expo_text1_1 = font_title.render("先発", True, (255, 255, 255))
    expo_text1_2 = font_expo.render("停車駅", True, (255, 255, 255))
    expo_text1_3 = font_expo.render("接続列車", True, (255, 255, 255))
    expo_text2_1 = font_title.render("次発", True, (255, 255, 255))
    expo_text2_2 = font_expo.render("停車駅", True, (255, 255, 255))
    expo_text2_3 = font_expo.render("接続列車", True, (255, 255, 255))

    adjust1 = font_expo.render("調整中", True, (255, 255, 255))
    adjust2 = font_expo.render("調整中", True, (255, 255, 255))

    # --- スクロールテキスト位置計算のための準備 ---
    # 接続列車エリアのY座標範囲
    connect_area1_top_y = 355
    connect_area1_bottom_y = 465
    connect_area2_top_y = 740
    connect_area2_bottom_y = 850

    # 「調整中」テキストの描画Y座標 (上端)
    adjust1_draw_top_y = 415 + (50 - font_expo_height) // 2
    adjust2_draw_top_y = 800 + (50 - font_expo_height) // 2

    # 接続列車エリアの上線と「調整中」テキストの上端の間のマージン
    margin_connect1 = adjust1_draw_top_y - connect_area1_bottom_y # 465の線とadjust1の上端の間
    margin_connect2 = adjust2_draw_top_y - connect_area2_bottom_y # 850の線とadjust2の上端の間 (これは使わない)
    # 接続列車エリアの下線と「調整中」テキストの上端の間のマージンを使う
    margin_for_scroll1 = adjust1_draw_top_y - connect_area1_bottom_y
    margin_for_scroll2 = adjust2_draw_top_y - connect_area2_bottom_y

    # 停車駅スクロールエリアのY座標範囲
    scroll_area1_top_y = 130 # 仮 (実際はヘッダーの下) -> 描画エリアclip1_rectを使う
    scroll_area1_bottom_y = 355
    scroll_area2_top_y = 510 # 仮 -> 描画エリアclip2_rectを使う
    scroll_area2_bottom_y = 740

    # スクロールテキストの描画Y座標 (上端) を計算
    # テキストの下端が (scroll_area1_bottom_y - margin_for_scroll1) になるように
    scroll1_draw_top_y = scroll_area1_bottom_y - margin_for_scroll1 - font_scroll_height
    # テキストの下端が (scroll_area2_bottom_y - margin_for_scroll2) になるように
    scroll2_draw_top_y = scroll_area2_bottom_y - margin_for_scroll2 - font_scroll_height

    # --- ここまでスクロール位置計算準備 ---


    # 時刻表データの読み込み
    script_dir = os.path.dirname(__file__) # スクリプトのディレクトリを取得
    timetable_path = os.path.join(script_dir, "timetable.csv")
    timetable = load_timetable(timetable_path)

    # 最初に表示行を更新
    update_display_rows(timetable)

    # スクロール関連の変数（先発バス用）
    scroll1_x = screen_width # 右端からスタート
    scroll1_speed = 2
    scroll1_text_width = 0
    scroll1_text_surface = None
    clip1_rect = pygame.Rect(250, scroll_area1_bottom_y - font_scroll_height - margin_for_scroll1 - 5, 1300, font_scroll_height + 10) # クリップ領域を計算したY座標に合わせる
    # scroll1_y = clip1_rect.centery # 中央揃えではなく計算したY座標を使う

    # スクロール関連の変数（次発バス用）
    scroll2_x = screen_width # 右端からスタート
    scroll2_speed = 2
    scroll2_text_width = 0
    scroll2_text_surface = None
    clip2_rect = pygame.Rect(250, scroll_area2_bottom_y - font_scroll_height - margin_for_scroll2 - 5, 1300, font_scroll_height + 10) # クリップ領域を計算したY座標に合わせる
    # scroll2_y = clip2_rect.centery # 中央揃えではなく計算したY座標を使う

    wait_distance = 100 # 追加で待つドット数

    # アナウンスループを別スレッドで開始
    announcement_thread = threading.Thread(target=announcement_loop, daemon=True)
    announcement_thread.start()

    # メインループ
    clock = pygame.time.Clock()
    last_update_time = time.monotonic() # 最終更新時刻
    last_display_rows_count = len(display_rows) # 表示行数が変わったかチェック用

    while True:
        # イベント処理
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

        # --- 時刻表情報の更新 ---
        current_time = time.monotonic()
        if current_time - last_update_time >= 10: # 10秒ごとに更新チェック
            update_display_rows(timetable)
            last_update_time = current_time

            # 表示行数が変わったらスクロールテキストをリセット
            current_display_rows_count = len(display_rows)
            if current_display_rows_count != last_display_rows_count:
                print(f"表示行数が変更されました: {last_display_rows_count} -> {current_display_rows_count}")
                scroll1_text_surface = None
                scroll2_text_surface = None
                scroll1_x = screen_width # スクロール位置もリセット
                scroll2_x = screen_width
                last_display_rows_count = current_display_rows_count


        # --- 描画処理 ---
        screen.fill(background_color)

        #背景描画
        pygame.draw.rect(screen, (38, 38, 38), bg1)
        pygame.draw.rect(screen, (33, 95, 154), bg2)
        pygame.draw.rect(screen, (38, 38, 38), bg3)

        #図形描画
        pygame.draw.rect(screen, (192, 79, 21), rect1, border_radius=10)
        pygame.draw.rect(screen, (33, 95, 154), rect2, border_radius=10)

        # 線描画 (変更なし)
        pygame.draw.line(screen, (255, 255, 255), (250, 355), (1550, 355), 1) # 停車駅エリア下線1
        pygame.draw.line(screen, (255, 255, 255), (250, 465), (1550, 465), 1) # 接続列車エリア下線1
        pygame.draw.line(screen, (255, 255, 255), (250, 740), (1550, 740), 1) # 停車駅エリア下線2
        pygame.draw.line(screen, (255, 255, 255), (250, 850), (1550, 850), 1) # 接続列車エリア下線2

        #固定テキスト描画 (位置調整)
        screen.blit(expo_text0_1, (70, 93))
        screen.blit(expo_text0_2, (310, 93))
        screen.blit(expo_text0_3, (750, 93))
        screen.blit(expo_text0_4, (1130, 93))
        screen.blit(expo_text0_5, (1350, 93))
        screen.blit(expo_text1_1, expo_text1_1.get_rect(center=rect1.center)) # 先発 中央揃え
        # 停車駅テキストのY座標はスクロールテキストの位置に合わせる
        screen.blit(expo_text1_2, (77, scroll1_draw_top_y + (font_scroll_height - font_expo_height) // 2))
        screen.blit(expo_text1_3, (65, 415 + (50 - font_expo_height) // 2)) # 接続列車 縦中央揃え (変更なし)
        screen.blit(expo_text2_1, expo_text2_1.get_rect(center=rect2.center)) # 次発 中央揃え
        # 停車駅テキストのY座標はスクロールテキストの位置に合わせる
        screen.blit(expo_text2_2, (77, scroll2_draw_top_y + (font_scroll_height - font_expo_height) // 2))
        screen.blit(expo_text2_3, (65, 800 + (50 - font_expo_height) // 2)) # 接続列車 縦中央揃え (変更なし)

        screen.blit(adjust1, (840, adjust1_draw_top_y)) # 調整中 縦中央揃え (変更なし)
        screen.blit(adjust2, (840, adjust2_draw_top_y)) # 調整中 縦中央揃え (変更なし)

        # タイトル描画
        screen.blit(title_surface, title_rect)

        # --- 時刻表情報の描画 ---
        current_display_rows_render = []
        with announcement_lock: # display_rowsを読むときもロック
             current_display_rows_render = display_rows[:] # 描画用にコピー

        y_offset = 180
        # 先発
        if len(current_display_rows_render) > 0:
            row = current_display_rows_render[0]
            time_text = font_text.render(row['ETD'], True, (255, 255, 255))
            screen.blit(time_text, (310, y_offset))
            destination_text = "仁愛大学" if row['destination'] == '0' else "武生駅"
            destination_surface = font_text.render(destination_text, True, (255, 255, 255))
            screen.blit(destination_surface, (695, y_offset))
            car_surface = font_text.render(row.get('car', '-'), True, (255, 255, 255)) # carがない場合
            screen.blit(car_surface, (1150, y_offset))
            platform_surface = font_text.render(row.get('platform', '-'), True, (255, 255, 255)) # platformがない場合
            screen.blit(platform_surface, (1380, y_offset))

            # 停車駅スクロール (先発)
            stop1_info = create_stop_info(row)
            if scroll1_text_surface is None:
                scroll1_text_surface = font_scroll.render(stop1_info, True, (255, 255, 255))
                scroll1_text_width = scroll1_text_surface.get_width()
                # Y座標計算を再調整 (フォント高さが確定してから)
                scroll1_draw_top_y = scroll_area1_bottom_y - scroll1_text_surface.get_height()
                clip1_rect = pygame.Rect(250, scroll1_draw_top_y - 5, 1300, scroll1_text_surface.get_height() + 10) # クリップ領域再設定


            scroll1_x -= scroll1_speed
            if scroll1_x < -scroll1_text_width - wait_distance:
                scroll1_x = clip1_rect.width # クリップ領域の幅を使う

            screen.set_clip(clip1_rect)
            # 描画Y座標をscroll1_draw_top_yに設定
            screen.blit(scroll1_text_surface, (scroll1_x + clip1_rect.x, scroll1_draw_top_y))
            screen.set_clip(None)
        else:
            # 先発がない場合の表示
            no_bus_text = font_text.render("---", True, (128, 128, 128)) # グレー表示
            screen.blit(no_bus_text, (310, y_offset))
            screen.blit(no_bus_text, (695, y_offset))
            screen.blit(no_bus_text, (1150, y_offset))
            screen.blit(no_bus_text, (1380, y_offset))
            no_stop_text = font_scroll.render("本日のバスは終了しました", True, (128, 128, 128))
            # Y座標を計算した位置に合わせる
            no_stop_rect = no_stop_text.get_rect(midleft=(clip1_rect.x + 10, scroll1_draw_top_y + font_scroll_height // 2))
            screen.blit(no_stop_text, no_stop_rect)


        y_offset += 385 # 次発のYオフセット (180 + 385 = 565)

        # 次発
        if len(current_display_rows_render) > 1:
            row = current_display_rows_render[1]
            time_text = font_text.render(row['ETD'], True, (255, 255, 255))
            screen.blit(time_text, (310, y_offset))
            destination_text = "仁愛大学" if row['destination'] == '0' else "武生駅"
            destination_surface = font_text.render(destination_text, True, (255, 255, 255))
            screen.blit(destination_surface, (695, y_offset))
            car_surface = font_text.render(row.get('car', '-'), True, (255, 255, 255))
            screen.blit(car_surface, (1150, y_offset))
            platform_surface = font_text.render(row.get('platform', '-'), True, (255, 255, 255))
            screen.blit(platform_surface, (1380, y_offset))

            # 停車駅スクロール (次発)
            stop2_info = create_stop_info(row)
            if scroll2_text_surface is None:
                scroll2_text_surface = font_scroll.render(stop2_info, True, (255, 255, 255))
                scroll2_text_width = scroll2_text_surface.get_width()
                # Y座標計算を再調整 (フォント高さが確定してから)
                scroll2_draw_top_y = scroll_area2_bottom_y - scroll2_text_surface.get_height()
                clip2_rect = pygame.Rect(250, scroll2_draw_top_y - 5, 1300, scroll2_text_surface.get_height() + 10) # クリップ領域再設定

            scroll2_x -= scroll2_speed
            if scroll2_x < -scroll2_text_width - wait_distance:
                scroll2_x = clip2_rect.width # クリップ領域の幅を使う

            screen.set_clip(clip2_rect)
            # 描画Y座標をscroll2_draw_top_yに設定
            screen.blit(scroll2_text_surface, (scroll2_x + clip2_rect.x, scroll2_draw_top_y))
            screen.set_clip(None)
        else:
             # 次発がない場合の表示
            no_bus_text = font_text.render("---", True, (128, 128, 128)) # グレー表示
            screen.blit(no_bus_text, (310, y_offset))
            screen.blit(no_bus_text, (695, y_offset))
            screen.blit(no_bus_text, (1150, y_offset))
            screen.blit(no_bus_text, (1380, y_offset))
            no_stop_text = font_scroll.render("", True, (128, 128, 128)) # 次発がない場合は停車駅欄は空
            # Y座標を計算した位置に合わせる
            no_stop_rect = no_stop_text.get_rect(midleft=(clip2_rect.x + 10, scroll2_draw_top_y + font_scroll_height // 2))
            screen.blit(no_stop_text, no_stop_rect)


        # 画面更新
        pygame.display.update()
        clock.tick(30) # FPSを30に設定

if __name__ == "__main__":
    # multiprocessing を Windows で使う場合に必要な記述
    multiprocessing.freeze_support()
    main()
