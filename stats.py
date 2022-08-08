#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import struct
import os
import pathlib
import json
import argparse
#import traceback
import zipfile
import logging
import statistics
import fnmatch
import re
import subtreejson
import archive3tz as archive
import imgutils
import gltf
import base64


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


def serialize_sets(obj):
    if isinstance(obj, set):
        return list(obj)
    return obj


def isTilesetJson(parsed):
    return "root" in parsed and "geometricError" in parsed and "asset" in parsed


def isMetadataSchemaJson(parsed):
    return False


def tilesetjsonStats(stats, parsed, filename):
    if "tilesets" not in stats:
        stats["tilesets"] = {}

    if "versions" not in stats["tilesets"]:
        stats["tilesets"]["versions"] = set()
    stats["tilesets"]["versions"].add(parsed["asset"]["version"])

    if "extensionsUsed" in parsed:
        if "extensionsUsed" not in stats["tilesets"]:
            stats["tilesets"]["extensionsUsed"] = set()
        for ext in parsed["extensionsUsed"]:
            stats["tilesets"]["extensionsUsed"].add(ext)
    if "extensionsRequired" in parsed:
        if "extensionsRequired" not in stats["tilesets"]:
            stats["tilesets"]["extensionsRequired"] = set()
        for ext in parsed["extensionsRequired"]:
            stats["tilesets"]["extensionsRequired"].add(ext)

    # consider: list extras.draftVersion of each extension?
    # if "extensions" in parsed:
    #  draftVersion = ""
    #  if "extras" in parsed["extensionsRequired"][ext]:
    #    if "draftVersion" in parsed["extensionsRequired"][ext]["extras"]:
    # not all extensions are on the top level, so may need to look everywhere in the document

    # if filename not in stats["tilesets"]:
    #  stats["tilesets"][filename] = {}
    # if "tile_count" not in stats["tilesets"][filename]:
    #  stats["tilesets"][filename]["tile_count"] = 1 # "root" is a tile, so count it as 1
    # if "children" in parsed["root"]:
    #  stats["tilesets"][filename]["tile_count"] += len(parsed["root"]["children"])

    from collections import deque
    stack = deque()
    stack.append(parsed["root"])
    p = re.compile(r'\/?\w+[.]([^.]+$)')

    while stack:
        tile = stack.pop()
        if "content" in tile:
            if "uri" in tile["content"]:
                #logging.debug(f'Handling tile: {tile["content"]["uri"]}')
                if filename not in stats["tilesets"]:
                    stats["tilesets"][filename] = {}
                if "children" not in stats["tilesets"][filename]:
                    stats["tilesets"][filename]["children"] = {}
                if "extensions" in tile and "3DTILES_implicit_tiling" in tile["extensions"]:
                    if "implicit-root" not in stats["tilesets"][filename]["children"]:
                        stats["tilesets"][filename]["children"]["implicit-root"] = { "count": 0 }
                    stats["tilesets"][filename]["children"]["implicit-root"]["count"] += 1
                else:
                    res = p.search(tile["content"]["uri"])
                    if res:
                        typename = res.group(1)
                        if typename in stats["tilesets"][filename]["children"]:
                            stats["tilesets"][filename]["children"][typename]["count"] += 1
                        else:
                            stats["tilesets"][filename]["children"][typename] = {
                                "count": 1}
                    else:
                        logging.debug(f'Strange: {res} for {tile}')
            else:
                logging.error(
                    f'Content requires that uri is specified, filename: {filename} tile: {tile}')
        else:
            if filename not in stats["tilesets"]:
                stats["tilesets"][filename] = {}
            if "children" not in stats["tilesets"][filename]:
                stats["tilesets"][filename]["children"] = {}
            if "empty" not in stats["tilesets"][filename]["children"]:
                stats["tilesets"][filename]["children"]["empty"] = {"count": 0}
            stats["tilesets"][filename]["children"]["empty"]["count"] += 1
        if "children" in tile:
            for child in tile["children"]:
                stack.append(child)

    return stats


