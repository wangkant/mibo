"""What a thing is about, read from its own words.

A fixed list of subjects, each with the words that find it in a title, an
excerpt, a tag or a source's own line about itself. The fifteen topics offered
on the first run are among them; a finer subject names the offered topic it
sits under, so "Science" picked on the first run covers astronomy, physics and
biology, and the taste model then learns which of those the person opens.

This is the plain route every install has: no model call, no vectors. Words
are English and Chinese (Traditional read through a small table); a thing in
another language is found by what its source says it brings.
"""
from __future__ import annotations

import functools
import re

# key: (the offered topic it sits under or "", (English name, Chinese name), words)
SUBJECTS = {
    "tech": ("", ("Tech", "科技"), (
        "tech", "technology", "big tech", "silicon valley", "the verge", "科技", "数码圈", "互联网", "科技圈")),
    "gadgets": ("tech", ("Gadgets", "数码"), (
        "gadget", "smartphone", "iphone", "ipad", "macbook", "android", "laptop", "chip", "chipmaker",
        "semiconductor", "hardware", "gpu", "processor", "wearable", "smartwatch", "headphone", "earbuds",
        "samsung", "数码", "手机", "芯片", "半导体", "硬件", "显卡", "处理器", "笔记本电脑", "耳机", "平板",
        "华为", "小米", "三星", "晶片", "keyboard", "mechanical keyboard", "键盘", "机械键盘")),
    "internet": ("tech", ("Internet", "互联网"), (
        "social media", "social network", "tiktok", "facebook", "instagram", "browser", "app store",
        "online platform", "streamer", "influencer", "社交媒体", "社交平台", "短视频", "抖音", "微信", "微博",
        "小红书", "网民", "直播带货")),
    "security": ("tech", ("Security", "网络安全"), (
        "cybersecurity", "malware", "ransomware", "hacked", "hacking", "data breach", "vulnerability",
        "exploit", "phishing", "encryption", "privacy", "surveillance", "网络安全", "黑客", "漏洞", "勒索软件",
        "隐私", "泄露", "加密")),
    "ai": ("", ("AI", "AI"), (
        "ai", "a.i.", "llm", "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini", "deepseek", "copilot",
        "machine learning", "deep learning", "neural", "neural network", "language model", "diffusion model",
        "reinforcement learning", "computer vision", "generative", "chatbot", "artificial intelligence",
        "人工智能", "大模型", "机器学习", "深度学习", "神经网络", "智能体", "生成式", "人工智慧", "语言模型",
        "具身智能", "aigc", "robot", "robotics", "humanoid", "机器人", "机械臂")),
    "programming": ("", ("Programming", "编程"), (
        "programming", "programmer", "code", "coding", "developer", "python", "javascript", "typescript", "rust",
        "golang", "java", "c++", "github", "open source", "open-source", "compiler", "software", "hacker news",
        "stack overflow", "kubernetes", "linux", "api", "database", "sql", "git", "debugging", "framework",
        "backend", "frontend", "devops", "docker", "repo", "sdk", "runtime", "regex", "css", "编程", "代码",
        "程序员", "开发者", "开源", "前端", "后端", "编译", "数据库", "框架", "运维", "软件", "程式")),
    "science": ("", ("Science", "科学"), (
        "science", "scientist", "scientific", "researcher", "arxiv", "preprint", "peer-reviewed", "科学", "科研",
        "论文", "科学家", "科普", "研究人员")),
    "space": ("science", ("Space", "天文航天"), (
        "astronomy", "astronomer", "nasa", "spacex", "rocket", "satellite", "telescope", "galaxy", "galaxies",
        "planet", "mars", "lunar", "asteroid", "comet", "black hole", "cosmos", "universe", "orbit", "astronaut",
        "exoplanet", "spacecraft", "solar system", "supernova", "space station", "voyager", "天文", "航天", "宇宙",
        "火箭", "卫星", "望远镜", "星系", "行星", "火星", "月球", "黑洞", "宇航员", "空间站", "太空", "嫦娥",
        "神舟", "太陽系")),
    "physics": ("science", ("Physics, chemistry, maths", "物理化学数学"), (
        "physics", "physicist", "quantum", "particle", "chemistry", "chemist", "molecule", "atom", "atomic",
        "mathematics", "math", "maths", "mathematician", "theorem", "equation", "fusion", "superconductor",
        "thermodynamics", "randomness", "物理", "化学", "量子", "粒子", "数学", "分子", "原子", "核聚变", "超导",
        "定理")),
    "biology": ("science", ("Biology and medicine", "生物医学"), (
        "biology", "biologist", "gene", "genetic", "genetics", "genome", "genomic", "dna", "rna", "protein",
        "cell", "evolution", "neuroscience", "brain", "microbe", "bacteria", "virus", "vaccine",
        "clinical trial", "cancer", "tumor", "medical research", "drug discovery", "bioinformatics", "enzyme",
        "生物", "基因", "蛋白质", "细胞", "进化", "神经科学", "大脑", "细菌", "病毒", "疫苗", "癌症", "医学",
        "药物", "临床", "肿瘤")),
    "health": ("", ("Health", "健康"), (
        "health", "healthy", "diet", "nutrition", "sleep", "mental health", "anxiety", "depression", "therapy",
        "wellness", "doctor", "hospital", "disease", "symptom", "patient", "obesity", "diabetes", "grief",
        "healthcare", "健康", "减肥", "营养", "睡眠", "心理", "焦虑", "抑郁", "养生", "医院", "医生", "疾病",
        "症状", "患者", "医疗")),
    "fitness": ("sports", ("Fitness", "健身"), (
        "fitness", "workout", "gym", "exercise", "yoga", "marathon", "running", "runner", "cycling",
        "weightlifting", "健身", "锻炼", "减脂", "增肌", "瑜伽", "跑步", "马拉松", "骑行", "撸铁")),
    "games": ("", ("Games", "游戏"), (
        "game", "gaming", "gamer", "steam", "nintendo", "playstation", "xbox", "esports", "rpg", "fps", "dlc",
        "indie game", "speedrun", "zelda", "pokemon", "minecraft", "ps5", "itch.io", "multiplayer", "roguelike",
        "游戏", "电竞", "手游", "主机", "任天堂", "原神", "玩家", "网游", "单机", "通关", "英雄联盟", "王者荣耀",
        "塞尔达", "宝可梦", "黑神话", "npc")),
    "anime": ("", ("Anime", "动画"), (
        "anime", "manga", "bangumi", "cosplay", "ghibli", "动画", "动漫", "番剧", "新番", "漫画", "二次元", "声优",
        "轻小说", "漫展", "吉卜力")),
    "music": ("", ("Music", "音乐"), (
        "music", "song", "album", "concert", "band", "spotify", "musician", "singer", "guitar", "piano", "jazz",
        "hip-hop", "rapper", "orchestra", "symphony", "playlist", "vinyl", "grammy", "songwriter", "pop music",
        "k-pop", "kpop", "j-pop", "c-pop", "音乐", "流行音乐", "歌曲",
        "老歌", "新歌", "专辑", "演唱会", "乐队", "说唱", "翻唱", "歌手", "吉他", "钢琴", "爵士", "摇滚", "单曲")),
    "film": ("", ("Film", "电影"), (
        "film", "movie", "cinema", "trailer", "box office", "netflix", "director", "tv series", "tv show",
        "sitcom", "hbo", "oscar", "documentary", "actor", "actress", "screenplay", "sequel", "filmmaker",
        "rotten tomatoes", "电影", "影视", "剧集", "票房", "导演", "预告", "纪录片", "电视剧", "演员", "影评",
        "奥斯卡", "上映", "综艺")),
    "books": ("", ("Books", "读书"), (
        "book", "novel", "reading", "author", "literature", "literary", "poem", "poetry", "poet", "fiction",
        "memoir", "bookstore", "publisher", "essay", "novelist", "读书", "书单", "小说", "作家", "阅读", "文学",
        "诗歌", "散文", "出版", "书评", "诗人")),
    "history": ("", ("History", "历史"), (
        "history", "historical", "historian", "ancient", "archaeology", "archaeologist", "empire", "medieval",
        "dynasty", "world war", "civil war", "excavation", "centuries", "museum", "历史", "古代", "考古", "王朝",
        "文物", "遗址", "朝代", "二战", "抗战", "博物馆", "秦朝", "汉朝", "隋朝", "唐朝", "宋朝", "元朝", "明朝", "清朝",
        "晚清", "民国", "古罗马", "古希腊", "文艺复兴")),
    "philosophy": ("", ("Ideas", "思想"), (
        "philosophy", "philosopher", "psychology", "psychologist", "sociology", "ethics", "哲学", "心理学",
        "社会学", "伦理")),
    "design": ("", ("Design", "设计"), (
        "design", "designer", "ui", "ux", "typography", "font", "figma", "logo", "branding", "interior",
        "furniture", "设计", "字体", "排版", "配色", "家具", "室内")),
    "art": ("design", ("Art", "艺术"), (
        "art", "artist", "painting", "painter", "sculpture", "sculptor", "gallery", "exhibition",
        "illustration", "illustrator", "ceramic", "artwork", "installation", "艺术", "画家", "绘画", "雕塑", "展览",
        "美术馆", "插画", "书法")),
    "architecture": ("design", ("Architecture", "建筑"), (
        "architecture", "architect", "skyscraper", "pavilion", "建筑", "建筑师")),
    "photography": ("design", ("Photography", "摄影"), (
        "photography", "photographer", "photo", "photograph", "camera", "lens", "摄影", "摄影师", "照片", "相机",
        "镜头")),
    "fashion": ("", ("Fashion", "时尚"), (
        "fashion", "sneaker", "streetwear", "outfit", "beauty", "makeup", "skincare", "luxury", "runway", "时尚",
        "穿搭", "球鞋", "美妆", "护肤", "奢侈品", "潮流")),
    "food": ("", ("Food", "美食"), (
        "food", "recipe", "cooking", "cook", "baking", "bread", "chef", "restaurant", "kitchen", "dish", "dishes",
        "cuisine", "menu", "dessert", "wine", "coffee", "noodle", "dining", "美食", "菜谱", "做饭", "烹饪", "烘焙",
        "面包", "餐厅", "下厨", "食谱", "料理", "小吃", "火锅", "咖啡", "甜品", "探店", "外卖")),
    "travel": ("", ("Travel", "旅行"), (
        "travel", "trip", "tourism", "tourist", "flight", "hotel", "destination", "itinerary", "backpacking",
        "airline", "airport", "road trip", "traveler", "旅行", "旅游", "攻略", "景点", "出行", "自驾", "民宿",
        "机票", "酒店", "游记")),
    "outdoors": ("travel", ("Outdoors", "户外"), (
        "outdoors", "outdoor", "hiking", "hiker", "camping", "campsite", "mountaineering", "rock climbing",
        "bouldering", "fishing", "angler", "skiing", "snowboarding", "surfing", "kayaking", "户外", "徒步",
        "登山", "爬山", "露营", "野营", "钓鱼", "垂钓", "攀岩", "滑雪", "冲浪")),
    "finance": ("", ("Finance", "财经"), (
        "finance", "financial", "market", "stock", "stock market", "investor", "investing", "investment", "bond",
        "interest rate", "inflation", "bank", "hedge fund", "ipo", "earnings", "wall street", "nasdaq", "财经",
        "金融", "股市", "美股", "a股", "港股", "基金", "通胀", "央行", "投资", "理财", "股票", "利率", "债券",
        "财报")),
    "crypto": ("finance", ("Crypto", "加密货币"), (
        "bitcoin", "crypto", "cryptocurrency", "ethereum", "blockchain", "stablecoin", "比特币", "加密货币",
        "区块链", "虚拟货币")),
    "economy": ("finance", ("Economy", "经济"), (
        "economy", "economic", "economist", "gdp", "recession", "tariff", "trade war", "unemployment", "经济",
        "关税", "贸易", "失业", "衰退")),
    "business": ("finance", ("Business", "商业"), (
        "business", "startup", "ceo", "acquisition", "merger", "layoff", "revenue", "profit", "retail",
        "e-commerce", "supply chain", "antitrust", "billion-dollar", "企业", "创业", "融资", "收购", "裁员", "营收",
        "上市", "电商", "董事会", "商业")),
    "career": ("", ("Work", "职场"), (
        "career", "hiring", "job interview", "salary", "remote work", "workplace", "resume", "职场", "求职",
        "招聘", "面试", "薪资", "跳槽", "加班", "打工人", "简历")),
    "politics": ("", ("Politics and world news", "时政"), (
        "politics", "political", "election", "president", "prime minister", "parliament", "congress", "senate",
        "government", "minister", "diplomat", "diplomacy", "sanction", "summit", "treaty", "white house",
        "kremlin", "nato", "united nations", "trump", "putin", "xi jinping", "geopolitics", "world news",
        "international", "国际", "政治", "选举", "总统",
        "首相", "议会", "国会", "政府", "外交", "制裁", "峰会", "白宫", "联合国", "特朗普", "普京", "习近平",
        "参议院", "总理")),
    "military": ("", ("Military", "军事"), (
        "military", "army", "navy", "air force", "troops", "missile", "airstrike", "weapon", "war", "warfare",
        "ceasefire", "invasion", "pentagon", "soldier", "drone strike", "军事", "军队", "导弹", "武器", "战争",
        "停火", "袭击", "战机", "航母", "解放军", "国防", "士兵")),
    "society": ("", ("Society", "社会"), (
        "housing", "rent", "wages", "inequality", "immigration", "migrant", "homeless", "welfare", "pension",
        "社会", "民生", "房价", "工资", "养老", "户口", "移民", "就业", "热搜", "网友", "通报")),
    "relationships": ("", ("Relationships", "情感"), (
        "dating", "relationship", "marriage", "wedding", "divorce", "恋爱", "婚姻", "相亲", "分手", "情感",
        "彩礼")),
    "law": ("", ("Law and crime", "法律案件"), (
        "law", "lawsuit", "court", "judge", "trial", "verdict", "police", "crime", "murder", "arrested", "prison",
        "fraud", "supreme court", "attorney", "legislation", "法律", "法院", "案件", "警方", "犯罪", "诈骗", "判决",
        "律师", "起诉", "被捕", "监狱", "嫌疑人", "法案")),
    "environment": ("", ("Climate and environment", "环境气候"), (
        "climate", "climate change", "environment", "environmental", "emission", "carbon", "pollution",
        "renewable", "solar", "wind power", "wildfire", "flood", "drought", "hurricane", "biodiversity",
        "deforestation", "earthquake", "气候", "环境", "环保", "碳排放", "污染", "新能源", "洪水", "干旱", "台风",
        "地震", "能源")),
    "nature": ("", ("Animals and nature", "动物自然"), (
        "animal", "wildlife", "bird", "species", "forest", "ocean", "whale", "shark", "insect", "dinosaur",
        "fossil", "zoo", "tree", "botanical", "birdwatching", "birding", "动物", "野生", "鸟类", "观鸟", "物种",
        "森林", "海洋", "鲸", "恐龙", "化石", "昆虫", "大自然", "植物")),
    "pets": ("", ("Pets", "宠物"), (
        "pet", "dog", "cat", "puppy", "kitten", "宠物", "猫咪", "狗狗", "小猫", "小狗", "养猫", "养狗", "铲屎官")),
    "sports": ("", ("Sports", "运动"), (
        "sport", "football", "soccer", "nba", "nfl", "mlb", "basketball", "baseball", "tennis", "golf", "olympic",
        "f1", "formula 1", "world cup", "premier league", "champions league", "championship", "tournament",
        "athlete", "coach", "league", "espn", "运动", "体育", "足球", "篮球", "网球", "奥运", "世界杯", "比赛",
        "球员", "球队", "冠军", "联赛", "乒乓", "羽毛球", "国足")),
    "cars": ("", ("Cars", "汽车"), (
        "car", "ev", "electric vehicle", "tesla", "byd", "toyota", "automaker", "suv", "sedan", "self-driving",
        "汽车", "电动车", "新能源车", "特斯拉", "比亚迪", "车型", "驾驶", "自动驾驶")),
    "education": ("", ("Education", "教育"), (
        "education", "school", "university", "college", "student", "teacher", "exam", "classroom", "教育", "学校",
        "大学", "学生", "老师", "高考", "考研", "留学")),
    "parenting": ("", ("Parenting", "育儿"), (
        "parenting", "toddler", "newborn", "育儿", "宝宝", "带娃", "亲子", "母婴", "孕期", "幼儿园")),
    "humor": ("", ("Humor", "幽默"), (
        "funny", "comedy", "comedian", "meme", "joke", "satire", "hilarious", "webcomic", "xkcd", "幽默", "搞笑",
        "沙雕",
        "段子", "整活", "爆笑", "喜剧", "脱口秀", "鬼畜", "趣闻", "好玩")),
    "celebrity": ("", ("Celebrities", "明星八卦"), (
        "celebrity", "celebrities", "gossip", "royal family", "paparazzi", "明星", "八卦", "娱乐圈", "网红", "偶像",
        "粉丝", "绯闻", "爱豆", "塌房")),
    "diy": ("", ("Home and making", "家居手作"), (
        "diy", "gardening", "garden", "houseplant", "succulent", "bonsai", "woodworking", "renovation", "crafts",
        "knitting", "家居", "装修", "园艺", "盆栽", "绿植", "多肉", "养花", "种花", "种菜", "手工", "收纳", "手作")),
}

