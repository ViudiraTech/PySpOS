/*
 *
 *      GlassBand.qml
 *      Narrow live source, Qt GPU blur, portable refraction shader and dither.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

import QtQuick
import QtQuick.Effects

Item {
    id: glass
    objectName: "glass-band"
    required property Item scene
    required property real sceneX
    required property real sceneY
    // 档位由调用方选（Theme.blurTierFor 按面积，任务栏和菜单固定用半分辨率档）。
    property var tier: Theme.blurTiers[0]
    // 纹理半径 = 屏幕半径 × 比例：降采样省了像素，半径按比例补回来，观感不变。
    readonly property real textureRadius: tier.screenRadius * tier.scale

    ShaderEffect {
        id: refraction
        objectName: "glass-refraction"
        anchors.fill: parent
        property var source: blurTexture
        property vector2d sourceSize: Qt.vector2d(width + tier.expand * 2,
                                                  height + tier.expand * 2)
        property vector2d stripSize: Qt.vector2d(width, height)
        property real padding: tier.expand
        property real strength: 3
        fragmentShader: "../shaders/refraction.frag.qsb"
    }

    // 噪声压在折射之上：它是显示空间的抖动，不该被边缘折射带着一起弯。
    // 幅度靠图片自己的低 alpha 控制，这里只留一个总开关。
    Image {
        objectName: "glass-noise"
        anchors.fill: parent
        source: "../assets/noise.png"
        fillMode: Image.Tile
        opacity: Theme.noiseOpacity
    }

    // The source tree contains only sharp layers below this window, so it cannot recurse.
    ShaderEffectSource {
        id: sharp
        visible: false
        sourceItem: glass.scene
        sourceRect: Qt.rect(glass.sceneX - glass.tier.expand,
                            glass.sceneY - glass.tier.expand,
                            glass.width + glass.tier.expand * 2,
                            glass.height + glass.tier.expand * 2)
        width: sourceRect.width
        height: sourceRect.height
        textureSize: Qt.size(Math.ceil(sourceRect.width * glass.tier.scale),
                             Math.ceil(sourceRect.height * glass.tier.scale))
        live: true
    }
    MultiEffect {
        id: blurred
        visible: false
        width: sharp.textureSize.width
        height: sharp.textureSize.height
        source: sharp
        blurEnabled: true
        // blur 固定 1.0，强度全部由档位给的 blurMax 决定，免得多一处可调的半径。
        blurMax: Math.max(1, Math.ceil(glass.textureRadius))
        blur: 1.0
        autoPaddingEnabled: false
    }
    ShaderEffectSource {
        id: blurTexture
        visible: false
        sourceItem: blurred
        width: blurred.width
        height: blurred.height
        live: true
    }
}
