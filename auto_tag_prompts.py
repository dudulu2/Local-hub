from __future__ import annotations

# Starter packs are small, editable defaults for a media library. The UI may
# customize both the tag name and the description before analysis. Descriptions
# are intentionally plain language so they can be turned into text prompts by
# the semantic encoder without locking users into a rigid taxonomy.
STARTER_TAG_PACKS: dict[str, dict] = {
    "gaming": {
        "label": "游戏录像",
        "tags": {
            "剧情": "以剧情、过场或故事推进为主要内容的游戏片段。",
            "战斗": "明显包含持续战斗或交火的游戏片段。",
            "Boss": "包含正式 Boss 或首领级敌人的战斗，不把普通精英怪算作 Boss。",
            "探索": "以地图探索、发现地点或自由移动为主要内容。",
            "建造": "包含基地、建筑、生产线或明显的建造过程。",
            "多人": "明显包含多人联机、合作或对战。",
            "高光": "值得保留的精彩操作、关键胜利或明显高光时刻。",
            "搞笑": "主要价值是搞笑、意外或有趣反应。",
            "教程": "以教学、攻略、演示玩法或解释机制为主。",
            "Bug": "包含明显游戏故障、穿模、异常物理或其他 Bug。",
        },
    },
    "life": {
        "label": "生活视频",
        "tags": {
            "家人": "以家庭成员或家庭活动为主要内容。",
            "朋友": "以朋友聚会、朋友互动或共同活动为主要内容。",
            "旅行": "旅行途中、景点、酒店、交通或旅行记录。",
            "聚会": "聚餐、派对、庆祝或多人线下聚会。",
            "宠物": "宠物或家养动物是画面主要内容。",
            "美食": "食物、餐厅、烹饪或用餐是主要内容。",
            "风景": "自然景观或明显以景色观赏为主要内容。",
            "运动": "运动、健身或户外运动活动。",
            "日常": "普通生活记录，没有更明确的主题。",
            "纪念": "生日、毕业、婚礼、节日等值得纪念的事件。",
        },
    },
    "film": {
        "label": "影视收藏",
        "tags": {
            "电影": "电影、电影片段或完整电影内容。",
            "电视剧": "电视剧、网剧或连续剧集内容。",
            "纪录片": "纪录片、纪实节目或知识纪实内容。",
            "动画": "动画、动漫、卡通或明显非真人动画内容。",
            "真人": "真人影视或真人拍摄内容。",
            "动作": "动作场面、追逐、打斗或激烈冲突占明显比重。",
            "喜剧": "以幽默、喜剧效果或轻松搞笑为主要特点。",
            "悬疑": "悬疑、推理、犯罪调查或紧张谜题氛围明显。",
            "科幻": "科幻世界、未来科技、太空或明显科幻设定。",
            "高质量": "用户认为画面、内容或收藏价值较高的影视内容。",
        },
    },
    "footage": {
        "label": "视频素材",
        "tags": {
            "人物": "人物是主要拍摄主体。",
            "城市": "城市街道、建筑、交通或城市景观。",
            "自然": "山水、森林、海洋、草地或其他自然环境。",
            "室内": "主要场景位于室内。",
            "户外": "主要场景位于户外。",
            "航拍": "明显为无人机或高空航拍视角。",
            "特写": "主体以近距离或特写镜头为主。",
            "运动镜头": "镜头或主体存在明显运动，适合作为动态素材。",
            "夜景": "夜晚、低光或城市夜景是主要画面。",
            "可用素材": "用户认为适合后续剪辑、引用或再次使用的素材。",
        },
    },
    "learning": {
        "label": "学习资料",
        "tags": {
            "课程": "完整课程、章节课程或系统教学内容。",
            "教程": "解决具体问题、展示操作步骤或技能教学。",
            "编程": "编程、代码、软件工程或开发相关内容。",
            "设计": "设计、绘画、建模、UI 或视觉创作相关内容。",
            "AI": "人工智能、机器学习、生成式 AI 或相关工具。",
            "软件": "软件使用、工具操作或应用功能说明。",
            "讲座": "演讲、公开课、会议分享或讲座。",
            "笔记": "以复习、知识总结或笔记整理为主要用途。",
            "案例": "案例拆解、项目复盘或实例分析。",
            "待复习": "用户希望之后再次学习或复习的内容。",
        },
    },
    "adult": {
        "label": "成人内容",
        "tags": {
            "单人": "主要只有一名人物。",
            "多人": "主要有两名或更多人物。",
            "情侣": "以情侣或双人互动为主要内容。",
            "剧情": "具有明显剧情、角色关系或情境设置。",
            "角色扮演": "有明显角色扮演、服装造型或情境扮演。",
            "动画": "成人向动画、动漫或计算机生成动画内容。",
            "自拍视频": "自拍视频、业余拍摄或明显个人记录风格。",
            "专业制作": "灯光、机位、剪辑或制作流程明显较专业。",
            "室内": "主要场景位于室内。",
            "户外": "主要场景位于户外。",
            "系列": "属于同一系列、同一主题或连续编号内容。",
            "收藏": "用户认为值得长期保留的内容。",
        },
    },
    "all": {
        "label": "全部视频",
        "tags": {
            "人物": "人物是主要画面主体。",
            "风景": "自然或城市景观是主要内容。",
            "动物": "动物或宠物是主要内容。",
            "游戏": "游戏画面、游戏录像或游戏直播内容。",
            "影视": "电影、电视剧、综艺或其他影视内容。",
            "生活": "日常生活、旅行、聚会或个人记录。",
            "教程": "教学、攻略、软件演示或知识讲解。",
            "音乐": "音乐演奏、MV、演唱或音乐相关内容。",
            "运动": "体育、健身或运动活动。",
            "搞笑": "以幽默、搞笑或有趣瞬间为主要价值。",
            "动画": "动画、动漫、卡通或 CG 动画内容。",
            "成人": "明显属于成人向私人媒体。",
            "其他": "没有更合适现有 Tag 的其他内容。",
        },
    },
    "custom": {"label": "自定义", "tags": {}},
}

DEFAULT_PACK_ID = "all"


def pack_payload(pack_id: str) -> dict:
    key = pack_id if pack_id in STARTER_TAG_PACKS else DEFAULT_PACK_ID
    row = STARTER_TAG_PACKS[key]
    return {
        "id": key,
        "label": row["label"],
        "tags": [{"tag": tag, "description": description} for tag, description in row["tags"].items()],
    }


def prompts_from_tags(tags: list[dict]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for row in tags:
        tag = str(row.get("tag", "")).strip()
        description = str(row.get("description", "")).strip()
        if not tag:
            continue
        text = description or f"This video matches the category {tag}."
        result[tag] = (
            text,
            f"A representative video frame for the tag {tag}. {text}",
            f"This scene should be classified as {tag}. {text}",
        )
    return result


# Backward-compatible v1 vocabulary. Existing tests and older metadata can
# still use this, while AI Tag V2 builds prompts from the selected starter pack.
DEFAULT_TAG_PROMPTS: dict[str, tuple[str, ...]] = prompts_from_tags(pack_payload(DEFAULT_PACK_ID)["tags"])
