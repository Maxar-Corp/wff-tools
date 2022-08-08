#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import sys
import os
import pathlib
import json
import argparse
import zipfile
import logging
import fnmatch
import glbjson
import archive3tz as archive
import glbjson
import gltf as gltfutils
import base64
import re
#import traceback # only for debugging


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


def checkIfHasMetadata(gltfdoc, filename):
    if not gltfdoc.hasMetadata():
        logging.debug(gltfdoc.doc)
        raise Exception(
            f'File {filename} doesn\'t use EXT_feature_metadata or EXT_structural_metadata')

def handleFile(args, filename, fileContents):
    suffix = pathlib.PurePath(filename).suffix
    gltf = None
    if suffix == '.gltf' or suffix == '.glb':
        gltf = gltfutils.GltfDocument(fileContents, pathlib.PurePath(filename).parent)
        checkIfHasMetadata(gltf, filename)
        gltf.loadAllBuffers()
        gltf.loadMetadata()
 
    if gltf is not None:
        if args.ftName is not None:
            try:
                idx = int(args.ftName)
            except ValueError:
                idx = None
            
            if idx != None:
                try:
                    args.ftName = gltf.propertyTables[idx]["name"]
                except IndexError:
                    logging.warning(f'PropertyTable index out of range, attempting to use first PropertyTable instead...')
                    if len(gltf.propertyTables) > 0:
                        args.ftName = gltf.propertyTables[0]["name"]
                    else:
                        raise Exception('There are no PropertyTables in this file')

        if args.ftName is not None:
            logging.debug(f'Using table with name \'{args.ftName}\'')

        if args.ftx is not None:
            try:
                idx = int(args.ftx)
            except ValueError:
                idx = None
            
            if idx != None:
                try:
                    args.ftx = gltf.propertyTextures[idx]["name"]
                except IndexError:
                    logging.warning(f'PropertyTexture index out of range, attempting to use first PropertyTexture instead...')
                    if len(gltf.propertyTextures) > 0:
                        args.ftx = gltf.propertyTextures[0]["name"]
                    else:
                        raise Exception('There are no PropertyTextures in this file')

            if args.ftx == ".":
                for index, ftxName in enumerate(gltf.getFeatureTextureNames()):
                    print(f'PropertyTexture \'{ftxName}\':')
                    for prop, values in gltf.getAllFeatureTexturePropertyValues(ftxName, args.propName).items():
                        if args.listIdx:
                            print(f'{prop} values:')
                            for i, val in enumerate(values):
                                print(f'{i}: {val}')
                        else:
                            print(f'{prop} values:\n{values}')
            else:
                if args.propName is None:
                    print(f'PropertyTexture \'{args.ftx}\':')
                    for prop, values in gltf.getAllFeatureTexturePropertyValues(args.ftx).items():
                        if args.listIdx:
                            print(f'{prop} values:')
                            for i, val in enumerate(values):
                                print(f'{i}: {val}')
                        else:
                            print(f'{prop} values:\n{values}')
                else:
                    print(f'PropertyTexture \'{args.ftx}\' property \'{args.propName}\':')
                    values = gltf.getFeatureTexturePropertyValues(
                        args.ftName, args.propName)
                    if args.listIdx:
                        for i, val in enumerate(values):
                            print(f'{i}: {val}')
                    else:
                        print(values)

        if (args.ftName is None and args.propName is None):
            if args.verbosity == 0:
                ftNames = gltf.getFeatureTableNames()
                fTextureNames = gltf.getFeatureTextureNames()
                if len(ftNames) > 0:
                    print(f'\nFeatureTables from {filename}:')
                    print(list(ftNames))
                if len(fTextureNames) > 0:
                    print(f'\nFeatureTextures from {filename}:')
                    print(list(fTextureNames))
            else:
                featureTables = gltf.propertyTables
                logging.debug(f'FeatureTable names: {featureTables.getTableNames()}')
                featureTextures = gltf.propertyTextures
                logging.debug(f'FeatureTexture names: {featureTextures.getTableNames()}')
                if len(featureTables) > 0:
                    print(f'\nFeatureTables from {filename}:')
                    glbjson.printJson(json.dumps(
                        featureTables.getTableNames()), args.prettyPrint)
                if len(featureTextures) > 0:
                    print(f'\nFeatureTextures from {filename}:')
                    glbjson.printJson(json.dumps(
                        featureTextures.getTableNames()), args.prettyPrint)
        else:
            if args.ftName == ".":
                for index, ftName in enumerate(gltf.getFeatureTableNames()):
                    print(f'PropertyTable \'{ftName}\':')
                    for prop, values in gltf.getAllFeatureTablePropertyValues(ftName, args.propName).items():
                        if args.listIdx:
                            print(f'{prop} values:')
                            for i, val in enumerate(values):
                                print(f'{i}: {val}')
                        else:
                            print(f'{prop} values:\n{values}')
            else:
                if args.propName is None:
                    print(f'PropertyTable \'{args.ftName}\':')
                    for prop, values in gltf.getAllFeatureTablePropertyValues(args.ftName).items():
                        if args.listIdx:
                            print(f'{prop} values:')
                            for i, val in enumerate(values):
                                print(f'{i}: {val}')
                        else:
                            print(f'{prop} values:\n{values}')
                else:
                    print(f'PropertyTable \'{args.ftName}\' property \'{args.propName}\':')
                    values = gltf.getFeatureTablePropertyValues(
                        args.ftName, args.propName)
                    if args.listIdx:
                        for i, val in enumerate(values):
                            print(f'{i}: {val}')
                    else:
                        print(values)
    else:
        logging.error(f'Unhandled file: {filename}')


