/*
 *
 *      refraction.frag
 *      Portable shallow edge lens for live GPU frame textures.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */

#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 sourceSize;
    vec2 stripSize;
    float padding;
    float strength;
};
layout(binding = 1) uniform sampler2D source;

// Bend only near the strip edges; preserve premultiplied alpha and the sharp foreground.
void main() {
    vec2 p = qt_TexCoord0 * stripSize;
    vec2 edge = max(vec2(1.0), min(vec2(12.0), stripSize * 0.5));
    vec2 nearEdge = max(vec2(0.0), vec2(1.0) - p / edge);
    vec2 farEdge = max(vec2(0.0), vec2(1.0) - (stripSize - p) / edge);
    vec2 bend = strength * (nearEdge * nearEdge - farEdge * farEdge);
    vec2 uv = clamp((vec2(padding) + p + bend) / sourceSize,
                    vec2(0.5) / sourceSize, vec2(1.0) - vec2(0.5) / sourceSize);
    fragColor = texture(source, uv) * qt_Opacity;
}
