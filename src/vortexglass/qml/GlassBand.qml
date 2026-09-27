/*
 *
 *      GlassBand.qml
 *      Narrow live source, Qt GPU blur and portable refraction shader.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

import QtQuick
import QtQuick.Effects

ShaderEffect {
    id: glass
    objectName: "glass-band"
    required property Item scene
    required property real sceneX
    required property real sceneY
    property real resolutionScale: 1
    property var source: blurTexture
    property vector2d sourceSize: Qt.vector2d(width + 32, height + 32)
    property vector2d stripSize: Qt.vector2d(width, height)
    property real padding: 16
    property real strength: 3
    fragmentShader: "../shaders/refraction.frag.qsb"

    // The source tree contains only sharp layers below this window, so it cannot recurse.
    ShaderEffectSource {
        id: sharp
        visible: false
        sourceItem: glass.scene
        sourceRect: Qt.rect(glass.sceneX - 16, glass.sceneY - 16,
                            glass.width + 32, glass.height + 32)
        width: sourceRect.width
        height: sourceRect.height
        textureSize: Qt.size(Math.ceil(sourceRect.width * glass.resolutionScale),
                             Math.ceil(sourceRect.height * glass.resolutionScale))
        live: true
    }
    MultiEffect {
        id: blurred
        visible: false
        width: sharp.textureSize.width
        height: sharp.textureSize.height
        source: sharp
        blurEnabled: true
        blurMax: 8
        blur: glass.resolutionScale
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
