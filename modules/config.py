# -*- coding: utf-8 -*-
"""全局配置"""

# 机器人凭证
APPID = "YOUR_APPID"
SECRET = "YOUR_BOT_TOKEN"

# 第三方API配置（按需填写）
# 视频解析 API（ALAPI，关注公众号免费获取token）
VIDEO_PARSE_TOKEN = ""

# 短视频聚合解析 API（小渡 openapi.dwo.cc/api/svparse）
# 支持 20+ 平台：抖音 / 快手 / 小红书 / B站 / 视频号 / 油管 / TikTok /
# 西瓜视频 / 好看视频 / 微视 / 梨视频 / 微博 / 知乎 / AcFun / 皮皮虾等
# 返回结构：{"code":200,"msg":"success","data":{type,title,desc,cover,url,video_backup,images,...}}
DWO_VIDEO_PARSE_KEY = "EU1UX26RA2BPXWCWH8Z4"  # ckey

# QQ信息查询 API（按优先级依次尝试）
# 方案1：川源科技 dwo.cc qqxxcx（需 ckey，全套资料：昵称/QID/等级/注册时间/签名/vip）
# 文档地址：https://api.dwo.cc/api/192
DWO_QQ_FULL_URL = "https://openapi.dwo.cc/api/qqxxcx"
DWO_QQ_CKEY = "EU1UX26RA2BPXWCWH8Z4"  # 用户的 ckey

# 方案2：川源科技 openapi.dwo.cc/qqnet（免KEY，提供 detail_info/services: 会员/活跃天数/开通业务等）
# 文档地址：https://api.dwo.cc/api/15
DWO_QQ_INFO_URL = "https://openapi.dwo.cc/api/qqnet"

# 方案3：APIBYTE（apione.apibyte.cn，免KEY，提供昵称/头像/邮箱/QQ空间等）
# 文档地址：https://apibyte.cn/marketplace/qqinfo
APIBYTE_QQ_INFO_URL = "https://apione.apibyte.cn/qqinfo"

# 方案4：相见拾光API（免费注册，每日1000次，提供等级/会员/活跃天数等）
# 注册地址：https://api.shwgij.com  → 控制台 → 密钥管理
SHWGIJ_KEY = ""

# 方案5：小渡API（需KEY，提供注册时间/签名/名片等详细字段）
# 注：小渡 v2.xxapi.cn/api/qqinfo 当前KEY在该平台没有该接口权限
# 同时用于「天气查询」（openapi.dwo.cc/api/weather_gd 的 ckey）
QQ_INFO_KEY = "YOUR_BOT_TOKEN"

# 小小API 配置（今日运势 / 星座运势）
# 注册地址：https://xxapi.cn  → 控制台 → 密钥管理
# 免费接口也支持无 Key 调用；填写 Key 可提高稳定性与额度
XXAPI_KEY = "1fb99f34b2481d8d"

# 小小API - 随机4K图片（random4kPic，type=acg=二次元 / wallpaper=风景）
RANDOMPIC_API_URL = "https://v2.xxapi.cn/api/random4kPic"
RANDOMPIC_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 随机壁纸图片（wallpaper，独立接口，与 random4kPic 互为补充）
RANDOMBIZHI_API_URL = "https://v2.xxapi.cn/api/wallpaper"
RANDOMBIZHI_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 随机原神图片（ys）
GENSHIN_API_URL = "https://v2.xxapi.cn/api/ys"
GENSHIN_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 随机原神cosplay图片（yscos）
GENSHINCOS_API_URL = "https://v2.xxapi.cn/api/yscos"
GENSHINCOS_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 随机小姐姐图片（meinvpic，返回 JSON {code, data:图片URL}）
# 接口文档：https://xxapi.cn/api/detail/meinvpic
# 可选参数 return=302 → 返回 HTTP 302 重定向到图片本身（本项目走 JSON 路径，无需此参数）
MEINVPIC_API_URL = "https://v2.xxapi.cn/api/meinvpic"
MEINVPIC_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 观音灵签（guanyinrandom）
GUANYIN_API_URL = "https://v2.xxapi.cn/api/guanyinrandom"
GUANYIN_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 答案之书（answers，随机答案生成）
DAANZI_API_URL = "https://v2.xxapi.cn/api/answers"
DAANZI_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# 小小API - 常见疾病信息（disease）
DISEASE_API_URL = "https://v2.xxapi.cn/api/disease"
DISEASE_API_KEY = XXAPI_KEY  # 复用小小API统一密钥（Authorization: Bearer 头）

