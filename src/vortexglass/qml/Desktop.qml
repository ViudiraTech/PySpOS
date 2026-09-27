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
    focus: true
    clip: true
    onWidthChanged: controller.setDesktopSize(width, height)
    onHeightChanged: controller.setDesktopSize(width, height)
    Backdrop { anchors.fill: parent }
    Text { x: 28; y: 24; text: "PySpOS"; color: "#8faecf"; font.pixelSize: 26 }

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
                acceptedButtons: Qt.LeftButton
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
                }
                onPositionChanged: mouse => {
                    controller.hover(frame.wid, mouse.x, mouse.y)
                    if (!pressed) return
                    let dx = mouse.x + frame.x - startX
                    let dy = mouse.y + frame.y - startY
                    if (mode === "move") controller.moveWindow(frame.wid, windowX + dx, windowY + dy)
                    if (mode === "resize") controller.resizeWindow(frame.wid, windowW + dx, windowH + dy)
                }
                onReleased: mouse => controller.release(frame.wid, mouse.x, mouse.y, mode)
                onExited: controller.hover(frame.wid, -1, -1)
                onDoubleClicked: mouse => {
                    if (mouse.y < 28 && controller.press(frame.wid, mouse.x, mouse.y) === "move")
                        controller.release(frame.wid, mouse.x, mouse.y, "max")
                }
                onWheel: wheel => controller.scroll(frame.wid, wheel.angleDelta.y)
            }
            Keys.onPressed: event => {
                controller.key(frame.wid, event.key, event.text, event.modifiers)
                event.accepted = true
            }
        }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 42; color: "#101e30ed"; z: 1000
        Row {
            x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 6
            Rectangle {
                width: 98; height: 30; radius: 4; color: "#294765"
                Text { anchors.centerIn: parent; text: "PTY Shell"; color: "#edf4fc" }
                MouseArea { anchors.fill: parent; onClicked: controller.openTerminal() }
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
}
