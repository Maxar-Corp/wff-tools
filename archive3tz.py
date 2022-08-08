#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com

import os
import struct
import hashlib
import math
import zlib
import logging

logger = logging.getLogger(__name__)

try:
    import zstandard
    zstd = zstandard.ZstdDecompressor()
except ImportError as e:
    zstd = None
    logger.warning('Module \'zstandard\' not found, disabling zstd support.')
    logger.warning('To install: python3 -m pip install zstandard --user')
    logger.error(e)

ENDOFCENTRALDIRECTORY = 0x06054b50.to_bytes(4, byteorder='little')
STARTOFCENTRALDIRECTORY = 0x02014b50.to_bytes(4, byteorder='little')
LOCALFILEHEADERSIGNATURE = 0x04034b50.to_bytes(4, byteorder='little')
LOCALFILEHEADERSIZE = 30
ZIP64_EXTENDED_INFORMATION_EXTRA_SIGNATURE = 0x0001
ZIP_COMPRESSION_METHOD_DEFLATE = 0x08.to_bytes(2, byteorder='little')
ZIP_COMPRESSION_METHOD_STORE = 0x00.to_bytes(2, byteorder='little')
ZIP_COMPRESSION_METHOD_ZSTD = 0x5d.to_bytes(2, byteorder='little')
ZIP_COMPRESSION_METHOD_ZSTD_OLD = 0x17.to_bytes(2, byteorder='little')


def parseCentralDirectoryEntry(bytes):
    filenameLength = int.from_bytes(bytes[28:30], byteorder='little')
    extraFieldLength = int.from_bytes(bytes[30:32], byteorder='little')
    fileCommentLength = int.from_bytes(bytes[32:34], byteorder='little')
    return {
        "signature": bytes[0:4],
        "version": bytes[4:6],
        "versionNeeded": bytes[6:8],
        "generalBits": bytes[8:10],
        "compressionMethod": bytes[10:12],
        "lastModTime": bytes[12:14],
        "lastModDate": bytes[14:16],
        "crc32": bytes[16:20],
        "compressedSize": int.from_bytes(bytes[20:24], byteorder='little'),
        "uncompressedSize": int.from_bytes(bytes[24:28], byteorder='little'),
        "filenameLength": filenameLength,
        "extraFieldLength": extraFieldLength,
        "fileCommentLength": fileCommentLength,
        "distNumber": int.from_bytes(bytes[34:36], byteorder='little'),
        "internalFileAttributes": bytes[36:38],
        "externalFileAttributes": bytes[38:42],
        "relativeOffsetOfLocalHeader": int.from_bytes(bytes[42:46], byteorder='little'),
        "filename": bytes[46:46+filenameLength].decode('utf-8'),
        "extraField": bytes[46+filenameLength:46+filenameLength+extraFieldLength],
        "fileComment": bytes[46+filenameLength+extraFieldLength:46+filenameLength+extraFieldLength+fileCommentLength]
    }


def seekToFileContentsStartFromLocalFileHeader(file, lfh):
    current = file.tell()
    file.seek(current + lfh.get('filenameLength') +
              lfh.get('extraFieldLength') - 100)


def getRawFileContentsFromLocalFileHeader(file, lfh):
    """Returns the raw (possibly compressed) file contents for the given zip LocalFileHeader """
    seekToFileContentsStartFromLocalFileHeader(file, lfh)
    filesize = lfh.get('compressedSize')
    rawContents = file.read(filesize)
    if len(rawContents) != filesize:
        raise Exception(
            f'Read {len(rawContents)} bytes, expected {filesize} bytes')
    compmethod = lfh.get('compressionMethod')
    uncompressedFilesize = lfh.get('uncompressedSize')
    return [compmethod, uncompressedFilesize, rawContents]


