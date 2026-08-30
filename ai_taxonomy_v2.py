from __future__ import annotations

import copy


def _tag(tag: str, *prompts: str) -> dict:
    return {"tag": tag, "prompts": list(prompts)}


# Professional taxonomy v2.  The group ids deliberately keep the original
# LocalHub ids so existing enable/disable preferences can be migrated safely.
# Every built-in group contains at least 20 distinct candidates.
PROFESSIONAL_GROUPS = [
    {
        "id": "all",
        "name": "全部视频",
        "enabled": True,
        "tags": [
            _tag("室内", "An indoor scene inside a room or building.", "Interior footage with walls, ceiling, furniture, or an indoor venue."),
            _tag("户外", "An outdoor scene in open air.", "Exterior footage outside a building."),
            _tag("白天", "A daytime scene lit by daylight.", "Outdoor or indoor footage clearly recorded during the day."),
            _tag("夜晚", "A nighttime or late-evening scene.", "Dark night footage with artificial lights or night sky."),
            _tag("单人", "Exactly one visible person is the main subject.", "A single person appears prominently in the frame."),
            _tag("双人", "Exactly two people are visible as the main subjects.", "A two-person scene or conversation."),
            _tag("多人", "Three or more people are visibly present.", "A group of people appears together in the scene."),
            _tag("无人", "No person is visibly present in the scene.", "An empty environment, object shot, landscape, or screen without people."),
            _tag("真人", "Live-action camera footage of real people or real-world objects.", "Photoreal real-world footage rather than animation."),
            _tag("动画", "Animated, illustrated, anime, cartoon, or computer-generated imagery.", "The main visual content is not live-action footage."),
            _tag("竖屏", "A portrait-orientation vertical video composition.", "Vertical short-video framing designed for a phone screen."),
            _tag("横屏", "A landscape-orientation horizontal video composition.", "Wide horizontal video framing."),
            _tag("自拍", "A selfie-style recording made by the person on camera.", "Front-facing phone camera or arm-length creator footage."),
            _tag("固定机位", "A locked-off camera with a stable fixed viewpoint.", "Tripod or stationary camera footage with little camera movement."),
            _tag("手持拍摄", "Handheld camera footage with natural camera movement.", "A moving handheld phone or camera viewpoint."),
            _tag("航拍", "Aerial or drone footage from high above the ground.", "Bird's-eye drone camera view."),
            _tag("屏幕录制", "A computer or phone screen recording is the main visual content.", "Software interface, desktop, mobile UI, or gameplay captured directly from a screen."),
            _tag("近景特写", "A close-up shot filling the frame with a face, object, or detail.", "Tight framing focused on fine visual detail."),
            _tag("中景", "A medium shot showing a person roughly from waist or chest upward.", "Medium framing balancing subject and surrounding context."),
            _tag("全景", "A wide shot showing the full environment or full body with substantial background.", "Wide establishing view of a scene."),
            _tag("低光环境", "A dim, dark, low-light visual scene.", "Low illumination with deep shadows or dark exposure."),
            _tag("高亮环境", "A bright, strongly illuminated scene.", "High-key lighting, bright daylight, or a very luminous environment."),
            _tag("高速运动", "Fast physical motion, rapid action, or strongly moving subjects.", "High-motion action footage rather than a calm static scene."),
            _tag("静态场景", "A mostly static scene with little subject or camera motion.", "Calm stationary footage without significant movement."),
        ],
    },
    {
        "id": "life",
        "name": "生活",
        "enabled": True,
        "tags": [
            _tag("家庭生活", "Everyday family life inside or around a home.", "Family members doing normal household activities."),
            _tag("做饭", "Cooking or preparing food in a kitchen.", "Hands, cookware, ingredients, or a person actively making a meal."),
            _tag("吃饭", "People eating a meal or tasting food.", "Dining, eating, or food tasting is the central activity."),
            _tag("咖啡茶饮", "Coffee, tea, cafe drinks, or beverage preparation.", "A cafe drink or beverage is visually central."),
            _tag("宠物", "A pet such as a dog or cat is a main subject.", "Domestic companion animals are prominently visible."),
            _tag("购物", "Shopping for products in stores, malls, or markets.", "Retail browsing, choosing goods, or purchasing products."),
            _tag("家居", "Home interior, furniture, decoration, or household living space.", "Residential interior and home lifestyle content."),
            _tag("清洁", "Cleaning a room, appliance, surface, or household item.", "Vacuuming, wiping, washing, or professional cleaning work."),
            _tag("收纳", "Home organization, decluttering, folding, or storage arrangement.", "Organizing possessions into drawers, shelves, boxes, or closets."),
            _tag("育儿", "Parenting, childcare, or caring for a baby or child.", "Daily activities involving parents and young children."),
            _tag("通勤", "Daily commuting to work or school.", "Travel by subway, bus, walking, bicycle, or car as a routine commute."),
            _tag("驾驶", "Driving a car or vehicle from inside or around the vehicle.", "A driver operating a vehicle on the road."),
            _tag("健身", "Personal exercise, gym training, or fitness workout.", "Workout movements, weights, treadmill, or fitness routine."),
            _tag("美妆", "Makeup application, cosmetics, skincare, or beauty routine.", "A beauty tutorial or cosmetic product use."),
            _tag("穿搭", "Fashion outfit, clothing styling, or outfit-of-the-day content.", "A person presenting or changing clothing and accessories."),
            _tag("约会", "A romantic date or couple spending leisure time together.", "Two partners in a dating or romantic social setting."),
            _tag("朋友聚会", "Friends gathering, chatting, eating, or spending leisure time together.", "A casual social gathering among friends."),
            _tag("旅行日常", "Everyday travel diary or vacation lifestyle footage.", "A traveler documenting a trip, hotel, transport, or destination."),
            _tag("街头生活", "Street-life footage showing pedestrians, vendors, or everyday urban activity.", "Daily life happening on a street or public outdoor space."),
            _tag("手工DIY", "Hands-on crafting, repair, making, or DIY activity.", "A person manually building, crafting, or modifying an object."),
            _tag("园艺", "Gardening, planting, flowers, yard work, or caring for plants.", "A person working with plants, soil, pots, or a garden."),
            _tag("健康护理", "Wellness, personal care, massage, therapy, or non-emergency health routine.", "Personal health maintenance or care activity."),
            _tag("酒店住宿", "Hotel room, resort stay, accommodation tour, or lodging experience.", "Travel accommodation or hotel lifestyle footage."),
            _tag("开箱体验", "Unboxing and first-use experience of a newly opened product.", "Opening packaging and showing the contents for the first time."),
        ],
    },
    {
        "id": "study",
        "name": "学习",
        "enabled": True,
        "tags": [
            _tag("阅读", "Reading a book, document, article, or study material.", "A person visibly reading printed or digital text."),
            _tag("课堂", "A classroom lesson with students, teacher, or school setting.", "Formal teaching inside a classroom."),
            _tag("写作", "Writing notes, handwriting, or composing text.", "A person actively writing on paper, board, tablet, or computer."),
            _tag("电脑办公", "Office work using a desktop or laptop computer.", "Professional computer work at a desk."),
            _tag("会议", "A business or team meeting with multiple participants.", "People discussing work around a table or on a video call."),
            _tag("演讲", "A person delivering a speech or presentation to an audience.", "Public speaking on a stage, podium, or presentation space."),
            _tag("教程", "A step-by-step instructional how-to demonstration.", "The video explicitly teaches how to perform a task."),
            _tag("在线课程", "An online lesson, remote lecture, or e-learning session.", "A teacher or educational screen in a digital course format."),
            _tag("编程", "Programming, source code, software development, or coding tutorial.", "Code editor, terminal, IDE, or developer workflow is central."),
            _tag("数学", "Mathematics, equations, formulas, geometry, or calculation teaching.", "A math lesson with numbers or equations."),
            _tag("科学实验", "A scientific experiment or laboratory demonstration.", "Hands-on science procedure with instruments, samples, or measurements."),
            _tag("语言学习", "Learning or teaching a spoken or written language.", "Vocabulary, pronunciation, grammar, or language lesson content."),
            _tag("考试答题", "Taking a test, solving exam questions, or reviewing answers.", "Exam papers, quiz questions, or problem-solving practice."),
            _tag("图书馆", "A library environment with bookshelves, study desks, or reading areas.", "Study or research taking place in a library."),
            _tag("实验室", "A laboratory, research room, or technical lab environment.", "Scientific or engineering work performed in a lab."),
            _tag("PPT演示", "A slide presentation or PowerPoint-style presentation is visible.", "Presentation slides, projector screen, or slide deck content."),
            _tag("软件教学", "Tutorial about using software, an app, or a digital tool.", "Screen-based instruction demonstrating software operations."),
            _tag("设计绘图", "Graphic design, illustration, CAD, drawing, or visual design work.", "A person creating visual artwork or technical drawings."),
            _tag("工程技术", "Engineering, machinery, electronics, construction, or technical instruction.", "Technical engineering work or explanation."),
            _tag("商业分析", "Business analysis, management, strategy, charts, or professional consulting content.", "A business presentation analyzing operations, markets, or strategy."),
            _tag("财经讲解", "Finance, investing, markets, economics, or financial education.", "Charts, stocks, money, or economic analysis are central."),
            _tag("法律知识", "Legal education, law explanation, contracts, or courtroom-related knowledge.", "A legal professional or educational explanation of law."),
            _tag("医学科普", "Medical or health science education intended to explain a condition or treatment.", "Doctor, anatomy, clinic, or medical educational content."),
            _tag("职业培训", "Professional skills training, workplace instruction, or vocational education.", "Structured training for a job, trade, or professional skill."),
        ],
    },
    {
        "id": "scenery",
        "name": "风景",
        "enabled": True,
        "tags": [
            _tag("城市街道", "A city street with roads, sidewalks, buildings, or urban traffic.", "Street-level urban city scenery."),
            _tag("商业街", "A shopping street or dense commercial pedestrian area.", "Storefronts, signs, retail streets, or busy commercial district."),
            _tag("办公室", "An office workspace with desks, computers, or employees.", "Corporate or professional office interior."),
            _tag("会议室", "A meeting or conference room with a table and business seating.", "Dedicated conference-room environment."),
            _tag("教室", "A classroom with desks, board, teacher area, or students.", "School or training-room interior."),
            _tag("客厅", "A residential living room with sofa, television, or lounge furniture.", "Home living-room interior."),
            _tag("卧室", "A bedroom with bed, wardrobe, or sleeping-area furniture.", "Residential bedroom interior."),
            _tag("厨房", "A kitchen with counters, stove, sink, or cooking equipment.", "Home or professional kitchen environment."),
            _tag("餐厅", "A restaurant or dining-room environment with dining tables.", "Commercial or formal dining venue."),
            _tag("咖啡馆", "A cafe or coffee shop with tables, counter, or coffee service.", "Coffee-shop interior or cafe seating area."),
            _tag("商店", "A retail store interior with shelves, merchandise, or checkout area.", "Shop or retail-store environment."),
            _tag("商场", "A shopping mall or large indoor retail complex.", "Mall corridors, multiple stores, escalators, or atrium."),
            _tag("体育场馆", "A gymnasium, stadium, sports court, field, or athletic venue.", "Dedicated sports facility or competition venue."),
            _tag("舞台", "A stage with performance lighting, curtain, or performers.", "Concert, theater, or presentation stage environment."),
            _tag("直播间", "A creator studio, streaming room, podcast room, or webcam setup.", "Microphones, headphones, camera, lights, or streaming desk are visible."),
            _tag("工厂车间", "A factory floor, workshop, production line, or industrial interior.", "Industrial manufacturing environment with machinery."),
            _tag("交通工具", "Inside a car, bus, train, airplane, boat, or other transport vehicle.", "Vehicle cabin or passenger interior is the main environment."),
            _tag("车站机场", "A railway station, subway station, bus terminal, or airport.", "Public transportation terminal environment."),
            _tag("公园花园", "A park, garden, landscaped green space, or public lawn.", "Managed outdoor greenery and recreational landscape."),
            _tag("森林", "Dense trees, woodland, or forest environment.", "Natural forest scenery is the main subject."),
            _tag("山地", "Mountains, hills, cliffs, valleys, or alpine terrain.", "Mountain landscape or hiking terrain."),
            _tag("海边", "Beach, sea, ocean, coast, or shoreline scenery.", "Marine coastal landscape with ocean water."),
            _tag("湖河", "Lake, river, canal, stream, or inland waterfront scenery.", "Freshwater landscape or riverside environment."),
            _tag("雪景", "Snow-covered landscape, snowfall, ice, or winter scenery.", "A visibly snowy outdoor environment."),
        ],
    },
    {
        "id": "entertainment",
        "name": "娱乐",
        "enabled": True,
        "tags": [
            _tag("游戏实况", "Gameplay footage or a person actively playing a video game.", "Video game screen and gaming activity are central."),
            _tag("电竞", "Competitive esports match, gaming tournament, or esports players.", "Organized competitive video gaming."),
            _tag("直播", "A livestream or streamer speaking to an online audience in real time.", "Creator livestream setup with webcam, chat, microphone, or streaming presentation."),
            _tag("播客", "A podcast recording with microphones, headphones, or seated hosts.", "Long-form conversational audio-video podcast setup."),
            _tag("访谈", "An interview with interviewer and guest in a question-and-answer format.", "Formal or casual interview conversation."),
            _tag("综艺", "Variety-show style entertainment with hosts, guests, games, or studio segments.", "Television variety entertainment format."),
            _tag("短剧", "Short-form scripted drama with actors performing a narrative scene.", "Vertical or short episodic fictional drama."),
            _tag("电影电视剧", "A scripted movie or television drama scene.", "Cinematic narrative footage with actors and dramatic staging."),
            _tag("影视剪辑", "Edited clips or montage sourced from movies or television programs.", "Compilation, fan edit, or commentary using film and TV footage."),
            _tag("动漫", "Anime, cartoon, manga-style, or animated entertainment content.", "2D animated characters or anime-style scene."),
            _tag("音乐演出", "A live music performance, concert, band, or musician on stage.", "Musical performance in front of an audience or camera."),
            _tag("MV", "A produced music video with stylized performance and edited visuals.", "Music-video format rather than a simple live performance."),
            _tag("唱歌", "A person singing or performing vocals.", "Vocal performance is the central action."),
            _tag("乐器演奏", "A person playing guitar, piano, drums, violin, or another musical instrument.", "Instrumental performance is clearly visible."),
            _tag("舞蹈", "Dancing, choreography, or a dance performance.", "One or more people performing dance movements."),
            _tag("体育赛事", "A competitive sports match, race, tournament, or game.", "Organized athletic competition rather than personal exercise."),
            _tag("喜剧", "Comedy performance, humorous sketch, stand-up, or intentionally funny scene.", "Entertainment designed primarily for humor."),
            _tag("魔术", "Magic trick, illusion, sleight of hand, or magician performance.", "A performer demonstrating a magic illusion."),
            _tag("Cosplay", "Cosplay, costume roleplay, or characters dressed as fictional figures.", "Costumed fan or convention-style character performance."),
            _tag("Reaction", "A reaction video showing a person watching and responding to other content.", "Creator facial reactions or commentary while viewing media."),
            _tag("桌游", "Board games, card games, tabletop games, or role-playing games around a table.", "People playing a physical tabletop game."),
            _tag("颁奖活动", "Awards ceremony, trophy presentation, or formal recognition event.", "People receiving awards on a stage or event venue."),
            _tag("粉丝活动", "Fan meeting, convention, signing event, or fandom gathering.", "Creators, celebrities, or fans interacting at a fan event."),
            _tag("舞台表演", "Non-musical stage performance such as theater, acrobatics, or live show.", "Performers acting or presenting on a stage."),
        ],
    },
    {
        "id": "people",
        "name": "人物 / 关系",
        "enabled": True,
        "tags": [
            _tag("主播", "A streamer or online creator presenting directly to camera.", "A host speaking to an online audience from a creator setup."),
            _tag("主持人", "A host or presenter guiding a program, event, or show.", "Presenter facing camera or audience and leading a segment."),
            _tag("采访者", "An interviewer asking questions to another person.", "The person conducting an interview."),
            _tag("嘉宾", "A guest appearing in an interview, talk show, podcast, or program.", "Featured guest participating in a hosted conversation."),
            _tag("演讲者", "A speaker presenting information to an audience.", "Lecturer, keynote speaker, or presenter speaking publicly."),
            _tag("老师", "A teacher or instructor teaching students.", "Educator leading a lesson or demonstration."),
            _tag("学生", "Students studying, attending class, or doing schoolwork.", "Learners in an educational setting."),
            _tag("情侣", "A romantic couple together.", "Two partners showing dating or romantic relationship cues."),
            _tag("亲子", "A parent and child interacting together.", "Parent-child family relationship is visibly central."),
            _tag("家庭", "Multiple family members together.", "Family relationship or household group is central."),
            _tag("朋友", "Friends socializing casually together.", "Peer friendship group interacting informally."),
            _tag("同事", "Coworkers collaborating or communicating in a workplace.", "Professional colleagues working together."),
            _tag("运动员", "Athletes training or competing in sports.", "Sports participants are the central people."),
            _tag("演员", "Actors performing a scripted dramatic scene.", "Professional or staged acting performance."),
            _tag("歌手", "A singer or vocalist performing music.", "Vocal performer is the main person."),
            _tag("舞者", "A dancer or dance group performing choreography.", "Dance performer is the main subject."),
            _tag("游戏玩家", "A gamer actively playing a video game.", "Person using controller, keyboard, or gaming setup."),
            _tag("顾客", "A customer shopping, dining, or receiving a service.", "Consumer interacting with a business or service provider."),
            _tag("服务人员", "Staff providing hospitality, retail, cleaning, beauty, or customer service.", "Worker directly serving a customer."),
            _tag("儿童", "Young children are prominently visible.", "Child subjects rather than teenagers or adults."),
            _tag("青少年", "Teenagers or adolescent people are prominently visible.", "Teen subjects in school, social, or daily-life context."),
            _tag("成年人", "Adult people are the primary visible subjects.", "Clearly adult human subjects."),
            _tag("老年人", "Older adults or elderly people are prominently visible.", "Senior people are the central subjects."),
            _tag("人宠互动", "A person actively interacting with a pet or companion animal.", "Human and pet relationship is central to the scene."),
        ],
    },
    {
        "id": "vertical",
        "name": "行业 / 垂类",
        "enabled": True,
        "tags": [
            _tag("科技数码", "Consumer technology, gadgets, electronics, or digital devices.", "Technology product content for a consumer audience."),
            _tag("手机", "Smartphone hardware, phone comparison, phone demonstration, or mobile-device review.", "A smartphone is the primary product or topic."),
            _tag("电脑硬件", "Computer hardware, PC building, GPU, CPU, laptop, or computer components.", "PC hardware products or technical computer equipment."),
            _tag("AI人工智能", "Artificial intelligence, generative AI, machine learning, AI tools, or intelligent robots.", "AI software or AI technology is the main topic."),
            _tag("汽车", "Cars, driving, automotive review, vehicle technology, or car ownership.", "Automotive content with a car as the primary topic."),
            _tag("房产", "Real estate, apartments, house tours, property sales, or housing market.", "Property or housing is the main topic."),
            _tag("金融投资", "Stocks, investing, markets, personal finance, or wealth management.", "Financial investment content and market analysis."),
            _tag("电商带货", "E-commerce sales livestream, product selling, shopping host, or product promotion.", "A creator actively presenting products for purchase."),
            _tag("产品评测", "A structured review, comparison, test, or evaluation of a product.", "Reviewer demonstrating strengths, weaknesses, or performance."),
            _tag("广告宣传", "Commercial advertisement, brand promotion, campaign video, or promotional spot.", "Professionally produced marketing content for a product or brand."),
            _tag("新闻时事", "News report, current affairs, breaking news, or news commentary.", "Journalistic presentation of current events."),
            _tag("纪录片", "Documentary-style nonfiction storytelling about real people, places, or events.", "Observational or factual documentary footage."),
            _tag("科普", "Popular science explanation or educational science communication.", "Accessible explanation of scientific facts or concepts."),
            _tag("历史文化", "History, heritage, traditional culture, museum, or cultural education.", "Historical or cultural topic is central."),
            _tag("旅游攻略", "Travel guide, destination recommendation, itinerary, or tourism tips.", "Practical travel information about places to visit."),
            _tag("美食探店", "Restaurant review, food shop visit, tasting, or local food recommendation.", "Creator visiting a food business and evaluating dishes."),
            _tag("时尚", "Fashion industry, clothing trends, runway, styling, or apparel content.", "Fashion is the main editorial topic."),
            _tag("美妆护肤", "Beauty products, cosmetics, skincare review, or makeup tutorial.", "Beauty and skincare products are the primary topic."),
            _tag("家居装修", "Interior design, renovation, furniture, home improvement, or decoration.", "Home renovation or interior-design content."),
            _tag("母婴", "Pregnancy, baby care, parenting products, or mother-and-baby content.", "Parenting and infant-related vertical content."),
            _tag("宠物知识", "Pet care, pet training, veterinary advice, or animal education.", "Informational content about caring for companion animals."),
            _tag("农业", "Farming, crops, livestock, agricultural machinery, or rural production.", "Agricultural work or farming industry content."),
            _tag("工业制造", "Manufacturing, factory production, industrial machinery, machining, or assembly line.", "Industrial production process is the main topic."),
            _tag("医疗健康", "Healthcare, clinics, doctors, treatment, wellness, or medical services.", "Medical or healthcare industry content."),
        ],
    },
    {
        "id": "adult",
        "name": "色情",
        "enabled": False,
        "tags": [
            _tag("成人内容", "Adult-oriented sexual or erotic content intended for adults.", "Sexually explicit or strongly erotic adult media."),
            _tag("裸露", "Visible adult nudity or substantial exposed intimate body areas.", "Adult nude or nearly nude presentation."),
            _tag("局部裸露", "Partial adult nudity or exposed intimate body areas without full nudity.", "Partially nude adult presentation."),
            _tag("全裸", "A fully nude adult body is clearly visible.", "Full adult nudity is a central visual element."),
            _tag("性感", "Sexually suggestive adult posing or presentation.", "Provocative adult-oriented visual presentation."),
            _tag("内衣", "Lingerie, underwear, or intimate apparel is visually prominent.", "Adult subject wearing lingerie or underwear."),
            _tag("泳装", "Swimsuit or bikini presentation is visually prominent.", "Adult subject wearing swimwear as a central visual element."),
            _tag("接吻", "Adults kissing romantically.", "A romantic kiss between adult people."),
            _tag("情侣亲密", "Adult couple showing close romantic physical intimacy.", "Intimate romantic interaction between adult partners."),
            _tag("暧昧互动", "Flirtatious or sexually suggestive interaction between adults.", "Adult flirting or suggestive interpersonal behavior."),
            _tag("成人自拍", "Adult-oriented selfie or self-recorded sensual presentation.", "Self-recorded adult intimate or erotic content."),
            _tag("成人直播", "Adult-oriented webcam or livestream presentation.", "Erotic adult streaming or webcam-style content."),
            _tag("情色写真", "Erotic glamour photography or sensual adult posing.", "Adult glamour shoot with erotic presentation."),
            _tag("角色扮演", "Adult-oriented costume roleplay or erotic cosplay.", "Sexually suggestive adult roleplay in costume."),
            _tag("卧室成人场景", "Adult intimate or erotic scene in a bedroom.", "Bedroom setting with adult-oriented sensual content."),
            _tag("浴室成人场景", "Adult sensual or nude scene in a bathroom or shower setting.", "Bathroom or shower with adult-oriented intimate presentation."),
            _tag("成人舞蹈", "Sexually suggestive or erotic dance performed by adults.", "Adult sensual dance or provocative choreography."),
            _tag("成人动画", "Animated or illustrated adult sexual or erotic content.", "Adult-oriented erotic animation or illustration."),
            _tag("亲密拥抱", "Adults embracing in a strongly intimate romantic context.", "Close romantic physical affection between adults."),
            _tag("成人表演", "Staged adult-oriented erotic performance.", "Adult sensual performance presented for an audience or camera."),
        ],
    },
]


