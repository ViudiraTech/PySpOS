pragma Singleton
import QtQuick

/*
 *      Theme.qml
 *      Design tokens for every VortexGlass surface.
 *
 *      2026/10/16 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 * QML 只引用这里的名字，不再写字面量。颜色沿用收拢前的取值，本文件是重命名，
 * 唯一的例外是 textPrimary：原先 #f0f5fb 与 #f3f7fc 两处近白被合并成一个。
 * 圆角按 Fluent 规则分档（顶层容器 8 / 页内元素 4 / 贴边或最大化 0），间距梯
 * 与网站那层的 docs/css/tokens.css 的 --pg-space-*（4px 基数）对齐。
 */

QtObject {
    // ------------------------------------------------------------------
    // 间距：4px 基数梯，与 docs/css/tokens.css 的 --pg-space-1..9 对齐
    // ------------------------------------------------------------------
    readonly property int space1: 4
    readonly property int space2: 8
    readonly property int space3: 12
    readonly property int space4: 16
    readonly property int space5: 24
    readonly property int space6: 32
    readonly property int space7: 48
    readonly property int space8: 72
    readonly property int space9: 96

    // ------------------------------------------------------------------
    // 圆角：Fluent 的 ControlCornerRadius / OverlayCornerRadius 两个旋钮
    // ------------------------------------------------------------------
    readonly property int radiusControl: 4      // 页内元素：按钮、输入框、列表项
    readonly property int radiusOverlay: 8      // 顶层容器：窗口、flyout、dialog
    readonly property int radiusFlush: 0        // 贴屏幕边或最大化

    // ------------------------------------------------------------------
    // 颜色：桌面
    // ------------------------------------------------------------------
    readonly property color wallpaperTitle: "#8faecf"
    readonly property int watermarkX: 28
    readonly property int watermarkY: 24
    readonly property string themeCredit: "VortexGlass 主题素材：开放版 XJ380 · Uinxed-Kernel"
    // 没有可用壁纸图片时的兜底渐变
    readonly property color backdropTop: "#263d59"
    readonly property color backdropBottom: "#0d1929"

    // ------------------------------------------------------------------
    // 颜色：任务栏
    // ------------------------------------------------------------------
    // 这两处的 alpha 不是随手定的：玻璃面最终颜色取决于壁纸，而壁纸可能是纯白
    // 的。tools/checks/check_gui_tokens_contrast.py 按纯白/纯黑两个极端校验，
    // 这里的取值是让面上的文字在两种极端下都过 WCAG AA 的最小值再留余量。
    readonly property color taskbarBackground: "#b8142c43"
    readonly property color taskbarBorder: "#61839f"
    readonly property color windowButton: "#21364c"
    readonly property color windowButtonFocused: "#365c7c"

    // ------------------------------------------------------------------
    // 颜色：控件
    // ------------------------------------------------------------------
    readonly property color controlBackground: "#294765"
    readonly property color controlBackgroundActive: "#42678c"
    readonly property color textOnChrome: "#edf4fc"
    readonly property color dangerBackground: "#503442"

    // ------------------------------------------------------------------
    // 颜色：菜单与弹出层
    // ------------------------------------------------------------------
    readonly property color menuBackground: "#e01a3047"
    readonly property color menuBorder: "#8eafcd"
    readonly property color fieldBackground: "#263d56"
    readonly property color rowHover: "#42617f"

    // ------------------------------------------------------------------
    // 颜色：文字
    // ------------------------------------------------------------------
    readonly property color textPrimary: "#f0f5fb"
    readonly property color textSecondary: "#a6bed5"
    readonly property color textPlaceholder: "#9cb6cf"
    // 应用图标画在 SRGB 里，颜色烤进了 SVG 的 stroke：改这里就要一起改
    // assets/icons/*.svg，否则对比度检查挡的是 token 而界面用的是文件里的色。
    readonly property color iconAccent: "#b6d8fa"

    // ------------------------------------------------------------------
    // 字号
    // ------------------------------------------------------------------
    readonly property int fontTitle: 26         // 桌面水印
    readonly property int fontHeading: 20       // 菜单标题
    readonly property int fontBody: 15
    readonly property int fontCaption: 12

    // ------------------------------------------------------------------
    // 任务栏
    // ------------------------------------------------------------------
    readonly property int taskbarHeight: 42
    readonly property int controlHeight: 30
    readonly property int controlSpacing: 6
    readonly property int taskbarPadding: 10
    readonly property int startButtonWidth: 104
    readonly property int windowButtonWidth: 140
    readonly property int windowButtonPadding: 8

    // ------------------------------------------------------------------
    // 开始菜单
    // ------------------------------------------------------------------
    readonly property int menuMaxWidth: 380
    readonly property int menuMaxHeight: 400
    readonly property int menuHeightTrim: 64    // 菜单高度相对桌面高度的收缩
    readonly property int menuMargin: 10
    readonly property int menuBottomGap: 48
    readonly property int menuTitleX: 20
    readonly property int menuTitleY: 18
    readonly property int menuPadding: 16
    readonly property int menuSearchY: 54
    readonly property int menuSearchHeight: 38
    readonly property int fieldPadding: 10
    readonly property int menuListY: 104
    readonly property int menuListInset: 12
    readonly property int menuListBottomGap: 16
    // 系统级动作（退出桌面）放菜单底部，不占任务栏。KDE HIG 明确窗口管理动作
    // 不该和窗口按钮并列在任务栏上。
    readonly property int menuFooterHeight: 46
    readonly property int appRowHeight: 58
    readonly property int appRowSpacing: 4
    // 应用图标：assets/icons/ 下的 SVG，由 QML 按名字解析。
    readonly property int appIconX: 19
    readonly property int appIconSize: 22
    readonly property int appTextX: 58
    readonly property int appTitleY: 9
    readonly property int appCaptionY: 31

    // ------------------------------------------------------------------
    // 任务栏托盘
    // ------------------------------------------------------------------
    // Windows 11 的托盘是 16px 图标、32px 槽宽、4,0 内边距，但那根任务栏高 48；
    // 这里的任务栏是 42，所以槽位和字号都收一档。
    readonly property int trayChipPadding: 7
    readonly property int trayChipSize: 14
    readonly property int clockWidth: 86
    readonly property int clockTimeSize: 13
    readonly property int clockDateSize: 11
    // 标记底和任务栏同族但更深：白壁纸下四个强调色要同时达标，底色必须压到
    // #1a3047 这一档，用更亮的 #3a5c80 会有两项掉到 4.5 以下。
    readonly property color trayChipBackground: "#e01a3047"
    readonly property color trayText: "#dce7f2"
    readonly property color traySlot: "#9bc5e9"
    readonly property color trayLocked: "#e8c07d"
    readonly property color trayUnlocked: "#86cd9a"
    readonly property color trayRoot: "#e88b8b"
    readonly property color trayHover: "#e01a3047"

    // ------------------------------------------------------------------
    // 窗口装饰。这几个值跟着主题 PNG 的尺寸走（top.png 高 27、四角 8x25、
    // bottom.png 高 20），不是随手取的，改主题素材时要一起改。
    // ------------------------------------------------------------------
    readonly property int titleBarHeight: 28
    readonly property int frameBandTop: 25
    readonly property int frameBandLeft: 5
    readonly property int frameBandWidth: 6
    readonly property int frameBandRightInset: 11    // frameBandLeft + frameBandWidth
    readonly property int frameBandBottomInset: 39   // frameBandTop + frameBandWidth + frameFooterHeight
    readonly property int frameFooterHeight: 8
    readonly property int frameFooterTop: 20

    // ------------------------------------------------------------------
    // 模糊档位
    // ------------------------------------------------------------------
    // KWin 的 blur 插件把强度表达成 (降采样次数, offset) 而不是半径，理由是
    // 降采样省了像素之后，靠调 offset 就能把强度补回来。这里的对应物是
    // (比例, 屏幕半径)：纹理半径 = 屏幕半径 × 比例，所以降采样不改变观感。
    //
    // expand 是采样时向外多留的边，必须 >= 纹理半径，否则双线性插值会取到玻璃
    // 带以外的像素。屏幕半径本身也受伪影边界约束：太小看不出模糊，太大则外扩
    // 跟不上，边缘会出现一圈被拉进来的画面。
    readonly property var blurTiers: [
        { scale: 1.0, screenRadius: 8, expand: 16 },
        { scale: 0.5, screenRadius: 8, expand: 16 },
    ]
    // 超过这个像素数就用半分辨率档：省一半采样，半径按比例补回。
    readonly property int blurDownsampleArea: 500000
    // 噪声强度。模糊把渐变压成平滑过渡后，8 位色深会显出条带；叠一层静态噪声
    // 把量化误差打散。它不改变平均色，只是抖一下，所以要压得很低。
    readonly property real noiseOpacity: 1.0

    // 按面积选档：小窗原分辨率，大窗半分辨率。
    function blurTierFor(width, height) {
        return width * height > blurDownsampleArea ? blurTiers[1] : blurTiers[0]
    }
}
