# -*- coding: utf-8 -*-

"""

娱乐系统模块

功能：五子棋（AI对战 / 二人对战） + 看图猜成语

"""



import random

import re

import asyncio

import os

import time

from modules.common import (

    send_text,

    send_text_with_keyboard,

    send_local_image_for_scene,

    send_image_for_scene,

    load_json,

    save_json,

    build_keyboard_multi,

    build_keyboard_command,

    build_keyboard_callback,

    is_duplicate,

    clean_content,

    logger,

    http_get,

    http_post,

    http_get_text,

    format_duration,

    ChatScene,

)





def _scene(s):

    """场景默认值为群聊（向后兼容）"""

    return s or ChatScene.GROUP

from modules import config



# ============ 五子棋常量 ============

BOARD_SIZE = 15          # 棋盘大小 15x15

EMPTY = 0                # 空位

BLACK = 1                # 黑棋

WHITE = 2                # 白棋

BLACK_SYMBOL = "●"       # 黑棋显示符号

WHITE_SYMBOL = "○"       # 白棋显示符号

EMPTY_SYMBOL = "·"       # 空位显示符号

COLUMNS = "ABCDEFGHIJKLMNO"  # 列字母 A-O



# ============ 数据文件名 ============

GOMOKU_DATA_FILE = "gomoku_games.json"             # 五子棋棋局数据
GOMOKU_STATS_FILE = "gomoku_stats.json"            # 五子棋战绩数据

IDIOM_DATA_FILE = "idioms.json"                    # 成语库（历史兼容，已不再使用）

IDIOM_GAME_DATA_FILE = "idiom_games.json"          # 猜成语游戏数据

# 雾笙云「看图猜成语」多轮游戏 API（截图实测：https://wsapi.top/API/game_ktccy.php，大写 API）
# 协议：msg=开始游戏/我猜<成语>/提示；id=自定义会话ID。
# 本 bot 仅用「开始游戏」+ 每次新随机 id 拿单题，判分仍走本地比对 current_idiom（最小改动方案）。
# 服务器响应里 msg 字段换行为字面 "\n"（无 hint 字段）；图片为相对 HTTP 路径。
# 密钥 a92f89d7bffd21a3 由用户 2026-08 提供（平台配额/统计用，匿名也通）。
IDIOM_API_URL = "https://wsapi.top/API/game_ktccy.php"
IDIOM_API_KEY = "a92f89d7bffd21a3"

# 观音灵签在线 API（小小API guanyinrandom）
GUANYIN_API_URL = "https://v2.xxapi.cn/api/guanyinrandom"
_GUANYIN_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Authorization": "Bearer %s" % config.XXAPI_KEY,
}

# 答案之书在线 API（小小API answers）
DAANZI_API_URL = "https://v2.xxapi.cn/api/answers"
_DAANZI_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Authorization": "Bearer %s" % config.XXAPI_KEY,
}

# 塔罗牌在线 API（OIAPI Tarot，完全免鉴权）
# 每次返回 4 张牌：position（牌位）/ meaning（牌位含义）/ name_cn / name_en /
# type（正位/逆位）/ pic（牌图 URL）/ 「正位」或「逆位」（该方向解释，**按 type 只出现一个**）
TAROT_API_URL = "https://oiapi.net/api/Tarot"
_TAROT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
}
TAROT_TIMEOUT = 8  # HTTP 超时（秒），OIAPI 偶发慢


# ============ 星座运势（小小API / xxapi.cn，无需密钥） ============
_HOROSCOPE_SIGN_MAP = {
    "白羊": "aries", "白羊座": "aries", "aries": "aries",
    "金牛": "taurus", "金牛座": "taurus", "taurus": "taurus",
    "双子": "gemini", "双子座": "gemini", "gemini": "gemini",
    "巨蟹": "cancer", "巨蟹座": "cancer", "cancer": "cancer",
    "狮子": "leo", "狮子座": "leo", "leo": "leo",
    "处女": "virgo", "处女座": "virgo", "virgo": "virgo",
    "天秤": "libra", "天秤座": "libra", "libra": "libra",
    "天蝎": "scorpio", "天蝎座": "scorpio", "scorpio": "scorpio",
    "射手": "sagittarius", "射手座": "sagittarius", "sagittarius": "sagittarius",
    "摩羯": "capricorn", "摩羯座": "capricorn", "capricorn": "capricorn",
    "水瓶": "aquarius", "水瓶座": "aquarius", "aquarius": "aquarius",
    "双鱼": "pisces", "双鱼座": "pisces", "pisces": "pisces",
}
_HOROSCOPE_SIGN_NAMES = {
    "aries": "白羊座", "taurus": "金牛座", "gemini": "双子座",
    "cancer": "巨蟹座", "leo": "狮子座", "virgo": "处女座",
    "libra": "天秤座", "scorpio": "天蝎座", "sagittarius": "射手座",
    "capricorn": "摩羯座", "aquarius": "水瓶座", "pisces": "双鱼座",
}
_HOROSCOPE_API = "https://v2.xxapi.cn/api/horoscope"


# ============ 中国象棋常量 ============

XIANGQI_DATA_FILE = "xiangqi_games.json"           # 象棋棋局数据

XIANGQI_STATS_FILE = "xiangqi_stats.json"          # 象棋战绩数据

XIANGQI_NAMES_FILE = "console_names.json"          # 成员名映射（用于排行榜显示）

XQ_FILES = "abcdefghi"                             # 列字母 a-i（左→右）

XQ_PIECE_CHAR = {                                  # 棋子显示汉字

    "rK": "帅", "rA": "仕", "rB": "相", "rN": "马", "rR": "车", "rC": "炮", "rP": "兵",

    "bK": "将", "bA": "士", "bB": "象", "bN": "马", "bR": "车", "bC": "炮", "bP": "卒",

}

XQ_PIECE_VALUE = {"K": 10000, "R": 600, "C": 285, "N": 270, "B": 120, "A": 120, "P": 30}

XQ_COLOR_NAME = {"red": "红方", "black": "黑方"}





