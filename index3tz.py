#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com

import os
import struct
import logging
import argparse
import zipfile
import hashlib
import operator
import math


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


def checkIfSupportedZipItem(item):
    # File must not be encrypted
    # Local File Headers must have file sizes set
    # No compressed patched data
    # No encrypted central directory
    disallowedFlagBits = (1 << 0) | (1 << 3) | (1 << 5) | (1 << 13)
    #logging.info(f'Disallowed flag bits: {disallowedFlagBits}')
    if item.compress_type != 8 and item.compress_type != 93 and item.compress_type != 0:
        raise AssertionError(f'Bad compression type: {item.compress_type}')
    if item.flag_bits & disallowedFlagBits != 0:
        #logging.error(f'Disallowed flag bits: {item.flag_bits & disallowedFlagBits} for file {item.filename}')
        if item.flag_bits & disallowedFlagBits == (1 << 0):
            raise AssertionError('File is encrypted')
        if item.flag_bits & disallowedFlagBits == (1 << 3):
            raise AssertionError(
                'Local File Headers don\'t have file size set')
        if item.flag_bits & disallowedFlagBits == (1 << 5):
            raise AssertionError('File has compressed patched data')
        if item.flag_bits & disallowedFlagBits == (1 << 13):
            raise AssertionError('File has encrypted central file directory')
        raise AssertionError(
            f'Disallowed flag bits: {item.flag_bits & disallowedFlagBits}')
    if item.compress_size == 0 and item.file_size != 0:
        raise AssertionError(
            'Local file headers must have compressed sizes set.')


class ZipStatistics:
    def __init__(self, zipfilepath):
        self.maxFileSize = 0
        self.maxCompFileSize = 0
        self.maxHeaderOffset = 0
        self.numFiles = 0
        self.fileSize = 0
        self.gather(zipfilepath)

    def gather(self, zipfilepath):
        logging.debug(
            f'Gathering stats for {os.path.basename(zipfilepath)}...')
        self.fileSize = os.path.getsize(zipfilepath)
        with zipfile.ZipFile(zipfilepath) as zip:
            infolist = zip.infolist()
            for item in infolist:
                if not item.is_dir() and item.filename != "@3dtilesIndex1@":
                    if item.file_size > self.maxFileSize:
                        self.maxFileSize = item.file_size
                    if item.compress_size > self.maxCompFileSize:
                        self.maxCompFileSize = item.compress_size
                    if item.header_offset > self.maxHeaderOffset:
                        self.maxHeaderOffset = item.header_offset
                    self.numFiles += 1

    def summary(self):
        # just a quick summary, looking at if it's possible to pack the offset
        # bits to have room for the file size in the 64 bits (to optimize reads).
        numBitsToRepresentOffset = math.ceil(math.log2(self.maxHeaderOffset))
        remainingBitsToRepresentFileSize = 64 - numBitsToRepresentOffset
        numBitsToRepresentLargestCompressedFileSize = math.ceil(
            math.log2(self.maxCompFileSize))
        numBitsToRepresentLargestUncompressedFileSize = math.ceil(
            math.log2(self.maxFileSize))
        logging.info('For compressed filesizes\n------------------------')
        logging.info(
            f'Max compressed filesize: {self.maxCompFileSize / (1024*1024)}MB, Max offset: {self.maxHeaderOffset}')
        logging.info(
            f'Bits required for offset: {numBitsToRepresentOffset} Bits required for largest compressed filesize: {numBitsToRepresentLargestCompressedFileSize}')
        logging.info(
            f'Max compressed filesize that can be represented with {numBitsToRepresentLargestCompressedFileSize} bits: {math.pow(2, numBitsToRepresentLargestCompressedFileSize) / (1024*1024)}MB')
        logging.info(
            '\nFor uncompressed filesizes\n--------------------------')
        logging.info(
            f'Max uncompressed filesize: {self.maxFileSize / (1024*1024)}MB, Max offset: {self.maxHeaderOffset}')
        logging.info(
            f'Bits required for offset: {numBitsToRepresentOffset} Bits required for largest uncompressed filesize: {numBitsToRepresentLargestUncompressedFileSize}')
        logging.info(
            f'Max uncompressed filesize that can be represented with {numBitsToRepresentLargestUncompressedFileSize} bits: {math.pow(2, numBitsToRepresentLargestUncompressedFileSize) / (1024*1024)}MB')
        logging.info(
            f'\nTotal\n-----\nMax filesize value that could be represented with the remaining {remainingBitsToRepresentFileSize} bits: {math.pow(2, remainingBitsToRepresentFileSize) / (1024*1024)} MB')


def buildIndex(zipPath):
    '''Returns the zip index as bytes'''
    unsortedIndex = []
    with zipfile.ZipFile(zipPath) as zip:
        infolist = zip.infolist()
        for item in infolist:
            checkIfSupportedZipItem(item)
            if not item.is_dir() and item.filename != "@3dtilesIndex1@":
                # if item.filename.endswith("tileset.json"):
                #  print(item)
                #print(f'filename: {item.filename} offset: {item.header_offset}')
                md5hash = hashlib.md5(item.filename.encode('utf-8'))
                #print(f'md5: {md5hash}')
                digest = md5hash.digest()
                [lo, hi] = struct.unpack("QQ", digest)
                offset = item.header_offset
                #print(f'lo: {lo} hi: {hi} offset: {offset}')
                unsortedIndex.append([lo, hi, offset])
    sortedIndex = sorted(unsortedIndex, key=operator.itemgetter(0, 1))
    indexBytes = bytearray()
    for item in sortedIndex:
        indexBytes += struct.pack('<QQQ', item[0], item[1], item[2])
    return indexBytes


if __name__ == '__main__':
    example_text = '''Example usage:
  Generate index file for zip):
    %(prog)s path/to/some.zip

  Inspect zip for offset packing (experiment):
    %(prog)s path/to/some.zip -s -v'''

    parser = argparse.ArgumentParser(
        epilog=example_text,
        description="A tool that builds a 3tz index file given a zip file",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('-v', '--verbose',
                        action='count',
                        dest='verbosity',
                        default=0,
                        help="verbose output (repeat for increased verbosity)")
    parser.add_argument('-q', '--quiet',
                        action='store_const',
                        const=-1,
                        default=0,
                        dest='verbosity',
                        help="quiet output (show errors only)")
    parser.set_defaults(prettyPrint=True)
    parser.add_argument('-s', '--stats', help='Get stats for the 3tz or zip',
                        action='store_true', dest='getStats', default=False)
    parser.add_argument(
        'containerpath', help='Path to 3tz or zip container file')
    parser.add_argument('outpath', nargs='?',
                        help='Path to output file', default="@3dtilesIndex1@")
    try:
        args = parser.parse_args()
    except Exception:
        parser.print_help()
        exit(0)

    setup_logging(args.verbosity)

    if args.getStats:
        stats = ZipStatistics(args.containerpath)
        stats.summary()
    else:
        indexBytes = buildIndex(args.containerpath)
        with open(args.outpath, "wb") as file:
            file.write(indexBytes)
            print(f'Successfully wrote \'{args.outpath}\'')
