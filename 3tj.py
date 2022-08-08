#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import pathlib
import glbjson
import subtreejson
import argparse
import archive3tz as archive
import logging


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


if __name__ == '__main__':
    example_text = '''Example usage:
  Print the root tileset.json inside the 3tz:
    %(prog)s /path/to/some.3tz

  Print the json part of a given GLB file inside the 3tz:
    %(prog)s /path/to/some.3tz 0/0/0/0.glb

  Extract the given GLB file from inside the 3tz:
    %(prog)s --extract /path/to/some.3tz 2/12/1823.glb
  '''
    parser = argparse.ArgumentParser(
        epilog=example_text,
        description="A tool to quickly inspect 3tz archive content",
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
    parser.add_argument('--pretty', dest='prettyPrint',
                        action='store_true', help='Prett-print the JSON output')
    parser.add_argument('--no-pretty', dest='prettyPrint',
                        action='store_false', help='Don\'t pretty-print the JSON output')
    parser.add_argument('-x', '--extract', dest='extract', action='store_true',
                        default=False, help='Extracts the given file from the 3tz')
    parser.set_defaults(prettyPrint=True)
    parser.add_argument(
        'containerpath', help='Path to 3tz or zip container file')
    parser.add_argument('filepath', nargs='?',
                        help='Inner path in archive, e.g 0/0/0.json', default='tileset.json')
    try:
        args = parser.parse_args()
    except Exception:
        parser.print_help()
        exit(0)

    setup_logging(args.verbosity)

    try:
        with open(args.containerpath, mode='rb') as file:
            cde = archive.getLastEntryInCentralDirectory(
                file, args.containerpath)
            lfh = archive.getLocalFileHeaderFromCentralDirectoryEntry(
                file, cde)
            if lfh.get('filename') == '@3dtilesIndex1@':
                logging.debug('Reading index content')
                indexContent = archive.getFileContentsFromLocalFileHeader(
                    file, lfh)
                index = archive.readIndex(indexContent)
                offset = archive.findLocalFileHeaderOffsetInIndex(
                    index, args.filepath)
                if offset is None:
                    logging.error(f'File not found: {args.filepath}')
                    exit(-1)
                lfh2 = archive.getLocalFileHeaderAtOffset(file, offset)
                fileExtension = pathlib.PurePath(lfh2.get('filename')).suffix
                if lfh2.get('filename') != args.filepath:
                    logging.error(
                        f"Expected {args.filepath} but got {lfh2.get('filename')}")
                    exit(-1)
                if (args.extract):
                    filename = pathlib.PurePath(args.filepath).name
                    filecontents = archive.getFileContentsFromLocalFileHeader(
                        file, lfh2)
                    with open(filename, "wb") as out:
                        out.write(filecontents)
                        logging.info(f'Saved to {filename}')
                else:
                    if fileExtension == '.json' or fileExtension == '.geojson':
                        filecontents = archive.getFileContentsFromLocalFileHeader(
                            file, lfh2)
                        glbjson.printJson(filecontents.decode(
                            'utf-8'), args.prettyPrint)
                    elif fileExtension == '.glb':
                        # TODO: do streamed extraction to read as little data as necessary
                        filecontents = archive.getFileContentsFromLocalFileHeader(
                            file, lfh2)
                        glbjson.printJson(glbjson.getJsonFromBuffer(
                            filecontents), args.prettyPrint)
                    elif fileExtension == '.subtree':
                        # TODO: do streamed extraction to read as little data as necessary
                        filecontents = archive.getFileContentsFromLocalFileHeader(
                            file, lfh2)
                        subtreejson.printJson(subtreejson.getJsonFromBuffer(
                            filecontents), args.prettyPrint)
                    else:
                        logging.error(
                            f'Unknown file extension: {fileExtension}')
            else:
                logging.error('Failed to find 3tz index file.')
                logging.debug(
                    f'The last entry in {pathlib.PurePath(args.containerpath).name} was \'{lfh.get("filename")}\'.')
    except Exception as e:
        logging.error(e)
