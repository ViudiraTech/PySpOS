'''
 *
 *      test_pngcodec.py
 *      The PNG reader and writer used to repaint VortexGlass strips.
 *
 *      Tk 8.6 cannot resize a PhotoImage without dropping its alpha channel,
 *      so the window paints its frame in RGBA and hands Tk encoded PNG bytes.
 *      That makes this codec part of the window's correctness: a wrong
 *      unfilter step or a lost alpha byte shows up as a broken glass frame.
 *
 *      2026/9/27 By GoutouStdio
 *      Copyright (C) 2022-2026 GoutouStdio, based on the MIT license.
 *
 */
'''

import struct
import zlib

import pytest

import pngcodec

# Build one PNG from raw samples, used to cover every colour type we accept.
def make_png(width, height, color, depth, samples, palette=None,
             transparency=None, interlace=0):
    channels = pngcodec.COLOR_CHANNELS[color]
    step = channels * (depth // 8)
    raw = bytearray()
    for row in range(height):
        raw.append(0)
        start = row * width * step
        raw += samples[start:start + width * step]
    chunks = [pngcodec.PNG_SIGNATURE]
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0,
                         interlace)
    chunks.append(pngcodec._chunk(b"IHDR", header))
    if palette is not None:
        chunks.append(pngcodec._chunk(b"PLTE", palette))
    if transparency is not None:
        chunks.append(pngcodec._chunk(b"tRNS", transparency))
    chunks.append(pngcodec._chunk(b"IDAT", zlib.compress(bytes(raw))))
    chunks.append(pngcodec._chunk(b"IEND", b""))
    return b"".join(chunks)


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_round_trip_keeps_every_byte(tmp_path):
    pixels = bytearray()
    for index in range(64):
        pixels += bytes((index * 3 % 256, index * 5 % 256, index * 7 % 256,
                         255 - index))
    image = pngcodec.RgbaImage(8, 8, bytes(pixels))
    path = write(tmp_path, "out.png", pngcodec.write_png(image))
    assert pngcodec.read_png(path).pixels == image.pixels


def test_write_png_returns_the_same_bytes_it_wrote(tmp_path):
    image = pngcodec.RgbaImage(2, 2, bytes([1, 2, 3, 4] * 4))
    path = str(tmp_path / "out.png")
    returned = pngcodec.write_png(image, path)
    with open(path, "rb") as stream:
        assert stream.read() == returned


def test_reads_greyscale_rgb_and_rgba(tmp_path):
    grey = make_png(2, 1, 0, 8, bytes([0, 255]))
    assert pngcodec.read_png(write(tmp_path, "g.png", grey)).pixel(0, 0) == bytes([0, 0, 0, 255])
    assert pngcodec.read_png(write(tmp_path, "g.png", grey)).pixel(1, 0) == bytes([255, 255, 255, 255])

    rgb = make_png(1, 1, 2, 8, bytes([10, 20, 30]))
    assert pngcodec.read_png(write(tmp_path, "rgb.png", rgb)).pixel(0, 0) == bytes([10, 20, 30, 255])

    rgba = make_png(1, 1, 6, 8, bytes([10, 20, 30, 40]))
    assert pngcodec.read_png(write(tmp_path, "rgba.png", rgba)).pixel(0, 0) == bytes([10, 20, 30, 40])


def test_reads_grey_alpha_and_palette(tmp_path):
    grey_alpha = make_png(1, 1, 4, 8, bytes([77, 88]))
    assert pngcodec.read_png(write(tmp_path, "ga.png", grey_alpha)).pixel(0, 0) == bytes([77, 77, 77, 88])

    palette = make_png(1, 1, 3, 8, bytes([1]), palette=bytes([1, 2, 3, 4, 5, 6]),
                       transparency=bytes([255, 200]))
    decoded = pngcodec.read_png(write(tmp_path, "pal.png", palette))
    assert decoded.pixel(0, 0) == bytes([4, 5, 6, 200])


