"""配置项额外属性（``ConfigField`` 家族）的行为护栏。

三件事必须一直成立，缺一条这套设计就崩：

1. ``DEFAULTS`` 里**只有纯值** —— Field 绝不漏进去，否则落盘时
   ``json.dump`` 直接抛 ``TypeError``；
2. ``FIELDS`` 里**只有 Field**，且继承、``memory()`` 之后都还在；
3. 老写法（``default(...)``）一个字都不用改，行为完全不变。

运行：
    pytest test_config_field.py -v
"""

import dataclasses
import json

import pytest

from xiaoe_config_manager import (
    PATH_MODES,
    ChoiceField,
    ColorField,
    Config,
    ConfigField,
    ConfigItemProxy,
    ConfigKeysBase,
    ConfigMemory,
    DateField,
    DictField,
    GradientField,
    ImageField,
    ListField,
    NumberField,
    PathField,
    TextField,
    default,
)


# ══════════════════════════════════════════════════════════════
# 声明形态：Field 代替 default
# ══════════════════════════════════════════════════════════════

class AppKeys(ConfigKeysBase):
    """一份典型声明：四种 Field + 一个老写法的键。"""

    height = NumberField(
        default=500, range=(0, 1080), step=1, unit="px",
        title="窗口高度", desc="仅对新建窗口生效",
    )
    mode = ChoiceField(
        default="auto", options=("auto", "manual"),
        title="模式", desc="自动还是手动",
    )
    accent = ColorField(
        default=(1, 2, 3), rgba=False,
        title="主题色",
    )
    note = TextField(
        default="",
        title="备注", desc="可以留空",
    )
    legacy = default(7)


def test_defaults_holds_only_plain_values():
    """``DEFAULTS`` 里绝不能出现 Field —— 它是落盘的那一份。"""
    assert AppKeys.DEFAULTS == {
        "height": 500, "mode": "auto", "accent": (1, 2, 3),
        "note": "", "legacy": 7,
    }
    for key, value in AppKeys.DEFAULTS.items():
        assert not isinstance(value, ConfigField), f"{key} 把 Field 漏进 DEFAULTS 了"


def test_defaults_is_json_serializable():
    """落盘路径会在构造期 ``json.dump``；Field 在里面就会当场炸。"""
    json.dumps(AppKeys.DEFAULTS)          # 不许抛


def test_fields_holds_the_declared_objects():
    """``FIELDS`` 与 ``DEFAULTS`` 同形状，但存的是声明时那个 Field。"""
    assert set(AppKeys.FIELDS) == {"height", "mode", "accent", "note"}
    assert isinstance(AppKeys.FIELDS["height"], NumberField)
    assert isinstance(AppKeys.FIELDS["mode"], ChoiceField)
    assert AppKeys.FIELDS["height"].range == (0, 1080)
    assert AppKeys.FIELDS["height"].step == 1
    assert AppKeys.FIELDS["height"].unit == "px"
    assert AppKeys.FIELDS["mode"].options == ("auto", "manual")


def test_legacy_key_has_no_field():
    """老写法不产生额外属性 —— 这是 ``proxy.field is None`` 的来源。"""
    assert "legacy" not in AppKeys.FIELDS


def test_class_attribute_still_reads_as_the_default():
    """``AppKeys.height`` 仍是 ``500``，不是 Field 对象。

    所有把声明类当"默认值字典"用的老代码都依赖这一条。
    """
    assert AppKeys.height == 500
    assert AppKeys.mode == "auto"
    assert AppKeys.legacy == 7
    # 而 vars() 里那个位置才是 Field —— 扫描器读的是这里
    assert isinstance(vars(AppKeys)["height"], NumberField)


def test_field_is_inherited_by_subclasses():
    """子类不写一遍也照样有额外属性。"""

    class ChildKeys(AppKeys):
        extra = default("x")

    assert set(ChildKeys.FIELDS) == {"height", "mode", "accent", "note"}
    assert ChildKeys.FIELDS["height"].range == (0, 1080)
    assert ChildKeys.DEFAULTS["extra"] == "x"


def test_redeclaring_an_inherited_key_still_conflicts():
    """一条继承链上重名照旧报错 —— Field 不改变这条规则。"""
    with pytest.raises(TypeError, match="重复声明"):
        class Dup(AppKeys):
            height = NumberField(default=1, range=(0, 10), step=1)