# OIAPI Openid 接口（QQ 官方机器人免鉴权反查用户昵称）
# 文档：https://oiapi.net/api/Openid
# 入参：openid（QQ Bot 平台用户 openid） + appid（机器人 appid）
# 返回：{"code":1,"message":"昵称","data":{"openid":"...","nickname":"...","button":0,"age":0,"head_decorate":0}}
# 成功 code=1，message 与 data.nickname 均为昵称；失败 code=-1（参数错误 / openid 不存在）
# 鉴权：免 ckey（实测三种鉴权方式返回完全一致）
# 用途：填 _upsert_member 时 author.username 为空 / 用户未绑 QQ 时无法反查昵称的洞
OIAPI_OPENID_URL = "https://oiapi.net/api/Openid"
OIAPI_OPENID_APPID = ""  # 留空时自动用上方 APPID 常量（推荐）
OIAPI_OPENID_TIMEOUT = 8  # HTTP 超时（秒）

# OIAPI 垃圾分类（WasteSorting）接口 - 完全免鉴权
# 文档：https://oiapi.net/api/WasteSorting
# 入参：word（垃圾名字，必填）/ n（索引，必填）/ category（1-回收/2-有害/4-湿/8-干/16-大件，可选）
# 行为：
#   - 只传 word → 返回 data.list（所有候选 variant 列表），message 是换行拼接
#   - 传 word + n=N → 返回 data.waste（标准名）+ data.name（类别中文）+ message "X是Y垃圾"
#   - code=-2 → "换个词，或者反馈给管理员"（未匹配）
# 注意：n=N 是 OIAPI 列表的索引，同一关键词不同候选可能属于不同类别
#       （如「电池」 N=1 有害垃圾，N=3 干垃圾），所以多结果场景给用户选择是必要的
OIAPI_WASTE_URL = "https://oiapi.net/api/WasteSorting"
OIAPI_WASTE_TIMEOUT = 8  # HTTP 超时（秒）

# Qwen3-1.7B 大模型配置（学习系统「AI 智能出题」搜索后端）
# 接口地址：https://openapi.dwo.cc/api/Qwen3_1.7B
# 请求方式：POST，JSON 参数 { "prompt": "..." }（或 "message"）
# 免 KEY，约 5 QPS；返回 data.content / msg 字段
# 用途：语文/英语/数学 题目搜索改为由大模型直接生成题目+答案+解析
QWEN_ENDPOINT = "https://openapi.dwo.cc/api/Qwen3_1.7B"
QWEN_TIMEOUT = 60       # 大模型生成较慢，给足超时
QWEN_MODEL = ""         # 留空由平台决定模型；如有多个模型可填写

# 音乐API配置
NETEASE_API_BASE = "https://autumnfish.cn"  # 网易云API（公共测试，建议自建）

# 酷狗音乐API配置
# 说明：酷狗播放接口(getCdnIfo)需要签名，算法可能随官方调整变化；
#       若内置签名接口失效，请把 KUGOU_PLAY_API 指向你自建/可用的代理：
#       格式如 "https://你的代理/api/kugou/url?hash={hash}"（{hash} 会被自动替换）
KUGOU_API_BASE = "https://www.kugou.com"   # 酷狗API根地址（可替换为自建代理）
KUGOU_APPID = "1014"
KUGOU_PLATID = "4"
KUGOU_MID = "8888"
KUGOU_DFID = ""                            # 留空即可；个别接口需要 cookie 中的 dfid
KUGOU_SIGN_PREFIX = "OIllegeO"             # 签名盐（官方变更时可在此调整）
KUGOU_SECRET = "BAIDU_SECRET_KEY"          # 签名盐
KUGOU_PLAY_API = ""                        # 留空用内置签名接口；填自定义代理地址可绕过签名

# 数据文件目录
DATA_DIR = "data"

# 签到积分配置
CHECKIN_BASE_POINTS = 10  # 每次签到固定积分
CHECKIN_BONUS_CAP = 200   # 连续签到奖励上限



# 机器人事件接收方式 (websocket / webhook)
BOT_EVENT_MODE = "websocket"

# 机器人运行环境 (sandbox / production)
BOT_ENVIRONMENT = "production"

