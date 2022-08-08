#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com

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


def getJsonFromBuffer(buffer):
    """Returns the json part of the given subtree file contents, as a string."""
    header = struct.unpack('<iiQQ', buffer[:24])
    if (header[0] != 0x74627573):
        raise ValueError(
            f'Not a subtree file, has bad header signature: {header[0]}')
    if (header[1] != 1):
        raise ValueError(f'Unknown subtree version: {header[1]}')
    if (header[2] == 0):
        logger.info('Subtree is empty (no json content)')
        return None
    jsondata = buffer[24:24+header[2]].decode('utf-8')
    return jsondata


def getChunksFromBuffer(buffer):
    """Returns the json part and the binary part."""
    header = struct.unpack('<iiQQ', buffer[:24])
    if (header[0] != 0x74627573):
        raise ValueError(
            f'Not a subtree file, has bad header signature: {header[0]}')
    if (header[1] != 1):
        raise ValueError(f'Unknown subtree version: {header[1]}')
    if (header[2] == 0):
        logger.info('Subtree is empty (no json content)')
        return [None, None]
    jsondata = buffer[24:24+header[2]].decode('utf-8')
    bindata = None
    if header[3] > 0:
        if header[3] != len(buffer)-24-header[2]:
            raise ValueError(
                f'Invalid binary length in subtree header, expected {len(buffer)-24-header[2]} but got {header[3]}')
        bindata = buffer[24+header[2]:]
    return [jsondata, bindata]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pretty', dest='prettyPrint', action='store_true')
    parser.add_argument('--no-pretty', dest='prettyPrint',
                        action='store_false')
    parser.set_defaults(prettyPrint=True)
    parser.add_argument('filepath', help='Path to glb file')
    args = parser.parse_args()
    try:
        with open(args.filepath, mode='rb') as file:
            printJson(getJsonFromBuffer(file.read()), args.prettyPrint)
    except ValueError as e:
        logger.error(f'Error: {e}')
    except FileNotFoundError:
        logger.error(f'File not found {args.filepath}')
        exit(-1)
