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
    Text { x: 28; y: 24; text: "PySpOS"; color: "#8faecf"; font.pixelSize: 26 }

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
                model: [[0, 0, frame.width, 28], [5, 25, 6, frame.height - 39],
                        [frame.width - 11, 25, 6, frame.height - 39],
                        [0, frame.height - 20, frame.width, 8]]
                delegate: GlassBand {
                    required property var modelData
                    x: modelData[0]; y: modelData[1]
                    width: modelData[2]; height: modelData[3]
                    scene: sharpScene
                    sceneX: frame.x + x; sceneY: frame.y + y
                    resolutionScale: frame.width * frame.height > 500000 ? 0.5 : 1
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
                    if (mouse.y < 28 && controller.press(frame.wid, mouse.x, mouse.y) === "move")
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
        height: 42; z: 1000
        GlassBand {
            anchors.fill: parent
            scene: panelScene
            sceneX: taskbar.x; sceneY: taskbar.y
            resolutionScale: 0.5
        }
        Rectangle { anchors.fill: parent; color: "#9a142c43"; border.color: "#61839f" }
        Row {
            x: 10; width: parent.width - 105; clip: true
            anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Rectangle {
                width: 104; height: 30; radius: 4; color: desktop.menuOpen ? "#42678c" : "#294765"
                Text { anchors.centerIn: parent; text: "◈  开始"; color: "#edf4fc" }
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
                    width: 140; height: 30; radius: 4
                    color: focused ? "#365c7c" : "#21364c"
                    Text {
                        anchors.fill: parent; anchors.margins: 8
                        verticalAlignment: Text.AlignVCenter
                        text: parent.caption; elide: Text.ElideRight; color: "#edf4fc"
                    }
                    MouseArea { anchors.fill: parent; onClicked: controller.activate(parent.wid) }
                }
            }
        }
        Rectangle {
            width: 72; height: 30; radius: 4; color: "#503442"
            anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
            Text { anchors.centerIn: parent; text: "退出桌面"; color: "#edf4fc" }
            MouseArea { anchors.fill: parent; onClicked: controller.exitDesktop() }
        }
    }
    Item {
        id: startMenu
        objectName: "start-menu"
        visible: desktop.menuOpen
        z: 1001
        x: 10; y: desktop.height - height - 48
        width: Math.min(380, desktop.width - 20)
        height: Math.min(400, desktop.height - 64)
        GlassBand {
            anchors.fill: parent
            scene: panelScene
            sceneX: startMenu.x; sceneY: startMenu.y
            resolutionScale: 0.5
        }
        Rectangle {
            anchors.fill: parent
            radius: 10
            color: "#a51a3047"
            border.color: "#8eafcd"
            border.width: 1
        }
        Text {
            x: 20; y: 18
            text: "PySpOS 应用"
            color: "#f0f5fb"
            font.pixelSize: 20
            font.bold: true
        }
        Rectangle {
            x: 16; y: 54; width: parent.width - 32; height: 38
            radius: 6; color: "#263d56"
            TextInput {
                id: menuSearch
                objectName: "app-search"
                anchors.fill: parent; anchors.margins: 10
                color: "#f0f5fb"
                font.pixelSize: 15
                verticalAlignment: TextInput.AlignVCenter
                clip: true
                Keys.onEscapePressed: desktop.menuOpen = false
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !menuSearch.text
                    text: "搜索应用"
                    color: "#8ba5bf"
                }
            }
        }
        Flickable {
            x: 12; y: 104; width: parent.width - 24; height: parent.height - 120
            contentHeight: appList.height
            clip: true
            Column {
                id: appList
                width: parent.width
                spacing: 4
                Repeater {
                    model: controller.appCatalog
                    delegate: Rectangle {
                        required property var modelData
                        property bool matches: menuSearch.text === "" ||
                            modelData.title.toLowerCase().includes(menuSearch.text.toLowerCase()) ||
                            modelData.description.toLowerCase().includes(menuSearch.text.toLowerCase())
                        width: appList.width
                        height: matches ? 58 : 0
                        visible: matches
                        radius: 6
                        color: appMouse.containsMouse ? "#42617f" : "transparent"
                        Text {
                            x: 12; anchors.verticalCenter: parent.verticalCenter
                            width: 36; horizontalAlignment: Text.AlignHCenter
                            text: parent.modelData.glyph
                            color: "#b6d8fa"; font.pixelSize: 24
                        }
                        Text {
                            x: 58; y: 9
                            text: parent.modelData.title
                            color: "#f3f7fc"; font.pixelSize: 15
                        }
                        Text {
                            x: 58; y: 31
                            text: parent.modelData.description
                            color: "#a6bed5"; font.pixelSize: 12
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
    }
}