def upgrade_settings(raw: dict | None) -> dict:
    """Upgrade old saved settings without discarding the user's choices.

    Built-in groups get the v2 taxonomy. Existing enabled state and any custom
    tags/prompts are preserved.  New groups are enabled by their v2 defaults.
    Adult content stays opt-in unless the user already enabled the old group.
    """
    source = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    try:
        version = int(source.get("version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= 2:
        return source

    old_groups = source.get("groups") if isinstance(source.get("groups"), list) else []
    old_by_id = {str(row.get("id", "")): row for row in old_groups if isinstance(row, dict)}
    upgraded = []
    built_in_ids = set()

    for default_group in PROFESSIONAL_GROUPS:
        group = copy.deepcopy(default_group)
        gid = group["id"]
        built_in_ids.add(gid)
        previous = old_by_id.get(gid)
        if previous:
            group["enabled"] = bool(previous.get("enabled", group["enabled"]))
            previous_tags = previous.get("tags") if isinstance(previous.get("tags"), list) else []
            by_key = {str(row.get("tag", "")).strip().casefold(): row for row in group["tags"] if isinstance(row, dict)}
            for row in previous_tags:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("tag", "")).strip()
                if not name:
                    continue
                key = name.casefold()
                # Preserve user-edited prompts for an existing tag; preserve any
                # truly custom tags by appending them after the professional set.
                if key in by_key:
                    prompts = row.get("prompts") if isinstance(row.get("prompts"), list) else []
                    if prompts:
                        by_key[key]["prompts"] = list(prompts)
                else:
                    group["tags"].append(copy.deepcopy(row))
        upgraded.append(group)

    # Preserve user-created groups exactly as they were. The >=20 guarantee is
    # for LocalHub's built-in taxonomy, not arbitrary user-defined groups.
    for previous in old_groups:
        if not isinstance(previous, dict):
            continue
        gid = str(previous.get("id", ""))
        if gid and gid not in built_in_ids:
            upgraded.append(copy.deepcopy(previous))

    source["version"] = 2
    source["groups"] = upgraded
    return source
