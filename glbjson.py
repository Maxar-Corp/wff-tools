#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import struct
import json
import argparse
import logging

logger = logging.getLogger(__name__)


def printJson(jsondata, pretty=False):
    """Prints the json data string to stdout, optionally prettified."""
    if pretty:
        parsed = json.loads(jsondata)
        print(json.dumps(parsed, indent=2, sort_keys=False))
    else:
        print(jsondata)


def getJsonFromFile(file):
    """Returns the json part of the given GLB file, as a string."""
    readbytes = 65535
    buffer = file.read(readbytes)
    header = struct.unpack('<iiiii', buffer[:20])
    if (header[0] != 0x46546C67):
        raise Exception('Not a glb file')
    if (header[1] != 2):
        raise Exception('Unknown glb container version')
    if (header[4] != 0x4E4F534A):
        raise Exception('First glb chunk not json, glb is invalid')
    if (header[3] == 0):
        raise Exception('Empty json chunk')
    if (header[3] >= readbytes - 20):
        # Need to read more data, due to long json chunk
        buffer += file.read(header[3] + 20 - readbytes)
        readbytes = len(buffer)
    jsondata = buffer[20:20 + header[3]].decode('utf-8')
    return jsondata


def getJsonFromBuffer(buffer):
    """Returns the json part of the given GLB file contents, as a string."""
    header = struct.unpack('<iiiii', buffer[:20])
    if (header[0] != 0x46546C67):
        raise Exception('Not a glb file')
    if (header[1] != 2):
        raise Exception('Unknown glb container version')
    if (header[4] != 0x4E4F534A):
        raise Exception('First glb chunk not json, glb is invalid')
    if (header[3] == 0):
        raise Exception('Empty json chunk')
    jsondata = buffer[20:20 + header[3]].decode('utf-8')
    return jsondata


def getChunksFromBuffer(buffer):
    """Returns the json part and the glb binary part."""
    header = struct.unpack('<iiiii', buffer[:20])
    if (header[0] != 0x46546C67):
        raise Exception('Not a glb file')
    if (header[1] != 2):
        raise Exception('Unknown glb container version')
    if (header[4] != 0x4E4F534A):
        raise Exception('First glb chunk not json, glb is invalid')
    if (header[3] == 0):
        raise Exception('Empty json chunk')
    jsondata = buffer[20:20 + header[3]].decode('utf-8')
    data = buffer[20 + header[3]:]
    bindata = None
    if len(data) > 8:
        chunkheader = struct.unpack('<ii', data[:8])
        if chunkheader[1] != 0x004E4942:
            raise Exception('Glb binary chunk header error')
        bindata = data[8:8 + chunkheader[0]]
    return [jsondata, bindata]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pretty', dest='prettyPrint',
                        action='store_true', help='Prett-print the JSON output')
    parser.add_argument('--no-pretty', dest='prettyPrint',
                        action='store_false', help='Don\'t pretty-print the JSON output')
    parser.set_defaults(prettyPrint=True)
    parser.add_argument('filepath', help='Path to glb file')
    args = parser.parse_args()
    try:
        with open(args.filepath, mode='rb') as file:
            printJson(getJsonFromFile(file), args.prettyPrint)
    except FileNotFoundError:
        logger.error(f'File not found {args.filepath}')
        exit(-1)