def geojsonStats(stats, parsed):
    if "geojson" not in stats:
        stats["geojson"] = {}
    if "total_features_count" not in stats["geojson"]:
        stats["geojson"]["total_features_count"] = 0
    if "properties" not in stats["geojson"]:
        stats["geojson"]["properties"] = dict()
    stats["geojson"]["total_features_count"] += len(parsed["features"])
    if "types" not in stats["geojson"]:
        stats["geojson"]["types"] = {}
    for f in parsed["features"]:
        if f["geometry"]["type"] not in stats["geojson"]["types"]:
            stats["geojson"]["types"][f["geometry"]["type"]] = {
                "count": 0, "coord_counts": []}
        stats["geojson"]["types"][f["geometry"]["type"]]["count"] += 1
        if f["geometry"]["type"] == "MultiLineString" or f["geometry"]["type"] == "Polygon" or f["geometry"]["type"] == "MultiPoint":
            # logging.debug(f["geometry"])
            for shape in f["geometry"]["coordinates"]:
                stats["geojson"]["types"][f["geometry"]["type"]
                                          ]["coord_counts"].append(len(shape))
        elif f["geometry"]["type"] == "MultiPolygon":
            if "polygon_count" not in stats["geojson"]["types"][f["geometry"]["type"]]:
                stats["geojson"]["types"][f["geometry"]
                                          ["type"]]["polygon_count"] = 0
            for shape in f["geometry"]["coordinates"]:
                stats["geojson"]["types"][f["geometry"]
                                          ["type"]]["polygon_count"] += 1
                for innerpolygon in shape:
                    stats["geojson"]["types"][f["geometry"]["type"]
                                              ]["coord_counts"].append(len(innerpolygon))
        else:
            stats["geojson"]["types"][f["geometry"]["type"]]["coord_counts"].append(
                len(f["geometry"]["coordinates"]))
        for key, value in f["properties"].items():
            if key not in stats["geojson"]["properties"]:
                stats["geojson"]["properties"][key] = list()
            stats["geojson"]["properties"][key].append(value)
    return stats


def typeSizeInBytes(propType):
    if propType == 'INT32' or propType == 'UINT32' or propType == 'FLOAT32':
        return 4
    elif propType == 'UINT8' or propType == 'INT8':
        return 1
    elif propType == 'UINT16' or propType == 'INT16':
        return 2
    elif propType == 'FLOAT64' or propType == 'INT64' or propType == 'UINT64':
        return 8
    else:
        raise ValueError(f'Unhandled property type: {propType}')


def buildSummaryOfList(values, prop, result, args):
    if type(values) != list:
        logging.debug(values)
        raise ValueError(f'Expected list, but got {type(values)}')
    if len(values) == 0:
        logging.warning(f'Got empty values list for property {prop}')
        # logging.debug(result)
        return result
    itemtype = type(values[0])
    if any(type(x) != itemtype for x in values):
        logging.warning(
            f'Type of "{prop}" is varying, ignoring values not of type {itemtype}')
        values = list(filter(lambda n: type(n) == itemtype, values))

    #logging.debug(f'prop: {prop} type of values: {type(values)} type item: {type(values[0])}')

    if itemtype == list:
        valueSet = {tuple(i) for i in values}
    else:
        valueSet = set(values)

    result[prop] = {}
    result[prop]["count"] = len(values)
    result[prop]["unique_count"] = len(valueSet)
    if itemtype == int or itemtype == float:
        if args.keepunique_threshold < 0 or (args.keepunique_threshold > 0 and args.keepunique_threshold >= result[prop]["unique_count"]):
            result[prop]["unique_values"] = valueSet
        if result[prop]["unique_count"] > 1:
            result[prop]["min"] = min(values)
            result[prop]["max"] = max(values)
            result[prop]["average"] = statistics.mean(values)
            result[prop]["median"] = statistics.median(values)
    elif itemtype == list:
        # need to serialize to string id
        stringifiedValues = list(map(str, values))
        #logging.error(f'Values: {values}')
        #logging.error(f'StringifiedValues: {stringifiedValues}')
        if args.keepunique_threshold < 0 or (args.keepunique_threshold > 0 and args.keepunique_threshold >= result[prop]["unique_count"]):
            result[prop]["unique_values"] = dict.fromkeys(stringifiedValues, 0)
            for value in values:
                result[prop]["unique_values"][str(value)] += 1
    elif itemtype == tuple:
        # need to serialize to string id
        stringifiedValues = list(map(str, valueSet))
        #logging.error(f'Values: {values}')
        #logging.error(f'StringifiedValues: {stringifiedValues}')
        if args.keepunique_threshold < 0 or (args.keepunique_threshold > 0 and args.keepunique_threshold >= result[prop]["unique_count"]):
            result[prop]["unique_values"] = dict.fromkeys(stringifiedValues, 0)
            for value in values:
                result[prop]["unique_values"][str(value)] += 1
    else:
        if args.keepunique_threshold < 0 or (args.keepunique_threshold > 0 and args.keepunique_threshold >= result[prop]["unique_count"]):
            result[prop]["unique_values"] = dict.fromkeys(valueSet, 0)
            for value in values:
                result[prop]["unique_values"][value] += 1
    return result


