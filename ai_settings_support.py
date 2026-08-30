from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

import ai_balanced_siglip
import ai_taxonomy_v2


def _tag(tag: str, *prompts: str) -> dict:
    return {"tag": tag, "prompts": list(prompts)}


DEFAULT_GROUPS = [
    {
        "id": "all",
        "name": "全部视频",
        "enabled": True,
        "tags": [
            _tag("室内", "An indoor video scene.", "The scene is inside a room or building."),
            _tag("户外", "An outdoor video scene.", "The scene is outside in the open air."),
            _tag("单人", "One person is visible in the video.", "A single person is the main subject."),
            _tag("多人", "Multiple people are visible in the video.", "A group of people appears in the scene."),
            _tag("真人", "Live action footage of real people or real objects.", "A real-world camera recording rather than animation."),
            _tag("动画", "Animated, anime, cartoon, or computer generated artwork.", "The video is primarily animation or illustrated content."),
            _tag("白天", "A daytime scene with daylight.", "The video is recorded during the day."),
            _tag("夜晚", "A nighttime or dark evening scene.", "The video is recorded at night."),
        ],
    },
    {
        "id": "life",
        "name": "生活",
        "enabled": True,
        "tags": [
            _tag("家庭", "A family or everyday home-life scene.", "People spending time with family at home."),
            _tag("美食", "Food, cooking, eating, or a meal is an important part of the scene.", "A food or dining video."),
            _tag("宠物", "A pet such as a cat or dog is visible.", "A domestic animal is the main subject."),
            _tag("购物", "Shopping, stores, products, or buying goods.", "A retail or shopping scene."),
            _tag("家居", "Home interior, furniture, cleaning, decorating, or household activity.", "A household or home organization scene."),
            _tag("工作", "Workplace, office work, professional activity, or a job-related scene.", "People are working or doing professional tasks."),
            _tag("社交", "Friends or people socializing and talking together.", "A casual social interaction or gathering."),
        ],
    },
    {
        "id": "study",
        "name": "学习",
        "enabled": True,
        "tags": [
            _tag("阅读", "Reading a book, document, article, or study material.", "A person is reading or reviewing written material."),
            _tag("课堂", "A classroom, lesson, school, or teaching scene.", "Students or a teacher in an educational setting."),
            _tag("写作", "Writing notes, handwriting, typing text, or composing content.", "A person is writing or taking notes."),
            _tag("电脑", "A computer, laptop, monitor, coding, or desktop work is central to the scene.", "A person is using a computer."),
            _tag("会议", "A meeting, group discussion, conference, or team collaboration.", "People are participating in a meeting."),
            _tag("演讲", "A speech, lecture, presentation, or public speaking scene.", "A person is presenting or speaking to an audience."),
            _tag("教程", "An instructional demonstration, tutorial, lesson, or how-to video.", "The video is teaching how to do something."),
        ],
    },
    {
        "id": "scenery",
        "name": "风景",
        "enabled": True,
        "tags": [
            _tag("自然", "Natural scenery, vegetation, wilderness, or an outdoor landscape.", "Nature is the main visual subject."),
            _tag("城市", "City streets, buildings, urban architecture, or a city skyline.", "An urban city scene."),
            _tag("海边", "Sea, ocean, beach, coast, or waterfront scenery.", "A beach or seaside scene."),
            _tag("山景", "Mountains, hills, valleys, or elevated natural scenery.", "A mountain landscape."),
            _tag("夜景", "Night city lights, illuminated buildings, or nighttime scenery.", "A scenic view at night with lights."),
            _tag("公园", "A park, garden, green public space, or landscaped outdoor area.", "A park or garden scene."),
            _tag("旅行", "Travel, tourism, sightseeing, transportation, or visiting a destination.", "A travel or sightseeing video."),
        ],
    },
    {
        "id": "entertainment",
        "name": "娱乐",
        "enabled": True,
        "tags": [
            _tag("游戏", "Video game footage, gameplay, gaming screens, or people playing games.", "A gaming or gameplay video."),
            _tag("音乐", "Music performance, instruments, singing, concert, or music-related content.", "A music or singing scene."),
            _tag("舞蹈", "Dancing, choreography, or a dance performance.", "People are dancing."),
            _tag("体育", "Sports, exercise, athletic activity, competition, or training.", "A sports or fitness scene."),
            _tag("聚会", "Party, celebration, social event, or festive gathering.", "People are at a party or celebration."),
            _tag("影视", "Movie, television, drama, cinematic footage, or filmed entertainment.", "A movie or television style scene."),
            _tag("直播", "Live streaming, webcam presentation, streamer, podcast, or creator talking to an audience.", "A livestream or online creator scene."),
        ],
    },
    {
        "id": "adult",
        "name": "色情",
        "enabled": False,
        "tags": [
            _tag("成人内容", "Adult sexual or erotic content intended for adults.", "An adult-oriented intimate or sexual scene."),
            _tag("裸露", "Visible adult nudity or substantial exposed intimate body areas.", "A scene containing adult nudity."),
            _tag("性感", "Suggestive, erotic, or sexually provocative posing or presentation.", "A sexually suggestive adult-oriented scene."),
            _tag("内衣", "Lingerie, underwear, or intimate apparel is visually prominent.", "A person wearing lingerie or intimate clothing."),
            _tag("亲密行为", "Adults showing intimate romantic or sexual behavior.", "An intimate adult couple scene."),
        ],
    },
]


