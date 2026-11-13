"""配置项的额外属性：声明一个配置项时，顺带说清它的形状。

只写默认值说不清「这一项是什么」—— 范围多大、步进多少、有哪些选项、
标题叫什么。这些描述写在这里，绑同一个键的多个控件就不用各抄一份::

    class AppKeys(ConfigKeysBase):
        height = NumberField(
            default=500, range=(0, 1080), step=1, unit="px",
            title="窗口高度", desc="仅对新建窗口生效",
        )

    SliderItem(config_item=cfg.height)      # 标题/范围/步进/单位全从声明来

只管类型，不管值
----------------
``NumberField(default=500, range=(0, 100))`` 是合法的：500 超出范围属于
「这个值合不合规矩」，由消费侧判断。本模块只把**类型**定死 ——
``range`` 是二元组、``options`` 是非空序列、``mode`` 三选一，
和 ``bool`` 只有真/假是同一类事。形状不对当场 ``ValueError``。

哪些属性放这里
--------------
标准：**配一个纯 CLI（不用 xiaoe_ui）时，这个属性还会不会被用到**。
会用到就留下 —— ``unit``（CLI 打印 ``500 px``）、``start_dir``（选择器起点）、
``check_exists``（CLI 校验路径）都算。

只有画界面才用得上的（``btn_text`` / ``placeholder`` / ``dialog_*`` /
``empty_img_text`` / ``size``）不在这里，由 :mod:`xiaoe_ui.config.field_ui`
以子类扩展。

槽位归属
--------
``title`` / ``desc`` 归 L3（配置行），子类自有字段归 L2（输入控件），
``default`` 是数据本身。三者互不重叠。

为什么 ``kw_only`` + ``frozen``
-------------------------------
``kw_only`` 让漏写参数当场报错，而不是把值塞给隔壁那个参数
（``NumberField(500)`` 会变成 ``range=500``）；同时它对子类加必填槽。

``frozen`` 让一个 Field 实例可以被多处安全共享（同一份声明、``memory()``
合成的类、主题参数），``dataclasses.replace()`` 也能用。
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from typing import (
    TYPE_CHECKING, Any, Callable, Generic, Literal, TypeVar, get_args, overload,
)

if TYPE_CHECKING:
    from xiaoe_config_manager.config_dot import ConfigItemProxy

__all__ = [
    "PATH_MODES",
    "ChoiceField",
    "ColorField",
    "ConfigField",
    "DateField",
    "DictField",
    "FloatField",
    "GradientField",
    "ImageField",
    "IntField",
    "ListField",
    "NumberField",
    "PathField",
    "PathMode",
    "TextField",
]

T = TypeVar("T")


#: 「一个数」的运行时判据。``bool`` 是 ``int`` 的子类，但把 ``True`` 当范围
#: 端点显然是写错了，所以单独排除。
_NUMBERS = (int, float)


def _is_number(value: Any) -> bool:
    """``True`` 表示这是个当数值用的数（排除 ``bool``）。"""
    return isinstance(value, _NUMBERS) and not isinstance(value, bool)


def _as_range(value: Any) -> tuple:
    """把 ``range`` 收敛成 ``(min, max)``，形状不对当场抛。

    这是**类型**层面的检查（这个字段必须是一个区间），不是"值合不合适"——
    ``(0, 1080)`` 里放什么都行，但必须是两个数、且 ``min <= max``。

    Args:
        value: 声明里传的 ``range``。

    Returns:
        规范化的 ``(lo, hi)`` 二元组（``list`` 会被转成 ``tuple``）。

    Raises:
        ValueError: 不是二元组/二元素列表、元素不是数、或 ``min > max``。
    """
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError(
            f"range 的类型是 (min, max) 二元组，实际是 {type(value).__name__}。"
            f"写 range=({value!r}, 100) 这种带括号的写法；只有一个数不是区间。"
        )
    if len(value) != 2:
        raise ValueError(
            f"range 必须正好两个数 (min, max)，实际给了 {len(value)} 个：{value!r}。"
        )
    lo, hi = value
    for name, item in (("min", lo), ("max", hi)):
        if not _is_number(item):
            raise ValueError(
                f"range 的 {name} 必须是数字（int / float），"
                f"实际是 {type(item).__name__}：{item!r}。"
            )
    if lo > hi:
        raise ValueError(
            f"range 的 min 不能大于 max：{value!r}。"
            f"（写反了的话滑块范围是空的，位置算出来是负数。）"
        )
    return (lo, hi)


def _check_step(value: Any) -> None:
    """``step`` 必须是正数，否则当场抛。

    ``position = (value - min) / step``：``step <= 0`` 直接除零或倒着走。

    Args:
        value: 声明里传的 ``step``。

    Raises:
        ValueError: 不是数、或是非正数。
    """
    if not _is_number(value):
        raise ValueError(
            f"step 必须是数字（int / float），实际是 {type(value).__name__}：{value!r}。"
        )
    if value <= 0:
        raise ValueError(
            f"step 必须是正数，实际是 {value!r}。"
            f"（位置 = (值 - min) / step，非正数算不出位置。）"
        )

#: 路径的三种取值模式：``file`` 选已存在的文件 / ``dir`` 选目录 /
#: ``save`` 选要写入的位置。
PathMode = Literal["file", "dir", "save"]

#: :data:`PathMode` 的全部取值（``mode`` 这个类型的定义域）
PATH_MODES: tuple[str, ...] = get_args(PathMode)


@dataclass(frozen=True, kw_only=True)
class ConfigField(Generic[T]):
    """所有额外属性的基类：只管「值 + 语义」。

    它同时是个描述符 —— 访问类属性拿到的是**默认值**，不是 Field 对象::

        class AppKeys(ConfigKeysBase):
            height = NumberField(default=500, range=(0, 1080), step=1)

        AppKeys.height                  # 500
        vars(AppKeys)["height"]         # NumberField(...)，扫描器从这里读

    没有这一步，把声明类当默认值字典用的代码会静默改行为。

    Args:
        default: 默认值。必须是可落盘的配置值（``str`` / ``int`` / ``float``
            / ``bool`` / ``list`` / ``dict`` / ``None``）；Field 本身不进
            ``DEFAULTS``。
        title: 行标题。L3 消费。
        desc: 补充说明。L3 消费，渲染成说明行还是悬停提示由控件决定。
    """

    #: 默认值。会进 ``DEFAULTS``、落盘、参与 ``reset``。
    default: T | None = None

    #: 配置项的名字，L3 拿来当行标题。
    title: str = ""

    #: 这个配置项是干什么的。L3 自己决定渲染成说明行还是 tooltip。
    desc: str = ""

    @overload
    def __get__(self, obj: None, objtype: type | None = None) -> T: ...

    @overload
    def __get__(self, obj: object, objtype: type | None = None) -> ConfigItemProxy[T]: ...

    def __get__(self, obj: Any = None, objtype: type | None = None) -> Any:
        """属性访问：**类上拿默认值，实例上拿配置项句柄**。

        两个重载分别对应这两种访问，返回值类型也因此不同：

        * ``AppKeys.height`` → ``T``（默认值本身，``500``）；
        * ``cfg.height`` → ``ConfigItemProxy[T]``（.get() / .set() 都能用）。

        为什么要两个重载：声明处写的是 ``IntField`` 对象，但**实例上根本
        不是它** —— ``ConfigDeclareMixin`` 会把这个属性换成
        :class:`~xiaoe_config_manager.config_dot.ConfigItemProxy` 的 property。
        只写一个返回 ``T`` 的话，检查器会以为 ``cfg.height`` 是个 ``int``，
        于是 ``cfg.height.get()`` 被误报。反过来只写代理的话，
        ``AppKeys.height`` 这个"读默认值"的用法就断了。

        Args:
            obj: 访问者。``None`` 表示通过类访问。
            objtype: 所属类（描述符协议的第二个参数，本类不用）。

        Returns:
            类访问返回 :attr:`default`；实例访问返回配置项句柄。

        Note:
            实例访问在运行时**不会**走到这里（property 先一步接管），
            第二个重载只服务类型检查器。
        """
        return self.default


@dataclass(frozen=True, kw_only=True)
class NumberField(ConfigField[T]):
    """数值型配置项的基类：**一个落在区间里的数**。

    一般不直接用，用下面两个子类之一：

    * :class:`IntField` —— 值一定是 ``int``；
    * :class:`FloatField` —— 值一定是 ``float``。

    拆开的理由和 Django 一样：类型是**字段类自己的属性**，不该让检查器
    从 ``default`` 去猜。``IntField(default=3)`` 天然只收整数，
    ``FloatField(default=0.5)`` 天然只收小数，写的人不用额外说明，
    读的人（IDE / CLI）也不用推断。

    范围和步进都必填 —— 少一个就算不出滑块位置（``(value - min) / step``）。

    Args:
        default: 默认值。
        title: 行标题。
        desc: 补充说明。
        range: ``(min, max)``，两个数值且 ``min <= max``。
        step: 正数步进，同时决定显示几位小数（``1`` → 无小数，``0.01`` → 两位）。
        unit: 单位文本（如 ``"px"``），CLI 输出和滑块提示都会用。

    Raises:
        ValueError: ``range`` 不是两个数值、``min > max``、``step`` 不是正数，
            或整数区间配了小数步进。
    """

    #: ``(min, max)``。必填。
    range: tuple = _dc_field()

    #: 步进。必填 —— 决定显示几位小数。
    step: float | int = _dc_field()

    #: 单位文本，如 ``"px"``。
    unit: str = ""

    def __post_init__(self):
        """检查 ``range`` / ``step`` 的形状、数值族，以及默认值是否合这个族。

        不管「值合不合适」—— ``default`` 超出 ``range`` 照样合法，
        那是消费侧的事。这里只管「这个数是不是这个类的那种数」。
        """
        lo_hi = _as_range(self.range)
        _check_step(self.step)
        # 整数区间配小数步进：每步都落在整数之间，显示值和实际值必然错位。
        int_range = all(isinstance(v, int) and not isinstance(v, bool) for v in lo_hi)
        int_step = isinstance(self.step, int) and not isinstance(self.step, bool)
        if int_range and not int_step:
            raise ValueError(
                f"range={self.range} 是整数区间，step={self.step!r} 却是小数 —— "
                f"滑块会停在整数之间。要小数请把 range 也写成小数"
                f"（如 (0.0, 1.0)），或者改用 FloatField。"
            )
        self._check_default_kind()

    def _check_default_kind(self) -> None:
        """子类实现：这个类的值必须是哪种数。

        基类不限制（``int`` / ``float`` 都收）。
        """


@dataclass(frozen=True, kw_only=True)
class IntField(NumberField[int | None]):
    """整数配置项：值一定是 ``int``。

    ``step`` 必须是整数（不能是 ``0.5``），否则滑块会停在整数之间。

    Args:
        default / title / desc / range / step / unit: 见 :class:`NumberField`。

    Examples:
        ::

            height = IntField(default=500, range=(0, 1080), step=1, unit="px")
            cfg.height.get()        # -> int
    """

    def __post_init__(self):
        """先跑基类的形状检查，再要求 ``step`` 和 ``default`` 都是整数。"""
        super().__post_init__()
        if not (isinstance(self.step, int) and not isinstance(self.step, bool)):
            raise ValueError(
                f"IntField 的 step 必须是整数，实际是 {self.step!r}。"
                f"要小数步进请改用 FloatField。"
            )
        self._check_default_kind()

    def _check_default_kind(self) -> None:
        """``default`` 必须是整数（``None`` = 没给，放行）。"""
        if self.default is None:
            return
        if isinstance(self.default, bool) or not isinstance(self.default, int):
            raise ValueError(
                f"IntField 的 default 必须是整数，实际是 "
                f"{type(self.default).__name__}：{self.default!r}。"
                f"要小数请改用 FloatField。"
            )


@dataclass(frozen=True, kw_only=True)
class FloatField(NumberField[float | None]):
    """小数配置项：值一定是 ``float``。

    ``range`` 建议写成小数（``(0.0, 1.0)``）；写整数区间配小数步进会被拦。

    Args:
        default / title / desc / range / step / unit: 见 :class:`NumberField`。

    Examples:
        ::

            opacity = FloatField(default=0.85, range=(0.0, 1.0), step=0.01)
            cfg.opacity.get()       # -> float
    """

    def __post_init__(self):
        """先跑基类的形状检查，再要求 ``default`` 是小数（或整数，会按小数存）。"""
        super().__post_init__()
        self._check_default_kind()

    def _check_default_kind(self) -> None:
        """``default`` 必须是数（整数也接受 —— 它是"可以写成小数的值"）。

        ``default=1`` 在 FloatField 上是合法的（就是 ``1.0``），所以这里只
        排除非数值，不强制 ``isinstance(x, float)``。
        """
        if self.default is None:
            return
        if isinstance(self.default, bool) or not isinstance(self.default, (int, float)):
            raise ValueError(
                f"FloatField 的 default 必须是数字，实际是 "
                f"{type(self.default).__name__}：{self.default!r}。"
            )


@dataclass(frozen=True, kw_only=True)
class ChoiceField(ConfigField[T | None]):
    """从固定选项里挑一个。

    ``store_index`` 决定配置里存的是**索引**还是**原始值** —— 同一个下拉框，
    存 ``2`` 和存 ``"选项B"`` 是两种不同的数据。

    Args:
        default: 默认值。
        title: 行标题。
        desc: 补充说明。
        options: 候选项，非空序列。空下拉框的选中项索引是 -1。
        store_index: ``True`` 存索引（``int``）；``False`` 存选项本身的值。

    Raises:
        ValueError: ``options`` 是字符串（多半忘了逗号）、为空，
            或 ``store_index`` 不是 bool。
    """

    #: 候选项。必填。
    options: tuple = _dc_field()

    #: ``True`` = 配置里存索引；``False`` = 存原始值。
    store_index: bool = False

    def __post_init__(self):
        """检查 ``options`` 和 ``store_index`` 的形状。

        ``options="abc"`` 会变成三个字符的选项，那是少写逗号的笔误。
        """
        if isinstance(self.options, str) or not isinstance(self.options, (list, tuple)):
            raise ValueError(
                f"options 的类型是「非空序列」，实际是 {type(self.options).__name__}。"
                f"想给一个选项请写 options=({self.options!r},) —— 带逗号的元组。"
            )
        if not self.options:
            raise ValueError(
                "options 不能为空：空下拉框的选中项索引是 -1，value() 会当场 IndexError。"
            )
        if not isinstance(self.store_index, bool):
            raise ValueError(
                f"store_index 的类型是 bool，实际是 "
                f"{type(self.store_index).__name__}：{self.store_index!r}。"
                f"它决定配置里存索引还是存原值，不接受模糊的值。"
            )


@dataclass(frozen=True, kw_only=True)
class ColorField(ConfigField[list[int] | None]):
    """颜色配置项：**一个由分量组成的颜色**。

    ``rgba`` 是数据形状：``False`` 存三个分量（RGB），``True`` 存四个
    （RGBA，最后一个是 alpha）。``default`` 的分量个数必须和它一致，否则
    下游按 ``rgba`` 取分量时会多丢少补，颜色不对但不报错。

    值是 **list**（``[r, g, b]``），不是 tuple —— 配置值只支持 JSON 能表达的
    类型，列表才是落盘再读回来还长得一样的那一种。

    Args:
        default: RGB 或 RGBA 分量列表，如 ``[255, 0, 0]``；``None`` = 没给。
        title: 行标题。
        desc: 补充说明。
        rgba: 值是否带透明度（4 个分量 vs 3 个）。

    Raises:
        ValueError: ``rgba`` 不是 bool；``default`` 不是序列、分量不是
            0~255 的整数、或个数和 ``rgba`` 对不上。

    Note:
        按钮上的提示文字不在这里（CLI 没有按钮），见
        :class:`xiaoe_ui.config.field_ui.ColorOptions`。
    """

    #: 值是否带 alpha。
    rgba: bool = False

    def __post_init__(self):
        """把 ``default`` 和 ``rgba`` 一起限定成「一个颜色」。

        三件事一起查，因为它们互相约束：

        1. ``rgba`` 的类型是 bool；
        2. ``default`` 是 3 或 4 个分量的序列（``None`` = 没给默认值，放行）；
        3. 分量个数和 ``rgba`` **一致** —— 这条是本类存在的理由。

        注意这里**不检查颜色好不好看**（那不归 Field 管），只检查它是不是
        一个该形状的颜色。
        """
        if not isinstance(self.rgba, bool):
            raise ValueError(
                f"rgba 的类型是 bool，实际是 {type(self.rgba).__name__}：{self.rgba!r}。"
                f"它决定值是 3 个分量还是 4 个分量，不接受模糊的值。"
            )
        if self.default is None:
            return                       # 没给默认值，不涉及形状

        value = self.default
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError(
                f"颜色的类型是 [r, g, b] 或 [r, g, b, a] 这样的分量列表，"
                f"实际是 {type(value).__name__}：{value!r}。"
                f"字符串颜色（如 \"#ff0000\"）不在这里接受 —— 存的是分量。"
            )

        expect = 4 if self.rgba else 3
        if len(value) != expect:
            raise ValueError(
                f"rgba={self.rgba} 要求 {expect} 个分量，"
                f"但 default 给了 {len(value)} 个：{value!r}。"
                + (
                    "（rgba=True 是带透明度的那一种，最后一位是 alpha。）"
                    if self.rgba else
                    "（rgba=False 是 RGB；要带透明度请写 rgba=True。）"
                )
            )

        for i, item in enumerate(value):
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(
                    f"颜色分量必须是 0~255 的整数，第 {i} 个是 "
                    f"{type(item).__name__}：{item!r}。"
                )
            if not 0 <= item <= 255:
                raise ValueError(
                    f"颜色分量必须在 0~255 之间，第 {i} 个是 {item}。"
                )


@dataclass(frozen=True, kw_only=True)
class TextField(ConfigField[str | None]):
    """文本配置项：**一个字符串**。

    ``value_type`` 决定配置里存的是 ``str`` 还是数字 —— 它是值的类型，
    不是输入时的检查。

    Args:
        default: 默认值。
        title: 行标题。
        desc: 补充说明。
        value_type: 把输入框里的字符串转成什么。``str``（默认）存字符串；
            ``int`` / ``float`` 存数字。也可以是自定义的可调用对象。

    Raises:
        ValueError: ``value_type`` 不是可调用的。

    Note:
        ``placeholder``（框里那行灰字）不在这里，见
        :class:`xiaoe_ui.config.field_ui.TextOptions`。
    """

    #: 把输入文本转成什么类型（决定 config 里存 str 还是 int/float）。
    value_type: Callable[[str], Any] = str

    def __post_init__(self):
        """``value_type`` 必须是可调用的。

        不是 callable 的话要到提交时才 ``TypeError``，那时用户已经输入完了。
        """
        if not callable(self.value_type):
            raise ValueError(
                f"value_type 必须是可调用的（str / int / float / 自定义函数），"
                f"实际是 {type(self.value_type).__name__}：{self.value_type!r}。"
                f"它决定 config 里存字符串还是数字。"
            )


@dataclass(frozen=True, kw_only=True)
class DateField(ConfigField[str | None]):
    """日期配置项：**一个按固定格式序列化的时间点**。

    配置里存的是按 ``fmt`` 转出来的字符串，所以它决定值的形状而不是外观：
    ``"2025-01-01"`` 和 ``"2025/01/01"`` 是两个不同的值，下游按它解析回来。
    格式一变，老配置就读不出来了。

    Args:
        default: 默认值（按 ``fmt`` 格式化的字符串，或空串）。
        title: 行标题。
        desc: 补充说明。
        fmt: 日期格式串，如 ``"yyyy-MM-dd"`` / ``"yyyy/MM/dd HH:mm"``。

    Raises:
        ValueError: ``fmt`` 不是非空、非全空白的字符串。
    """

    #: Qt 日期格式串（同时决定 config 里那个字符串的形状）。
    fmt: str = "yyyy-MM-dd"

    def __post_init__(self):
        """``fmt`` 必须是非空字符串。

        空串在 Qt 里不会报错，只会让 ``toString("")`` 返回空 —— 于是配置里
        存的全是空字符串、界面永远显示空。这种"能跑但什么都不显示"最难查。
        """
        if not isinstance(self.fmt, str):
            raise ValueError(
                f"fmt 的类型是 str，实际是 {type(self.fmt).__name__}：{self.fmt!r}。"
                f"要默认格式请写 fmt=\"yyyy-MM-dd\"。"
            )
        if not self.fmt:
            raise ValueError(
                "fmt 不能为空：空格式串会让 Qt 转出空字符串，"
                "配置里存的就永远是 \"\"、界面也永远显示空。"
            )
        if not self.fmt.strip():
            raise ValueError(
                f"fmt 不能全是空白：{self.fmt!r}。"
                f"Qt 会照原样输出空白，配置里存的就是空格。"
            )


@dataclass(frozen=True, kw_only=True)
class ImageField(ConfigField[str | None]):
    """图片配置项：**一张图片的文件地址**。

    比 :class:`PathField` 收窄的地方是语义：这里明确「要一个**文件**」并且
    当图片用，所以没有 ``mode``。

    后缀只由 :attr:`file_filter` 表达，**不校验**：能加载哪些格式取决于运行时
    那一侧的图像后端，我们没有立场比它更严格。

    Args:
        default: 默认值（图片路径字符串，或 ``None`` 表示没设）。
        title: 行标题。
        desc: 补充说明。
        file_filter: 文件选择器的过滤器，默认是常见图片后缀。
            要加格式就往里加（如 ``"*.webp"``）。
        start_dir: 选择器的起始目录；空 = 用当前路径所在目录。

    Raises:
        ValueError: ``file_filter`` / ``start_dir`` 不是字符串，
            或 ``file_filter`` 是空白。

    Note:
        预览区相关（``empty_img_text`` / ``size``）不在这里，见
        :class:`xiaoe_ui.config.field_ui.ImageOptions`。
    """

    #: 文件选择器过滤器（哪些后缀算图片）。
    file_filter: str = "图片 (*.png *.jpg *.jpeg *.bmp *.gif)"

    #: 选择器的起始目录；空 = 用当前路径所在目录。
    start_dir: str = ""

    def __post_init__(self):
        """把每个槽限定在自己的类型里。

        ``file_filter`` 直接进选择器：给空串会让它列出**所有**文件，
        跟"我要一张图片"的声明自相矛盾，所以要拦住。
        """
        for name in ("file_filter", "start_dir"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(
                    f"{name} 的类型是 str，实际是 {type(value).__name__}：{value!r}。"
                )
        if not self.file_filter.strip():
            raise ValueError(
                "file_filter 不能为空：空过滤器会列出所有文件，"
                "和「这个键存的是一张图片」自相矛盾。"
            )


@dataclass(frozen=True, kw_only=True)
class PathField(ConfigField[str | None]):
    """路径配置项：**这个地址是什么东西**。

    ``mode`` / ``file_filter`` / ``start_dir`` / ``check_exists`` 描述取值方
    对它的期待（要文件夹还是文件、只要 .exe、从哪找、允许还不存在）。
    给错就会拿到一个当时不该出现的地址，而且往往在很远的地方才炸。

    路径内容本身不检查（允许用户手输）。``mode`` 被限定在 :data:`PathMode`
    的定义域里 —— 那是类型，不是「这个值好不好」。

    Args:
        default: 默认值（一个路径字符串）。
        title: 行标题。
        desc: 补充说明。
        mode: ``"file"`` 选已存在的文件 / ``"dir"`` 选目录 /
            ``"save"`` 选要写入的位置。
        file_filter: 文件过滤器，如 ``"程序 (*.exe)"``；``dir`` 模式忽略。
        start_dir: 选择器的起始目录；空则用当前路径所在目录。
        check_exists: 是否要求路径**现在就存在**。要选还没创建的目录/文件时
            传 ``False``。

    Raises:
        ValueError: ``mode`` 不在 :data:`PATH_MODES` 里，或某个槽的类型不对。

    Note:
        对话框外观（``placeholder`` / ``icon`` / ``dialog_*``）不在这里，
        见 :class:`xiaoe_ui.config.field_ui.PathOptions`。

    Examples:
        ::

            class AppKeys(ConfigKeysBase):
                game_dir = PathField(
                    default="", mode="dir", check_exists=False,
                    title="游戏目录", desc="存档和截图都存在这里",
                )
    """

    #: 取值模式：选文件 / 选目录 / 选保存位置（类型是 :data:`PathMode`）。
    mode: PathMode = "file"

    #: 文件过滤器；``dir`` 模式忽略。
    file_filter: str = "所有文件 (*)"

    #: 选择器起始目录；空 = 用当前路径所在目录。
    start_dir: str = ""

    #: 是否要求路径现在就必须存在。
    check_exists: bool = True

    def __post_init__(self):
        """把每个槽限定在自己的类型里。

        ``dataclasses.replace()`` 会重跑本方法，所以"换一份改错"也能拦住。

        Raises:
            ValueError: ``mode`` 不在 :data:`PATH_MODES` 里，或某个槽的类型不对。
        """
        if self.mode not in PATH_MODES:
            raise ValueError(
                f"mode 的类型是 {PATH_MODES} 三选一，实际是 {self.mode!r}。"
                f"file=选已存在的文件，dir=选目录，save=选要写入的位置。"
            )
        for name in ("file_filter", "start_dir"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(
                    f"{name} 的类型是 str，实际是 {type(value).__name__}：{value!r}。"
                )
        if not isinstance(self.check_exists, bool):
            raise ValueError(
                f"check_exists 的类型是 bool，实际是 {type(self.check_exists).__name__}："
                f"{self.check_exists!r}。"
            )


@dataclass(frozen=True, kw_only=True)
class DictField(ConfigField[dict | None]):
    """字典配置项：**固定几个键，每个键各是一种类型**。

    键是写死的，不是自由字典：``fields`` 声明的就是它的 schema，键顺序也按
    声明顺序。

    Args:
        default: 默认值（一个 dict）；``None`` = 没给。
        title: 行标题。
        desc: 补充说明。
        fields: ``{键名: ConfigField}``，键固定、顺序固定。

    Raises:
        ValueError: ``fields`` 不是 dict、为空，或其中某项不是
            :class:`ConfigField`。

    Examples:
        ::

            addr = DictField(fields={
                "path": PathField(mode="dir"),
                "port": NumberField(range=(1, 65535), step=1),
            })
    """

    #: ``{键名: ConfigField}``。必填 —— 空字典等于"没有键"。
    fields: dict = _dc_field(default_factory=dict)

    def __post_init__(self):
        """``fields`` 必须是「键 -> ConfigField」的表。"""
        if not isinstance(self.fields, dict):
            raise ValueError(
                f"fields 的类型是 dict，实际是 {type(self.fields).__name__}："
                f"{self.fields!r}。写成 fields={{'名字': PathField(...)}}。"
            )
        if not self.fields:
            raise ValueError(
                "fields 不能为空：DictField 的键是声明出来的，没有键就无从取值。"
            )
        for key, sub in self.fields.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"fields 的键必须是 str，实际是 {type(key).__name__}：{key!r}。"
                )
            if not isinstance(sub, ConfigField):
                raise ValueError(
                    f"fields[{key!r}] 必须是 ConfigField，实际是 "
                    f"{type(sub).__name__}：{sub!r}。"
                )

    @property
    def keys(self) -> list:
        """键名列表，按声明顺序。"""
        return list(self.fields)

    def new_item(self) -> dict:
        """新增一整条时的初值：每个键各自取自己 Field 的默认值。

        这是 ``DictField`` 里子字段 ``default`` 的唯一用途 —— 决定**新加的一条**
        长什么样，和这个键当前有几条无关::

            DictField(fields={
                "path": PathField(default=""),
                "port": NumberField(default=8080, range=(1, 65535), step=1),
            }).new_item()      # {"path": "", "port": 8080}

        子字段本身也是容器时（``DictField`` / ``ListField``）会继续往里递归，
        所以嵌套的默认值不会丢。
        """
        out = {}
        for key, sub in self.fields.items():
            maker = getattr(sub, "new_item", None)
            out[key] = maker() if callable(maker) else sub.default
        return out


@dataclass(frozen=True, kw_only=True)
class ListField(ConfigField[list[T] | None], Generic[T]):
    """列表配置项：**一串同类型的东西**。

    ``default`` 和 ``item`` 里的默认值是**两回事**，容易混：

    * ``default`` —— 这个键**初始有几项**（一般是空列表）；
    * ``item`` —— 每次**新增一项**时，那一项的初值从这里的 ``default`` 来。

    所以 ``item`` 必填：它说明"往里加什么"。想知道新加的一项长什么样看
    ``item.default``；想知道现在列表里有什么看这个键的值。

    ``item`` 也可以是 :class:`DictField` —— 那时列表里装的是固定几个键的字典
    （``L3List`` 期望的正是这个形状）::

        paths = ListField(
            default=[],
            item=DictField(fields={"path": PathField(mode="file")}),
        )

    Args:
        default: 初始值（一个 list）；``None`` = 没给。
        title: 行标题。
        desc: 补充说明。
        item: 每一项是什么，必须是 :class:`ConfigField`。

    Raises:
        ValueError: ``item`` 不是 :class:`ConfigField`。

    Examples:
        ::

            tags = ListField(default=["常用"], item=TextField())
            ports = ListField(item=NumberField(range=(1, 65535), step=1))
    """

    #: 每一项是什么。
    item: ConfigField = None

    def __post_init__(self):
        """``item`` 必须是 Field —— 它说明列表里装什么。"""
        if not isinstance(self.item, ConfigField):
            raise ValueError(
                f"item 的类型是 ConfigField，实际是 "
                f"{type(self.item).__name__}：{self.item!r}。"
                f"它说明列表里每一项是什么，比如 item=TextField()、"
                f"item=DictField(fields={{...}})。"
            )

    def new_item(self) -> Any:
        """新增一项时的初值 —— 一行长什么样，由 ``item`` 决定。

        * ``item=DictField(...)`` → 按每个键的默认值拼出整条；
        * ``item=TextField(default="x")`` → ``"x"``；
        * ``item=ListField(...)`` → ``[]``（列表里的一行本身又是一个列表）。

        这也是 ``item`` 必填的原因：没有它，新增的一行不知道该填什么。
        """
        # 嵌套列表：新的一行是一个空列表，不是内层元素的初值
        if isinstance(self.item, ListField):
            return []
        maker = getattr(self.item, "new_item", None)
        return maker() if callable(maker) else self.item.default


#: 渐变色每一项的形状（``GradientField`` 自动填进 ``item``）。
_GRADIENT_STOP = DictField(fields={
    "pos": NumberField(default=0.0, range=(0.0, 1.0), step=0.01),
    "color": ColorField(default=[0, 0, 0, 255], rgba=True),
})


@dataclass(frozen=True, kw_only=True)
class GradientField(ListField[dict | None]):
    """渐变色配置项：**一串色标**，每项固定是 ``{"pos", "color"}``。

    ``pos`` 是 0~1 的位置，``color`` 是 ``(r, g, b, a)`` 四元组。两个键由本类
    固定，不用手写 :class:`DictField`。

    Args:
        default: 初始色标列表；``None`` = 没给。
        title: 行标题。
        desc: 补充说明。

    Examples:
        ::

            bg = GradientField(default=[
                {"pos": 0.0, "color": (255, 255, 255, 255)},
                {"pos": 1.0, "color": (0, 0, 0, 255)},
            ])
    """

    def __post_init__(self):
        """先填好固定的 ``item``，再走 ``ListField`` 的检查。"""
        if self.item is None:
            object.__setattr__(self, "item", _GRADIENT_STOP)
        super().__post_init__()