def buildSummaryOfFeatures(featuresDict, args):
    '''The expected format is { 'propname': [...values...] }'''
    if type(featuresDict) != dict:
        raise ValueError(f'Expected dict, but got {type(featuresDict)}')
    result = {}
    for prop in featuresDict:
        values = featuresDict[prop]

        logging.debug(f'Prop: {prop} values type: {type(values)}')
        if type(values) == dict:
            result[prop] = buildSummaryOfFeatures(values, args)
        else:
            result = buildSummaryOfList(values, prop, result, args)

    return result


def subtreeStats(stats, parsed, binarydata, filename):
    if "subtree" not in stats:
        stats["subtree"] = {}

    # fixme: needs the class definitions from the top tileset
    # fixme: might need the subtree root definition from the tileset
    # fixme: output how many tiles are available in this subtree
    # fixme: output how many tiles have contents in this subtree
    # fixme: output how many child subtrees exists below this subtree

    # hack
    schema = None
    with open("testcases/wff14schema.json", "r") as file:
        schema = json.load(file)

    if "classes" not in schema:
        raise Exception('No classes found in schema')

    # fixme: output all used feature values
    if "extensions" in parsed:
        if "3DTILES_metadata" in parsed["extensions"]:
            if "properties" in parsed["extensions"]["3DTILES_metadata"]:
                className = parsed["extensions"]["3DTILES_metadata"]["class"]
                if className not in schema["classes"]:
                    logging.error(
                        f'{className} class not found in schema definitions')
                    return stats
                classes = schema["classes"]
                for prop in parsed["extensions"]["3DTILES_metadata"]["properties"]:
                    if "properties" not in stats["subtree"]:
                        stats["subtree"]["properties"] = {}
                    if prop not in stats["subtree"]["properties"]:
                        stats["subtree"]["properties"][prop] = list()
                    #logging.info(f'{prop}: {parsed["extensions"]["3DTILES_metadata"]["properties"][prop]}')
                    bufferView = parsed["extensions"]["3DTILES_metadata"]["properties"][prop]["bufferView"]
                    #logging.debug(f'Prop: {prop} bufferView: {bufferView}')
                    propType = None
                    try:
                        propType = classes[className]["properties"][prop]["type"]
                        #logging.debug(f'Property {prop} type: {propType}')
                    except Exception:
                        raise ValueError(
                            f'Error: prop: {prop} className: {className} classes: {classes}')
                    if propType != 'STRING':
                        valueCount = int(
                            parsed["bufferViews"][bufferView]["byteLength"] / typeSizeInBytes(propType))
                        if propType == 'INT32':
                            #logging.info(f'Read {featureTable["count"]} INT32 values from bufferView: {parsed["bufferViews"][bufferView]}')
                            values = struct.unpack('<' + str(valueCount) + 'i', binarydata[parsed["bufferViews"][bufferView]["byteOffset"]:parsed["bufferViews"][bufferView]["byteOffset"] + parsed["bufferViews"][bufferView]["byteLength"]])
                            stats["subtree"]["properties"][prop].extend(values)
                            #logging.info(f'Values: {values}')
                        elif propType == 'UINT32':
                            #logging.info(f'Read {featureTable["count"]} UINT32 values from bufferView: {parsed["bufferViews"][bufferView]}')
                            values = struct.unpack('<' + str(valueCount) + 'I', binarydata[parsed["bufferViews"][bufferView]["byteOffset"]:parsed["bufferViews"][bufferView]["byteOffset"] + parsed["bufferViews"][bufferView]["byteLength"]])
                            stats["subtree"]["properties"][prop].extend(values)
                            #logging.info(f'Values: {values}')
                        elif propType == 'UINT8':
                            #logging.info(f'Read {featureTable["count"]} UINT8 values from bufferView: {parsed["bufferViews"][bufferView]}')
                            values = struct.unpack('<' + str(valueCount) + 'B', binarydata[parsed["bufferViews"][bufferView]["byteOffset"]:parsed["bufferViews"][bufferView]["byteOffset"] + parsed["bufferViews"][bufferView]["byteLength"]])
                            stats["subtree"]["properties"][prop].extend(values)
                            #logging.info(f'Values: {values}')
                        elif propType == 'FLOAT32':
                            logging.info(
                                f'Read {valueCount} FLOAT32 values from bufferView: {parsed["bufferViews"][bufferView]} binarydataLen: {len(binarydata)}')
                            values = struct.unpack('<' + str(valueCount) + 'f',
                                                   binarydata[parsed["bufferViews"][bufferView]["byteOffset"]:parsed["bufferViews"][bufferView]["byteOffset"] + parsed["bufferViews"][bufferView]["byteLength"]])
                            stats["subtree"]["properties"][prop].extend(values)
                            #logging.info(f'Values: {values}')
                        else:
                            raise ValueError(
                                f'Unhandled property type: {propType}')
                    else:
                        raise ValueError(
                            f'Unhandled property type: {propType}')
                        # the below code needs to be fixed and cleaned up
                        # if propType == 'STRING':
                        #    if "offsetType" in featureTable["properties"][prop]:
                        #        if featureTable["properties"][prop]["offsetType"] != "UINT32":
                        #            logging.error(
                        #                f'Unhandled offsetType: {featureTable["properties"][prop]["offsetType"]}')
                        #            exit(-1)
                        #    try:
                        #        stringOffsetBufferView = featureTable["properties"][prop]["stringOffsetBufferView"]
                        #        #logging.info(f'stringOffsetBufferView: {stringOffsetBufferView}')
                        #        start = parsed["bufferViews"][stringOffsetBufferView]["byteOffset"]
                        #        length = parsed["bufferViews"][stringOffsetBufferView]["byteLength"]
                        #        #logging.info(f'string offset start: {start} length: {length} count: {featureTable["count"]} binarydataLength: {len(binarydata)}')
                        #        typeBytesize = 4  # UINT32
                        #        numOffsets = featureTable["count"] + 1
                        #        # if more data than is needed, trim buffer
                        #        if length > numOffsets * typeBytesize:
                        #            # offsets are 8 byte aligned, so need to trim the padding due to how struct.unpack works
                        #            length = (
                        #                featureTable["count"]+1) * typeBytesize
                        #        stringOffsets = struct.unpack(
                        #            "<" + str(numOffsets) + "I", binarydata[start:start+length])
                        #        #logging.info(f'stringoffsets: {stringOffsets}')
                        #        bufferByteOffset = parsed["bufferViews"][bufferView]["byteOffset"]
                        #        bufferByteLength = parsed["bufferViews"][bufferView]["byteLength"]
                        #        for i in range(0, len(stringOffsets)-1, 1):
                        #            rawbytes = binarydata[bufferByteOffset +
                        #                                  stringOffsets[i]:bufferByteOffset+stringOffsets[i+1]]
                        #            #logging.info(f'{i} of {len(stringOffsets)}: {rawbytes}')
                        #            string = rawbytes.decode("utf8")
                        #            #logging.info(f'{i}: {string}')
                        #            stats["glb"]["featureTables"][prop].append(
                        #                string)
                        #        #logging.info(f'Read {featureTable["count"]} STRING values from bufferView: {parsed["bufferViews"][bufferView]}')
                        #    except Exception as e:
                        #        logging.error(
                        #            f'filename: {filename} prop: {prop}, count: {featureTable["count"]} stringOffsetBufferView: {parsed["bufferViews"][stringOffsetBufferView]} error: {e}')
                        #        #logging.info(f'{prop} stringoffsets {i}: {stringOffsets} {stringOffsets[i]}, error: {e}')
                        #        exit(-1)
    return stats