# v2 replaces the small starter taxonomy with a professional built-in set.
# The old literal above is intentionally retained as historical source context;
# runtime defaults and migrations use the v2 taxonomy below.
DEFAULT_GROUPS = copy.deepcopy(ai_taxonomy_v2.PROFESSIONAL_GROUPS)

DEFAULT_SETTINGS = {
    "version": 2,
    "autoAnalyzeLibrary": True,
    "backgroundMode": "balanced",
    "showViewerButton": True,
    "onboardingCompleted": False,
    "aiOptIn": False,
    "groups": DEFAULT_GROUPS,
}


def _clean_text(value, *, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def normalize_settings(raw) -> dict:
    source = ai_taxonomy_v2.upgrade_settings(raw if isinstance(raw, dict) else {})
    result = {
        "version": 2,
        "autoAnalyzeLibrary": bool(source.get("autoAnalyzeLibrary", DEFAULT_SETTINGS["autoAnalyzeLibrary"])),
        "backgroundMode": str(source.get("backgroundMode", DEFAULT_SETTINGS["backgroundMode"])),
        "showViewerButton": bool(source.get("showViewerButton", DEFAULT_SETTINGS["showViewerButton"])),
        "onboardingCompleted": bool(source.get("onboardingCompleted", DEFAULT_SETTINGS["onboardingCompleted"])),
        "aiOptIn": bool(source.get("aiOptIn", DEFAULT_SETTINGS["aiOptIn"])),
        "groups": [],
    }
    if result["backgroundMode"] not in {"idle", "balanced"}:
        result["backgroundMode"] = "balanced"

    groups = source.get("groups")
    if not isinstance(groups, list):
        groups = copy.deepcopy(DEFAULT_GROUPS)

    seen_group_ids: set[str] = set()
    for index, group in enumerate(groups[:20]):
        if not isinstance(group, dict):
            continue
        group_id = _clean_text(group.get("id") or f"group-{index+1}", limit=40).casefold().replace(" ", "-")
        if not group_id or group_id in seen_group_ids:
            group_id = f"group-{index+1}"
        seen_group_ids.add(group_id)
        name = _clean_text(group.get("name") or group_id, limit=24)
        tags_out = []
        seen_tags: set[str] = set()
        tags = group.get("tags") if isinstance(group.get("tags"), list) else []
        for tag_row in tags[:30]:
            if not isinstance(tag_row, dict):
                continue
            tag_name = _clean_text(tag_row.get("tag"), limit=32)
            key = tag_name.casefold()
            if not tag_name or key in seen_tags:
                continue
            seen_tags.add(key)
            prompts = []
            raw_prompts = tag_row.get("prompts") if isinstance(tag_row.get("prompts"), list) else []
            for prompt in raw_prompts[:8]:
                clean = _clean_text(prompt, limit=180)
                if clean and clean not in prompts:
                    prompts.append(clean)
            if not prompts:
                prompts = [f"A video frame related to {tag_name}."]
            tags_out.append({"tag": tag_name, "prompts": prompts})
        result["groups"].append({
            "id": group_id,
            "name": name,
            "enabled": bool(group.get("enabled", True)),
            "tags": tags_out,
        })

    if not result["groups"]:
        result["groups"] = copy.deepcopy(DEFAULT_GROUPS)
    return result


def prompt_map(settings: dict) -> dict[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for group in settings.get("groups", []):
        if not group.get("enabled"):
            continue
        for row in group.get("tags", []):
            tag = str(row.get("tag", "")).strip()
            if not tag:
                continue
            key = tag.casefold()
            labels.setdefault(key, tag)
            bucket = merged.setdefault(key, [])
            for prompt in row.get("prompts", []):
                text = str(prompt).strip()
                if text and text not in bucket:
                    bucket.append(text)
    return {labels[key]: tuple(values) for key, values in merged.items() if values}


class AISettingsStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.path = self.root / ".localhub" / "ai-settings.json"
        self.lock = threading.RLock()
        self._settings = self._load()
        ai_balanced_siglip.set_mode(self.root, self._settings.get("backgroundMode", "balanced"))

    def _load(self) -> dict:
        try:
            return normalize_settings(json.loads(self.path.read_text("utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return normalize_settings(DEFAULT_SETTINGS)

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self._settings)

    def save(self, raw) -> dict:
        clean = normalize_settings(raw)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), "utf-8")
            os.replace(temp, self.path)
            self._settings = clean
            ai_balanced_siglip.set_mode(self.root, clean.get("backgroundMode", "balanced"))
            return copy.deepcopy(clean)

    def prompts(self) -> dict[str, tuple[str, ...]]:
        return prompt_map(self.snapshot())