class GameManager:

    """娱乐系统 - 五子棋 + 看图猜成语"""



    def __init__(self):

        pass



    # ================================================================

    #                         五子棋模块

    # ================================================================



    def _new_board(self):

        """创建新的空棋盘（15x15二维列表，值为EMPTY）"""

        return [[EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)]



    def _board_to_text(self, board):

        """将棋盘转换为文本形式展示（降级备用）"""

        lines = []

        # 列头：A B C ... O

        header = "   " + " ".join(COLUMNS)

        lines.append(header)

        for i in range(BOARD_SIZE):

            # 行号左对齐占2位

            row_label = "%-2d" % (i + 1)

            cells = []

            for j in range(BOARD_SIZE):

                val = board[i][j]

                if val == BLACK:

                    cells.append(BLACK_SYMBOL)

                elif val == WHITE:

                    cells.append(WHITE_SYMBOL)

                else:

                    cells.append(EMPTY_SYMBOL)

            lines.append(row_label + " " + " ".join(cells))

        return "\n".join(lines)



    def _board_to_image(self, board, last_move=None):

        """

        将棋盘渲染为PNG图片，返回bytes。

        - board: 15x15二维列表

        - last_move: (row, col) 最后一步落子位置，用红点标记

        """

        from PIL import Image, ImageDraw, ImageFont

        import io



        cell_size = 40

        margin = 35

        board_pixels = (BOARD_SIZE - 1) * cell_size

        img_size = board_pixels + margin * 2



        # 木色棋盘背景

        img = Image.new("RGB", (img_size, img_size), (220, 179, 92))

        draw = ImageDraw.Draw(img)



        # 加载字体

        font = None

        for font_path in [

            "C:/Windows/Fonts/simhei.ttf",

            "C:/Windows/Fonts/msyh.ttc",

            "C:/Windows/Fonts/arial.ttf",

        ]:

            try:

                font = ImageFont.truetype(font_path, 14)

                break

            except Exception:

                continue

        if font is None:

            font = ImageFont.load_default()



        line_color = (60, 40, 20)



        # 画网格线

        for i in range(BOARD_SIZE):

            pos = margin + i * cell_size

            # 横线

            draw.line([(margin, pos), (margin + board_pixels, pos)], fill=line_color, width=1)

            # 竖线

            draw.line([(pos, margin), (pos, margin + board_pixels)], fill=line_color, width=1)



        # 画天元和星位

        star_points = [(3, 3), (3, 11), (7, 7), (11, 3), (11, 11)]

        for r, c in star_points:

            x = margin + c * cell_size

            y = margin + r * cell_size

            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=line_color)



        # 画列标签 A-O 和行标签 1-15

        for i in range(BOARD_SIZE):

            x = margin + i * cell_size

            draw.text((x - 5, 10), COLUMNS[i], fill=line_color, font=font)

            y = margin + i * cell_size

            draw.text((8, y - 7), str(i + 1), fill=line_color, font=font)



        # 画棋子

        stone_r = cell_size // 2 - 3

        for i in range(BOARD_SIZE):

            for j in range(BOARD_SIZE):

                val = board[i][j]

                if val == EMPTY:

                    continue

                x = margin + j * cell_size

                y = margin + i * cell_size

                if val == BLACK:

                    # 黑棋：深色渐变效果

                    draw.ellipse([x - stone_r, y - stone_r, x + stone_r, y + stone_r],

                                 fill=(40, 40, 40), outline=(10, 10, 10))

                    # 高光

                    draw.ellipse([x - stone_r + 3, y - stone_r + 3, x - 2, y - 2],

                                 fill=(80, 80, 80))

                else:

                    # 白棋

                    draw.ellipse([x - stone_r, y - stone_r, x + stone_r, y + stone_r],

                                 fill=(250, 250, 250), outline=(120, 120, 120))

                    # 高光

                    draw.ellipse([x - stone_r + 3, y - stone_r + 3, x - 2, y - 2],

                                 fill=(255, 255, 255))



        # 标记最后一步（红点）

        if last_move:

            r_idx, c_idx = last_move

            x = margin + c_idx * cell_size

            y = margin + r_idx * cell_size

            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(220, 40, 40))



        # 转为bytes

        buf = io.BytesIO()

        img.save(buf, format="PNG")

        return buf.getvalue()



    async def _send_board(self, api, group_openid, board, content, msg_id=None, last_move=None, scene=None):

        """

        发送棋盘图片消息，失败时降级为文本。

        - content: 随图附带的文字说明

        - last_move: 最后一步坐标用于标记

        """

        try:

            img_bytes = self._board_to_image(board, last_move=last_move)

            result = await send_local_image_for_scene(api, _scene(scene), group_openid, img_bytes, content=content, msg_id=msg_id

            )

            if result is not None:

                return

        except Exception as e:

            logger.error("生成/发送棋盘图片失败: %s，降级为文本" % e)

        # 降级：纯文本

        board_text = self._board_to_text(board)

        await send_text(api, _scene(scene), group_openid, content + "\n\n" + board_text, msg_id=msg_id)



    def _parse_move(self, content):

        """

        解析落子坐标

        支持格式：“下棋 H8”、“落子 H8”、"下棋h8" 等

        返回 (row, col) 元组或 None

        """

        # 去除命令前缀

        text = content

        for prefix in ("下棋", "落子"):

            if text.startswith(prefix):

                text = text[len(prefix):]

                break

        text = text.strip().upper()

        if not text:

            return None

        # 匹配：列字母(A-O) + 行号(1-15)

        m = re.match(r"^([A-O])\s*(\d{1,2})$", text)

        if not m:

            return None

        col_letter = m.group(1)

        row_num = int(m.group(2))

        col = COLUMNS.index(col_letter)

        row = row_num - 1

        if 0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE:

            return (row, col)

        return None



    def _check_win(self, board, row, col, player):

        """

        检查在 (row, col) 落子后是否形成五连

        检查四个方向：水平、垂直、主对角线、副对角线

        """

        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]

        for dr, dc in directions:

            count = 1  # 当前落子算1个

            # 正方向延伸

            r, c = row + dr, col + dc

            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == player:

                count += 1

                r += dr

                c += dc

            # 反方向延伸

            r, c = row - dr, col - dc

            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == player:

                count += 1

                r -= dr

                c -= dc

            if count >= 5:

                return True

        return False



    def _evaluate_position(self, board, row, col):

        """

        评估某个空位的得分（用于AI决策）

        越靠近中心、周围棋子越多，得分越高

        """

        score = 0

        center = BOARD_SIZE // 2

        # 中心距离加分（越靠中心分越高）

        score += (BOARD_SIZE - abs(row - center) - abs(col - center))

        # 周围2格内的棋子加分

        for dr in range(-2, 3):

            for dc in range(-2, 3):

                if dr == 0 and dc == 0:

                    continue

                r, c = row + dr, col + dc

                if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE:

                    if board[r][c] == BLACK:

                        score += 2  # 附近有黑棋

                    elif board[r][c] == WHITE:

                        score += 3  # 附近有白棋（AI自己的棋子权重更高）

        return score



    def _ai_move(self, board):

        """

        简单AI落子策略：

        1. 检查自己（白棋）能否一步获胜 → 直接获胜

        2. 检查对手（黑棋）能否一步获胜 → 堵住

        3. 否则评估所有空位，选择得分最高的位置（偏向中心和已有棋子附近）

        返回 (row, col) 元组

        """

        # 1. 检查AI能否一步获胜

        for i in range(BOARD_SIZE):

            for j in range(BOARD_SIZE):

                if board[i][j] == EMPTY:

                    board[i][j] = WHITE

                    if self._check_win(board, i, j, WHITE):

                        board[i][j] = EMPTY

                        return (i, j)

                    board[i][j] = EMPTY



        # 2. 检查对手能否一步获胜，堵住

        for i in range(BOARD_SIZE):

            for j in range(BOARD_SIZE):

                if board[i][j] == EMPTY:

                    board[i][j] = BLACK

                    if self._check_win(board, i, j, BLACK):

                        board[i][j] = EMPTY

                        return (i, j)

                    board[i][j] = EMPTY



        # 3. 评估最佳位置

        best_score = -1

        best_move = (BOARD_SIZE // 2, BOARD_SIZE // 2)  # 默认中心

        for i in range(BOARD_SIZE):

            for j in range(BOARD_SIZE):

                if board[i][j] != EMPTY:

                    continue

                score = self._evaluate_position(board, i, j)

                # 加入随机扰动避免每次都走同一步

                score += random.uniform(0, 0.5)

                if score > best_score:

                    best_score = score

                    best_move = (i, j)

        return best_move



    # ---------- 五子棋游戏流程 ----------



    async def _gomoku_show_modes(self, api, group_openid, msg_id, scene=None):

        """显示五子棋模式选择按钮"""

        keyboard = build_keyboard_multi([

            {"label": "AI对战", "command": "AI对战", "enter": True, "id": "gomoku_ai"},

            {"label": "二人对战", "command": "二人对战", "enter": True, "id": "gomoku_pvp"},

            {"label": "排行榜", "command": "五子棋排行", "enter": True, "id": "gomoku_rank"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid,

            "请选择五子棋功能：\n✨ AI对战/二人对战 启动新棋局，排行榜查看战绩",
            keyboard, msg_id=msg_id,

        )



    async def _gomoku_start_ai(self, api, group_openid, member_openid, msg_id, scene=None, member_nick=None):

        """开始AI对战（玩家执黑先行）"""

        games = load_json(GOMOKU_DATA_FILE)

        if group_openid in games and games[group_openid].get("status") == "playing":

            await send_text(api, _scene(scene), group_openid,

                "当前已有进行中的棋局，请先结束（发送“结束棋局”）",

                msg_id=msg_id,

            )

            return



        board = self._new_board()

        games[group_openid] = {

            "board": board,

            "current_player": BLACK,  # 黑方先行

            "mode": "ai",

            "players": {"black": member_openid, "white": "ai"},

            "status": "playing",

        }

        save_json(GOMOKU_DATA_FILE, games)



        self._xq_save_name(member_openid, member_nick)

        msg = (

            "五子棋AI对战开始！\n"

            "你执黑先行，发送“下棋 H8”落子\n"

            "（列 A-O，行 1-15）"

        )

        await self._send_board(api, group_openid, board, msg, msg_id=msg_id, scene=scene)



    async def _gomoku_show_colors(self, api, group_openid, msg_id, scene=None):

        """显示棋色选择按钮（二人对战模式）"""

        keyboard = build_keyboard_multi([

            {"label": "选择黑方", "command": "选择黑方", "enter": True, "id": "gomoku_black"},

            {"label": "选择白方", "command": "选择白方", "enter": True, "id": "gomoku_white"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "请选择你的棋色（黑方先手）：", keyboard, msg_id=msg_id

        )



    async def _gomoku_select_color(self, api, group_openid, member_openid, color, msg_id, scene=None, member_nick=None):

        """选择棋色并开始二人对战"""

        games = load_json(GOMOKU_DATA_FILE)

        if group_openid in games and games[group_openid].get("status") == "playing":

            await send_text(api, _scene(scene), group_openid,

                "当前已有进行中的棋局，请先结束（发送“结束棋局”）",

                msg_id=msg_id,

            )

            return



        board = self._new_board()

        players = {}

        if color == BLACK:

            players["black"] = member_openid

            color_name = "黑方"

            turn_msg = "你执黑方先行，发送“下棋 H8”落子"

        else:

            players["white"] = member_openid

            color_name = "白方"

            turn_msg = "你执白方后手，等待黑方先落子"



        games[group_openid] = {

            "board": board,

            "current_player": BLACK,  # 黑方始终先行

            "mode": "pvp",

            "players": players,

            "status": "playing",

        }

        save_json(GOMOKU_DATA_FILE, games)



        self._xq_save_name(member_openid, member_nick)

        msg = "二人对战开始！你执%s\n%s" % (color_name, turn_msg)

        await self._send_board(api, group_openid, board, msg, msg_id=msg_id, scene=scene)



    async def _gomoku_move(self, api, text, group_openid, member_openid, msg_id, scene=None, member_nick=None):

        """处理落子指令"""

        games = load_json(GOMOKU_DATA_FILE)

        if group_openid not in games or games[group_openid].get("status") != "playing":

            await send_text(api, _scene(scene), group_openid, "当前没有进行中的棋局", msg_id=msg_id)

            return



        game = games[group_openid]

        board = game["board"]

        current_player = game["current_player"]

        players = game.get("players", {})

        mode = game.get("mode", "ai")



        # 解析坐标

        pos = self._parse_move(text)

        if pos is None:

            await send_text(api, _scene(scene), group_openid,

                "坐标格式错误，请使用“下棋 H8”格式（列A-O，行1-15）",

                msg_id=msg_id,

            )

            return



        row, col = pos



        # 检查位置是否已有棋子

        if board[row][col] != EMPTY:

            await send_text(api, _scene(scene), group_openid, "该位置已有棋子，请选择其他位置", msg_id=msg_id)

            return



        # 权限检查：是否轮到该玩家

        if mode == "ai":

            # AI模式：只有黑方（玩家）能动

            if current_player != BLACK:

                await send_text(api, _scene(scene), group_openid, "请等待AI落子", msg_id=msg_id)

                return

            if players.get("black") != member_openid:

                await send_text(api, _scene(scene), group_openid, "这不是你的棋局", msg_id=msg_id)

                return

        else:

            # PVP模式：检查当前颜色是否已分配玩家

            current_key = "black" if current_player == BLACK else "white"

            other_key = "white" if current_player == BLACK else "black"

            if players.get(current_key):

                # 已有玩家分配该颜色，检查是否为当前用户

                if players[current_key] != member_openid:

                    color_name = "黑方" if current_player == BLACK else "白方"

                    await send_text(api, _scene(scene), group_openid, "当前轮到%s落子" % color_name, msg_id=msg_id

                    )

                    return

            else:

                # 该颜色尚未分配，分配给当前用户（但不能与另一方相同）

                if players.get(other_key) == member_openid:

                    await send_text(api, _scene(scene), group_openid, "你已选择另一方，不能代对方落子", msg_id=msg_id

                    )

                    return

                players[current_key] = member_openid

                game["players"] = players
                self._xq_save_name(member_openid, member_nick)



        # 执行落子

        board[row][col] = current_player

        color_name = "黑方" if current_player == BLACK else "白方"

        col_letter = COLUMNS[col]

        row_num = row + 1

        move_str = "%s%d" % (col_letter, row_num)



        # 检查胜负

        if self._check_win(board, row, col, current_player):

            game["status"] = "ended"

            save_json(GOMOKU_DATA_FILE, games)

            # 记录战绩（排行榜用）：current_player 即胜方颜色
            self._record_gomoku_result(group_openid, game, current_player)

            msg = "%s落子 %s\n%s 获胜！" % (color_name, move_str, color_name)

            await self._send_board(api, group_openid, board, msg, msg_id=msg_id, last_move=(row, col), scene=scene)

            await self._gomoku_end_keyboard(api, group_openid, msg_id, scene=scene)

            return



        # 切换玩家

        game["current_player"] = WHITE if current_player == BLACK else BLACK

        next_color = "白方" if game["current_player"] == WHITE else "黑方"



        # AI回合自动落子

        if mode == "ai" and game["current_player"] == WHITE:

            save_json(GOMOKU_DATA_FILE, games)

            msg = "%s落子 %s，AI思考中..." % (color_name, move_str)

            await self._send_board(api, group_openid, board, msg, msg_id=msg_id, last_move=(row, col), scene=scene)

            # AI落子

            ai_row, ai_col = self._ai_move(board)

            board[ai_row][ai_col] = WHITE

            ai_move_str = "%s%d" % (COLUMNS[ai_col], ai_row + 1)



            # 检查AI是否获胜

            if self._check_win(board, ai_row, ai_col, WHITE):

                game["status"] = "ended"

                save_json(GOMOKU_DATA_FILE, games)

                # 记录战绩（排行榜用）：AI 胜
                self._record_gomoku_result(group_openid, game, "ai")

                msg = "AI落子 %s\nAI获胜！" % ai_move_str

                await self._send_board(api, group_openid, board, msg, msg_id=msg_id, last_move=(ai_row, ai_col), scene=scene)

                await self._gomoku_end_keyboard(api, group_openid, msg_id, scene=scene)

                return



            # 切回玩家

            game["current_player"] = BLACK

            save_json(GOMOKU_DATA_FILE, games)

            msg = "AI落子 %s，轮到你落子" % ai_move_str

            await self._send_board(api, group_openid, board, msg, msg_id=msg_id, last_move=(ai_row, ai_col), scene=scene)

            return



        # PVP模式：通知下一玩家

        save_json(GOMOKU_DATA_FILE, games)

        msg = "%s落子 %s，轮到%s" % (color_name, move_str, next_color)

        await self._send_board(api, group_openid, board, msg, msg_id=msg_id, last_move=(row, col), scene=scene)



    async def _gomoku_surrender(self, api, group_openid, member_openid, msg_id, scene=None, member_nick=None):

        """认输/结束棋局"""

        games = load_json(GOMOKU_DATA_FILE)

        if group_openid not in games or games[group_openid].get("status") != "playing":

            await send_text(api, _scene(scene), group_openid, "当前没有进行中的棋局", msg_id=msg_id)

            return



        game = games[group_openid]

        players = game.get("players", {})

        mode = game.get("mode", "ai")



        # 判断认输方

        if mode == "ai":

            if players.get("black") == member_openid:

                loser = "玩家"

                winner = "AI"

            else:

                loser = "玩家"

                winner = "AI"

        else:

            if players.get("black") == member_openid:

                loser = "黑方"

                winner = "白方"

            elif players.get("white") == member_openid:

                loser = "白方"

                winner = "黑方"

            else:

                loser = "玩家"

                winner = "对手"



        game["status"] = "ended"

        save_json(GOMOKU_DATA_FILE, games)

        # 记录战绩（排行榜用）
        if mode == "ai":
            self._record_gomoku_result(group_openid, game, "ai")
        else:
            if winner in ("黑方", "白方"):
                self._record_gomoku_result(group_openid, game, "black" if winner == "黑方" else "white")

        await send_text(api, _scene(scene), group_openid, "%s认输，%s获胜！棋局结束。" % (loser, winner), msg_id=msg_id)

        await self._gomoku_end_keyboard(api, group_openid, msg_id, scene=scene)



    # ================================================================

    #                       看图猜成语模块

    # ================================================================



    async def _fetch_idiom_question(self) -> dict:

        """

        从雾笙云「看图猜成语」API 实时获取一道题目。

        接口：GET https://wsapi.top/API/game_ktccy.php

        参数：msg=开始游戏（始终发这个）；id=每次新随机串；key=密钥（可选）。

        响应：{"code":200,"data":{"msg":"...","pic":"http://wsapi.top/API/data/ktccy/img/<n>.jpg","answer":"<成语>"}}

        注：原 API 为多轮游戏状态机（msg=开始游戏/我猜<成语>/提示），本 bot 仅用「开始游戏」+ 新 id

        拿单题。判分仍走本地比对 idiom_games["current_idiom"]，以最小改动接入新数据源。

        返回 {"idiom": 答案, "image_url": 图片URL, "hint": ""}，失败返回 None。

        """

        import aiohttp

        import json as _json

        import urllib.parse

        # 每次新随机 id，避免和历史会话状态串台（即使服务端不记忆也防止万一）

        session_id = "bot_%d_%s" % (int(time.time()), os.urandom(3).hex())

        try:

            params = [("msg", "开始游戏"), ("id", session_id), ("key", IDIOM_API_KEY)]

            qs = urllib.parse.urlencode(params)

            url = IDIOM_API_URL + "?" + qs

            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:

                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:

                    if resp.status != 200:

                        logger.error("猜成语API请求失败: status=%s, url=%s" % (resp.status, url))

                        return None

                    text = await resp.text()

                    try:

                        data = _json.loads(text)

                    except Exception:

                        logger.error("猜成语API返回非JSON: %s" % text[:200])

                        return None

                    if data.get("code") != 200:

                        logger.error("猜成语API返回错误: %s" % data)

                        return None

                    payload = data.get("data") or {}

                    answer = str(payload.get("answer", "")).strip()

                    pic = str(payload.get("pic", "")).strip()

                    if not answer or not pic:

                        logger.error("猜成语API返回字段缺失: %s" % data)

                        return None

                    return {"idiom": answer, "image_url": pic, "hint": ""}

        except Exception as e:

            logger.error("猜成语API异常: %s" % e)

            return None



    async def _download_image_bytes(self, url: str) -> bytes:

        """下载/读取图片为bytes：支持 http(s) URL 与 本地路径，失败返回None"""

        # 本地路径：支持 file:// 与 裸 相对/绝对路径

        if not url:

            return None

        if url.startswith("file://"):

            local_path = url[len("file://"):]

        elif url.startswith("http://") or url.startswith("https://"):

            local_path = None

        else:

            # 裸路径（相对 data/、绝对路径都可）

            local_path = url



        # 本地读取

        if local_path is not None:

            try:

                if not os.path.isabs(local_path):

                    local_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", local_path)

                if os.path.exists(local_path):

                    with open(local_path, "rb") as f:

                        return f.read()

                logger.error("本地图片不存在: %s" % local_path)

                return None

            except Exception as e:

                logger.error("读取本地图片异常: %s, url=%s" % (e, url))

                return None



        # 远程 URL 下载

        import aiohttp

        try:

            async with aiohttp.ClientSession() as session:

                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:

                    if resp.status == 200:

                        return await resp.read()

                    logger.error("下载图片失败: status=%s, url=%s" % (resp.status, url))

                    return None

        except Exception as e:

            logger.error("下载图片异常: %s, url=%s" % (e, url))

            return None



    async def _idiom_send_question(self, api, group_openid, idiom_item, round_num, msg_id, scene=None):

        """

        发送一道猜成语题目（图片 + 操作按钮）

        """

        image_url = idiom_item.get("image_url", "")

        hint = idiom_item.get("hint", "")

        correct_idiom = idiom_item.get("idiom", "")



        # 构建按钮：作答 + 提示 + 跳过 + 结束

        # 注意：QQ 内联键盘最多 5 行，超出会报 40034029 “内联键盘行/列超限”

        # 玩家输入“作答XXX”由“作答”按钮点击后填入输入框补齐：例如“作答守株待兔”

        # 第1行：🔤 作答（type=2 指令按钮，enter=False）

        # 点击后输入框插入“作答”，玩家直接接上答案发送，如“作答画蛇添足”

        row1 = [

            {"label": "🔤 作答", "command": "作答", "enter": False, "id": "idiom_answer_btn"},

        ]

        # 第2行：提示 + 跳过（同一行 2 个按钮）

        row2 = [

            {"label": "💡 提示", "command": "成语提示", "enter": True, "id": "idiom_hint"},

            {"label": "⏭️ 跳过", "command": "跳过", "enter": True, "id": "idiom_skip"},

        ]

        # 第3行：结束（独占一行）

        row3 = [

            {"label": "🛑 结束游戏", "command": "结束", "enter": True, "id": "idiom_end"},

        ]



        keyboard = {"content": {"rows": [

            {"buttons": [self._make_option_btn(b) for b in row1]},

            {"buttons": [self._make_option_btn(b) for b in row2]},

            {"buttons": [self._make_option_btn(b) for b in row3]},

        ]}}



        # 尝试下载图片并本地上传（图片无法携带按钮，分两条消息发）

        image_sent = False

        if image_url:

            img_bytes = await self._download_image_bytes(image_url)

            if img_bytes:

                # 只发图片作为题目（【第%d轮】看图猜成语），玩家需看图猜成语

                result = await send_local_image_for_scene(api, _scene(scene), group_openid, img_bytes, content="【第%d轮】看图猜成语" % round_num, msg_id=msg_id

                )

                if result is not None:

                    image_sent = True



        # 图片发送失败，使用文字提示

        if not image_sent:

            if hint:

                await send_text(api, _scene(scene), group_openid,

                    "【第%d轮】看图猜成语（文字提示）：\n%s" % (round_num, hint),

                    msg_id=msg_id,

                )

            else:

                await send_text(api, _scene(scene), group_openid, "【第%d轮】看图猜成语" % round_num, msg_id=msg_id

                )



        # 发送选项按钮

        await send_text_with_keyboard(api, _scene(scene), group_openid, "请选择你的答案👇", keyboard, msg_id=msg_id

        )



    def _make_option_btn(self, cfg):

        """构建选项按钮"""

        return {

            "id": cfg.get("id", "idiom_opt"),

            "render_data": {

                "label": cfg["label"],

                "visited_label": cfg.get("visited_label", cfg["label"]),

                "style": cfg.get("style", 1),

            },

            "action": {

                "type": 2,

                "permission": {"type": 2},

                "data": cfg["command"],

                "enter": cfg.get("enter", True),

                "unsupport_tips": "请更新QQ版本",

            },

        }



    def _make_callback_btn(self, cfg):

        """

        构建回调按钮（type=1）。点击后会触发 on_interaction_create 事件，

        由 bot.py 路由到对应模块的 handle_callback 方法。



        用于【自由答题】按钮：点击后不发送、不填入输入框，而是进入

        “下一条文本被当作答题”模式，避免 enter=False 填入占位符在不同

        QQ 客户端表现不一致的问题。

        """

        return {

            "id": cfg.get("id", "idiom_cb"),

            "render_data": {

                "label": cfg["label"],

                "visited_label": cfg.get("visited_label", cfg["label"]),

                "style": cfg.get("style", 1),

            },

            "action": {

                "type": 1,

                "permission": {"type": 2},

                "data": cfg["command"],

                "unsupport_tips": "请更新QQ版本",

            },

        }



    def _idiom_compare(self, answer, guess):

        """

        逐字比对，生成提示

        正确的字显示原字，错误的字显示下划线

        例如：answer="守株待兔", guess="守株待机" → "守 株 待 _"

        """

        result = []

        for i in range(len(answer)):

            if i < len(guess) and guess[i] == answer[i]:

                result.append(answer[i])

            else:

                result.append("_")

        return " ".join(result)



    async def _idiom_start(self, api, group_openid, msg_id, scene=None):

        """开始看图猜成语游戏（共10轮，每轮从 ffapi.cn 实时拉取题目）"""

        first_item = await self._fetch_idiom_question()

        if not first_item:

            await send_text(api, _scene(scene), group_openid,

                            "⚠️ 看图猜成语接口暂时不可用，请稍后再试～", msg_id=msg_id)

            return



        total_rounds = 10



        games = load_json(IDIOM_GAME_DATA_FILE)

        games[group_openid] = {

            "current_round": 1,

            "total_rounds": total_rounds,

            "current_idiom": first_item["idiom"],

            "current_image_url": first_item["image_url"],

            "current_hint": first_item.get("hint", ""),

            "results": [],

            "status": "playing",

        }

        save_json(IDIOM_GAME_DATA_FILE, games)



        await send_text(api, _scene(scene), group_openid,

            "看图猜成语游戏开始！\n共%d轮，直接发送成语答案即可～\n\n【第1轮】"

            % total_rounds,

            msg_id=msg_id,

        )



        await self._idiom_send_question(

            api, group_openid, first_item, 1, msg_id, scene=scene

        )



    async def _idiom_next_round(self, api, group_openid, msg_id, scene=None):

        """进入下一轮或结束游戏"""

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid not in games:

            return

        game = games[group_openid]



        # 检查是否已结束

        if game["current_round"] >= game["total_rounds"]:

            game["status"] = "ended"

            save_json(IDIOM_GAME_DATA_FILE, games)

            await self._idiom_summary(api, group_openid, msg_id, scene=scene)

            return



        # 从 API 拉取下一题

        next_item = await self._fetch_idiom_question()

        if not next_item:

            await send_text(api, _scene(scene), group_openid,

                            "⚠️ 下一题获取失败，游戏结束。", msg_id=msg_id)

            game["status"] = "ended"

            save_json(IDIOM_GAME_DATA_FILE, games)

            await self._idiom_summary(api, group_openid, msg_id, scene=scene)

            return



        # 推进到下一轮

        game["current_round"] += 1

        game["current_idiom"] = next_item["idiom"]

        game["current_image_url"] = next_item["image_url"]

        game["current_hint"] = next_item.get("hint", "")

        save_json(IDIOM_GAME_DATA_FILE, games)



        await self._idiom_send_question(

            api, group_openid, next_item, game["current_round"], msg_id, scene=scene

        )



    async def _idiom_correct(self, api, group_openid, msg_id, scene=None):

        """回答正确，记录结果并进入下一轮（最多 10 轮）"""

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid not in games:

            return

        game = games[group_openid]

        current_idiom = game["current_idiom"]

        current_round = game["current_round"]

        total_rounds = game["total_rounds"]



        game["results"].append({

            "round": current_round,

            "correct": True,

            "idiom": current_idiom,

        })

        save_json(IDIOM_GAME_DATA_FILE, games)



        # 检查是否最后一轮

        if current_round >= total_rounds:

            await send_text(api, _scene(scene), group_openid,

                "✅ 回答正确！%s\n\n🎉 已完成全部 %d 轮，游戏结束！" % (current_idiom, total_rounds),

                msg_id=msg_id,

            )

            await self._idiom_summary(api, group_openid, msg_id, scene=scene)

            return



        # 提示当前轮次 + 即将进入下一轮

        await send_text(api, _scene(scene), group_openid,

            "✅ 回答正确！%s\n\n➡️ 进入第 %d/%d 题..." % (current_idiom, current_round + 1, total_rounds),

            msg_id=msg_id,

        )

        await self._idiom_next_round(api, group_openid, msg_id, scene=scene)



    async def _idiom_wrong(self, api, group_openid, guess, msg_id, scene=None):

        """回答错误，提示再试（按钮模式下直接点其他选项即可）"""

        await send_text(api, _scene(scene), group_openid,

            "❌ 答错了，再试试其他选项吧～",

            msg_id=msg_id,

        )



    async def _idiom_skip(self, api, group_openid, msg_id, scene=None):

        """跳过当前题目"""

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid not in games:

            return

        game = games[group_openid]

        current_idiom = game["current_idiom"]



        game["results"].append({

            "round": game["current_round"],

            "correct": False,

            "idiom": current_idiom,

        })

        save_json(IDIOM_GAME_DATA_FILE, games)



        # 检查是否最后一轮

        if game["current_round"] >= game["total_rounds"]:

            await send_text(api, _scene(scene), group_openid,

                "已跳过！正确答案：%s\n\n游戏结束！" % current_idiom,

                msg_id=msg_id,

            )

            await self._idiom_summary(api, group_openid, msg_id, scene=scene)

            return



        await send_text(api, _scene(scene), group_openid, "已跳过！正确答案：%s" % current_idiom, msg_id=msg_id

        )

        await self._idiom_next_round(api, group_openid, msg_id, scene=scene)



    async def _idiom_end(self, api, group_openid, msg_id, scene=None):

        """提前结束猜成语游戏"""

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid in games:

            games[group_openid]["status"] = "ended"

            save_json(IDIOM_GAME_DATA_FILE, games)

        await send_text(api, _scene(scene), group_openid, "猜成语游戏已结束！", msg_id=msg_id)

        await self._idiom_summary(api, group_openid, msg_id, scene=None)



    async def _idiom_force_end(self, api, group_openid, msg_id, scene=None, reason=""):

        """

        【静默结束】用于收到全局指令时：结束游戏但不发送“游戏结束”提示文字，

        避免在响应其他指令（如“菜单”）的多层气泡中间插入多一条游戏结束文案。

        战绩仍保存。

        """

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid in games and games[group_openid].get("status") == "playing":

            games[group_openid]["status"] = "ended"

            games[group_openid]["end_reason"] = reason or "global_command"

            save_json(IDIOM_GAME_DATA_FILE, games)



    # 猜成语游戏进行中，需要“透传”给其他模块响应的全局指令关键词

    # （与 bot.py 中 _KEYWORDS 同步：菜单 / 帮助 / 签到 / 学习 / 娱乐菜单…）

    _GLOBAL_COMMAND_KEYWORDS = frozenset([

        # 帮助/菜单导航

        "帮助", "功能", "菜单", "使用帮助",

        "签到菜单", "视频菜单", "音乐菜单", "娱乐菜单", "工具菜单",

        "群管菜单", "学习菜单", "返回主菜单", "主菜单",

        # 娱乐

        "五子棋", "五子棋AI", "AI对战", "五子棋双人", "二人对战", "五子棋排行",

        "象棋", "象棋AI", "象棋AI红", "象棋AI黑",

        "选择黑方", "选择白方",

        "认输", "结束棋局", "结束对局",

        # 工具

        "视频解析", "取消", "天气",

        # 群管

        "违禁词列表", "违禁词设置",

        # 学习

        "学习", "学习系统",

        "语文", "英语", "数学", "物理", "化学", "生物", "历史", "政治", "地理",

        # 个人信息

        "我的信息",

        # 体验群

        "加入体验群", "体验群", "加群", "加群二维码",

    ])



    def _is_global_command(self, text: str) -> bool:

        """判断文本是否是其他模块的全局指令（猜成语进行中需要“隔离”的指令集）"""

        if not text:

            return False

        return text in self._GLOBAL_COMMAND_KEYWORDS



    async def _idiom_summary(self, api, group_openid, msg_id, scene=None):

        """显示猜成语结果汇总"""

        games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid not in games:

            return

        game = games[group_openid]

        results = game.get("results", [])

        if not results:

            return



        lines = ["猜成语结果"]

        correct_count = 0

        for r in results:

            status = "回答正确" if r["correct"] else "回答错误"

            if r["correct"]:

                correct_count += 1

            lines.append("第%d轮 %s %s" % (r["round"], status, r["idiom"]))

        lines.append("")

        lines.append("总计：%d/%d 正确" % (correct_count, len(results)))



        await send_text(api, _scene(scene), group_openid, "\n".join(lines), msg_id=msg_id)



    #                       中国象棋模块

    # ================================================================



    # ---------- 棋盘与规则基础 ----------



    def _xq_initial_board(self):

        """生成中国象棋初始棋盘（10 行 × 9 列）。



        行 0 = 黑方底线（上方），行 9 = 红方底线（下方）；红方先行。

        棋子用字符串表示：首字符 r/b（红/黑），次字符为兵种 K/A/B/N/R/C/P。

        """

        empty = [[None] * 9 for _ in range(10)]

        back = ["R", "N", "B", "A", "K", "A", "B", "N", "R"]

        # 黑方（行 0、2、3）

        for c in range(9):

            empty[0][c] = "b" + back[c]

        empty[2][1] = "bC"

        empty[2][7] = "bC"

        for c in range(0, 9, 2):

            empty[3][c] = "bP"

        # 红方（行 6、7、9）

        for c in range(0, 9, 2):

            empty[6][c] = "rP"

        empty[7][1] = "rC"

        empty[7][7] = "rC"

        for c in range(9):

            empty[9][c] = "r" + back[c]

        return empty



    def _xq_in_board(self, r, c):

        return 0 <= r < 10 and 0 <= c < 9



    def _xq_in_palace(self, r, c, color):

        if not (3 <= c <= 5):

            return False

        return (7 <= r <= 9) if color == "r" else (0 <= r <= 2)



    def _xq_find_king(self, board, color):

        color = color[0]

        k = color + "K"

        for r in range(10):

            for c in range(9):

                if board[r][c] == k:

                    return (r, c)

        return None



    def _xq_is_attacked(self, board, sq_r, sq_c, by_color):

        """判断 by_color 的一方是否攻击到 (sq_r, sq_c)。"""

        by_color = by_color[0]

        for r in range(10):

            for c in range(9):

                p = board[r][c]

                if p and p[0] == by_color:

                    for (tr, tc) in self._xq_pseudo_moves(board, r, c):

                        if tr == sq_r and tc == sq_c:

                            return True

        return False



    def _xq_king_in_check(self, board, color):

        """判断 color 一方的将/帅是否处于被将军状态（含飞将）。"""

        color = color[0]

        king = self._xq_find_king(board, color)

        if king is None:

            return False

        kr, kc = king

        opp = "b" if color == "r" else "r"

        if self._xq_is_attacked(board, kr, kc, opp):

            return True

        # 飞将：两将同列且中间无子

        ek = self._xq_find_king(board, opp)

        if ek and ek[1] == kc:

            step = 1 if ek[0] > kr else -1

            rr = kr + step

            while rr != ek[0]:

                if board[rr][kc] is not None:

                    break

                rr += step

            else:

                return True

        return False



    def _xq_pseudo_moves(self, board, r, c):

        """生成 (r,c) 处棋子的伪合法走法（忽略是否送将）。"""

        piece = board[r][c]

        if not piece:

            return []

        color = piece[0]

        t = piece[1]

        moves = []



        def add(tr, tc):

            if self._xq_in_board(tr, tc):

                tp = board[tr][tc]

                if tp is None or tp[0] != color:

                    moves.append((tr, tc))



        if t == "R":  # 车：直线任意格，遇子停

            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):

                nr, nc = r + dr, c + dc

                while self._xq_in_board(nr, nc):

                    tp = board[nr][nc]

                    if tp is None:

                        moves.append((nr, nc))

                    else:

                        if tp[0] != color:

                            moves.append((nr, nc))

                        break

                    nr += dr

                    nc += dc

        elif t == "C":  # 炮：移动无阻碍；吃子需隔一子（炮架）

            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):

                nr, nc = r + dr, c + dc

                jumped = False

                while self._xq_in_board(nr, nc):

                    tp = board[nr][nc]

                    if not jumped:

                        if tp is None:

                            moves.append((nr, nc))

                        else:

                            jumped = True

                    else:

                        if tp is not None:

                            if tp[0] != color:

                                moves.append((nr, nc))

                            break

                    nr += dr

                    nc += dc

        elif t == "N":  # 马：日字，蹩马腿

            cand = [

                (2, 1, 1, 0), (2, -1, 1, 0), (-2, 1, -1, 0), (-2, -1, -1, 0),

                (1, 2, 0, 1), (1, -2, 0, -1), (-1, 2, 0, 1), (-1, -2, 0, -1),

            ]

            for dr, dc, lr, lc in cand:

                leg_r, leg_c = r + lr, c + lc

                if self._xq_in_board(leg_r, leg_c) and board[leg_r][leg_c] is None:

                    add(r + dr, c + dc)

        elif t == "B":  # 象：田字，不过河，塞象眼

            for dr, dc in ((2, 2), (2, -2), (-2, 2), (-2, -2)):

                tr, tc = r + dr, c + dc

                if self._xq_in_board(tr, tc):

                    if color == "r" and tr <= 4:

                        continue

                    if color == "b" and tr >= 5:

                        continue

                    er, ec = r + dr // 2, c + dc // 2

                    if board[er][ec] is None:

                        add(tr, tc)

        elif t == "A":  # 士：宫内斜走一格

            for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):

                tr, tc = r + dr, c + dc

                if self._xq_in_palace(tr, tc, color):

                    add(tr, tc)

        elif t == "K":  # 将/帅：宫内直走一格

            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):

                tr, tc = r + dr, c + dc

                if self._xq_in_palace(tr, tc, color):

                    add(tr, tc)

        elif t == "P":  # 兵/卒：向前一格，过河后可横走

            d = -1 if color == "r" else 1

            add(r + d, c)

            crossed = (r <= 4) if color == "r" else (r >= 5)

            if crossed:

                add(r, c - 1)

                add(r, c + 1)

        return moves



    def _xq_is_legal(self, board, r, c, tr, tc, color):

        nb = [row[:] for row in board]

        nb[tr][tc] = nb[r][c]

        nb[r][c] = None

        return not self._xq_king_in_check(nb, color)



    def _xq_all_legal_moves(self, board, color):

        color = color[0]

        res = []

        for r in range(10):

            for c in range(9):

                p = board[r][c]

                if p and p[0] == color:

                    for (tr, tc) in self._xq_pseudo_moves(board, r, c):

                        if self._xq_is_legal(board, r, c, tr, tc, color):

                            res.append((r, c, tr, tc))

        return res



    def _xq_has_legal_move(self, board, color):

        color = color[0]

        for r in range(10):

            for c in range(9):

                p = board[r][c]

                if p and p[0] == color:

                    for (tr, tc) in self._xq_pseudo_moves(board, r, c):

                        if self._xq_is_legal(board, r, c, tr, tc, color):

                            return True

        return False



    def _xq_evaluate(self, board, color):

        """从 color 视角的局面评估（子力差 + 轻微机动性）。"""

        color = color[0]

        opp = "b" if color == "r" else "r"

        score = 0

        for r in range(10):

            for c in range(9):

                p = board[r][c]

                if not p:

                    continue

                v = XQ_PIECE_VALUE.get(p[1], 0)

                score += v if p[0] == color else -v

        return score



    def _xq_ai_move(self, board, color):

        """为 color 选择一步棋：1 层搜索 + 子力评估 + 轻微随机扰动。"""

        color = color[0]

        legal = self._xq_all_legal_moves(board, color)

        if not legal:

            return None

        opp = "b" if color == "r" else "r"

        best = None

        best_score = -10 ** 9

        for (r, c, tr, tc) in legal:

            nb = [row[:] for row in board]

            nb[tr][tc] = nb[r][c]

            nb[r][c] = None

            s = self._xq_evaluate(nb, color)

            if self._xq_king_in_check(nb, opp):

                s += 80

            s += random.randint(0, 20)

            if s > best_score:

                best_score = s

                best = (r, c, tr, tc)

        return best



    # ---------- 坐标与渲染 ----------



    def _xq_parse_move(self, text):

        """解析走子指令，返回 (fr, fc, tr, tc) 或 None。



        坐标：列 a-i（左→右），行 1-10（红方在下方，rank1 = 红底线）。

        board_row = 10 - rank。支持「走 a1 b3」「a1 b3」「a1-b3」「a1→b3」。

        """

        t = text.strip()

        for pfx in ("走", "落子", "移动", "move"):

            if t.lower().startswith(pfx):

                t = t[len(pfx):].strip()

                break

        t = t.replace(" ", "")

        m = re.match(r"^([a-iA-I])(10|\d)[-~→]?([a-iA-I])(10|\d)$", t)

        if not m:

            return None

        try:

            fc = XQ_FILES.index(m.group(1).lower())

            fr = 10 - int(m.group(2))

            tc = XQ_FILES.index(m.group(3).lower())

            tr = 10 - int(m.group(4))

        except Exception:

            return None

        if not (self._xq_in_board(fr, fc) and self._xq_in_board(tr, tc)):

            return None

        return (fr, fc, tr, tc)



    def _xq_board_to_text(self, board, view_color="red"):
        black = (view_color == "black")
        if black:
            board = [row[::-1] for row in board[::-1]]
            top = "  " + " ".join(XQ_FILES[8 - C] for C in range(9))
        else:
            top = "  " + " ".join(XQ_FILES)
        lines = [top]

        for R in range(10):
            rank = (R + 1) if black else (10 - R)
            row = str(rank).rjust(2) + " "
            for c in range(9):
                p = board[R][c]
                row += (XQ_PIECE_CHAR.get(p, "·") if p else "·") + " "

            lines.append(row)

        return "\n".join(lines)



    def _xq_board_to_image(self, board, last_move=None, view_color="red"):

        """把象棋棋盘渲染成清晰的 PNG（超采样抗锯齿 + 传统棋盘样式）。"""

        from PIL import Image, ImageDraw, ImageFont

        import io

        black = (view_color == "black")
        if black:
            board = [row[::-1] for row in board[::-1]]
            if last_move and len(last_move) == 4:
                r0, c0, r1, c1 = last_move
                last_move = [9 - r0, 8 - c0, 9 - r1, 8 - c1]

        s = 2                       # 超采样倍数，提升清晰度

        cell = 50                   # 逻辑单元格尺寸

        mx, mtop, mbot = 55, 60, 60

        W = 8 * cell + mx * 2

        H = 9 * cell + mtop + mbot

        Wp, Hp = W * s, H * s

        cellp = cell * s

        mxp, mtopp = mx * s, mtop * s

        board_w, board_h = 8 * cellp, 9 * cellp

        x0, y0 = mxp, mtopp



        img = Image.new("RGB", (Wp, Hp), (244, 214, 156))

        draw = ImageDraw.Draw(img)



        # 字体（优先粗体，棋子更醒目；坐标标签单独加大）

        font = None

        label_font = None

        for fp in ("C:/Windows/Fonts/simhei.ttf",

                   "C:/Windows/Fonts/msyhbd.ttc",

                   "C:/Windows/Fonts/arialbd.ttf",

                   "C:/Windows/Fonts/msyh.ttc",

                   "C:/Windows/Fonts/arial.ttf"):

            try:

                font = ImageFont.truetype(fp, int(30 * s))

                medium = ImageFont.truetype(fp, int(18 * s))

                label_font = ImageFont.truetype(fp, int(22 * s))

                break

            except Exception:

                continue

        if font is None:

            font = ImageFont.load_default()

            medium = font

            label_font = font



        line = (78, 52, 24)

        lw = max(1, s)



        def _x(c):

            return x0 + c * cellp



        def _y(r):

            return y0 + r * cellp



        def _t(cx, cy, text, font, fill):

            """在 (cx, cy) 处居中绘制文字（兼容所有 PIL 版本，不依赖 anchor）。"""

            bbox = draw.textbbox((0, 0), text, font=font)

            w = bbox[2] - bbox[0]

            h = bbox[3] - bbox[1]

            draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), text,

                      font=font, fill=fill)



        # 横线

        for r in range(10):

            yy = _y(r)

            draw.line([(x0, yy), (x0 + board_w, yy)], fill=line, width=lw)

        # 竖线（楚河汉界处断开）

        for c in range(9):

            xx = _x(c)

            draw.line([(xx, y0), (xx, y0 + 4 * cellp)], fill=line, width=lw)

            draw.line([(xx, y0 + 5 * cellp), (xx, y0 + board_h)], fill=line, width=lw)

        # 九宫斜线

        draw.line([(_x(3), _y(0)), (_x(5), _y(2))], fill=line, width=lw)

        draw.line([(_x(5), _y(0)), (_x(3), _y(2))], fill=line, width=lw)

        draw.line([(_x(3), _y(7)), (_x(5), _y(9))], fill=line, width=lw)

        draw.line([(_x(5), _y(7)), (_x(3), _y(9))], fill=line, width=lw)



        # 兵 / 炮 位标记（传统米字标）

        def _mark(cx, cy, L):

            h = L // 2

            draw.line([(cx - h, cy), (cx + h, cy)], fill=line, width=lw)

            draw.line([(cx, cy - h), (cx, cy + h)], fill=line, width=lw)

            draw.line([(cx - h, cy - h), (cx + h, cy + h)], fill=line, width=lw)

            draw.line([(cx - h, cy + h), (cx + h, cy - h)], fill=line, width=lw)



        L = int(9 * s)

        for r in (2, 7):                       # 炮位

            for c in (1, 7):

                _mark(_x(c), _y(r), L)

        for r in (3, 6):                       # 兵 / 卒位

            for c in (0, 2, 4, 6, 8):

                _mark(_x(c), _y(r), L)



        # 楚河汉界

        _t(_x(2), _y(4) + cellp * 0.5, "楚 河", medium, line)

        _t(_x(6), _y(4) + cellp * 0.5, "漢 界", medium, line)



        # 最后一步高亮（起点淡红圈 + 终点红框）

        if last_move and len(last_move) == 4:

            r0, c0, r1, c1 = last_move

            rad = int(cellp * 0.42)

            x0m, y0m = _x(c0), _y(r0)

            x1m, y1m = _x(c1), _y(r1)

            draw.ellipse([x0m - rad * 0.55, y0m - rad * 0.55,

                          x0m + rad * 0.55, y0m + rad * 0.55],

                         outline=(220, 70, 70), width=max(2, 2 * s))

            draw.rectangle([x1m - rad, y1m - rad, x1m + rad, y1m + rad],

                           outline=(210, 40, 40), width=max(3, 3 * s))



        # 棋子（双层圆 + 居中文字）

        for r in range(10):

            for c in range(9):

                p = board[r][c]

                if not p:

                    continue

                x, y = _x(c), _y(r)

                rad = int(cellp * 0.42)

                edge = (198, 46, 46) if p[0] == "r" else (48, 48, 48)

                draw.ellipse([x - rad, y - rad, x + rad, y + rad],

                             fill=(253, 249, 240), outline=edge, width=max(2, 2 * s))

                draw.ellipse([x - int(rad * 0.82), y - int(rad * 0.82),

                              x + int(rad * 0.82), y + int(rad * 0.82)],

                             outline=edge, width=max(1, 1 * s))

                ch = XQ_PIECE_CHAR.get(p, "?")

                _t(x, y, ch, font, edge)



        # 坐标标注（上下列标、左右行号）

        # 放在棋子之后绘制，并增大边距，避免被棋子覆盖

        lab_off = 42 * s

        for c in range(9):

            _t(_x(c), y0 - lab_off, XQ_FILES[8 - c] if black else XQ_FILES[c], label_font, line)

            _t(_x(c), y0 + board_w + lab_off, XQ_FILES[8 - c] if black else XQ_FILES[c], label_font, line)

        for r in range(10):

            label = str(r + 1) if black else str(10 - r)

            _t(x0 - lab_off, _y(r), label, label_font, line)

            _t(x0 + board_w + lab_off, _y(r), label, label_font, line)



        # 缩回逻辑尺寸，获得抗锯齿清晰图

        img = img.resize((W, H), Image.LANCZOS)

        buf = io.BytesIO()

        img.save(buf, format="PNG")

        return buf.getvalue()



    def _xq_resolve_name(self, openid):

        if not openid or openid == "AI":

            return "AI"

        try:

            names = load_json(XIANGQI_NAMES_FILE)

            users = names.get("users", {}) if isinstance(names, dict) else {}

            if openid in users and users[openid]:

                return users[openid]

        except Exception:

            pass

        return openid[-6:]


    def _xq_save_name(self, openid, nick):
        """持久化 openid → nick 映射（用于排行榜和胜方显示）。
        单聊/缺 username 时，参考消息监控用 OIAPI Openid 反查昵称兜底。
        """

        openid = (openid or "").strip()
        if not openid or openid == "AI":
            return
        nick = (nick or "").strip()
        if not nick:
            # 单聊场景 event.author.username 可能为空，参考消息监控用 OIAPI Openid 反查昵称
            try:
                from console_server import _fetch_nickname_via_oiapi_openid
                nick = _fetch_nickname_via_oiapi_openid(openid) or ""
            except Exception:
                nick = ""
        nick = (nick or "").strip()
        if not nick or nick == "AI":
            return

        try:

            names = load_json(XIANGQI_NAMES_FILE) or {}

            users = names.setdefault("users", {})

            if users.get(openid) != nick:

                users[openid] = nick

                save_json(XIANGQI_NAMES_FILE, names)

        except Exception:

            pass


    def _xq_name_of(self, group_openid, g, color):

        return self._xq_resolve_name(g["players"].get(color))



    # ---------- 会话与流程 ----------



    async def _xq_send_board(self, api, group_openid, g, msg_id=None, start=False, scene=None):

        board = g["board"]
        view = g["human_color"] if g["mode"] == "ai" else g["turn"]
        img = self._xq_board_to_image(board, g.get("last_move"), view_color=view)

        turn = g["turn"]

        turn_name = XQ_COLOR_NAME[turn]

        if g["mode"] == "ai":

            turn_name += "（你）" if turn == g["human_color"] else "（AI）"

        else:

            turn_name += "（%s）" % self._xq_name_of(group_openid, g, turn)

        mode_txt = "人机对战" if g["mode"] == "ai" else "二人对战"

        content = ("♟ 中国象棋 · %s\n➡️ 轮到：%s\n"

                   "走子格式：走 a1 b3（列a-i，行1-10，%s在下）" % (mode_txt, turn_name, XQ_COLOR_NAME[view]))

        if start:

            content = "🎉 象棋开局！\n" + content

        try:

            await send_local_image_for_scene(api, _scene(scene), group_openid, img, content=content, msg_id=msg_id)

        except Exception as e:

            logger.error("象棋棋盘图发送失败，降级文本: %s" % e)

            await send_text(api, _scene(scene), group_openid, content + "\n\n" + self._xq_board_to_text(board, view_color=view), msg_id=msg_id)

        kb = build_keyboard_multi([

            {"label": "🛑 结束对局", "command": "结束象棋", "id": "xq_end"},

            {"label": "🏆 排行榜", "command": "象棋排行", "id": "xq_rank"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "操作：结束对局 / 查看排行榜", kb, msg_id=None)



    def _record_xq_result(self, group_openid, g, winner):

        stats = load_json(XIANGQI_STATS_FILE)

        group_stats = stats.setdefault(group_openid, {})

        if g["mode"] == "ai":

            hc = g["human_color"]

            ho = g["players"][hc]

            if ho and ho != "AI":

                rec = group_stats.setdefault(ho, {"wins": 0, "losses": 0})

                if winner == hc:

                    rec["wins"] += 1

                else:

                    rec["losses"] += 1

        else:

            for color in ("red", "black"):

                oid = g["players"][color]

                if oid and oid != "AI":

                    rec = group_stats.setdefault(oid, {"wins": 0, "losses": 0})

                    if color == winner:

                        rec["wins"] += 1

                    else:

                        rec["losses"] += 1

        save_json(XIANGQI_STATS_FILE, stats)


    def _record_gomoku_result(self, group_openid, g, winner):
        """记录五子棋战绩（winner: 'black' / 'white' / 'ai'）。

        与象棋共用 console_names.json 昵称映射（_xq_save_name / _xq_resolve_name）。
        """
        stats = load_json(GOMOKU_STATS_FILE)
        group_stats = stats.setdefault(group_openid, {})
        players = g.get("players", {})
        mode = g.get("mode", "ai")

        def _add(oid, is_win):
            if not oid or oid == "ai":
                return
            rec = group_stats.setdefault(oid, {"wins": 0, "losses": 0})
            if is_win:
                rec["wins"] += 1
            else:
                rec["losses"] += 1

        if mode == "ai":
            # AI 模式只有人类(黑方)有真实 openid；AI 胜则 human 负，human 胜则记一胜
            human = players.get("black")
            _add(human, winner != "ai")
        else:
            for color in ("black", "white"):
                oid = players.get(color)
                _add(oid, winner == color)

        save_json(GOMOKU_STATS_FILE, stats)


    async def _xq_finish(self, api, group_openid, g, winner, reason, msg_id=None, scene=None):

        self._record_xq_result(group_openid, g, winner)

        board = g["board"]
        view = g["human_color"] if g["mode"] == "ai" else g.get("turn")
        try:
            img = self._xq_board_to_image(board, g.get("last_move"), view_color=view)

            await send_local_image_for_scene(api, _scene(scene), group_openid, img, content="🏁 对局结束：" + reason, msg_id=msg_id)

        except Exception:

            await send_text(api, _scene(scene), group_openid, "🏁 对局结束：" + reason + "\n\n" + self._xq_board_to_text(board, view_color=view), msg_id=msg_id)

        winner_name = self._xq_name_of(group_openid, g, winner)

        kb = build_keyboard_multi([

            {"label": "🎲 再来一局", "command": "象棋", "id": "xq_again"},

            {"label": "🏆 排行榜", "command": "象棋排行", "id": "xq_rank2"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "🏆 胜方：%s\n👉 点击下方按钮再来一局或查看排行榜" % winner_name, kb, msg_id=None)



    async def _xiangqi_show_modes(self, api, group_openid, msg_id, scene=None):

        kb = build_keyboard_multi([

            {"label": "🤖 人机对战", "command": "象棋AI", "id": "xq_ai"},

            {"label": "👥 二人对战", "command": "象棋双人", "id": "xq_pvp"},

            {"label": "🏆 排行榜", "command": "象棋排行", "id": "xq_rank3"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "♟ 中国象棋\n请选择对战模式：", kb, msg_id=msg_id)



    async def _xiangqi_ai_menu(self, api, group_openid, msg_id, scene=None):

        kb = build_keyboard_multi([

            {"label": "🔴 我执红（先手）", "command": "象棋AI红", "id": "xq_air"},

            {"label": "⚫ 我执黑（后手）", "command": "象棋AI黑", "id": "xq_aib"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "🤖 人机对战\n请选择你要执的棋子颜色：", kb, msg_id=msg_id)



    async def _xiangqi_start_ai(self, api, group_openid, member_openid, msg_id, human_color, scene=None, member_nick=None):

        board = self._xq_initial_board()

        ai_color = "black" if human_color == "red" else "red"

        g = {

            "status": "playing", "mode": "ai", "board": board, "turn": "red",

            "human_color": human_color, "ai_color": ai_color,

            "players": {human_color: member_openid, ai_color: "AI"},

            "last_move": None, "move_count": 0,

        }

        games = load_json(XIANGQI_DATA_FILE)

        self._xq_save_name(member_openid, member_nick)

        games[group_openid] = g

        save_json(XIANGQI_DATA_FILE, games)

        # AI 执红（人执黑）时 AI 先走

        if ai_color == "red":

            nb = [row[:] for row in board]

            mv = self._xq_ai_move(nb, "red")

            if mv:

                r0, c0, r1, c1 = mv

                nb[r1][c1] = nb[r0][c0]

                nb[r0][c0] = None

                g["board"] = nb

                g["last_move"] = [r0, c0, r1, c1]

                g["move_count"] = 1

                g["turn"] = "black"

                games[group_openid] = g

                save_json(XIANGQI_DATA_FILE, games)

        await self._xq_send_board(api, group_openid, g, msg_id=msg_id, start=True, scene=scene)



    async def _xiangqi_pvp_menu(self, api, group_openid, msg_id, scene=None):

        kb = build_keyboard_multi([

            {"label": "🔴 执红先行", "command": "象棋双人红", "id": "xq_r"},

            {"label": "⚫ 执黑后行", "command": "象棋双人黑", "id": "xq_b"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "👥 二人对战模式\n请选择你要执的棋子颜色（红方先行）：", kb, msg_id=msg_id)



    async def _xiangqi_pvp_join(self, api, group_openid, member_openid, msg_id, color, scene=None, member_nick=None):

        games = load_json(XIANGQI_DATA_FILE)

        g = games.get(group_openid)

        if g and g.get("status") == "waiting":

            open_color = "red" if g["players"]["red"] is None else "black"

            g["players"][open_color] = member_openid

            self._xq_save_name(member_openid, member_nick)

            g["status"] = "playing"

            g["turn"] = "red"

            games[group_openid] = g

            save_json(XIANGQI_DATA_FILE, games)

            await self._xq_send_board(api, group_openid, g, msg_id=msg_id, start=True, scene=scene)

            return

        # 新建等待中的对局

        board = self._xq_initial_board()

        players = {"red": None, "black": None}

        players[color] = member_openid

        self._xq_save_name(member_openid, member_nick)

        g = {"status": "waiting", "mode": "pvp", "board": board, "turn": "red",

             "players": players, "last_move": None, "move_count": 0}

        games[group_openid] = g

        save_json(XIANGQI_DATA_FILE, games)

        await send_text(api, _scene(scene), group_openid,

                              "✅ 已就位（%s）。等待另一名玩家发送「象棋双人」加入对局…"

                              % ("红方" if color == "red" else "黑方"), msg_id=msg_id)



    async def _xiangqi_move(self, api, text, group_openid, member_openid, msg_id, scene=None):

        games = load_json(XIANGQI_DATA_FILE)

        g = games.get(group_openid)

        if not g or g.get("status") != "playing":

            return

        turn = g["turn"]

        mv = self._xq_parse_move(text)

        if not mv:

            await send_text(api, _scene(scene), group_openid,

                                  "❓ 走子格式：例如 “走 a1 b3” 或 “a1 b3”（列 a-i，行 1-10，坐标以棋盘标签为准）",

                                  msg_id=msg_id)

            return

        fr, fc, tr, tc = mv

        board = g["board"]

        if not (self._xq_in_board(fr, fc) and self._xq_in_board(tr, tc)):

            await send_text(api, _scene(scene), group_openid, "❓ 坐标超出棋盘范围", msg_id=msg_id)

            return

        piece = board[fr][fc]

        if piece is None or piece[0] != ("r" if turn == "red" else "b"):

            await send_text(api, _scene(scene), group_openid, "❓ 该位置没有你的棋子，或还没轮到你走", msg_id=msg_id)

            return

        # 走子权限校验

        if g["mode"] == "ai":

            if member_openid != g["players"][turn]:

                await send_text(api, _scene(scene), group_openid, "🤖 这是 AI 的回合，请等待 AI 走子", msg_id=msg_id)

                return

        else:

            if member_openid != g["players"][turn]:

                await send_text(api, _scene(scene), group_openid, "❓ 当前轮到对方走子", msg_id=msg_id)

                return

        # 合法性校验

        if (fr, fc, tr, tc) not in self._xq_all_legal_moves(board, turn):

            await send_text(api, _scene(scene), group_openid, "❌ 这步棋不符合规则，请换一步", msg_id=msg_id)

            return

        # 落子

        nb = [row[:] for row in board]

        nb[tr][tc] = nb[fr][fc]

        nb[fr][fc] = None

        g["board"] = nb

        g["last_move"] = [fr, fc, tr, tc]

        g["move_count"] = g.get("move_count", 0) + 1

        opp = "black" if turn == "red" else "red"

        # 对方是否被将死/困毙

        if not self._xq_has_legal_move(nb, opp):

            g["status"] = "ended"

            games[group_openid] = g

            save_json(XIANGQI_DATA_FILE, games)

            await self._xq_finish(api, group_openid, g, winner=turn, reason="将死 / 困毙", msg_id=msg_id, scene=scene)

            return

        g["turn"] = opp

        # 人机模式：AI 自动回手

        if g["mode"] == "ai" and opp == g["ai_color"]:

            ai_mv = self._xq_ai_move(nb, g["ai_color"])

            if ai_mv is None:

                g["status"] = "ended"

                games[group_openid] = g

                save_json(XIANGQI_DATA_FILE, games)

                await self._xq_finish(api, group_openid, g, winner=turn, reason="AI 无棋可走", msg_id=msg_id, scene=scene)

                return

            r0, c0, r1, c1 = ai_mv

            nb2 = [row[:] for row in nb]

            nb2[r1][c1] = nb2[r0][c0]

            nb2[r0][c0] = None

            g["board"] = nb2

            g["last_move"] = [r0, c0, r1, c1]

            g["move_count"] = g.get("move_count", 0) + 1

            # 注意：此时 g["turn"] 仍是 AI 颜色，需检测“人类(=turn)是否被将死”

            if not self._xq_has_legal_move(nb2, turn):

                g["status"] = "ended"

                games[group_openid] = g

                save_json(XIANGQI_DATA_FILE, games)

                await self._xq_finish(api, group_openid, g, winner=g["ai_color"], reason="将死 / 困毙", msg_id=msg_id, scene=scene)

                return

            g["turn"] = turn

        games[group_openid] = g

        save_json(XIANGQI_DATA_FILE, games)

        await self._xq_send_board(api, group_openid, g, msg_id=msg_id, scene=None)



    async def _xiangqi_surrender(self, api, group_openid, member_openid, msg_id, scene=None):

        games = load_json(XIANGQI_DATA_FILE)

        g = games.get(group_openid)

        if not g or g.get("status") != "playing":

            await send_text(api, _scene(scene), group_openid, "当前没有进行中的象棋对局", msg_id=msg_id)

            return

        if g["mode"] == "ai":

            if member_openid != g["players"][g["human_color"]]:

                await send_text(api, _scene(scene), group_openid, "只有对局参与者可以结束", msg_id=msg_id)

                return

            winner = g["ai_color"]

        else:

            if member_openid == g["players"]["red"]:

                loser, winner = "red", "black"

            elif member_openid == g["players"]["black"]:

                loser, winner = "black", "red"

            else:

                await send_text(api, _scene(scene), group_openid, "只有对局参与者可以结束", msg_id=msg_id)

                return

        g["status"] = "ended"

        games[group_openid] = g

        save_json(XIANGQI_DATA_FILE, games)

        await self._xq_finish(api, group_openid, g, winner=winner, reason="认输", msg_id=msg_id, scene=None)



    async def _xiangqi_ranking(self, api, group_openid, msg_id=None, scene=None):

        stats = load_json(XIANGQI_STATS_FILE)

        gs = stats.get(group_openid, {})

        if not gs:

            await send_text(api, _scene(scene), group_openid,

                                  "📊 本群还没有象棋战绩，快来下一局吧！发送「象棋」开始", msg_id=msg_id)

            return

        items = []

        for oid, rec in gs.items():

            w = rec.get("wins", 0)

            l = rec.get("losses", 0)

            tot = w + l

            rate = (w / tot * 100) if tot else 0

            items.append((w, rate, self._xq_resolve_name(oid), l))

        items.sort(key=lambda x: (x[0], x[1]), reverse=True)

        lines = ["🏆 象棋排行榜（按胜场）"]

        for i, (w, rate, name, l) in enumerate(items[:10], 1):

            lines.append("%d. %s — %d胜%d负（胜率%.0f%%）" % (i, name, w, l, rate))

        kb = build_keyboard_multi([

            {"label": "🎲 开始象棋", "command": "象棋", "id": "xq_start2"},

        ])

        await send_text_with_keyboard(api, _scene(scene), group_openid, "\n".join(lines), kb, msg_id=msg_id)


    async def _gomoku_ranking(self, api, group_openid, msg_id=None, scene=None):
        """五子棋排行榜（按胜场），显示真实昵称。"""
        stats = load_json(GOMOKU_STATS_FILE)
        gs = stats.get(group_openid, {})
        if not gs:
            await send_text(api, _scene(scene), group_openid,
                            "📊 本群还没有五子棋战绩，快来下一局吧！发送「五子棋」开始", msg_id=msg_id)
            return

        items = []
        for oid, rec in gs.items():
            w = rec.get("wins", 0)
            l = rec.get("losses", 0)
            tot = w + l
            rate = (w / tot * 100) if tot else 0
            items.append((w, rate, self._xq_resolve_name(oid), l))

        items.sort(key=lambda x: (x[0], x[1]), reverse=True)

        lines = ["🏆 五子棋排行榜（按胜场）"]
        for i, (w, rate, name, l) in enumerate(items[:10], 1):
            lines.append("%d. %s — %d胜%d负（胜率%.0f%%）" % (i, name, w, l, rate))

        kb = build_keyboard_multi([
            {"label": "🎲 开始五子棋", "command": "五子棋", "id": "gm_start2"},
        ])
        await send_text_with_keyboard(api, _scene(scene), group_openid, "\n".join(lines), kb, msg_id=msg_id)


    async def _gomoku_end_keyboard(self, api, group_openid, msg_id=None, scene=None):
        """五子棋对局结算后，发送「排行榜 / 再来一局」按钮。"""
        kb = build_keyboard_multi([
            {"label": "🏆 排行榜", "command": "五子棋排行", "id": "gm_rank"},
            {"label": "🎲 再来一局", "command": "五子棋", "id": "gm_again"},
        ])
        await send_text_with_keyboard(api, _scene(scene), group_openid, "操作：查看排行榜 / 再来一局", kb, msg_id=msg_id)


    # ================================================================

    #                       命令处理入口

    # ================================================================



    def has_active_session(self, group_openid: str) -> bool:

        """检查该群是否有进行中的五子棋、猜成语或象棋游戏"""

        gomoku_games = load_json(GOMOKU_DATA_FILE)

        if group_openid in gomoku_games and gomoku_games[group_openid].get("status") == "playing":

            return True

        idiom_games = load_json(IDIOM_GAME_DATA_FILE)

        if group_openid in idiom_games and idiom_games[group_openid].get("status") == "playing":

            return True

        xiangqi_games = load_json(XIANGQI_DATA_FILE)

        if group_openid in xiangqi_games and xiangqi_games[group_openid].get("status") == "playing":

            return True

        return False



    def has_idiom_session(self, group_openid: str) -> bool:

        """检查该群是否有进行中的猜成语游戏（用于优先路由）"""

        idiom_games = load_json(IDIOM_GAME_DATA_FILE)

        return group_openid in idiom_games and idiom_games[group_openid].get("status") == "playing"





    async def handle_callback(self, api, data, target_id, member_openid, scene=None,

                              msg_id=None, event_id=None):

        """

        处理回调按钮点击事件（type=1）。返回 True 表示已处理。

        bot.py 在 on_interaction_create 中调用此方法。



        - target_id: 裸 ID（与 handle_command 调用方约定一致）

        - member_openid: 点击按钮的用户 openid

        - scene: ChatScene.GROUP / C2C / CHANNEL

        """

        if data == "idiom_free_text":

            # 【自由答题】按钮：标记该群进入“下一条文本当作答案”模式

            # 由于猜成语进行中时，所有文本消息本来就会被判定为猜测答案，

            # 这里只需发送提示语告知玩家怎么用，不需额外状态机。

            await send_text(api, _scene(scene), target_id,

                "✏️ 已进入自由答题模式！\n请直接发送你要猜的成语（4个汉字）。\n"

                "下一条文本消息会被当作你的答案进行判断。",

                msg_id=msg_id,

            )

            return True

        return False



    # ================================================================

    #                         观音灵签模块

    # ================================================================



    async def _qiuqian_fetch(self):

        """

        向小小API观音灵签接口请求一签，返回 data dict，失败返回 None。

        """

        try:

            data = await http_get(GUANYIN_API_URL, params=None,

                                  headers=_GUANYIN_HEADERS, timeout=10)

        except Exception as e:

            logger.error("观音灵签接口请求异常: %s" % e)

            return None

        if not isinstance(data, dict) or data.get("code") != 200:

            code = data.get("code") if isinstance(data, dict) else "None"

            logger.warning("观音灵签接口返回异常: code=%s" % code)

            return None

        d = data.get("data")

        if not isinstance(d, dict):

            logger.warning("观音灵签接口未返回有效签文: %r" % d)

            return None

        return d



    def _qiuqian_format(self, d):

        """将签文 data 格式化为可读文本（QQ 群聊友好）。"""

        name = d.get("name") or "—"

        fortune = d.get("fortune") or "—"

        palace = d.get("palace") or "—"

        meaning = d.get("meaning") or ""

        explanation = d.get("explanation") or ""

        p1 = d.get("poem_version_1") or ""

        p2 = d.get("poem_version_2") or ""

        lines = [

            "🎲 观音灵签",

            "━━━━━━━━━━",

            "📜 签名：%s" % name,

            "🔮 吉凶：%s" % fortune,

            "🏯 宫位：%s" % palace,

        ]

        if p1:

            lines.append("")

            lines.append("【签诗】")

            lines.append(p1.replace("  ", "\n"))

        if p2 and p2 != p1:

            lines.append("（又曰）")

            lines.append(p2.replace("  ", "\n"))

        if meaning:

            lines.append("")

            lines.append("【卦象】%s" % meaning)

        if explanation:

            lines.append("")

            lines.append("【解签】%s" % explanation)

        return "\n".join(lines)



    async def send_qiuqian(self, api, group_openid, msg_id, scene=None):

        """求签并发送结果（签文文本 + 签文配图 GIF + 再求一签按钮）。"""

        await send_text(api, _scene(scene), group_openid,

                        "🎲 心诚则灵，观音菩萨为你指点迷津，请稍候...",

                        msg_id=msg_id)



        d = await self._qiuqian_fetch()

        if not d:

            await send_text(api, _scene(scene), group_openid,

                            "😢 签筒一时失灵，请稍后再试～",

                            msg_id=msg_id)

            return True



        text = self._qiuqian_format(d)

        await send_text(api, _scene(scene), group_openid, text, msg_id=msg_id)



        # 签文配图（GIF），失败不影响文本展示

        img = d.get("image")

        if isinstance(img, str) and img.startswith("http"):

            try:

                await send_image_for_scene(api, _scene(scene), group_openid, img,

                                           msg_id=msg_id, content="🎲 签文")

            except Exception as e:

                logger.warning("签文配图发送失败: %s" % e)



        # 再求一签 + 返回主菜单

        keyboard = build_keyboard_multi([

            {"label": "🎲 再求一签", "command": "求签", "enter": True},

            {"label": "🔙 返回主菜单", "command": "返回主菜单", "enter": False},

        ])

        await send_text_with_keyboard(

            api, _scene(scene), group_openid,

            "心有所惑？再求一签或返回主菜单 👇", keyboard, msg_id=msg_id,

        )

        logger.info("求签成功[%s]: %s" % (_scene(scene), d.get("name")))

        return True


    # ================================================================
    #                          答案之书模块
    # ================================================================

    async def _daanzi_fetch(self, question):
        """
        调用小小API答案之书接口（answers），传入问题，返回 data。
        data 可能是字符串答案，也可能是 dict（含 answer/result/text 等字段），失败返回 None。
        """
        try:
            data = await http_get(
                DAANZI_API_URL,
                params={"question": question},
                headers=_DAANZI_HEADERS,
                timeout=10,
            )
        except Exception as e:
            logger.error("答案之书接口请求异常: %s" % e)
            return None

        if not isinstance(data, dict) or data.get("code") != 200:
            code = data.get("code") if isinstance(data, dict) else "None"
            logger.warning("答案之书接口返回异常: code=%s" % code)
            return None

        d = data.get("data")
        if d is None or d == "":
            logger.warning("答案之书接口未返回答案: data=%r" % d)
            return None
        return d

    def _daanzi_format(self, question, d):
        """
        将答案之书 data 格式化为可读文本。
        接口（小小API answers）返回 dict：title_zh / description_zh（兼容旧字段 title/answer/result/text/content）。
        """
        if isinstance(d, str):
            title = d
            desc = ""
        elif isinstance(d, dict):
            title = (
                d.get("title_zh")
                or d.get("title")
                or d.get("answer")
                or d.get("result")
                or d.get("text")
                or d.get("content")
                or ""
            )
            desc = d.get("description_zh") or d.get("description") or ""
        else:
            title = str(d)
            desc = ""

        if not title and not desc:
            title = "（宇宙沉默中...）"

        lines = [
            "🔮 答案之书",
            "━━━━━━━━━━",
            "❓ 问题：%s" % question,
            "📖 答案：%s" % (title or "（宇宙沉默中...）"),
        ]
        if desc:
            lines.append("📝 解读：%s" % desc)
        return "\n".join(lines)

    async def send_daanzi(self, api, group_openid, msg_id, question, scene=None):
        """
        调用答案之书并发送结果（问题 + 答案 + 再问一次 / 返回主菜单 按钮）。
        question 为空时直接返回用法说明，由调用方在分发处判断。
        """
        if not question:
            await send_text(
                api, _scene(scene), group_openid,
                "🔮 答案之书\n"
                "━━━━━━━━━━\n"
                "用法：答案之书 问题\n"
                "示例：答案之书 我该继续吗\n\n"
                "直接发送问题，答案之书为你揭晓～",
                msg_id=msg_id,
            )
            return

        await send_text(
            api, _scene(scene), group_openid,
            "🔮 答案之书正在翻阅中...请稍候...",
            msg_id=msg_id,
        )

        d = await self._daanzi_fetch(question)
        if not d:
            await send_text(
                api, _scene(scene), group_openid,
                "😢 答案之书暂时失联，请稍后再试～",
                msg_id=msg_id,
            )
            return True

        text = self._daanzi_format(question, d)

        keyboard = build_keyboard_multi([
            {"label": "🔮 再问一次", "command": "答案之书 ", "enter": False},
            {"label": "🔙 返回主菜单", "command": "返回主菜单", "enter": False},
        ])

        await send_text_with_keyboard(
            api, _scene(scene), group_openid,
            text, keyboard, msg_id=msg_id,
        )

        logger.info("答案之书成功[%s]: question=%s" % (_scene(scene), question[:30]))
        return True

    # ================================================================
    #                          塔罗牌模块
    # ================================================================
    async def _tarot_fetch(self):
        """调用 OIAPI Tarot 接口获取 4 张牌（过去/现在/未来/切牌）。

        接口：https://oiapi.net/api/Tarot（完全免鉴权，带不带 ckey 都 ok）
        返回：4 张牌的 list[dict]（position / meaning / name_cn / name_en /
              type / pic / 「正位」或「逆位」），失败返回 None。
        """
        try:
            data = await http_get(
                TAROT_API_URL, params=None,
                headers=_TAROT_HEADERS, timeout=TAROT_TIMEOUT,
            )
        except Exception as e:
            logger.error("塔罗牌接口请求异常: %s" % e)
            return None

        if not isinstance(data, dict) or data.get("code") != 1:
            code = data.get("code") if isinstance(data, dict) else "None"
            logger.warning("塔罗牌接口返回异常: code=%s" % code)
            return None

        cards = data.get("data")
        if not isinstance(cards, list) or len(cards) < 1:
            logger.warning("塔罗牌接口未返回牌阵: %r" % cards)
            return None
        return cards

    def _tarot_format(self, cards):
        """把 OIAPI 返回的 4 张牌格式化为可读文本，并收集 pic URL 列表。

        返回 (text, pic_urls)：
          - text：QQ 群聊友好的多牌文本（4 张牌按 OIAPI 顺序：过去/现在/未来/切牌）
          - pic_urls：4 个牌图 URL（pic 缺失或非 http 链接的跳过）
        """
        if not cards:
            return ("", [])

        lines = [
            "🃏 塔罗牌占卜",
            "━━━━━━━━━━",
        ]

        # 4 张牌的展示序号（按 OIAPI 固定顺序：过去/现在/未来/切牌）
        pos_name_map = {
            "第一张牌": "过去",
            "第二张牌": "现在",
            "第三张牌": "未来",
            "切牌": "你的状态",
        }
        pos_emoji_map = {
            "第一张牌": "⏪",
            "第二张牌": "⏺️",
            "第三张牌": "⏩",
            "切牌": "🎴",
        }

        pic_urls = []
        for i, card in enumerate(cards, 1):
            if not isinstance(card, dict):
                continue
            pos = card.get("position") or ("第%d张牌" % i)
            meaning = card.get("meaning") or ""
            name_cn = card.get("name_cn") or "—"
            name_en = card.get("name_en") or ""
            typ = card.get("type") or "—"
            # 解释字段：正位牌只有「正位」，逆位牌只有「逆位」，按 type 选取
            explanation = card.get(typ) or card.get("正位") or card.get("逆位") or "—"
            short_name = pos_name_map.get(pos, pos)
            emoji = pos_emoji_map.get(pos, "🃏")

            lines.append("")
            lines.append("%s %s · %s" % (emoji, short_name, pos))
            lines.append("  牌名：%s (%s)" % (name_cn, name_en))
            lines.append("  状态：%s" % typ)
            if meaning:
                lines.append("  牌位：%s" % meaning)
            lines.append("  牌意：%s" % explanation)

            # 收集牌图 URL
            pic = card.get("pic")
            if isinstance(pic, str) and pic.startswith("http"):
                pic_urls.append(pic)

        lines.append("")
        lines.append("💫 塔罗为你揭示命运的轨迹，祝你心想事成～")
        return ("\n".join(lines), pic_urls)

    async def send_tarot(self, api, group_openid, msg_id, scene=None):
        """塔罗占卜并发送结果（4 张牌位文本 + 4 张牌图 + 再抽一次 / 返回主菜单按钮）。"""
        await send_text(api, _scene(scene), group_openid,
                        "🃏 正在为你翻开命运的牌面，请稍候...",
                        msg_id=msg_id)

        cards = await self._tarot_fetch()
        if not cards:
            await send_text(api, _scene(scene), group_openid,
                            "😢 牌面一时模糊，请稍后再试～",
                            msg_id=msg_id)
            return True

        text, pic_urls = self._tarot_format(cards)
        if text:
            await send_text(api, _scene(scene), group_openid, text, msg_id=msg_id)

        # 4 张牌图（每张单独发送；pic 缺失自动跳过）
        for idx, url in enumerate(pic_urls, 1):
            try:
                await send_image_for_scene(
                    api, _scene(scene), group_openid, url,
                    msg_id=msg_id, content="🃏 塔罗牌 %d" % idx,
                )
            except Exception as e:
                logger.warning("塔罗牌图发送失败[%d]: %s" % (idx, e))

        # 再抽一次 + 返回主菜单
        keyboard = build_keyboard_multi([
            {"label": "🃏 再抽一次", "command": "塔罗牌", "enter": True},
            {"label": "🔙 返回主菜单", "command": "返回主菜单", "enter": False},
        ])
        await send_text_with_keyboard(
            api, _scene(scene), group_openid,
            "心有所惑？再抽一次或返回主菜单 👇", keyboard, msg_id=msg_id,
        )

        logger.info("塔罗牌成功[%s]: %d 张" % (_scene(scene), len(cards)))
        return True




    #                  今日运势查询（小小API / xxapi.cn）
    # ================================================================

    async def _query_horoscope(self, api, sign_input, group_openid, msg_id, scene=None):
        """查询今日星座运势（小小API，无需密钥）

        接口: https://v2.xxapi.cn/api/horoscope
        参数: type=星座英文小写(aries...), time=today
        星座支持: 中文(白羊座/白羊/水瓶...) 或 英文(aries...)
        """
        if scene is None:
            scene = ChatScene.GROUP

        raw = (sign_input or "").strip().lower()
        sign_en = _HOROSCOPE_SIGN_MAP.get(raw)
        if not sign_en:
            # 容错：去掉「座」字再试（如「白羊座」已覆盖，这里处理异常输入）
            sign_en = _HOROSCOPE_SIGN_MAP.get(raw.replace("座", ""))
        if not sign_en:
            await send_text(
                api, scene, group_openid,
                "🔮 今日运势\n━━━━━━━━━━\n"
                "未识别到星座，请按以下格式输入：\n"
                "运势 白羊座 / 运势 水瓶 / 运势 aries\n\n"
                "可选星座：\n"
                "白羊座 金牛座 双子座 巨蟹座\n"
                "狮子座 处女座 天秤座 天蝎座\n"
                "射手座 摩羯座 水瓶座 双鱼座",
                msg_id=msg_id,
            )
            return

        headers = {"User-Agent": "xiaoxiaoapi/1.0.0 (https://xxapi.cn)"}
        if config.XXAPI_KEY:
            headers["Authorization"] = "Bearer %s" % config.XXAPI_KEY

        try:
            data = await http_get(
                _HOROSCOPE_API,
                params={"type": sign_en, "time": "today"},
                headers=headers,
                timeout=10,
            )
        except Exception as e:
            logger.error("今日运势请求异常: %s" % e)
            data = {}

        if not data or data.get("code") != 200:
            await send_text(
                api, scene, group_openid,
                "今日运势查询失败，请稍后重试",
                msg_id=msg_id,
            )
            return

        d = data.get("data", {}) or {}
        title = d.get("title", _HOROSCOPE_SIGN_NAMES.get(sign_en, sign_en))
        day = d.get("time", "")
        f = d.get("fortune", {}) or {}
        idx = d.get("index", {}) or {}
        ft = d.get("fortunetext", {}) or {}
        todo = d.get("todo", {}) or {}

        def _stars(n):
            try:
                n = int(n)
            except (TypeError, ValueError):
                return "—"
            n = max(0, min(5, n))
            return "★" * n + "☆" * (5 - n)

        def _g(dct, key):
            v = dct.get(key, "")
            return v if v not in (None, "") else "—"

        msg = (
            "🔮 %s · 今日运势\n"
            "━━━━━━━━━━\n"
            "📅 %s\n\n"
            "⭐ 综合：%s（%s）\n"
            "❤️ 爱情：%s（%s）\n"
            "💰 财运：%s（%s）\n"
            "💪 健康：%s（%s）\n"
            "📈 事业：%s（%s）\n\n"
            "🎨 幸运色：%s\n"
            "🔢 幸运数字：%s\n"
            "✨ 幸运星座：%s\n"
            "✅ 宜：%s\n"
            "⛔ 忌：%s\n\n"
            "📜 %s\n%s"
        ) % (
            title, day,
            _stars(f.get("all")), _g(idx, "all"),
            _stars(f.get("love")), _g(idx, "love"),
            _stars(f.get("money")), _g(idx, "money"),
            _stars(f.get("health")), _g(idx, "health"),
            _stars(f.get("work")), _g(idx, "work"),
            _g(d, "luckycolor"), _g(d, "luckynumber"),
            _g(d, "luckyconstellation"),
            _g(todo, "yi").lstrip("宜"), _g(todo, "ji").lstrip("忌"),
            _g(d, "shortcomment"), _g(ft, "all"),
        )
        await send_text(api, _scene(scene), group_openid, msg, msg_id=msg_id)



    async def handle_command(self, api, content, group_openid, member_openid, msg_id, scene=None, member_nick=None):
        """

        处理娱乐系统命令，返回 True 表示已处理。

        scene: "group" / "c2c" / "channel"（用于发送消息时选择正确的 API）



        优先级：

        1. 猜成语游戏进行中 → 所有消息优先交给猜成语处理（结束/跳过/答案）

        2. 显式命令（五子棋、猜成语等）

        3. 五子棋落子指令

        """

        text = content.strip()



        # ========== 猜成语优先路由（有进行中的游戏时，所有消息优先处理）==========

        idiom_games = load_json(IDIOM_GAME_DATA_FILE)

        idiom_active = (

            group_openid in idiom_games

            and idiom_games[group_openid].get("status") == "playing"

        )



        if idiom_active:

            # 结束猜成语（兼容多种退出说法）

            if text in ("结束", "结束游戏", "退出", "退出游戏", "不玩了"):

                await self._idiom_end(api, group_openid, msg_id, scene=scene)

                return True

            # 【全局指令隔离】如果是其他功能的指令（如“菜单”、“帮助”、“签到”等），

            # 先强制结束本轮猜成语，避免被当成答案错误判定，

            # 然后返回 False 让其他模块接手。

            if self._is_global_command(text):

                await self._idiom_force_end(api, group_openid, msg_id, scene=scene,

                                            reason="收到其他指令「%s」" % text)

                return False

            # 跳过当前题

            if text == "跳过":

                await self._idiom_skip(api, group_openid, msg_id, scene=scene)

                return True

            # 查看提示（不发答案，仅提示线索）

            if text == "成语提示":

                game = idiom_games[group_openid]

                current_idiom = game.get("current_idiom", "")

                # 猜对一个字提示一个，赛马场1：或字面意思

                hint = game.get("current_hint", "")

                if hint:

                    await send_text(api, _scene(scene), group_openid,

                        "💡 提示：%s\n（提示不计入成绩，继续选择你的答案吧～）" % hint,

                        msg_id=msg_id,

                    )

                else:

                    # 退化提示：拆字提示第一个字与长度

                    if current_idiom:

                        await send_text(api, _scene(scene), group_openid,

                            "💡 提示：首字「%s」（共%d个字）" % (current_idiom[0], len(current_idiom)),

                            msg_id=msg_id,

                        )

                    else:

                        await send_text(api, _scene(scene), group_openid,

                            "💡 本轮暂无额外提示",

                            msg_id=msg_id,

                        )

                return True

            # 【作答】按钮点入后：鲁棒处理某些 QQ 客户端可能直接发送占位符原文

            # 理想路径是 enter=False 填入输入框，玩家直接在后面接上答案发送，如“作答画蛇添足”

            # 鲁棒1：如果玩家发了纯“作答”，提示怎么用

            if text == "作答":

                await send_text(api, _scene(scene), group_openid,

                    "✏️ 请在「作答」后面直接接上你的成语发送～\n例如：作答守株待兔",

                    msg_id=msg_id,

                )

                return True

            # 鲁棒2：如果玩家发了“作答XXX”，去掉“作答”后作为答案判定

            if text.startswith("作答") and len(text) > 2:

                guess = text[2:].strip()

                game = idiom_games[group_openid]

                current_idiom = game.get("current_idiom", "")

                if guess == current_idiom:

                    await self._idiom_correct(api, group_openid, msg_id, scene=scene)

                else:

                    await self._idiom_wrong(api, group_openid, guess, msg_id, scene=scene)

                return True

            # 其他消息一律作为答案猜测

            game = idiom_games[group_openid]

            current_idiom = game.get("current_idiom", "")

            if text == current_idiom:

                await self._idiom_correct(api, group_openid, msg_id, scene=scene)

            else:

                await self._idiom_wrong(api, group_openid, text, msg_id, scene=scene)

            return True



        # ========== 象棋优先路由（有进行中的棋局时，所有消息优先交给象棋处理）==========

        xiangqi_games = load_json(XIANGQI_DATA_FILE)

        xq_active = (

            group_openid in xiangqi_games

            and xiangqi_games[group_openid].get("status") == "playing"

        )

        if xq_active:

            if text == "结束象棋":

                await self._xiangqi_surrender(api, group_openid, member_openid, msg_id, scene=scene)

                return True

            if text == "象棋排行":
                await self._xiangqi_ranking(api, group_openid, msg_id, scene=scene)
                return True

            if text == "五子棋排行":
                await self._gomoku_ranking(api, group_openid, msg_id, scene=scene)
                return True

            if text == "象棋":

                await send_text(api, _scene(scene), group_openid,

                                      "棋局进行中，请走子（如 走 a1 b3）或发送「结束象棋」结束。",

                                      msg_id=msg_id)

                return True

            mv = self._xq_parse_move(text)

            if mv:

                await self._xiangqi_move(api, text, group_openid, member_openid, msg_id, scene=scene)

                return True

            await send_text(api, _scene(scene), group_openid,

                                  "♟ 棋局进行中，请发送走子指令（如 a1 b3）或「结束象棋」。",

                                  msg_id=msg_id)

            return True



        # ========== 无进行中游戏时，正常处理显式命令 ==========

        is_group = (scene == ChatScene.GROUP)



        # 五子棋

        if text == "五子棋":

            await self._gomoku_show_modes(api, group_openid, msg_id, scene=scene)

            return True



        if text in ("五子棋AI", "AI对战"):

            await self._gomoku_start_ai(api, group_openid, member_openid, msg_id, scene=scene, member_nick=member_nick)

            return True



        # 五子棋二人对战 — 仅群聊可用

        if text in ("五子棋双人", "二人对战"):

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 二人对战需要群聊场景（两名玩家在同一群），私聊请使用「AI对战」。",

                                msg_id=msg_id)

                return True

            await self._gomoku_show_colors(api, group_openid, msg_id, scene=scene)

            return True



        if text == "选择黑方":

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 二人对战棋色选择仅限群聊。",

                                msg_id=msg_id)

                return True

            await self._gomoku_select_color(api, group_openid, member_openid, BLACK, msg_id, scene=scene, member_nick=member_nick)

            return True



        if text == "选择白方":

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 二人对战棋色选择仅限群聊。",

                                msg_id=msg_id)

                return True

            await self._gomoku_select_color(api, group_openid, member_openid, WHITE, msg_id, scene=scene, member_nick=member_nick)

            return True



        # 猜成语（开始游戏）

        if text == "猜成语":

            await self._idiom_start(api, group_openid, msg_id, scene=scene)

            return True





        # 中国象棋

        if text == "象棋":

            await self._xiangqi_show_modes(api, group_openid, msg_id, scene=scene)

            return True

        if text == "象棋AI":

            await self._xiangqi_ai_menu(api, group_openid, msg_id, scene=scene)

            return True

        if text == "象棋AI红":

            await self._xiangqi_start_ai(api, group_openid, member_openid, msg_id, "red", scene=scene, member_nick=member_nick)

            return True

        if text == "象棋AI黑":

            await self._xiangqi_start_ai(api, group_openid, member_openid, msg_id, "black", scene=scene, member_nick=member_nick)

            return True

        # 象棋二人对战 — 仅群聊可用

        if text == "象棋双人":

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 二人对战需要群聊场景（两名玩家在同一群），私聊请使用「象棋AI」。",

                                msg_id=msg_id)

                return True

            await self._xiangqi_pvp_menu(api, group_openid, msg_id, scene=scene)

            return True

        if text == "象棋双人红":

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 象棋二人对战棋色选择仅限群聊。",

                                msg_id=msg_id)

                return True

            await self._xiangqi_pvp_join(api, group_openid, member_openid, msg_id, "red", scene=scene, member_nick=member_nick)

            return True

        if text == "象棋双人黑":

            if not is_group:

                await send_text(api, _scene(scene), group_openid,

                                "⚠️ 象棋二人对战棋色选择仅限群聊。",

                                msg_id=msg_id)

                return True

            await self._xiangqi_pvp_join(api, group_openid, member_openid, msg_id, "black", scene=scene, member_nick=member_nick)

            return True

        if text == "象棋排行":
            await self._xiangqi_ranking(api, group_openid, msg_id, scene=scene)
            return True

        if text == "五子棋排行":
            await self._gomoku_ranking(api, group_openid, msg_id, scene=scene)
            return True



        # 观音灵签

        if text == "求签":

            await self.send_qiuqian(api, group_openid, msg_id, scene=scene)

            return True

        # 塔罗牌

        if text == "塔罗牌":

            await self.send_tarot(api, group_openid, msg_id, scene=scene)

            return True

        # 答案之书

        if text == "答案之书":

            await send_text(
                api, _scene(scene), group_openid,
                "🔮 答案之书\n"
                "━━━━━━━━━━\n"
                "用法：答案之书 问题\n"
                "示例：答案之书 我该继续吗\n\n"
                "直接发送问题，答案之书为你揭晓～",
                msg_id=msg_id,
            )

            return True

        if text.startswith("答案之书 ") or text.startswith("答案之书\u3000"):
            question = text[len("答案之书"):].strip()
            if question:
                await self.send_daanzi(api, group_openid, msg_id, question, scene=scene)
                return True



        # ========== 今日运势查询（小小API） ==========
        if text == "运势" or text == "今日运势" or text == "星座运势":
            await send_text(
                api, scene, group_openid,
                "🔮 今日运势\n━━━━━━━━━━\n"
                "用法：运势 星座名\n"
                "示例：运势 白羊座 / 运势 水瓶 / 运势 aries\n\n"
                "可选星座：\n"
                "白羊座 金牛座 双子座 巨蟹座\n"
                "狮子座 处女座 天秤座 天蝎座\n"
                "射手座 摩羯座 水瓶座 双鱼座",
                msg_id=msg_id,
            )
            return True

        if text.startswith("运势 ") or text.startswith("运势\u3000"):
            sign_input = text[2:].strip()
            if sign_input:
                await self._query_horoscope(api, sign_input, group_openid, msg_id, scene)
                return True
            await send_text(
                api, scene, group_openid,
                "🔮 今日运势\n━━━━━━━━━━\n请告诉我你的星座，例如：\n运势 白羊座",
                msg_id=msg_id,
            )
            return True


        # 认输/结束棋局

        if text in ("认输", "结束棋局", "结束对局"):

            gomoku_games = load_json(GOMOKU_DATA_FILE)

            if group_openid in gomoku_games and gomoku_games[group_openid].get("status") == "playing":

                # 私聊不允许二人对战投降（仅 AI 对战可用）

                game = gomoku_games[group_openid]

                if not is_group and game.get("mode") == "pvp":

                    await send_text(api, _scene(scene), group_openid,

                                    "⚠️ 私聊不支持二人对战。",

                                    msg_id=msg_id)

                    return True

                await self._gomoku_surrender(api, group_openid, member_openid, msg_id, scene=scene, member_nick=member_nick)

                return True

            return False



        # 结束象棋（兜底：未在进行中时给出提示）

        if text == "结束象棋":

            await self._xiangqi_surrender(api, group_openid, member_openid, msg_id, scene=scene)

            return True



        # 五子棋落子指令

        if text.startswith("下棋") or text.startswith("落子"):

            gomoku_games = load_json(GOMOKU_DATA_FILE)

            if group_openid in gomoku_games and gomoku_games[group_openid].get("status") == "playing":

                # 私聊不允许 PvP 模式落子（同一用户操作两边等于自玩）

                game = gomoku_games[group_openid]

                if not is_group and game.get("mode") == "pvp":

                    await send_text(api, _scene(scene), group_openid,

                                    "⚠️ 私聊不支持二人对战。请使用「五子棋AI」。",

                                    msg_id=msg_id)

                    return True

                await self._gomoku_move(api, text, group_openid, member_openid, msg_id, scene=scene, member_nick=member_nick)

                return True

            return False



        return False