def decompressFileContents(compMethod, uncompressedFilesize, bytes):
    """Returns decompressed file data"""
    if compMethod == ZIP_COMPRESSION_METHOD_DEFLATE:
        uncompressedBytes = zlib.decompress(bytes, -zlib.MAX_WBITS)
        if len(uncompressedBytes) != uncompressedFilesize:
            raise Exception(
                f'Decompression failed, got {len(uncompressedBytes)} bytes, expected {uncompressedFilesize} bytes')
        return uncompressedBytes
    elif compMethod == ZIP_COMPRESSION_METHOD_ZSTD or compMethod == ZIP_COMPRESSION_METHOD_ZSTD_OLD:
        if zstd is None:
            raise NotImplementedError(
                f'Unsupported compression method {int.from_bytes(compMethod, byteorder="little")} (requires zstandard module installed).')
        uncompressedBytes = zstd.decompress(
            bytes, max_output_size=uncompressedFilesize)
        if len(uncompressedBytes) != uncompressedFilesize:
            raise Exception(
                f'Decompression failed, got {len(uncompressedBytes)} bytes, expected {uncompressedFilesize} bytes')
        return uncompressedBytes
    elif compMethod != ZIP_COMPRESSION_METHOD_STORE:
        raise Exception(
            f'Unsupported compression method {int.from_bytes(compMethod, byteorder="little")}')
    # if uncompressed, return the in data
    return bytes


def getFileContentsFromLocalFileHeader(file, lfh):
    """Returns the file contents for the given zip LocalFileHeader"""
    seekToFileContentsStartFromLocalFileHeader(file, lfh)
    filesize = lfh.get('compressedSize')
    bytes = file.read(filesize)
    if len(bytes) != filesize:
        raise Exception(f'Read {len(bytes)} bytes, expected {filesize} bytes')
    compmethod = lfh.get('compressionMethod')

    if compmethod == ZIP_COMPRESSION_METHOD_STORE:
        return bytes

    uncompressedFilesize = lfh.get('uncompressedSize')
    try:
        return decompressFileContents(compmethod, uncompressedFilesize, bytes)
    except NotImplementedError as e:
        raise NotImplementedError(
            f'Failed to decompress \'{lfh.get("filename")}\': {e}')
    except Exception as e:
        raise Exception(f'Failed to decompress \'{lfh.get("filename")}\': {e}')


def getLocalFileHeaderAtOffset(file, offset):
    """Returns the zip LocalFileHeader at the given offset."""
    file.seek(offset)
    bytes = file.read(LOCALFILEHEADERSIZE + 100)
    filenameLength = int.from_bytes(bytes[26:28], byteorder='little')
    extraFieldLength = int.from_bytes(bytes[28:30], byteorder='little')
    return {
        "signature": bytes[0:4],
        "versionNeeded": bytes[4:6],
        "generalBits": bytes[6:8],
        "compressionMethod": bytes[8:10],
        "lastModTime": bytes[10:12],
        "lastModDate": bytes[12:14],
        "crc32": bytes[14:18],
        "compressedSize": int.from_bytes(bytes[18:22], byteorder='little'),
        "uncompressedSize": int.from_bytes(bytes[22:26], byteorder='little'),
        "filenameLength": filenameLength,
        "extraFieldLength": extraFieldLength,
        "filename": bytes[LOCALFILEHEADERSIZE:LOCALFILEHEADERSIZE+filenameLength].decode('utf-8'),
        "extraField": bytes[LOCALFILEHEADERSIZE+filenameLength:LOCALFILEHEADERSIZE+filenameLength+extraFieldLength]
    }