# ══════════════════════════════════════════════════════════════
# 必填性：漏参数当场报错（而不是把值塞给隔壁参数）
# ══════════════════════════════════════════════════════════════

def test_number_field_requires_range_and_step():
    """``range`` / ``step`` 必填 —— 没有它们算不出滑块位置。"""
    with pytest.raises(TypeError, match="range"):
        NumberField(step=1)
    with pytest.raises(TypeError, match="step"):
        NumberField(range=(0, 10))
    with pytest.raises(TypeError):
        NumberField()


def test_number_field_rejects_positional_arguments():
    """全 kw_only：``NumberField(500)`` 不许把 500 当成 range。

    位置参数模式下 ``NumberField(500)`` 会静默生成 ``range=500`` 的滑块，
    直到某处解包才炸 —— 那种错误极难定位。
    """
    with pytest.raises(TypeError):
        NumberField(500)


def test_choice_field_requires_options():
    with pytest.raises(TypeError, match="options"):
        ChoiceField()


def test_color_and_text_fields_are_all_optional():
    """``ColorField`` / ``TextField`` 可以全用默认值。"""
    assert ColorField().rgba is False
    assert TextField().value_type is str


def test_field_is_frozen():
    """frozen：一个 Field 被多处引用时，谁都不能改它。"""
    field = NumberField(default=1, range=(0, 10), step=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        field.step = 2


def test_replace_keeps_other_slots():
    """``replace`` 换默认值不动别的槽（``memory()`` 就是靠这条）。"""
    field = NumberField(default=1, range=(0, 10), step=1, unit="px", title="宽")
    changed = dataclasses.replace(field, default=99)
    assert changed.default == 99
    assert changed.range == (0, 10)
    assert changed.step == 1
    assert changed.unit == "px"
    assert changed.title == "宽"
    assert field.default == 1, "原对象不该被改动"


def test_field_does_not_validate_values():
    """**不校验配置值**：默认值超出 range 也不报错。

    这条和下面那组「类型定义」是两回事：

    * ``default=500`` 落在 ``range=(0, 100)`` 之外 —— 这是「值合不合适」，
      属于消费侧的事，Field 不管；
    * ``range=500``（不是二元组）—— 这是「这个字段的类型不对」，
      Field 当场抛。
    """
    field = NumberField(default=500, range=(0, 100), step=1)   # 500 > 100，但合法
    assert field.default == 500


# ══════════════════════════════════════════════════════════════
# 类型定义：每个槽的「形状」在构造期就说清楚
# ══════════════════════════════════════════════════════════════
#
# 这一组测的不是「值合不合适」，而是「这个东西是不是那个类型」。
# 和 bool 只有真/假同一种性质：range 必须是一个区间，step 必须能当步长用。

@pytest.mark.parametrize("bad_range", [
    500,                       # 忘了写括号
    (0,),                      # 少一个端点
    (0, 1, 2),                 # 多一个端点
    ("0,100",),                # 端点不是数
    (None, 100),
    [True, False],             # bool 不是数值端点
    (10, 0),                   # min > max，区间是空的
])
def test_number_field_defines_range_shape(bad_range):
    """``range`` 的类型是「两个数的区间」，形状不对当场抛。"""
    with pytest.raises(ValueError, match="range"):
        NumberField(range=bad_range, step=1)


@pytest.mark.parametrize("bad_step", [0, -1, -0.5, "1", None, True])
def test_number_field_defines_step_shape(bad_step):
    """``step`` 的类型是「正数」—— 非正数算不出滑块位置。"""
    with pytest.raises(ValueError, match="step"):
        NumberField(range=(0, 10), step=bad_step)


def test_number_field_rejects_int_range_with_float_step():
    """整数区间配小数步进：每一步都落在整数之间，界面和值必然错位。"""
    with pytest.raises(ValueError, match="整数区间"):
        NumberField(range=(0, 100), step=0.5)


@pytest.mark.parametrize("ok_range, ok_step", [
    ((0, 1080), 1),
    ((0, 100), 5),
    ((0.0, 1.0), 0.01),
    ((0.0, 1.0), 1),          # 小数区间配整数 1 是可以的
    ([0, 10], 2),             # list 也接受
])
def test_number_field_accepts_well_formed(ok_range, ok_step):
    assert NumberField(range=ok_range, step=ok_step).step == ok_step


@pytest.mark.parametrize("bad_options", [
    "abc",                     # 忘了逗号 —— 会变成三个字符的选项
    "选项A",
    (),
    [],
    None,
    123,
])
def test_choice_field_defines_options_shape(bad_options):
    """``options`` 的类型是「非空序列，且不是字符串」。"""
    with pytest.raises(ValueError, match="options"):
        ChoiceField(options=bad_options)


def test_choice_field_accepts_tuple_and_list():
    assert ChoiceField(options=("a",)).options == ("a",)
    assert ChoiceField(options=["a", "b"]).options == ["a", "b"]


@pytest.mark.parametrize("bad", [1, 0, "True", None, [True]])
def test_color_field_defines_rgba_as_bool(bad):
    """``rgba`` 决定值是 3 元组还是 4 元组，必须是真 bool。"""
    with pytest.raises(ValueError, match="rgba"):
        ColorField(rgba=bad)


@pytest.mark.parametrize("bad", [None, 0, 1.5, ["a"]])
def test_text_field_defines_value_type_as_callable(bad):
    """``value_type`` 必须是可调用的 —— 它决定 config 里存 str 还是数字。"""
    with pytest.raises(ValueError, match="value_type"):
        TextField(value_type=bad)


@pytest.mark.parametrize("kwargs", [
    {"check_exists": 1},
    {"file_filter": None},
    {"start_dir": 0},
])
def test_path_field_defines_each_slot(kwargs):
    """``PathField`` 的每个槽也有类型 —— 不只是 ``mode``。

    只管「值是什么」的那些（``mode`` / ``file_filter`` / ``start_dir`` /
    ``check_exists``）。对话框旋钮归 ``xiaoe_ui.config.field_ui.PathOptions``。
    """
    with pytest.raises(ValueError):
        PathField(**kwargs)


def test_frozen_replace_also_reruns_type_checks():
    """``replace()`` 重跑 ``__post_init__``，所以改错了同样拦住。"""
    good = NumberField(range=(0, 10), step=1)
    with pytest.raises(ValueError, match="range"):
        dataclasses.replace(good, range=5)
    assert dataclasses.replace(good, range=(0, 20)).range == (0, 20)


# ══════════════════════════════════════════════════════════════
# PathField：路径的物理属性
# ══════════════════════════════════════════════════════════════

def test_path_field_holds_the_physical_slots():
    """``mode`` / ``file_filter`` / ``check_exists`` 是物理槽，都在这一个类里。"""
    field = PathField(
        default="", mode="dir", check_exists=False,
        file_filter="程序 (*.exe)", start_dir="C:/games",
        title="游戏目录", desc="存档在这里",
    )
    assert field.mode == "dir"
    assert field.check_exists is False
    assert field.file_filter == "程序 (*.exe)"
    assert field.start_dir == "C:/games"
    assert field.title == "游戏目录"


def test_path_field_defaults():
    """全默认：选已存在的文件、要检查存在。"""
    field = PathField()
    assert field.mode == "file"
    assert field.file_filter == "所有文件 (*)"
    assert field.check_exists is True
    assert field.start_dir == ""


def test_path_field_has_no_gui_only_slots():
    """对话框旋钮**不在** manager 里 —— 纯 CLI 用不上它们。

    标准：manager 配一个纯 CLI 时，这个属性还会不会被用到。
    ``dialog_width`` 显然不会；它在 ``xiaoe_ui.config.field_ui.PathOptions``。
    """
    slots = set(PathField.__dataclass_fields__)
    for gui_only in ("placeholder", "icon", "dialog_title",
                     "dialog_width", "dialog_height", "dialog_fixed_size"):
        assert gui_only not in slots, f"{gui_only} 不该在 manager 的 PathField 里"


def test_unit_stays_because_cli_prints_it():
    """``unit`` **留在** manager：CLI 输出 ``500 px`` 要用到它。

    这条容易被人"顺手优化掉"，所以拿测试钉住。
    """
    assert "unit" in NumberField.__dataclass_fields__
    assert NumberField(range=(0, 10), step=1, unit="px").unit == "px"


def test_start_dir_stays_because_cli_needs_it():
    """``start_dir`` 同样留下：CLI 弹选择器也要有起点。"""
    assert "start_dir" in PathField.__dataclass_fields__
    assert "start_dir" in ImageField.__dataclass_fields__


def test_path_field_rejects_bad_mode():
    """``mode`` 是枚举，写错了当场炸（这是唯一会校验的槽）。

    注意这条和"只存储不校验"不冲突：那个说的是**配置值**（路径字符串）——
    路径写错了不报错，与 ImagePicker 一致。``mode`` 是作者的声明，写错就是
    代码错，早炸早好。
    """
    with pytest.raises(ValueError, match="mode"):
        PathField(mode="folder")          # type: ignore[arg-type]


def test_path_field_accepts_every_legal_mode():
    for mode in PATH_MODES:
        assert PathField(mode=mode).mode == mode


def test_path_field_replace_revalidates():
    """``replace`` 会重跑 ``__post_init__``，所以改错 mode 也拦得住。"""
    good = PathField(mode="dir")
    with pytest.raises(ValueError, match="mode"):
        dataclasses.replace(good, mode="nope")       # type: ignore[arg-type]
    assert dataclasses.replace(good, mode="save").mode == "save"


def test_path_field_is_a_field_and_a_descriptor():
    """它既是 ConfigField（能写进声明），也仍是描述符（类访问给默认值）。"""
    field = PathField(default="", mode="dir")
    assert isinstance(field, ConfigField)
    assert field.__get__(None, None) == ""


def test_path_field_declared_in_keys():
    """写在声明里：default 进 DEFAULTS，整个对象进 FIELDS。"""
    class PathKeys(ConfigKeysBase):
        game_dir = PathField(
            default="", mode="dir", check_exists=False,
            title="游戏目录", desc="存档与截图存放在这里",
        )

    assert PathKeys.DEFAULTS == {"game_dir": ""}
    assert isinstance(PathKeys.FIELDS["game_dir"], PathField)
    assert PathKeys.FIELDS["game_dir"].mode == "dir"
    assert PathKeys.game_dir == "", "类访问拿到的仍是默认值"


def test_path_field_roundtrip_through_backends(tmp_path):
    """文件后端的落盘仍是纯字符串，重开后 mode 还在。"""

    class PathKeys(ConfigKeysBase):
        game_dir = PathField(default="", mode="dir", check_exists=False)

    class PathCfg(Config, PathKeys):
        pass

    path = str(tmp_path / "p")
    cfg = PathCfg(path)
    cfg.game_dir.set("C:/games")
    cfg.flush()

    with open(cfg.path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk == {"game_dir": "C:/games"}

    again = PathCfg(path)
    assert again.game_dir.get() == "C:/games"
    assert again.game_dir.field.mode == "dir"


# ══════════════════════════════════════════════════════════════
# 消费侧：cfg.键名.field
# ══════════════════════════════════════════════════════════════

def test_proxy_field_reads_declared_metadata():
    """声明式配置：``cfg.键名.field`` 拿到声明时那个 Field。"""
    mem = ConfigMemory(AppKeys.DEFAULTS)

    class MemKb(ConfigMemory, AppKeys):
        pass

    cfg = MemKb()
    assert isinstance(cfg.height, ConfigItemProxy)
    assert cfg.height.field is AppKeys.FIELDS["height"]
    assert cfg.height.field.range == (0, 1080)
    assert cfg.mode.field.options == ("auto", "manual")
    assert cfg.legacy.field is None, "老写法的键没有额外属性"
    # 同一个键永远返回同一个对象，额外属性不会每次新建
    assert cfg.height.field is cfg.height.field


def test_proxy_field_is_none_for_non_declarative_config(tmp_path):
    """非声明式配置（``default_config=``）没有 FIELDS 表 → 返回 None，不抛。"""
    cfg = Config(str(tmp_path / "plain"), default_config={"x": 1})
    assert cfg.item("x").field is None


def test_memory_copy_keeps_fields():
    """``Config.memory()`` 合成的临时类必须把 FIELDS 带上。

    不带的话「声明了额外属性 → 想用内存版调界面」就直接拿不到元数据，
    用户会以为功能没生效。
    """

    class FileKb(Config, AppKeys):
        pass

    cfg = FileKb.memory()
    assert isinstance(cfg, ConfigMemory)
    assert cfg.height.field is not None
    assert cfg.height.field.range == (0, 1080)
    assert cfg.height.field.step == 1
    assert cfg.height.field.unit == "px"


def test_memory_override_keeps_fields_but_changes_default():
    """``memory({"height": 999})``：值被覆盖，元数据留着、default 跟着换。"""

    class FileKb(Config, AppKeys):
        pass

    cfg = FileKb.memory({"height": 999})
    assert cfg.height.get() == 999
    field = cfg.height.field
    assert field is not None
    assert field.default == 999
    assert field.range == (0, 1080), "覆盖默认值不该把范围弄丢"
    assert field.unit == "px"


def test_memory_without_declarations_still_works():
    """没有声明的类走原来的路径（不合成临时类）。"""
    cfg = ConfigMemory({"a": 1})
    assert cfg.item("a").field is None


def test_file_backend_roundtrip_keeps_fields(tmp_path):
    """文件后端：落盘的是纯值，重开后额外属性还在。"""

    class FileKb(Config, AppKeys):
        pass

    path = str(tmp_path / "c")
    cfg = FileKb(path)
    assert cfg.height.field.range == (0, 1080)
    cfg.height.set(640)
    cfg.flush()

    with open(cfg.path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["height"] == 640
    assert all(not isinstance(v, ConfigField) for v in on_disk.values())

    again = FileKb(path)
    assert again.height.get() == 640
    assert again.height.field.range == (0, 1080)


# ══════════════════════════════════════════════════════════════
# 保留字
# ══════════════════════════════════════════════════════════════

def test_fields_in_class_body_is_ignored_not_absorbed():
    """类体里写 ``FIELDS = ...`` 不被当成配置键，也不会污染那张表。

    与 ``DEFAULTS`` 同一套规则（它也是"框架算出来的表，不是数据"）：
    扫描时跳过，之后由 ``__init_subclass__`` 无条件覆盖成真正算出来的那份。
    """
    class Bad(ConfigKeysBase):
        FIELDS = default(1)
        x = default(2)

    assert Bad.DEFAULTS == {"x": 2}, "FIELDS 不许混进配置键"
    assert Bad.FIELDS == {}, "作者写的那个值要被覆盖掉，不能留着"


def test_field_name_is_still_a_legal_key():
    """键名叫 ``field`` 仍然合法 —— 它和代理上的 ``.field`` 是两层东西。"""
    class HasFieldKey(ConfigKeysBase):
        field = default(1)

    class HasFieldCfg(ConfigMemory, HasFieldKey):
        pass

    assert HasFieldKey.DEFAULTS == {"field": 1}
    cfg = HasFieldCfg()
    assert isinstance(cfg.field, ConfigItemProxy), "cfg.field 是那个键的代理"
    assert cfg.field.field is None, "而这个键自己没声明额外属性"


# ══════════════════════════════════════════════════════════════
# 与老写法共存
# ══════════════════════════════════════════════════════════════

def test_legacy_default_still_works_untouched():
    """``default()`` 一个字符都没动。"""
    class Old(ConfigKeysBase):
        a = default(1)
        b = default("x")
        c = default(None, list)

    assert Old.DEFAULTS == {"a": 1, "b": "x", "c": None}
    assert Old.FIELDS == {}
    assert Old.a == 1


def test_mixed_declaration_in_one_class():
    """同一个类里 Field 和老写法可以混用。"""
    class Mixed(ConfigKeysBase):
        new = NumberField(default=1, range=(0, 10), step=1)
        old = default(2)

    assert Mixed.DEFAULTS == {"new": 1, "old": 2}
    assert set(Mixed.FIELDS) == {"new"}

# ══════════════════════════════════════════════════════════════
# ListField / DictField / GradientField：容器型
# ══════════════════════════════════════════════════════════════
#
# 这几个的特点是「值本身是容器」：里面装什么由另一个 Field 说。
# default 和 item 里的默认值是两回事，这一组把它们区分清楚。

def test_list_field_default_is_initial_items():
    """``default`` = 这个键**初始有几项**。"""
    f = ListField(default=["a", "b"], item=TextField())
    assert f.default == ["a", "b"]


def test_list_field_new_item_comes_from_item_default():
    """``item`` 里的默认值 = **新增一项时**那一项的初值。

    这是 ``item`` 必填的原因：没有它，新增的一行不知道该填什么。
    """
    f = ListField(item=TextField(default="新的一项"))
    assert f.new_item() == "新的一项"

    # 两件事互不影响
    f2 = ListField(default=["已有"], item=NumberField(
        default=7, range=(0, 10), step=1))
    assert f2.default == ["已有"]      # 现有内容
    assert f2.new_item() == 7          # 新加的初值


def test_list_field_item_is_required():
    """``item`` 说明列表里装什么，不能省。"""
    with pytest.raises(ValueError, match="item"):
        ListField()
    with pytest.raises(ValueError, match="item"):
        ListField(item="TextField()")      # 传了实例以外的东西


def test_list_field_default_shape_not_checked():
    """``default`` 形状**不查** —— 和 ``NumberField(default="abc")`` 一致。

    只有「声明里另有一个槽规定了它必须是什么」时才查（``ColorField`` 那种）。
    """
    assert ListField(default="不是列表", item=TextField()).default == "不是列表"


def test_list_field_with_dict_item_is_the_l3list_shape():
    """``ListField(item=DictField(...))`` 正是 L3List 期望的 ``list[dict]``。"""
    f = ListField(
        default=[{"path": "a"}],
        item=DictField(fields={"path": PathField(mode="dir")}),
    )
    assert f.item.keys == ["path"]
    assert isinstance(f.item, DictField)


def test_dict_field_holds_fixed_keys():
    f = DictField(fields={
        "path": PathField(mode="dir"),
        "port": NumberField(range=(1, 65535), step=1),
    })
    assert f.keys == ["path", "port"]      # 顺序按声明
    assert isinstance(f.fields["path"], PathField)


@pytest.mark.parametrize("bad", [
    {},                                     # 空 = 没有键
    ["path"],                               # 不是 dict
    None,
])
def test_dict_field_rejects_bad_fields(bad):
    with pytest.raises(ValueError, match="fields"):
        DictField(fields=bad)


def test_dict_field_rejects_non_field_values():
    """每个键的值都必须是 Field —— 这正是「每一列是什么类型」。"""
    with pytest.raises(ValueError, match="ConfigField"):
        DictField(fields={"path": "PathField()"})
    with pytest.raises(ValueError, match="ConfigField"):
        DictField(fields={"path": None})


def test_dict_field_rejects_non_str_keys():
    with pytest.raises(ValueError, match="str"):
        DictField(fields={1: TextField()})


def test_gradient_field_fills_item_automatically():
    """渐变的键是固定的，不用手写 DictField。"""
    f = GradientField(default=[{"pos": 0.0, "color": (1, 2, 3, 255)}])
    assert f.item.keys == ["pos", "color"]
    assert isinstance(f.item.fields["pos"], NumberField)
    assert isinstance(f.item.fields["color"], ColorField)
    # pos 是 0~1、color 是四元组
    assert f.item.fields["pos"].range == (0.0, 1.0)
    assert f.item.fields["color"].rgba is True


def test_gradient_field_is_a_list_field():
    """渐变是一种特定的列表 —— 继承方向保留了 isinstance。"""
    assert issubclass(GradientField, ListField)
    assert isinstance(GradientField(), ListField)


def test_container_fields_keep_fields_out_of_defaults():
    """嵌套 Field 绝不能漏进 DEFAULTS —— 它是落盘的那一份。"""
    class K(ConfigKeysBase):
        items = ListField(
            default=[{"path": "a"}],
            item=DictField(fields={"path": PathField()}),
        )
        grad = GradientField(default=[])

    assert K.DEFAULTS == {"items": [{"path": "a"}], "grad": []}
    assert not any(isinstance(v, ConfigField) for v in K.DEFAULTS.values())
    json.dumps(K.DEFAULTS)                 # 必须可序列化


def test_dict_field_new_item_fills_each_key_from_its_field():
    """``new_item()`` = 新增一整条时的初值，每个键取自己 Field 的默认值。

    这是 ``DictField`` 里子字段 ``default`` 的用途：决定**新加的一条**长什么样，
    和这个键当前有几条无关。
    """
    f = DictField(fields={
        "name": PathField(default="", mode="file"),
        "port": NumberField(default=8080, range=(1, 65535), step=1),
    })
    assert f.new_item() == {"name": "", "port": 8080}


def test_list_field_new_item_delegates_to_dict_field():
    """``ListField(item=DictField(...)).new_item()`` 就是整条初值。"""
    f = ListField(item=DictField(fields={
        "port": NumberField(default=8080, range=(1, 65535), step=1),
    }))
    assert f.new_item() == {"port": 8080}


def test_default_vs_new_item_are_different_things():
    """一条测试把「两回事」钉死，免得后来的人再混。"""
    f = ListField(
        default=[{"port": 80}, {"port": 443}],      # 现有两项
        item=DictField(fields={
            "port": NumberField(default=8080, range=(1, 65535), step=1),
        }),
    )
    assert f.default == [{"port": 80}, {"port": 443}]   # 初始有几项
    assert f.new_item() == {"port": 8080}               # 新增时那一项


# ──────────────────────────────────────────────────────────────
# 嵌套交叉：容器里塞容器
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inner, expected", [
    (TextField(default="s"), "s"),
    (NumberField(default=1, range=(0, 9), step=1), 1),
    (ChoiceField(default="a", options=("a", "b")), "a"),
    (ColorField(default=[1, 2, 3]), [1, 2, 3]),
    (PathField(default=""), ""),
    (ImageField(default=""), ""),
    (DateField(default="2025-01-01"), "2025-01-01"),
])
def test_list_item_accepts_every_scalar_field(inner, expected):
    """``ListField.item`` 塞任何标量 Field 都能取到初值。"""
    assert ListField(item=inner).new_item() == expected


@pytest.mark.parametrize("inner, expected", [
    (TextField(default="s"), {"v": "s"}),
    (NumberField(default=1, range=(0, 9), step=1), {"v": 1}),
    (PathField(default=""), {"v": ""}),
])
def test_dict_accepts_every_scalar_field(inner, expected):
    assert DictField(fields={"v": inner}).new_item() == expected


def test_list_of_dict_is_the_l3list_shape():
    """列表里装字典 —— L3List 的形状。"""
    f = ListField(item=DictField(fields={
        "path": PathField(default="p"),
        "port": NumberField(default=80, range=(1, 65535), step=1),
    }))
    assert f.new_item() == {"path": "p", "port": 80}


def test_list_of_list_gives_empty_inner_list():
    """列表套列表：新的一行**本身又是一个列表**，所以是 ``[]``。"""
    f = ListField(item=ListField(item=TextField(default="z")))
    assert f.new_item() == []


def test_dict_of_dict_recurses():
    """字典套字典：内层默认值不会丢。"""
    f = DictField(fields={
        "inner": DictField(fields={
            "x": NumberField(default=7, range=(0, 9), step=1),
        }),
    })
    assert f.new_item() == {"inner": {"x": 7}}


def test_gradient_is_list_of_fixed_dict():
    """渐变 = 特定形状的列表，两层的初值都对。"""
    g = GradientField()
    assert g.new_item() == {"pos": 0.0, "color": [0, 0, 0, 255]}
    assert g.item.keys == ["pos", "color"]


def test_deep_nesting_keeps_all_defaults():
    """三层嵌套：list -> dict -> dict。"""
    f = ListField(item=DictField(fields={
        "a": DictField(fields={
            "b": TextField(default="deep"),
        }),
    }))
    assert f.new_item() == {"a": {"b": "deep"}}


def test_nested_containers_stay_out_of_defaults():
    """再深的嵌套也不能让 Field 漏进 DEFAULTS。"""
    class K(ConfigKeysBase):
        deep = ListField(
            default=[],
            item=DictField(fields={
                "rows": ListField(
                    default=[],
                    item=DictField(fields={"n": TextField(default="x")}),
                ),
            }),
        )

    assert K.DEFAULTS == {"deep": []}
    assert not any(isinstance(v, ConfigField) for v in K.DEFAULTS.values())