# The fifteen offered on the first run, in the order the page shows them.
OFFERED = ("tech", "ai", "games", "anime", "music", "film", "science", "finance", "design", "food", "sports",
           "history", "programming", "travel", "books")
# At most this many subjects per thing: those its words name twice (once in the title), or the one named most.
MOST = 3
TITLE = SURE = 2


# Traditional characters and their Simplified ones, for the lexicon's own words and the commonest others
# (not a full converter): a title in Traditional Chinese is read by the same words.
_HANT = ("專专 業业 絲丝 臨临 為为 舉举 樂乐 習习 書书 爭争 亞亚 親亲 價价 倫伦 體体 債债 兒儿 關关 養养 內内 軍军 "
         "決决 減减 擊击 創创 製制 劇剧 動动 區区 醫医 華华 單单 賣卖 衛卫 廳厅 歷历 曆历 參参 發发 髮发 變变 臺台 "
         "後后 員员 園园 國国 場场 塊块 聲声 處处 頭头 奧奥 妝妆 娛娱 嬰婴 學学 寶宝 寵宠 宮宫 導导 爾尔 師师 帶带 "
         "幣币 庫库 開开 彈弹 錄录 總总 戀恋 戲戏 戰战 戶户 護护 報报 擬拟 據据 攝摄 搖摇 擼撸 數数 時时 顯显 術术 "
         "機机 鬆松 夢梦 氣气 汙污 濟济 遊游 滾滚 點点 煉炼 鍊炼 熱热 無无 愛爱 狀状 獄狱 貓猫 環环 電电 畫画 療疗 "
         "監监 碼码 禮礼 種种 稅税 競竞 筆笔 築筑 簡简 籃篮 類类 紀纪 納纳 細细 經经 繪绘 絡络 統统 緋绯 維维 綜综 "
         "編编 網网 聯联 職职 膚肤 腫肿 脹胀 腦脑 脫脱 藝艺 榮荣 藥药 營营 慮虑 虛虚 蟲虫 襲袭 裝装 視视 覽览 計计 "
         "議议 記记 論论 設设 評评 詐诈 訴诉 譯译 試试 詩诗 話话 語语 說说 説说 讀读 譜谱 財财 貨货 質质 購购 貿贸 "
         "資资 賽赛 車车 軟软 輕轻 輯辑 達达 運运 進进 遠远 選选 遺遗 鬱郁 鋼钢 鐵铁 鏟铲 鏈链 鍋锅 鍛锻 鏡镜 長长 "
         "間间 聞闻 閱阅 隊队 際际 隱隐 預预 頻频 風风 飪饪 飯饭 館馆 馬马 駛驶 駕驾 騎骑 騙骗 鯨鲸 鳥鸟 龍龙 測测 "
         "廚厨 麵面 傳传 會会 與与 這这 個个 們们 對对 還还 過过 裡里 裏里 來来 見见 覺觉 應应 東东 門门 問问 題题 "
         "請请 謝谢 沒没 廠厂 產产 現现 實实 灣湾 島岛 齊齐 歲岁 嚴严 壓压 團团 圖图 權权 歐欧 漢汉 災灾 獨独 獲获 "
         "紅红 級级 結结 給给 絕绝 續续 義义 聖圣 興兴 舊旧 蘇苏 號号 補补 觀观 規规 訊讯 證证 識识 調调 豐丰 負负 "
         "責责 費费 贏赢 輪轮 轉转 輸输 輛辆 邊边 適适 郵邮 釋释 針针 鐘钟 銀银 錯错 難难 韓韩 頁页 順顺 領领 額额 "
         "飛飞 驗验 魚鱼 黃黄 齡龄 殺杀 槍枪 罰罚 審审 檢检 訟讼 憲宪 黨党 烏乌 艦舰 衝冲 談谈 協协 銷销 虧亏 賺赚 "
         "漲涨 貸贷 匯汇 險险 積积 極极 颱台 綠绿 獸兽 樹树 農农 糧粮 飲饮 湯汤 雞鸡 鴨鸭 豬猪 蝦虾 醬酱 餅饼 蘋苹 "
         "葉叶 雲云 寫写 課课 獎奖 鐵铁 媽妈 聽听 讓让 誰谁 樣样 麼么 該该 將将 從从")
