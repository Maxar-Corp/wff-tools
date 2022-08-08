#!/usr/bin/env python3

# Copyright 2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import struct
import logging

logger = logging.getLogger(__name__)


def contentTypeFromFileExtension(fileExtension):
    contentTypes = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.ktx2': 'image/ktx2'
    }
    return contentTypes.get(fileExtension, None)


def sniffImageMimeType(buffer):
    if len(buffer) < 8:
        return None
    magic = struct.unpack("<II", buffer[0:8])
    if magic[0] == 0x474e5089 and magic[1] == 0xa1a0a0d:
        #logger.info("Was png")
        return "image/png"
    elif magic[0] == 0xe0ffd8ff:
        #logger.info("Was jpg")
        return "image/jpeg"
    else:
        logger.error(
            f'Unrecognized magic header: {hex(magic[0])} {hex(magic[1])}')
    return None


def getImageStats(buffer, mimetype):
    #logger.error(f'mimetype: {mimetype}')
    w = 0
    h = 0
    channels = 0
    bpc = 0
    if mimetype == "image/png":
        if len(buffer) < 33:
            raise ValueError('Image buffer too short to be valid PNG')
        ihdr = struct.unpack(">II", buffer[8:16])
        if ihdr[0] != 13:
            raise Exception(f'Bad IHDR chunk length: {ihdr[0]}')
        if ihdr[1] != 0x49484452:
            raise Exception(f'Invalid IHDR chunk: {hex(ihdr[1])}')
        w, h = struct.unpack(">II", buffer[16:24])
        bpc = buffer[24] # bit depth
        colortype = buffer[25]
        if colortype == 0: # grayscale
            channels = 1
            bpp = bpc
        elif colortype == 2: # rgb
            channels = 3
            bpp = channels * bpc
        elif colortype == 3: # indexed
            channels = 3
            bpp = channels * 8 # the bpc doesn't affect the bits-per-pixel
        elif colortype == 4: # grayscale + alpha
            channels = 2
            bpp = channels * bpc
        elif colortype == 6: # rgba
            channels = 4
            bpp = channels * bpc
    elif mimetype == "image/jpeg":
        i = 0
        while i < len(buffer):
            while buffer[i] == 0xff:
                i += 1
            curByte = buffer[i]
            i += 1
            #logger.debug(f'[{i}]: {hex(curByte)}')
            if curByte == 0xd8:  # SOI
                continue
            if curByte == 0xd9:  # EOI
                break
            if curByte > 0xd0 and curByte <= 0xd7:
                continue
            if curByte == 0x01:  # TEM
                continue
            if i + 2 < len(buffer):
                length = struct.unpack(">H", buffer[i:i+2])[0]
                i += 2
                if curByte == 0xc0:
                    if i + 6 < len(buffer):
                        bpc = buffer[i]
                        i += 1
                        w, h = struct.unpack(">HH", buffer[i:i+4])
                        i += 4
                        channels = buffer[i]
                        bpp = channels * bpc
                    else:
                        raise ValueError('Buffer too short to determine JPEG size')                        
                    break
                i += length - 2
            else:
                logging.debug(
                    f'i: {i} buffer[i]: {buffer[i:]} bufferLen: {len(buffer)}')
                raise ValueError('Buffer too short to determine JPEG size')
    else:
        logger.error(f'Unhandled mimetype: {mimetype}')
    #logger.error(f'WxH: {w}x{h}')
    return {
        "width": w,
        "height": h,
        "bpc": bpc,
        "channels": channels,
        "bpp": bpp
    }


def getImageDims(buffer, mimetype):
    #logger.error(f'mimetype: {mimetype}')
    w = 0
    h = 0
    if mimetype == "image/png":
        if len(buffer) < 33:
            raise ValueError('Image buffer too short to be valid PNG')
        ihdr = struct.unpack(">II", buffer[8:16])
        if ihdr[0] != 13:
            raise Exception(f'Bad IHDR chunk length: {ihdr[0]}')
        if ihdr[1] != 0x49484452:
            raise Exception(f'Invalid IHDR chunk: {hex(ihdr[1])}')
        w, h = struct.unpack(">II", buffer[16:24])
    elif mimetype == "image/jpeg":
        i = 0
        while i < len(buffer):
            while buffer[i] == 0xff:
                i += 1
            curByte = buffer[i]
            i += 1
            #logger.debug(f'[{i}]: {hex(curByte)}')
            if curByte == 0xd8:  # SOI
                continue
            if curByte == 0xd9:  # EOI
                break
            if curByte > 0xd0 and curByte <= 0xd7:
                continue
            if curByte == 0x01:  # TEM
                continue
            if i + 2 < len(buffer):
                length = struct.unpack(">H", buffer[i:i+2])[0]
                i += 2
                if curByte == 0xc0:
                    i += 1  # skip bits-per-channel
                    if i + 4 < len(buffer):
                        w, h = struct.unpack(">HH", buffer[i:i+4])
                    else:
                        raise ValueError('Buffer too short to determine JPEG size')                        
                    break
                i += length - 2
            else:
                logging.debug(
                    f'i: {i} buffer[i]: {buffer[i:]} bufferLen: {len(buffer)}')
                raise ValueError('Buffer too short to determine JPEG size')
    else:
        logger.error(f'Unhandled mimetype: {mimetype}')
    #logger.error(f'WxH: {w}x{h}')
    return [w, h]


if __name__ == '__main__':
    import argparse
    import pathlib
    parser = argparse.ArgumentParser()
    parser.add_argument('filepath', help='Path to image file')
    args = parser.parse_args()

    filepathsuffix = pathlib.PurePath(args.filepath).suffix
    contenttype = contentTypeFromFileExtension(filepathsuffix)
    with open(args.filepath, "rb") as file:
        print(f'Reading {args.filepath} as \'{contenttype}\'')
        print(getImageStats(file.read(), contenttype))
