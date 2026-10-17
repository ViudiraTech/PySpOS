/*
 *
 *      Desktop.qml
 *      Portable desktop with internal windows, live glass and a terminal taskbar.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

import QtQuick

Item {
    id: desktop
    objectName: "desktop"
    property bool menuOpen: false
    focus: true
    clip: true
    onWidthChanged: controller.setDesktopSize(width, height)
    onHeightChanged: controller.setDesktopSize(width, height)
    Backdrop { anchors.fill: parent }
    Text {
        x: Theme.watermarkX; y: Theme.watermarkY
        text: "PySpOS"; color: Theme.wallpaperTitle; font.pixelSize: Theme.fontTitle
    }
    // 素材归属：常驻桌面右下角，压在任务栏上方。底衬是必需的——壁纸可能是亮
    // 色（本机这张就有一片亮云），只靠文字颜色在亮背景上读不出来。
    Rectangle {
        objectName: "theme-credit"
        anchors.right: parent.right; anchors.bottom: taskbar.top
        anchors.rightMargin: Theme.space4; anchors.bottomMargin: Theme.space2
        width: creditText.width + Theme.space2 * 2
        height: creditText.height + Theme.space1 * 2
        radius: Theme.radiusControl
        color: Theme.taskbarBackground
        Text {
            id: creditText
            anchors.centerIn: parent
            text: Theme.themeCredit
            color: Theme.textOnChrome
            font.pixelSize: Theme.fontCaption
        }
    }

    // Panels sample the wallpaper and all sharp windows, without sampling themselves.
    Item {
        id: panelScene
        visible: false
        width: desktop.width; height: desktop.height
        Backdrop { anchors.fill: parent }
        Repeater {
            model: controller.windowModel
            delegate: Image {
                required property real wx
                required property real wy
                required property int ww
                required property int wh
                required property bool minimized
                required property string foreground
                x: wx; y: wy; width: ww; height: wh
                visible: !minimized
                source: foreground
                cache: false
            }
        }
    }

    Repeater {
        model: controller.windowModel
        delegate: Item {
            id: frame
            required property int wid
            required property string caption
            required property real wx
            required property real wy
            required property int ww
            required property int wh
            required property int rank
            required property bool minimized
            required property bool focused
            required property string foreground
            required property var backdrop
            x: wx; y: wy; width: ww; height: wh; z: rank + 1
            visible: !minimized
            objectName: "window-" + wid
            focus: focused

            // Offscreen copies follow live content revisions without including this glass.
            Item {
                id: sharpScene
                visible: false
                width: desktop.width; height: desktop.height
                Backdrop { anchors.fill: parent }
                Repeater {
                    model: frame.backdrop
                    delegate: Image {
                        required property var modelData
                        x: modelData.wx; y: modelData.wy
                        width: modelData.ww; height: modelData.wh
                        source: modelData.foreground
                        cache: false
                    }
                }
            }
            Repeater {
                model: [[0, 0, frame.width, Theme.titleBarHeight],
                        [Theme.frameBandLeft, Theme.frameBandTop, Theme.frameBandWidth,
                         frame.height - Theme.frameBandBottomInset],
                        [frame.width - Theme.frameBandRightInset, Theme.frameBandTop, Theme.frameBandWidth,
                         frame.height - Theme.frameBandBottomInset],
                        [0, frame.height - Theme.frameFooterTop, frame.width, Theme.frameFooterHeight]]
                delegate: GlassBand {
                    required property var modelData
                    x: modelData[0]; y: modelData[1]
                    width: modelData[2]; height: modelData[3]
                    scene: sharpScene
                    sceneX: frame.x + x; sceneY: frame.y + y
                    tier: Theme.blurTierFor(frame.width, frame.height)
                }
            }
            Image { anchors.fill: parent; source: frame.foreground; cache: false }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                property real startX
                property real startY
                property real windowX
                property real windowY
                property int windowW
                property int windowH
                property string mode: ""
                onPressed: mouse => {
                    controller.activate(frame.wid)
                    frame.forceActiveFocus()
                    startX = mouse.x + frame.x; startY = mouse.y + frame.y
                    windowX = frame.x; windowY = frame.y
                    windowW = frame.width; windowH = frame.height
                    mode = controller.press(frame.wid, mouse.x, mouse.y)
                    if (mouse.button !== Qt.LeftButton && mode !== "client") mode = ""
                    if (mode === "client") controller.pointer(frame.wid, "press", mouse.x, mouse.y,
                                                               mouse.button, mouse.buttons, mouse.modifiers)
                }
                onPositionChanged: mouse => {
                    controller.hover(frame.wid, mouse.x, mouse.y)
                    if (!pressed || mode === "client") controller.pointer(frame.wid, "move", mouse.x, mouse.y,
                                                                          mouse.button, mouse.buttons, mouse.modifiers)
                    if (!pressed) return
                    let dx = mouse.x + frame.x - startX
                    let dy = mouse.y + frame.y - startY
                    if (mode === "move") controller.moveWindow(frame.wid, windowX + dx, windowY + dy)
                    if (mode === "resize") controller.resizeWindow(frame.wid, windowW + dx, windowH + dy)
                }
                onReleased: mouse => {
                    if (mouse.button === Qt.LeftButton) controller.release(frame.wid, mouse.x, mouse.y, mode)
                    if (mode === "client") controller.pointer(frame.wid, "release", mouse.x, mouse.y,
                                                               mouse.button, mouse.buttons, mouse.modifiers)
                }
                onExited: controller.hover(frame.wid, -1, -1)
                onDoubleClicked: mouse => {
                    if (mouse.y < Theme.titleBarHeight && controller.press(frame.wid, mouse.x, mouse.y) === "move")
                        controller.toggleMaximize(frame.wid)
                }
                onWheel: wheel => controller.scroll(frame.wid, wheel.angleDelta.y, wheel.x, wheel.y, wheel.angleDelta.x)
            }
            Keys.onPressed: event => {
                controller.key(frame.wid, event.key, event.text, event.modifiers)
                event.accepted = true
            }
        }
    }
    MouseArea {
        anchors.fill: parent
        visible: desktop.menuOpen
        z: 999
        onClicked: desktop.menuOpen = false
    }
    Item {
        id: taskbar
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: Theme.taskbarHeight; z: 1000
        GlassBand {
            anchors.fill: parent
            scene: panelScene
            sceneX: taskbar.x; sceneY: taskbar.y
            tier: Theme.blurTiers[1]
        }
        Rectangle {
            anchors.fill: parent
            color: Theme.taskbarBackground
            border.color: Theme.taskbarBorder
        }
        Row {
            x: Theme.taskbarPadding
            width: parent.width - Theme.taskbarPadding * 2 - tray.width - Theme.controlSpacing
            clip: true
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.controlSpacing
            Rectangle {
                width: Theme.startButtonWidth; height: Theme.controlHeight
                radius: Theme.radiusControl
                color: desktop.menuOpen ? Theme.controlBackgroundActive : Theme.controlBackground
                Text { anchors.centerIn: parent; text: "◈  开始"; color: Theme.textOnChrome }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        desktop.menuOpen = !desktop.menuOpen
                        if (desktop.menuOpen) menuSearch.forceActiveFocus()
                    }
                }
            }
            Repeater {
                model: controller.windowModel
                delegate: Rectangle {
                    required property int wid
                    required property string caption
                    required property bool minimized
                    required property bool focused
                    width: Theme.windowButtonWidth; height: Theme.controlHeight
                    radius: Theme.radiusControl
                    color: focused ? Theme.windowButtonFocused : Theme.windowButton
                    Text {
                        anchors.fill: parent; anchors.margins: Theme.windowButtonPadding
                        verticalAlignment: Text.AlignVCenter
                        text: parent.caption; elide: Text.ElideRight; color: Theme.textOnChrome
                    }
                    MouseArea { anchors.fill: parent; onClicked: controller.activate(parent.wid) }
                }
            }
        }
        // 托盘：右侧常驻的状态标记和时钟。标记反映的是真实系统状态（启动信任域、
        // ROOT、当前 A/B 槽位），不是装饰图标。
        Row {
            id: tray
            anchors.right: parent.right; anchors.rightMargin: Theme.taskbarPadding
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.controlSpacing
            Repeater {
                model: controller.trayChips
                delegate: Rectangle {
                    required property var modelData
                    width: chipText.width + Theme.trayChipPadding * 2
                    height: Theme.controlHeight
                    radius: Theme.radiusControl
                    color: Theme.trayChipBackground
                    Text {
                        id: chipText
                        anchors.centerIn: parent
                        text: modelData.text
                        color: modelData.tone === "locked" ? Theme.trayLocked
                             : modelData.tone === "root" ? Theme.trayRoot
                             : modelData.tone === "unlocked" ? Theme.trayUnlocked
                             : Theme.traySlot
                        font.pixelSize: Theme.trayChipSize
                    }
                }
            }
            Rectangle {
                objectName: "tray-clock"
                width: Theme.clockWidth
                height: Theme.controlHeight
                radius: Theme.radiusControl
                color: clockMouse.containsMouse ? Theme.trayHover : "transparent"
                Column {
                    anchors.centerIn: parent
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: controller.clockTime
                        color: Theme.textOnChrome
                        font.pixelSize: Theme.clockTimeSize
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: controller.clockDate
                        color: Theme.trayText
                        font.pixelSize: Theme.clockDateSize
                    }
                }
                MouseArea {
                    id: clockMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: controller.openClock()
                }
            }
        }
    }
    Item {
        id: startMenu
        objectName: "start-menu"
        visible: desktop.menuOpen
        z: 1001
        x: Theme.menuMargin; y: desktop.height - height - Theme.menuBottomGap
        width: Math.min(Theme.menuMaxWidth, desktop.width - Theme.menuMargin * 2)
        height: Math.min(Theme.menuMaxHeight, desktop.height - Theme.menuHeightTrim)
        GlassBand {
            anchors.fill: parent
            scene: panelScene
            sceneX: startMenu.x; sceneY: startMenu.y
            tier: Theme.blurTiers[1]
        }
        Rectangle {
            anchors.fill: parent
            radius: Theme.radiusOverlay
            color: Theme.menuBackground
            border.color: Theme.menuBorder
            border.width: 1
        }
        Text {
            x: Theme.menuTitleX; y: Theme.menuTitleY
            text: "PySpOS 应用"
            color: Theme.textPrimary
            font.pixelSize: Theme.fontHeading
            font.bold: true
        }
        Rectangle {
            x: Theme.menuPadding; y: Theme.menuSearchY
            width: parent.width - Theme.menuPadding * 2
            height: Theme.menuSearchHeight
            radius: Theme.radiusControl
            color: Theme.fieldBackground
            TextInput {
                id: menuSearch
                objectName: "app-search"
                anchors.fill: parent; anchors.margins: Theme.fieldPadding
                color: Theme.textPrimary
                font.pixelSize: Theme.fontBody
                verticalAlignment: TextInput.AlignVCenter
                clip: true
                Keys.onEscapePressed: desktop.menuOpen = false
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !menuSearch.text
                    text: "搜索应用"
                    color: Theme.textPlaceholder
                }
            }
        }
        Flickable {
            x: Theme.menuListInset; y: Theme.menuListY
            width: parent.width - Theme.menuListInset * 2
            height: parent.height - Theme.menuListY - Theme.menuFooterHeight
            contentHeight: appList.height
            clip: true
            Column {
                id: appList
                width: parent.width
                spacing: Theme.appRowSpacing
                Repeater {
                    model: controller.appCatalog
                    delegate: Rectangle {
                        required property var modelData
                        property bool matches: menuSearch.text === "" ||
                            modelData.title.toLowerCase().includes(menuSearch.text.toLowerCase()) ||
                            modelData.description.toLowerCase().includes(menuSearch.text.toLowerCase())
                        width: appList.width
                        height: matches ? Theme.appRowHeight : 0
                        visible: matches
                        radius: Theme.radiusControl
                        color: appMouse.containsMouse ? Theme.rowHover : "transparent"
                        Image {
                            x: Theme.appIconX
                            anchors.verticalCenter: parent.verticalCenter
                            width: Theme.appIconSize; height: Theme.appIconSize
                            sourceSize: Qt.size(Theme.appIconSize, Theme.appIconSize)
                            source: "../assets/icons/" + modelData.icon + ".svg"
                            smooth: true
                        }
                        Text {
                            x: Theme.appTextX; y: Theme.appTitleY
                            text: parent.modelData.title
                            color: Theme.textPrimary; font.pixelSize: Theme.fontBody
                        }
                        Text {
                            x: Theme.appTextX; y: Theme.appCaptionY
                            text: parent.modelData.description
                            color: Theme.textSecondary; font.pixelSize: Theme.fontCaption
                        }
                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                controller.launchApp(parent.modelData.id)
                                desktop.menuOpen = false
                            }
                        }
                    }
                }
            }
        }
        // 系统级动作放在这里：窗口管理动作不该和窗口按钮挤在任务栏上。
        Rectangle {
            objectName: "menu-exit"
            anchors.left: parent.left; anchors.right: parent.right
            anchors.bottom: parent.bottom; anchors.margins: Theme.menuListInset
            height: Theme.controlHeight
            radius: Theme.radiusControl
            color: exitMouse.containsMouse ? Theme.dangerBackground : "transparent"
            Text {
                anchors.centerIn: parent
                text: "退出桌面"
                color: Theme.textPrimary
                font.pixelSize: Theme.fontBody
            }
            MouseArea {
                id: exitMouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: controller.exitDesktop()
            }
        }
    }
}
