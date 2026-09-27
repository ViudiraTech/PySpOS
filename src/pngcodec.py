'''
 *
 *      pngcodec.py
 *      Minimal PNG reader and writer for 8-bit images, RGBA in and out.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# PNG colour types this codec understands, mapped to their channel counts.
# Grey, palette, RGB, grey+alpha and RGBA all normalise to four channels.
COLOR_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


# One decoded image stored as straight (non-premultiplied) RGBA bytes.
class RgbaImage:
    # Store pixels in row-major order with four channels per pixel.
    def __init__(self, width, height, pixels):
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions must be positive")
        if len(pixels) != width * height * 4:
            raise ValueError("Pixel buffer does not match the image size")
        self.width = width
        self.height = height
        self.pixels = pixels

    # Return the four bytes of one pixel.
    def pixel(self, x, y):
        offset = (y * self.width + x) * 4
        return self.pixels[offset:offset + 4]

    # Return a new image cropped to a rectangle.
    def crop(self, x, y, width, height):
        rows = []
        for row in range(y, y + height):
            start = (row * self.width + x) * 4
            rows.append(self.pixels[start:start + width * 4])
        return RgbaImage(width, height, b"".join(rows))

    # Return a new image resized with nearest-neighbour sampling.
    def resize(self, width, height):
        out = bytearray(width * height * 4)
        for row in range(height):
            source_y = min(self.height - 1, row * self.height // height)
            for col in range(width):
                source_x = min(self.width - 1, col * self.width // width)
                source = (source_y * self.width + source_x) * 4
                target = (row * width + col) * 4
                out[target:target + 4] = self.pixels[source:source + 4]
        return RgbaImage(width, height, bytes(out))

    # Return a new image blended over one opaque background colour.
    def over_background(self, background):
        red, green, blue = background
        out = bytearray(self.pixels)
        for offset in range(0, len(out), 4):
            alpha = out[offset + 3]
            if alpha == 255:
                continue
            inverse = 255 - alpha
            out[offset] = (out[offset] * alpha + red * inverse) // 255
            out[offset + 1] = (out[offset + 1] * alpha + green * inverse) // 255
            out[offset + 2] = (out[offset + 2] * alpha + blue * inverse) // 255
            out[offset + 3] = 255
        return RgbaImage(self.width, self.height, bytes(out))


# Read the IHDR fields of a PNG file.
def read_header(data):
    if len(data) < 33 or data[:8] != PNG_SIGNATURE:
        raise ValueError("Not a PNG file")
    length, kind = struct.unpack(">I4s", data[8:16])
    if kind != b"IHDR" or length != 13:
        raise ValueError("PNG has no valid IHDR chunk")
    width, height, depth, color, _comp, _filt, interlace = struct.unpack(
        ">IIBBBBB", data[16:29])
    if depth not in (8, 16):
        raise ValueError(f"Unsupported PNG bit depth {depth}, expected 8 or 16")
    if color not in COLOR_CHANNELS:
        raise ValueError(f"Unsupported PNG colour type {color}")
    if interlace != 0:
        raise ValueError("Interlaced PNG images are not supported")
    return {"width": width, "height": height, "depth": depth, "color": color}


# Reverse the per-scanline PNG filters and return the raw bytes.
def _unfilter(raw, width, height, bpp):
    stride = width * bpp
    out = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        position += stride
        if filter_type == 0:
            pass
        elif filter_type == 1:
            for index in range(bpp, stride):
                line[index] = (line[index] + line[index - bpp]) & 0xFF
        elif filter_type == 2:
            for index in range(stride):
                line[index] = (line[index] + previous[index]) & 0xFF
        elif filter_type == 3:
            for index in range(stride):
                left = line[index - bpp] if index >= bpp else 0
                line[index] = (line[index] + ((left + previous[index]) >> 1)) & 0xFF
        elif filter_type == 4:
            for index in range(stride):
                left = line[index - bpp] if index >= bpp else 0
                up = previous[index]
                up_left = previous[index - bpp] if index >= bpp else 0
                estimate = left + up - up_left
                distance_left = abs(estimate - left)
                distance_up = abs(estimate - up)
                distance_corner = abs(estimate - up_left)
                if distance_left <= distance_up and distance_left <= distance_corner:
                    predictor = left
                elif distance_up <= distance_corner:
                    predictor = up
                else:
                    predictor = up_left
                line[index] = (line[index] + predictor) & 0xFF
        else:
            raise ValueError(f"Unknown PNG filter type {filter_type}")
        out[row * stride:(row + 1) * stride] = line
        previous = line
    return out


# Expand one unfiltered sample buffer into straight RGBA bytes.
# 16-bit samples are reduced to their high byte, which is what Tk needs anyway.
def _to_rgba(samples, width, height, color, depth, palette, transparency):
    channels = COLOR_CHANNELS[color]
    step = channels * (depth // 8)
    out = bytearray(width * height * 4)
    for index in range(width * height):
        source = index * step
        target = index * 4
        if color == 6:
            for channel in range(4):
                out[target + channel] = samples[source + channel * (step // 4)]
        elif color == 2:
            for channel in range(3):
                out[target + channel] = samples[source + channel * (step // 3)]
            out[target + 3] = 255
        elif color == 0:
            grey = samples[source]
            out[target] = grey
            out[target + 1] = grey
            out[target + 2] = grey
            out[target + 3] = 255
        elif color == 4:
            grey = samples[source]
            out[target] = grey
            out[target + 1] = grey
            out[target + 2] = grey
            out[target + 3] = samples[source + (step // 2)]
        else:
            entry = samples[source]
            base = entry * 3
            out[target] = palette[base]
            out[target + 1] = palette[base + 1]
            out[target + 2] = palette[base + 2]
            out[target + 3] = (transparency[entry]
                                if entry < len(transparency) else 255)
    return out


# Decode a PNG file into an RgbaImage.
def read_png(path):
    with open(path, "rb") as stream:
        data = stream.read()
    header = read_header(data)
    width = header["width"]
    height = header["height"]
    color = header["color"]
    compressed = bytearray()
    palette = b""
    transparency = b""
    position = 8
    while position + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if kind == b"IDAT":
            compressed += body
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IEND":
            break
    if color == 3 and not palette:
        raise ValueError("Palette PNG has no PLTE chunk")
    raw = zlib.decompress(bytes(compressed))
    # The filter unit is one complete pixel in bytes, not one sample.
    bpp = COLOR_CHANNELS[color] * (header["depth"] // 8)
    samples = _unfilter(raw, width, height, bpp)
    return RgbaImage(width, height, _to_rgba(samples, width, height, color,
                                            header["depth"], palette,
                                            transparency))


# Wrap one payload in a PNG chunk with its CRC.
def _chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


# Encode an RgbaImage as an 8-bit RGBA PNG.
def write_png(image, path=None):
    height = image.height
    raw = bytearray()
    stride = image.width * 4
    for row in range(height):
        raw.append(0)
        raw += image.pixels[row * stride:(row + 1) * stride]
    header = struct.pack(">IIBBBBB", image.width, height, 8, 6, 0, 0, 0)
    data = (PNG_SIGNATURE + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))
    if path is not None:
        with open(path, "wb") as stream:
            stream.write(data)
    return data
