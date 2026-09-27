/*
 *
 *      Backdrop.qml
 *      Desktop scenery shared by the visible scene and live backdrop sources.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

import QtQuick

Rectangle {
    gradient: Gradient {
        GradientStop { position: 0; color: "#263d59" }
        GradientStop { position: 1; color: "#0d1929" }
    }
}