def gltfStats(stats, fileExt, doc, filename):
    if fileExt not in stats:
        stats[fileExt] = {}
    parsed = doc.doc
    if "extensionsUsed" in parsed:
        if "extensionsUsed" not in stats[fileExt]:
            stats[fileExt]["extensionsUsed"] = set()
        for ext in parsed["extensionsUsed"]:
            stats[fileExt]["extensionsUsed"].add(ext)
    if "extensionsRequired" in parsed:
        if "extensionsRequired" not in stats[fileExt]:
            stats[fileExt]["extensionsRequired"] = set()
        for ext in parsed["extensionsRequired"]:
            stats[fileExt]["extensionsRequired"].add(ext)

    totalTriangleCount = 0
    totalVertexCount = 0
    drawCallCount = 0  # counts the number of mesh primitives
    materialCount = 0
    if "materials" in parsed:
        materialCount = len(parsed["materials"])
    maxUVs = 0
    maxAttributes = 0
    animationCount = 0
    if "animations" in parsed:
        animationCount = len(parsed["animations"])

    if "meshes" in parsed:
        for mesh in parsed["meshes"]:
            drawCallCount += len(mesh["primitives"])
            for primitive in mesh["primitives"]:
                index = primitive["indices"]
                pos = primitive["attributes"]["POSITION"]
                totalTriangleCount += parsed["accessors"][index]["count"] // 3
                totalVertexCount += parsed["accessors"][pos]["count"]

                texcoordCount = 0
                for key in primitive["attributes"].keys():
                    if key.startswith("TEXCOORD_"):
                        texcoordCount += 1
                maxUVs = max(maxUVs, texcoordCount)
                maxAttributes = max(maxAttributes, len(primitive["attributes"]))

    if "info" not in stats[fileExt]:
        stats[fileExt]["info"] = {"totalVertexCounts": [], "totalTriangleCounts": [], "drawCallCounts": [], "materialCounts": [
        ], "hasDefaultScenes": [], "hasSkins": [], "hasTextures": [], "animationCounts": [], "maxUVs": [], "maxAttributes": []}

    stats[fileExt]["info"]["totalVertexCounts"].append(totalVertexCount)
    stats[fileExt]["info"]["totalTriangleCounts"].append(totalTriangleCount)
    stats[fileExt]["info"]["drawCallCounts"].append(drawCallCount)
    stats[fileExt]["info"]["materialCounts"].append(materialCount)
    stats[fileExt]["info"]["hasDefaultScenes"].append("scene" in parsed)
    stats[fileExt]["info"]["hasSkins"].append(
        "skins" in parsed and len(parsed["skins"]) > 0)
    stats[fileExt]["info"]["hasTextures"].append(
        "textures" in parsed and len(parsed["textures"]) > 0)
    stats[fileExt]["info"]["animationCounts"].append(animationCount)
    stats[fileExt]["info"]["maxUVs"].append(maxUVs)
    stats[fileExt]["info"]["maxAttributes"].append(maxAttributes)

    if materialCount > 0:
        for mat in parsed["materials"]:
            if "pbrMetallicRoughness" in mat and "baseColorTexture" in mat["pbrMetallicRoughness"] and "index" in mat["pbrMetallicRoughness"]["baseColorTexture"]:
                textureInfo = parsed["textures"][mat["pbrMetallicRoughness"]
                                                 ["baseColorTexture"]["index"]]
                if "source" in textureInfo:
                    image = parsed["images"][textureInfo["source"]]
                    stats[fileExt]["info"]["resources"] = {
                        "embeddedImages": [], "dimensions": []}
                    if "uri" in image:
                        if "externalImages" not in stats[fileExt]["info"]["resources"]:
                            stats[fileExt]["info"]["resources"]["externalImages"] = []
                        stats[fileExt]["info"]["resources"]["externalImages"].append(
                            image["uri"])
                    elif "bufferView" in image:
                        stats[fileExt]["info"]["resources"]["embeddedImages"].append(
                            image["bufferView"])
                        bufferView = parsed["bufferViews"][image["bufferView"]]
                        # logging.error(bufferView)
                        if bufferView["buffer"] != 0:
                            raise Exception(
                                f'Unhandled external binary buffer: {bufferView["buffer"]}')
                        data = doc.buffers[bufferView["buffer"]]
                        byteOffset = 0
                        if "byteOffset" in bufferView:
                            byteOffset = bufferView["byteOffset"]
                        imageBytes = data[byteOffset:byteOffset+bufferView["byteLength"]]
                        #logging.debug(f'byteOffset: {byteOffset} byteLength: {bufferView["byteLength"]} data: {len(data)}')
                        dims = imgutils.getImageDims(
                            imageBytes, image["mimeType"])
                        stats[fileExt]["info"]["resources"]["dimensions"].append(
                            dims)
                    # logging.error(image)

    logging.debug(f'{filename}: drawCallCount: {drawCallCount} materialCount: {materialCount} tris: {totalTriangleCount} verts: {totalVertexCount} maxUVs: {maxUVs} maxAttribs: {maxAttributes}')

    classes = doc.getClasses()
    if classes is not None:
        for classname in classes:
            #logging.info(f'classname: {classname}')
            for prop in classes[classname]["properties"]:
                if "unique_properties" in stats[fileExt]:
                    stats[fileExt]["unique_properties"].add(prop)
                else:
                    stats[fileExt]["unique_properties"] = set([prop])

    if len(doc.propertyTables) > 0:
        if "featureTables" not in stats[fileExt]:
            stats[fileExt]["featureTables"] = {}
        for ftName in doc.propertyTables.getTableNames():
            featureTable = doc.propertyTables.getNamedTable(ftName)
            for prop in featureTable["properties"]:
                if prop not in stats[fileExt]["featureTables"]:
                    stats[fileExt]["featureTables"][prop] = list()
                #logging.info(f'{prop}: {featureTable["properties"][prop]}')
                values = doc.getFeatureTablePropertyValues(ftName, prop)
                #logging.debug(f'{prop}: {values}')
                stats[fileExt]["featureTables"][prop].extend(values)

    return stats