_SIMPLIFIED = str.maketrans({pair[0]: pair[1] for pair in _HANT.split()})


def _word(word: str) -> str:
    # A Latin word is found whole, with or without a plural s; Chinese has no spaces to look for.
    if word.isascii():
        return r"(?<![a-z0-9])" + re.escape(word) + r"(?:s|es)?(?![a-z0-9])"
    return re.escape(word)


_PATTERNS = {key: re.compile("|".join(_word(w) for w in sorted(words, key=len, reverse=True)))
             for key, (_, _, words) in SUBJECTS.items()}
# Set phrases that hold a subject's word without being about it: "the art of", a promo code, Blue Planet,
# a hot dog. They are taken out before that subject's words are looked for.
NOT = {"art": ("art of", "state of the art", "state-of-the-art"),
       "programming": ("promo code", "coupon code", "discount code", "voucher code", "referral code", "dress code",
                       "zip code", "postal code", "qr code"),
       "space": ("blue planet", "planet earth", "lonely planet"),
       "pets": ("hot dog",),
       "outdoors": ("钓鱼邮件", "钓鱼网站", "钓鱼链接", "钓鱼短信", "钓鱼执法"),
       "gadgets": ("potato chip", "chocolate chip", "blue chip"),
       "military": ("price war", "culture war", "trade war", "star war", "console war"),
       "music": ("pop-up", "pop up", "pop culture")}