def test_sixteen_bit_samples_reduce_to_their_high_byte(tmp_path):
    data = make_png(1, 1, 6, 16, bytes([0x12, 0x34, 0x56, 0x78,
                                        0x9A, 0xBC, 0xDE, 0xF0]))
    assert pngcodec.read_png(write(tmp_path, "p16.png", data)).pixel(0, 0) == bytes([0x12, 0x56, 0x9A, 0xDE])


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_unfilters_every_filter_type(tmp_path, filter_type):
    width, height = 4, 3
    original = bytes((x * 7 + y * 3) % 256 for y in range(height)
                     for x in range(width * 4))
    raw = bytearray()
    for row in range(height):
        line = original[row * width * 4:(row + 1) * width * 4]
        encoded = bytearray(len(line))
        previous = original[(row - 1) * width * 4:row * width * 4] if row else bytes(len(line))
        for index in range(len(line)):
            left = line[index - 4] if index >= 4 else 0
            up = previous[index]
            up_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                encoded[index] = line[index]
            elif filter_type == 1:
                encoded[index] = (line[index] - left) & 0xFF
            elif filter_type == 2:
                encoded[index] = (line[index] - up) & 0xFF
            elif filter_type == 3:
                encoded[index] = (line[index] - ((left + up) >> 1)) & 0xFF
            else:
                estimate = left + up - up_left
                distances = (abs(estimate - left), abs(estimate - up),
                             abs(estimate - up_left))
                predictor = (left, up, up_left)[distances.index(min(distances))]
                encoded[index] = (line[index] - predictor) & 0xFF
        raw.append(filter_type)
        raw += encoded
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = (pngcodec.PNG_SIGNATURE + pngcodec._chunk(b"IHDR", header)
            + pngcodec._chunk(b"IDAT", zlib.compress(bytes(raw)))
            + pngcodec._chunk(b"IEND", b""))
    decoded = pngcodec.read_png(write(tmp_path, "f.png", data))
    assert decoded.pixels == original


def test_rejects_malformed_input(tmp_path):
    with pytest.raises(ValueError):
        pngcodec.read_png(write(tmp_path, "bad.png", b"not a png at all"))
    interlaced = make_png(1, 1, 6, 8, bytes([1, 2, 3, 4]), interlace=1)
    with pytest.raises(ValueError):
        pngcodec.read_png(write(tmp_path, "i.png", interlaced))
    four_bit = make_png(1, 1, 6, 4, bytes([1, 2, 3, 4]))
    with pytest.raises(ValueError):
        pngcodec.read_png(write(tmp_path, "4.png", four_bit))
    with pytest.raises(ValueError):
        pngcodec.read_png(write(tmp_path, "p.png",
                                make_png(1, 1, 3, 8, bytes([0]))))


def test_image_rejects_a_buffer_that_does_not_match():
    with pytest.raises(ValueError):
        pngcodec.RgbaImage(2, 2, bytes(4))
    with pytest.raises(ValueError):
        pngcodec.RgbaImage(0, 1, bytes(4))


def test_crop_and_resize():
    image = pngcodec.RgbaImage(4, 2, bytes(range(32)))
    cropped = image.crop(1, 0, 2, 2)
    assert (cropped.width, cropped.height) == (2, 2)
    assert cropped.pixel(0, 0) == bytes([4, 5, 6, 7])
    scaled = image.resize(2, 1)
    assert (scaled.width, scaled.height) == (2, 1)
    # Nearest neighbour samples the source proportionally: column 1 of 2 comes
    # from source column 1 * 4 // 2, not from the far right edge.
    assert scaled.pixel(0, 0) == image.pixel(0, 0)
    assert scaled.pixel(1, 0) == image.pixel(2, 0)


def test_over_background_flattens_alpha():
    image = pngcodec.RgbaImage(1, 1, bytes([0, 0, 0, 0]))
    assert image.over_background((10, 20, 30)).pixel(0, 0) == bytes([10, 20, 30, 255])
    half = pngcodec.RgbaImage(1, 1, bytes([200, 100, 0, 128]))
    assert half.over_background((0, 0, 0)).pixel(0, 0) == bytes([100, 50, 0, 255])