if __name__ == '__main__':
    example_text = '''Example usage:
  List all FeatureTables in GLB inside 3tz:
    %(prog)s myfiles/archived/some.3tz 0/0/0/0.glb

  List all property values from the LandCover FeatureTable:
    %(prog)s tile.glb -ft LandCover

  List the 'name' property values from the LandCover FeatureTable:
    %(prog)s tile.glb -ft LandCover -p name

  List the 'src' property with property indices for each value from the first found FeatureTable:
    %(prog)s tile.glb -p src -li'''

    parser = argparse.ArgumentParser(
        epilog=example_text,
        description='A tool to inspect EXT_feature_metadata content',
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
    parser.add_argument('--pretty', dest='prettyPrint', action='store_true',
                        help='Pretty-print the JSON output', default=True)
    parser.add_argument('--no-pretty', dest='prettyPrint',
                        action='store_false', help='Don\'t pretty-print the JSON output')
    parser.add_argument('-ft', '--feature-table',
                        dest='ftName',
                        help='The name of the FeatureTable to query, or a number from 0..n (to get FeatureTable n)')
    parser.add_argument('-ftx', '--feature-texture',
                        dest='ftx',
                        help='The name of the FeatureTexture to query, or a number from 0..n (to get FeatureTexture n)')
    parser.add_argument('-p', '--property',
                        dest='propName',
                        help='The name of the property to query')
    parser.add_argument('-li', '--list-indices',
                        dest='listIdx',
                        help='List indices for each property value', action='store_true', default=False)
    parser.add_argument('filepath', help='Path to 3tz, zip or glb file')
    parser.add_argument(
        'filter', nargs='?', help='Filter for files, a glob to match one or more glb files', default='*')

    try:
        args = parser.parse_args()
    except Exception:
        parser.print_help()
        exit(0)

    setup_logging(args.verbosity)

    logging.debug(args)

    filepathsuffix = pathlib.PurePath(args.filepath).suffix
    filterIsSingleFile = False
    if args.filter is not None and "*" not in args.filter and "?" not in args.filter and "[" not in args.filter and "]" not in args.filter:
        filterIsSingleFile = True

    try:
        if filepathsuffix == ".3tz" or filepathsuffix == ".zip":
            if filepathsuffix == ".3tz":
                if filterIsSingleFile:
                    filename = args.filter
                    decompressedBytes = archive.getSingleFile(args.filepath, filename)
                    handleFile(args, filename, decompressedBytes)
                else:
                    with open(args.filepath, mode='rb') as file:
                        cde = archive.getLastEntryInCentralDirectory(
                            file, args.filepath)
                        indexLfh = archive.getLocalFileHeaderFromCentralDirectoryEntry(
                            file, cde)
                        if indexLfh.get('filename') == '@3dtilesIndex1@':
                            indexContent = archive.getFileContentsFromLocalFileHeader(
                                file, indexLfh)
                            index = archive.readIndex(indexContent)
                            logging.info(
                                f'Opened 3tz index containing {len(index)} files.')
                            for entry in index:
                                offset = entry[2]
                                lfh = archive.getLocalFileHeaderAtOffset(
                                    file, offset)
                                filename = lfh["filename"]
                                if fnmatch.fnmatchcase(filename, args.filter):
                                    decompressedBytes = archive.getFileContentsFromLocalFileHeader(
                                        file, lfh)
                                    handleFile(args, filename, decompressedBytes)
                        else:
                            logging.error(
                                f'Found no 3tz index file in {args.filepath}')
                            exit(-1)
            else:
                with zipfile.ZipFile(args.filepath) as zip:
                    infolist = zip.infolist()
                    logging.info(
                        f'Opened zip file containing {len(infolist)} files.')
                    for fileinfo in infolist:
                        if not fileinfo.is_dir():
                            if fnmatch.fnmatchcase(fileinfo.filename, args.filter):
                                handleFile(args, fileinfo.filename, zip.read(
                                    name=fileinfo.filename))
        else:
            with open(args.filepath, "rb") as file:
                handleFile(args, args.filepath, file.read())
    except Exception as e:
        logging.error(e)
        #traceback.print_exc()
        exit(-1)