_NOT = {key: re.compile("|".join(_word(w) for w in phrases)) for key, phrases in NOT.items()}
# A link with the short label before it ("Instagram: https://…"): a description's links and promotions say
# nothing of what the thing is about.
_LINKS = re.compile(r"(?:[^\s:：|]{1,24}\s*[:：|]\s*)?(?:https?://|www\.)\S+")
_NAMED: dict[str, list[str]] = {}
for _key, (_under, _names, _words) in SUBJECTS.items():
    for _name in (_key, *_names, *_words):
        _NAMED.setdefault(_name.casefold(), []).append(_key)


def under(key: str) -> list[str]:
    """A subject and the finer ones under it."""
    return [key] + [k for k, row in SUBJECTS.items() if row[0] == key]


def words(key: str) -> tuple:
    """Every word that finds an offered topic: its own and its finer subjects'."""
    return tuple(dict.fromkeys(w for k in under(key) for w in SUBJECTS[k][2]))


@functools.lru_cache(maxsize=4096)
def mentioned(title: str, rest: str = "") -> dict:
    """Every subject a thing's words name, with how often; a word in the title counts TITLE times one in
    the rest."""
    title = title.casefold().translate(_SIMPLIFIED)
    rest = _LINKS.sub(" ", rest.casefold().translate(_SIMPLIFIED))
    found = {}
    for key, pattern in _PATTERNS.items():
        head, tail = (_NOT[key].sub(" ", title), _NOT[key].sub(" ", rest)) if key in _NOT else (title, rest)
        n = TITLE * len(set(pattern.findall(head))) + len(set(pattern.findall(tail)))
        if n:
            found[key] = n
    return found