def getLocalFileHeaderFromCentralDirectoryEntry(file, cde):
    """Returns the zip LocalFileHeader from a given zip CentralDirectory entry."""
    if cde.get('relativeOffsetOfLocalHeader') == 0xFFFFFFFF:
        bytes = cde.get('extraField')
        currentPos = 0
        while currentPos < cde.get('extraFieldLength'):
            extra_tag, extra_size = struct.unpack(
                "<HH", bytes[currentPos:currentPos+4])
            if extra_tag == ZIP64_EXTENDED_INFORMATION_EXTRA_SIGNATURE and extra_size == 8:
                offset = struct.unpack(
                    "<Q", bytes[currentPos+4:currentPos+12])[0]
                return getLocalFileHeaderAtOffset(file, offset)
            else:
                currentPos = currentPos + 4 + extra_size
        return None
    else:
        return getLocalFileHeaderAtOffset(file, cde.get('relativeOffsetOfLocalHeader'))


def getLastEntryInCentralDirectory(file, containerpath):
    """Returns the last zip central directory entry."""
    try:
        filesize = os.path.getsize(containerpath)
        file.seek(filesize - 320)
        buffer = file.read()
        start = buffer.rfind(STARTOFCENTRALDIRECTORY)
        end = buffer.rfind(ENDOFCENTRALDIRECTORY)
        if start < end and start != end:
            return parseCentralDirectoryEntry(buffer[start:end])
        else:
            logger.error(
                f'start: {start} end: {end} (startMarker: {STARTOFCENTRALDIRECTORY} endMarker: {ENDOFCENTRALDIRECTORY})')
    except FileNotFoundError:
        logger.error('File not found')
    return None


class Index:
    """Implementation of the 3tz index file"""

    def __init__(self, indexBytes):
        self.view = memoryview(indexBytes)
        self.index = self.view.cast("Q")

    def __getitem__(self, i):
        return [self.index[3*i], self.index[3*i + 1], self.index[3*i + 2]]

    def __len__(self):
        return int(len(self.index)/3)


def readIndex(indexBytes):
    index = Index(indexBytes)
    logger.debug(f'Search index contains {len(index)} entries.')
    return index


def md5LessThan(aLo, aHi, bLo, bHi):
    if aLo == bLo:
        return aHi < bHi
    return aLo < bLo


def findLocalFileHeaderOffsetInIndex(index, filepath):
    """Finds the zip LocalFileHeader offset from a given filepath in the zip using the index."""
    md5hash = hashlib.md5(filepath.encode('utf-8'))
    #logger.debug(f'{filepath} -> {md5hash.hexdigest()}')
    digest = md5hash.digest()
    [a, b] = struct.unpack("QQ", digest)
    #logger.debug(f'digest: {digest} a: {a} b: {b}')

    # binary search
    low = 0
    high = len(index)
    while low <= high:
        mid = math.floor(low + (high - low) / 2)
        entry = index[mid]
        #logger.debug(f'mid: {mid} entry: {entry}')
        if entry[0] == a and entry[1] == b:
            return entry[2]
        elif md5LessThan(entry[0], entry[1], a, b):
            low = mid + 1
        else:
            high = mid - 1
    return None


"""Note: this is inefficient, if reading multiple files, save and use the index"""


def getSingleFile(containerpath, filepath):
    with open(containerpath, mode='rb') as file:
        cde = getLastEntryInCentralDirectory(file, containerpath)
        # print(cde)
        lfh = getLocalFileHeaderFromCentralDirectoryEntry(file, cde)
        if lfh.get('filename') == '@3dtilesIndex1@':
            logging.debug('Reading index content')
            indexContent = getFileContentsFromLocalFileHeader(file, lfh)
            index = readIndex(indexContent)
            offset = findLocalFileHeaderOffsetInIndex(index, filepath)
            if offset is None:
                logging.error(f'File not found: {filepath}')
                return None
            lfh2 = getLocalFileHeaderAtOffset(file, offset)
            # print(lfh2)
            if lfh2.get('filename') != filepath:
                logging.error(
                    f"Expected {filepath} but got {lfh2.get('filename')}")
                return None
            return getFileContentsFromLocalFileHeader(file, lfh2)
    logging.error(f'Failed to find {filepath}')
    return None