def handleFile(stats, filename, uncompFilesize, fileContents):
    suffix = pathlib.PurePath(filename).suffix
    if filename == "@3dtilesIndex1@":
        stats[filename] = {"file_sizes": [uncompFilesize],
                           "index_entries": int(uncompFilesize / 24)}
        return stats
    if not suffix:
        logging.warning(
            f'Skipping file {fileinfo.filename} since it has no file extension')
        return stats
    if suffix[1:] not in stats:
        stats[suffix[1:]] = {"file_sizes": []}
    stats[suffix[1:]]["file_sizes"].append(uncompFilesize)
    if suffix == '.geojson':
        parsed = json.loads(fileContents)
        stats = geojsonStats(stats, parsed)
    elif suffix == '.glb' or suffix == '.gltf':
        gltfdoc = gltf.GltfDocument(fileContents, pathlib.PurePath(filename).parent)
        gltfdoc.loadAllBuffers()
        gltfdoc.loadMetadata()
        stats = gltfStats(stats, suffix[1:], gltfdoc, filename)
    elif suffix == '.json':
        parsed = json.loads(fileContents)
        if isTilesetJson(parsed):
            stats = tilesetjsonStats(stats, parsed, filename)
        # elif isMetadataSchemaJson(parsed):
        #  stats = metadatajsonStats(stats, parsed, filename)
        else:
            logging.warning(f'Unrecognized json format found: {filename}')
    elif suffix == '.subtree':
        [jsondata, binarydata] = subtreejson.getChunksFromBuffer(fileContents)
        parsed = json.loads(jsondata)
        stats = subtreeStats(stats, parsed, binarydata, filename)
    elif suffix == '.jpg':
        dims = imgutils.getImageDims(fileContents, "image/jpeg")
        if "dimensions" not in stats[suffix[1:]]:
            stats[suffix[1:]]["dimensions"] = []
        stats[suffix[1:]]["dimensions"].append(dims)
    elif suffix == '.png':
        dims = imgutils.getImageDims(fileContents, "image/png")
        if "dimensions" not in stats[suffix[1:]]:
            stats[suffix[1:]]["dimensions"] = []
        stats[suffix[1:]]["dimensions"].append(dims)
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
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
    parser.add_argument('-f', '--full', action='store_const', const=True,
                        default=False, dest='fullstats', help='Keep full intermediate stats')
    parser.add_argument('-kut', '--keep-unique-threshold', action='store', type=int, default=0, dest='keepunique_threshold',
                        help='Threshold for keeping unique values in stats output, if negative retains all, 0 discards all, if positive retain if the number of unique values is less than this number')
    parser.add_argument('-i', '--use-3tz-index', dest='useindex',
                        action='store_true', help='Use 3tz index (default)', default=True)
    parser.add_argument('-ni', '--no-use-3tz-index', dest='useindex',
                        action='store_false', help='Don\'t use 3tz index')
    parser.add_argument('filepath', help='Path to 3tz, zip or plain file')
    parser.add_argument('filter', nargs='?',
                        help='Filter for files', default='*')
    args = parser.parse_args()

    setup_logging(args.verbosity)

    filepathsuffix = pathlib.PurePath(args.filepath).suffix
    stats = {"sourcePath": args.filepath}
    filterIsSingleFile = False
    if args.filter is not None and "*" not in args.filter and "?" not in args.filter and "[" not in args.filter and "]" not in args.filter:
        filterIsSingleFile = True

    if filepathsuffix == ".3tz" or filepathsuffix == ".zip":
        if args.useindex and filepathsuffix == ".3tz":
            if filterIsSingleFile:
                filename = args.filter
                decompressedBytes = archive.getSingleFile(
                    args.filepath, filename)
                stats = handleFile(stats, filename, len(
                    decompressedBytes), decompressedBytes)
            else:
                with open(args.filepath, mode='rb') as file:
                    cde = archive.getLastEntryInCentralDirectory(
                        file, args.filepath)
                    indexLfh = archive.getLocalFileHeaderFromCentralDirectoryEntry(
                        file, cde)
                    if indexLfh.get('filename') == '@3dtilesIndex1@':
                        indexContent = archive.getFileContentsFromLocalFileHeader(
                            file, indexLfh)
                        stats = handleFile(
                            stats, indexLfh["filename"], indexLfh["uncompressedSize"], indexContent)
                        index = archive.readIndex(indexContent)
                        logging.info(
                            f'Opened 3tz index containing {len(index)} files.')
                        for entry in index:
                            offset = entry[2]
                            try:
                                lfh = archive.getLocalFileHeaderAtOffset(
                                    file, offset)
                                filename = lfh["filename"]
                                if fnmatch.fnmatchcase(filename, args.filter):
                                    decompressedBytes = archive.getFileContentsFromLocalFileHeader(
                                        file, lfh)
                                    stats = handleFile(
                                        stats, filename, lfh["uncompressedSize"], decompressedBytes)
                            except Exception as e:
                                logging.warning(
                                    f'Skipping file \'{filename}\': {e}')
                                #traceback.print_exc()
                    else:
                        logging.error(
                            f'Found no 3tz index file in {args.filepath}')
                        exit(-1)
        else:
            try:
                with zipfile.ZipFile(args.filepath) as zip:
                    infolist = zip.infolist()
                    logging.info(
                        f'Opened zip file containing {len(infolist)} files.')
                    for fileinfo in infolist:
                        if not fileinfo.is_dir():
                            if fnmatch.fnmatchcase(fileinfo.filename, args.filter):
                                stats = handleFile(
                                    stats, fileinfo.filename, fileinfo.file_size, zip.read(name=fileinfo.filename))
            except NotImplementedError as e:
                logging.error(e)
                exit(-1)
    else:
        if args.filter is not None and os.path.isdir(args.filepath):
            for filename in os.listdir(args.filepath):
                if fnmatch.fnmatchcase(filename, args.filter):
                    filepath = os.path.join(args.filepath, filename)
                    with open(filepath, "rb") as file:
                        stats = handleFile(stats, filepath,
                                        os.path.getsize(filepath), file.read())
        else:
            with open(args.filepath, "rb") as file:
                stats = handleFile(stats, args.filepath,
                                os.path.getsize(args.filepath), file.read())

    for key in stats.keys():
        if "file_sizes" in stats[key]:
            numFiles = len(stats[key]["file_sizes"])
            if numFiles > 1:
                fileSizes = stats[key]["file_sizes"]
                stats[key]["num_files"] = numFiles
                stats[key]["avg_file_size"] = statistics.mean(fileSizes)
                stats[key]["median_file_size"] = statistics.median(fileSizes)
                stats[key]["min_file_size"] = min(fileSizes)
                stats[key]["max_file_size"] = max(fileSizes)
            if not args.fullstats and numFiles > 1:
                del stats[key]["file_sizes"]
        if "geojson" == key:
            if "properties" in stats[key]:
                summary = buildSummaryOfFeatures(
                    stats[key]["properties"], args)
                if len(summary) > 0:
                    stats[key]["summary"] = {"features": summary}
                if not args.fullstats:
                    del stats[key]["properties"]
            if "types" in stats[key]:
                for geomtype in stats[key]["types"]:
                    if "coordinates" in stats[key]["types"][geomtype] and len(stats[key]["types"][geomtype]["coordinates"]) > 1:
                        summary = {}
                        summary = buildSummaryOfList(
                            stats[key]["types"][geomtype]["coordinates"], "coordinates", summary, args)
                        # logging.debug(summary)
                        stats[key]["types"][geomtype]["coordinates"] = summary["coordinates"]
                    if "coord_counts" in stats[key]["types"][geomtype] and len(stats[key]["types"][geomtype]["coord_counts"]) > 1:
                        summary = {}
                        summary = buildSummaryOfList(
                            stats[key]["types"][geomtype]["coord_counts"], "coord_counts", summary, args)
                        # logging.debug(summary)
                        stats[key]["types"][geomtype]["coord_counts"] = summary["coord_counts"]
        if "subtree" == key:
            if "properties" in stats[key]:
                summary = buildSummaryOfFeatures(
                    stats[key]["properties"], args)
                if len(summary) > 0:
                    stats[key]["summary"] = {"features": summary}
                if not args.fullstats:
                    del stats[key]["properties"]
        if "glb" == key or "gltf" == key:
            stats[key]["summary"] = {}
            if "info" in stats[key]:
                summary = buildSummaryOfFeatures(stats[key]["info"], args)
                if len(summary) > 0:
                    stats[key]["summary"]["info"] = summary
                if not args.fullstats:
                    del stats[key]["info"]
            if "featureTables" in stats[key]:
                summary = buildSummaryOfFeatures(
                    stats[key]["featureTables"], args)
                if len(summary) > 0:
                    stats[key]["summary"]["features"] = summary
                if not args.fullstats:
                    del stats[key]["featureTables"]
        if "png" == key or "jpg" == key:
            stats[key]["summary"] = {}
            if "dimensions" in stats[key]:
                summary = {}
                summary = buildSummaryOfList(
                    stats[key]["dimensions"], "dimensions", summary, args)
                if len(summary) > 0:
                    stats[key]["summary"] = summary
                if not args.fullstats:
                    del stats[key]["dimensions"]
    print(json.dumps(stats, default=serialize_sets))