def of(title: str, rest: str = "") -> tuple:
    """The subjects a thing is about, most named first, MOST at most. One word in passing does not make a
    subject unless nothing says more."""
    found = mentioned(title, rest)
    ordered = sorted(found, key=lambda k: -found[k])[:MOST]
    return tuple([k for k in ordered if found[k] >= SURE] or ordered[:1])


# Everyday words a person says for a subject that are too short or too loose to look for in a title
# ("猫" is in 熊猫, "车" in 车间): they stand for the subject only as the person's own word.
SAID = {"猫": "pets", "猫猫": "pets", "狗": "pets", "车": "cars", "球": "sports", "看球": "sports", "剧": "film",
        "追剧": "film", "番": "anime", "追番": "anime", "画": "art", "画画": "art", "书": "books", "看书": "books",
        "歌": "music", "听歌": "music", "吃的": "food", "做菜": "food", "甜点": "food", "星星": "space",
        "看星星": "space", "星空": "space", "炒股": "finance", "出去玩": "travel", "拍照": "photography",
        "打仗": "military", "三国": "history", "战国": "history", "春秋": "history"}
# Everyday words not looked for inside a longer phrase: too often part of another word (地球, 番茄, 单车).
LOOSE = ("球", "番", "车")


def _plain(word: str) -> str:
    return " ".join(str(word).casefold().translate(_SIMPLIFIED).split())


