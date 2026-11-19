"""Local-only links from selected island miniatures to evidence-backed moments.

Only the shape field is suitable for sending to the model generator.
The date comments, card IDs, titles and descriptions stay on the island.
"""

EXISTING = {
    # 2026-08-24
    "folded-umbrella": {
        "zone": "moment", "moment_id": "moment:dfe27b8b2e9cb16a95b1",
        "title": "门边备着的伞",
        "description": "一把伞收在桶里，弯把手朝着门口。",
    },
    # 2023-09-12
    "teacup-pair": {
        "zone": "moment", "moment_id": "moment:67ec5d185a3424568a48",
    },
    # 2022-08-08
    "field-recorder": {
        "zone": "moment", "moment_id": "moment:6dbdd5f806718f9130ee",
    },
    # 2023-06-28
    "bookend-fox": {
        "zone": "moment", "moment_id": "moment:7acbc3cc0f731211cac0",
    },
}

DROP = {"patch-kit", "seed-pots", "knot-coil", "ribbon-spool"}

EXTRA = [
    {
        "id": "reel-projector",
        "title": "双盘放映机",
        "description": "两只开孔片盘高低相对，胶片绕过机壳上的转轴。",
        "shape": "矮胖机械放映机，两个大开孔片盘并排骑在机壳顶端，一小截有齿孔的厚胶片绕过正面凸出的镜头筒，机脚共用窄长木座，转轴嵌蜜色圆钮",
        "moment_id": "moment:466ae5c469a451b5fc49",  # 2022-08-04
    },
    {
        "id": "filter-camera",
        "title": "镜头前的滤片",
        "description": "方形机身一侧伸出圆形滤片架，收拢时正好盖住镜头。",
        "shape": "厚实的老式方形照相机，前脸只有一枚突出大镜筒，三枚有厚边框的圆滤片用短轴铰接成扇形，扇边贴住机身，最外一环嵌浅蜜色",
        "moment_id": "moment:f605bd9b8f062848d442",  # 2022-08-03
    },
    {
        "id": "hoop-bank",
        "title": "篮圈里的球",
        "description": "半颗球落在篮圈里，粗网绳沿着球身向下收拢。",
        "shape": "微缩篮球架，厚实的小方篮板背后有短弯支柱，橘陶色球的一半嵌在矮篮圈内，网袋由几条粗圆肋组成，支柱落在梯形底座上",
        "moment_id": "moment:1e8e6e840c57c107e1fd",  # 2023-09-27
    },
    {
        "id": "pleated-map",
        "title": "折页上的路线",
        "description": "一条浅浮雕小径穿过纸面的三道折痕，停在圆头定位钉旁。",
        "shape": "站立的手风琴折页地图，四块厚纸板高低错落如山脊，一条凸起曲折的细路横跨折面，终点嵌一枚蜜色圆头钉，底边自然伏在窄底座上，纸面不含文字",
        "moment_id": "moment:467aff35057554128939",  # 2023-09-04
    },
    {
        "id": "lunch-satchel",
        "tuning": {"yaw": -24},
        "title": "纸袋旁的粗笔",
        "description": "餐盒盖从纸袋里露出一边，粗笔插在袋侧的纸褶里。",
        "shape": "方底厚牛皮纸外带袋，两只短圆提手弯在顶部，袋口挤出圆形餐盒盖的一角，一支粗记号笔斜卡在侧面的厚纸折里，笔帽为蜜色，纸面空白",
        "moment_id": "moment:f25813e8c0befa94b3af",  # 2024-03-20
    },
    {
        "id": "tape-rule",
        "title": "伸出一截的卷尺",
        "description": "尺带从圆壳拉出一小截，端钩卡在底板另一端的方木块上。",
        "shape": "独立的小型卷尺模型，矮椭圆木底托左端固定一只扁圆卷尺壳，底托右端只有一枚拇指大的方木块，短宽厚尺带紧贴底托，从圆壳伸至方木块的蜜色端钩；尺带只有浅凹线，全部零件连成一体，木底托四周边缘完整地显露，构图中无墙无房间",
        "moment_id": "moment:3cd6ae2e109069d208d8",  # 2024-08-01
    },
    {
        "id": "shuttle-tubes",
        "title": "没盖好的球筒",
        "description": "三只球筒靠在同一个底座上，前面那只露出羽毛球的软木球头。",
        "shape": "三只长圆形羽毛球筒在矮底托里一立两斜，其中半开的筒口伸出一颗厚羽片的羽毛球，圆软木球头嵌蜜蜡色，盖子斜倚在前面，外壁光洁",
        "moment_id": "moment:6c47a29aef6891bc598b",  # 2025-05-25
    },
    {
        "id": "palette-fan",
        "title": "转开的配色扇",
        "description": "五张厚纸卡在同一枚铆钉上张开，每一层露出一个窄角。",
        "shape": "窄长厚色卡五片，一端由圆铆钉铰接，在斜立的扇形小底托上摊成半圆，片端有色块浅浮雕，奶油、浅陶、灰蓝交替，铆钉蜜蜡色",
        "moment_id": "moment:c60402732371913d88a3",  # 2025-09-22
    },
    {
        "id": "keyboard-step",
        "title": "被按下的小琴键",
        "description": "七枚浅色琴键里，有一枚落得比邻键低。",
        "shape": "微缩拱背木壳键盘，七枚厚白键和五枚短深色键，一枚白键压低露出侧面，一颗小蜜色珠子刚好嵌在它后端，琴键前缘清楚，矮宽的圆弧琴身稳放",
        "moment_id": "moment:a28fd00806b949c68de8",  # 2026-09-10
    },
    {
        "id": "cargo-lock",
        "title": "吊起的集装箱",
        "description": "一个小箱子悬在两根短导轨之间，和底下的凹槽还差一格。",
        "shape": "微缩桥式装卸架，短粗横梁跨过两根圆角立柱，上方滑车贴着横梁，向下连接一只带竖向波纹的厚集装箱，箱角搭在底座凸轨上，另一个矮箱横卧，吊钩为蜜色",
        "moment_id": "moment:f4624fda6c6c0bd0f413",  # 2026-11-06
    },
    {
        "id": "reading-seat",
        "title": "给你留的椅子",
        "description": "椅子的一边挂着布包，宽敞的座板仍然空着。",
        "shape": "矮宽的独立阅览椅，厚实圆角座板为单块光滑的水平平板，四脚稳固。椅背外侧仅挂一只扁平布包，短包带环住椅背，包完全垂在椅子外侧，离开座面。座板必须整块空白、完全没有任何物件，木框为栗棕色，座板与靠背灰绿，外侧布包陶红",
        "moment_id": "moment:2c0ab80f7493051ef6f3",  # 2024-03-18
    },
    {
        "id": "diploma-tube",
        "title": "系着结的证书",
        "description": "缎带把纸卷束在一起，打开的硬封套托住它。",
        "shape": "矮长圆证书筒搭在半开的硬封套上，露出一小截厚卷纸，短宽缎带在筒身打成简洁双耳结，纸卷断面为浅凹螺纹，尾端蜜色",
        "moment_id": "moment:2efbaf574ef657b1f68a",  # 2026-06-15
    },
    {
        "id": "shell-halves",
        "title": "两瓣圆角外壳",
        "description": "上盖斜靠在下壳边，露出里面的卡扣与螺丝柱。",
        "shape": "小型圆角电子外壳剖开，上下两片一平一斜，外表光洁，内侧有圆筒螺丝柱、成对卡舌和一条长圆开口，两片在一角相连，卡舌嵌浅蜜色，整体短宽",
        "moment_id": "moment:adbe0394db21c16a7a5f",  # 2026-09-18
    },
    {
        "id": "parking-guide",
        "tuning": {"yaw": -34, "scale": 1.05},
        "title": "转弯的小车",
        "description": "一辆矮车斜停在两根圆桩之间，车后的弧线还差半圈。",
        "shape": "长方形厚板上微缩两厢训练车，车头斜向一对圆头矮柱，地面两条浅刻平行槽接一道弯槽，车轮和车厢为一体，右侧后视镜嵌蜜色，俯角能看清",
        "moment_id": "moment:b79ddcfee5b5e013ec6c",  # 2024-05-07
    },
    {
        "id": "pinned-cylinder",
        "title": "掌心里的八音盒",
        "description": "转柄停在盒侧，滚筒上的一排细点正对着金属梳齿。",
        "shape": "敞盖的手摇八音盒，弧形盖板向后立起，矮木盒内一枚圆柱滚筒与一排厚梳齿契合，侧边曲柄贴着盒壁，滚筒有凸起小圆点、手柄蜜色",
        "moment_id": "moment:1d6ef2fb893b393cc93a",  # 2025-09-25
    },
    {
        "id": "recording-cradle",
        "title": "夹在支架上的镜头",
        "description": "镜头夹在短臂尽头，正对着桌面的一页纸。",
        "shape": "折叠式桌面拍摄架，一条粗弯臂从矮底座伸出，臂端有夹着扁平小相机的圆角夹，两处圆铰链清楚，镜头朝下对准底板上折角的空白厚纸，铰链一圈蜜色",
        "moment_id": "moment:f7077b7f2628f80991c4",  # 2022-11-17
    },
    {
        "id": "grid-loupe",
        "tuning": {"yaw": -23},
        "title": "格子上的放大镜",
        "description": "放大镜压着其中一格，短柄还搭在纸边。",
        "shape": "一面厚边圆放大镜斜立，短粗手柄搭在一摞带网格压纹的厚纸上，镜框中央是一块微凸浅色圆片，纸页有两枚阶梯形分页耳，镜框蜜色，网格内完全留白",
        "moment_id": "moment:f708f910925cdd890dcb",  # 2023-04-20
    },
    {
        "id": "clue-stone",
        "tuning": {"yaw": -22},
        "title": "石缝里的线索卡",
        "description": "两块扁石上下错开，石缝中露出纸卡带圆点的一角。",
        "shape": "低矮横向的双石藏卡小景，总宽度是高度的三倍。两块厚扁鹅卵石上下紧贴、略向两侧错位，上石稍小且偏左，一张厚纸质圆角小卡平躺压在二石缝隙之间，仅从右侧伸出一个带圆点暗纹的蜜色卡角。下石平底直接贴地，石面自然光滑；全景只有两块石头与一张卡，无木桩、无杆柱、无悬浮物",
        "moment_id": "moment:f342b8fa5dbd534bb9cc",  # 2024-03-29
    },
    {
        "id": "vanishing-frame",
        "tuning": {"yaw": 64},
        "title": "通向远处的线",
        "description": "两条浅浅的线从取景框脚下伸出，沿着斜面向前张开。",
        "shape": "一只直立空心矩形取景框带四个加厚圆角，框下伸出楔形小地台，地台两条凸线由宽至窄汇进框内，底下矮三脚台，蜜色只在框的一个角",
        "moment_id": "moment:b9ae2d2c740e03e76fcb",  # 2024-04-21
    },
    {
        "id": "subtitle-splicer",
        "title": "胶片上的两条空行",
        "description": "一段胶片穿过压片轮，画格下面留着两条浅槽。",
        "shape": "短宽剪片台，两个粗压片轮夹住一段半弯曲的厚胶片，底座向上翘起一格放大的方形画框，画框下缘有两条无字短条浮雕，胶片齿孔圆润，压杆蜜色",
        "moment_id": "moment:77d4583d4de1612f8b28",  # 2026-01-12
    },
    {
        "id": "relief-pear",
        "title": "从平面长出来的梨",
        "description": "纸片上的梨只有轮廓，到前方就成了一颗完整的果子。",
        "shape": "由后至前的三层立体小样紧连在椭圆底托上，后层是带浅凹梨形轮廓的方片，中间是半圆浅浮雕梨，前端是带短弯梗的完整圆梨，三者轮廓相似，梨梗蜜色",
        "moment_id": "moment:3be3c428fcb440efc520",  # 2026-01-12
    },
    {
        "id": "filament-spool",
        "tuning": {"yaw": -42},
        "title": "收住线尾的料盘",
        "description": "盘边露出一截圆线，末端刚好穿进一个小眼。",
        "shape": "侧立的矮宽耗材线盘，两片圆盘中心有大圆孔并各有三个弧形开窗，卷好的粗圆线有连续排纹，一截短线穿过盘缘小孔并向内弯，边缘小卡扣蜜色",
        "moment_id": "moment:49b43625b2bfb223a0d0",  # 2026-09-18
    },
    {
        "id": "corner-seal",
        "tuning": {"yaw": -46},
        "title": "压在纸角的印章",
        "description": "方形印章侧放在叠起的白纸上，一圈细边围住空白的印面。",
        "shape": "胖圆木柄接一枚方形小印章，斜搁在三层微翘的方纸角上，纸角有一圈抽象的方形凸边，印面无字无纹样，方印四周蜜蜡色细包边",
        "moment_id": "moment:ab854122744985ca88d7",  # 2026-10-10
    },
    {
        "id": "branch-cards",
        "title": "分出枝的索引片",
        "description": "几根弯枝绕着中央的圆片伸开，枝头各托着一张空白小牌。",
        "shape": "窄低台上直立一棵几何形索引树，中央厚圆片通过三根粗弯枝连接大小不同的矩形圆角牌，牌面空白，最外三块牌各有一个蜜色圆扣，枝条交错但互不遮挡",
        "moment_id": "moment:fb5afb7b23e581702c52",  # 2022-08-08
    },
]