@functools.lru_cache(maxsize=1024)
def parts(word: str) -> tuple:
    """The subjects a person's own word stands for, one group for each subject it names, each group that
    subject with the finer ones under it. A subject's key, name or one of its words, or an everyday word for
    one, is one group; a phrase has a group for each subject it holds ("AI 绘画" is AI and art; "太空探索"
    holds 太空), or failing those for each everyday word it holds ("撸猫" holds 猫); "国际新闻" holds none."""
    word = _plain(word)
    keys = _NAMED.get(word) or ([SAID[word]] if word in SAID else [])
    if keys:
        return (tuple(dict.fromkeys(k for key in keys for k in under(key))),)
    keys = list(of(word)) or [key for said, key in SAID.items() if said not in LOOSE and re.search(_word(said), word)]
    return tuple(tuple(under(key)) for key in dict.fromkeys(keys))


def named(word: str) -> tuple:
    """Every subject a person's own word stands for."""
    return tuple(dict.fromkeys(k for group in parts(word) for k in group))


@functools.lru_cache(maxsize=1024)
def _phrase(word: str) -> re.Pattern:
    return re.compile(r"\s*".join(_word(part) for part in _plain(word).split()))


def whole(word: str) -> bool:
    """A subject's key, name or one of its words, or an everyday word for one, rather than a phrase."""
    return _plain(word) in _NAMED or _plain(word) in SAID


def holds(word: str, on: set, text: str) -> bool:
    """Whether a thing on the subjects `on`, whose words are `text`, is on a person's word, taken as one
    interest: a word that is one subject's, when the thing is on that subject; a phrase, when the thing says
    the phrase or is on every subject the phrase holds; a word that holds none, when the thing says it."""
    groups = parts(word)
    if whole(word):
        return bool(set(groups[0]) & on)
    return bool(_phrase(word).search(_plain(text)) or (groups and all(set(group) & on for group in groups)))


def name(key: str, lang: str) -> str:
    names = SUBJECTS[key][1]
    return names[1] if str(lang).split("-")[0].lower() == "zh" else names[0]
