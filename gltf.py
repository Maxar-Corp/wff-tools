#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

from argparse import ArgumentError
import struct
import logging
import imgutils
from enum import Enum
import io
import math
import re
import base64
import json
import glbjson
import os
# import traceback # only for debugging


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


def isDataUri(uri):
    datauriRegexp = r'data:[^;]*;base64,(.*)'
    return re.match(datauriRegexp, uri)


def decodeDataUri(uri):
    match = isDataUri(uri)
    if match:
        if match.group(1):
            return base64.standard_b64decode(match.group(1))
    return None


def componentTypeSizeInBytes(propType):
    if propType == 'UINT8' or propType == 'INT8':
        return 1
    elif propType == 'UINT16' or propType == 'INT16':
        return 2
    elif propType == 'INT32' or propType == 'UINT32' or propType == 'FLOAT32':
        return 4
    elif propType == 'FLOAT64' or propType == 'INT64' or propType == 'UINT64':
        return 8
    else:
        logging.warning(
            f'Unhandled property type: {propType}, defaulting to component size 1 byte')
        return 1


def denormalize(propType, value):
    if propType == 'UINT8':
        return value / 255.0
    elif propType == 'INT8':
        return max(value / 127.0, -1.0)
    elif propType == 'UINT16':
        return value / 65535.0
    elif propType == 'INT16':
        return max(value / 32767.0, -1.0)
    elif propType == 'UINT32':
        return value / 4294967295.0
    elif propType == 'INT32':
        return max(value / 2147483647.0, -1.0)
    elif propType == 'UINT64':
        return value / 18446744073709551615.0
    elif propType == 'INT64':
        return max(value / 9223372036854775807.0, -1.0)
    else:
        raise ValueError(f'Unhandled type: {propType}')


def applyOffsetScale(propType, value, offset=0.0, scale=1.0, denormalizeValue=False):
    if denormalizeValue:
        return offset + scale * denormalize(propType, value)
    else:
        return offset + scale * value


def getComponentCount(propType):
    componentCount = 1
    if propType == 'SCALAR':
        componentCount = 1
    elif propType == 'VEC2':
        componentCount = 2
    elif propType == 'VEC3':
        componentCount = 3
    elif propType == 'VEC4':
        componentCount = 4
    elif propType == 'MAT2':
        componentCount = 4
    elif propType == 'MAT3':
        componentCount = 9
    elif propType == 'MAT4':
        componentCount = 16
    else:
        logging.warning(f'Unhandled componentType: {propType}')
    return componentCount


class Mode(Enum):
    UNKNOWN = 0
    EXT_FEATURE_METADATA = 1
    EXT_STRUCTURAL_METADATA = 2


class PropertyTables:
    def __init__(self, doc=None, tablePropName=None):
        self.tables = []
        self.nameToTableIndex = {}
        self.classToTableIndex = {}
        if doc is None or tablePropName is None:
            return
        idx = 0
        if "EXT_structural_metadata" in doc["extensionsUsed"]:
            if tablePropName in doc["extensions"]["EXT_structural_metadata"]:
                self.tables = doc["extensions"]["EXT_structural_metadata"][tablePropName]
                #logging.debug(self.tables)
                for table in self.tables:
                    if "class" in table:
                        self.classToTableIndex[table["class"]] = idx
                    if "name" in table:
                        self.nameToTableIndex[table["name"]] = idx
                    else:
                        table["name"] = table["class"]
                        self.nameToTableIndex[table["class"]] = idx
                    idx += 1
                #logging.debug(f'tablePropName: {tablePropName} nameToIndex: {self.nameToTableIndex} classToIndex: {self.classToTableIndex}')
        elif "EXT_feature_metadata" in doc["extensionsUsed"]:
            if tablePropName in doc["extensions"]["EXT_feature_metadata"]:
                for name, table in doc["extensions"]["EXT_feature_metadata"][tablePropName].items():
                    if "name" not in table:
                        table["name"] = name
                    self.tables.append(table)
                    self.nameToTableIndex[name] = idx
                    self.classToTableIndex[table["class"]] = idx
                    idx += 1

    def __len__(self):
        return len(self.tables)

    def __getitem__(self, idx):
        return self.tables[idx]

    def __iter__(self):
        for each in self.tables:
            yield each

    def __str__(self):
        return str(self.tables)

    def getNamedTable(self, name):
        return self.tables[self.nameToTableIndex[name]]

    def getTableNames(self):
        return list(self.nameToTableIndex.keys())

    def getTableClasses(self):
        return list(self.classToTableIndex.keys())


class GltfDocument():
    def __init__(self, buffer, basePath):
        '''Buffer is a python Buffer object, basePath is the directory that contains the file which contents are passed in.'''
        if len(buffer) < 12:
            raise ValueError('Buffer is too short to be a valid glTF file')
        
        (magic, version, length) = struct.unpack("<III", buffer[0:12])

        #logging.debug(f'Magic: {hex(magic)} version: {version} length: {length}')

        if magic == 0x46546c67:
            [jsonchunk, binchunk] = glbjson.getChunksFromBuffer(buffer)
            self.doc = json.loads(jsonchunk)
            self.buffers = [binchunk]
        else:
            self.doc = json.loads(buffer)
            self.buffers = []

        if "asset" not in self.doc or "version" not in self.doc["asset"] or self.doc["asset"]["version"] != "2.0":
            raise ValueError(f'Invalid glTF document')
        
        self.propertyTables = PropertyTables()
        self.propertyTextures = PropertyTables()
        self.mode = Mode.UNKNOWN
        self.basePath = basePath

        if "extensionsUsed" in self.doc:
            if "EXT_structural_metadata" in self.doc["extensionsUsed"]:
                self.mode = Mode.EXT_STRUCTURAL_METADATA
            elif "EXT_feature_metadata" in self.doc["extensionsUsed"]:
                self.mode = Mode.EXT_FEATURE_METADATA

    def hasMetadata(self):
        return self.mode != Mode.UNKNOWN

    def hasLoadedMetadata(self):
        return len(self.propertyTables > 0) or len(self.propertyTextures > 0)
        
    def loadMetadata(self):
        if self.mode == Mode.EXT_STRUCTURAL_METADATA:
            self.propertyTables = PropertyTables(self.doc, "propertyTables")
            self.propertyTextures = PropertyTables(self.doc, "propertyTextures")
        elif self.mode == Mode.EXT_FEATURE_METADATA:
            self.propertyTables = PropertyTables(self.doc, "featureTables")
            self.propertyTextures = PropertyTables(self.doc, "featureTextures")


    def loadAllBuffers(self):
        if "buffers" in self.doc:
            datauriRegexp = r'data:[^;]*;base64,(.*)'
            for buffer in self.doc["buffers"]:
                if "uri" in buffer:
                    match = re.match(datauriRegexp, buffer["uri"])
                    if match:
                        if match.group(1):
                            data = base64.standard_b64decode(match.group(1))
                            self.buffers.append(data)
                    else:
                        with open(os.path.join(self.basePath, buffer["uri"]), "rb") as file:
                            self.buffers.append(file.read())

    def getFeatureTable(self, ftName):
        return self.propertyTables.getNamedTable(ftName)

    def getFeatureTableNames(self):
        return self.propertyTables.getTableNames()

    def getFeatureTextureNames(self):
        return self.propertyTextures.getTableNames()

    def getPropertyTables(self):
        return self.propertyTables

    def getFeatureTablePropertyNames(self, ftName):
        return self.propertyTables.getNamedTable(ftName)["properties"].keys()

    def getAllFeatureTablePropertyValues(self, ftName, filterPropName=None):
        result = {}
        foundTable = False
        for num, table in enumerate(self.propertyTables):
            #logging.debug(f'[{num}: ftName: {ftName} Proptable: {table}')
            if table["name"] == ftName:
                foundTable = True
                #logging.debug(f'Proptable: {table}')
                for propName in table["properties"]:
                    if filterPropName is not None and propName != filterPropName:
                        continue
                    result[propName] = self.getFeatureTablePropertyValues(
                        ftName, propName)
        # logging.debug(result)
        if not foundTable:
            raise Exception(f'There is no table with name \'{ftName}\'')

        return result

    def getAllFeatureTexturePropertyValues(self, ftxName, filterPropName=None):
        result = {}
        foundTexture = False
        for num, texture in enumerate(self.propertyTextures):
            logging.debug(f'[{num}: ftxName: {ftxName} Proptexture: {texture}')
            if texture["name"] == ftxName:
                foundTexture = True
                for propName in texture["properties"]:
                    if filterPropName is not None and propName != filterPropName:
                        continue
                    result[propName] = self.getFeatureTexturePropertyValues(
                        ftxName, propName)
        # logging.debug(result)
        if not foundTexture:
            raise Exception(f'There is no texture with name \'{ftxName}\'')

        return result

    def getFeatureTexturePropertyValues(self, ftxName, propName):
        ftx = self.propertyTextures.getNamedTable(ftxName)
        #logging.debug(f'featureTexture: {ftx} propName: {propName}')
        if self.mode is Mode.EXT_FEATURE_METADATA:
            texture = self.doc["textures"][ftx["properties"]
                                           [propName]["texture"]["index"]]
        elif self.mode is Mode.EXT_STRUCTURAL_METADATA:
            texture = self.doc["textures"][ftx["properties"]
                                           [propName]["index"]]
        # logging.debug(texture)

        classes = self.getClasses()
        className = ftx["class"]
        propClassDef = classes[className]["properties"][propName]
        #propType = propClassDef["type"]
        componentType = propClassDef["componentType"]
        values = []

        image = self.doc["images"][texture["source"]]
        if "bufferView" in image:
            bufferView = self.doc["bufferViews"][image["bufferView"]]
            # logging.info(bufferView)
            # if bufferView["buffer"] != 0:
            #    raise NotImplementedError(
            #        f'Only buffer 0 is supported, bufferView: {bufferView}')
            buffer = self.buffers[bufferView["buffer"]]
            data = buffer[bufferView["byteOffset"]:bufferView["byteOffset"] + bufferView["byteLength"]]
            dims = imgutils.getImageDims(data, image["mimeType"])
            logging.debug(
                f'Image dims: {dims} mimeType: {image["mimeType"]} len: {len(data)}')
            if dims[0] * dims[1] > 256:
                logging.warning(
                    f'{ftxName} has too many values to print, {dims[0] * dims[1]}')
                return
            logging.debug(
                f'Channels: {ftx["properties"][propName]["channels"]}')

            try:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                imchan = im.getchannel(
                    ftx["properties"][propName]["channels"][0])
                for x in range(0, im.width):
                    for y in range(0, im.height):
                        logging.info(f'[{x}, {y}]: {imchan.getpixel((x,y))}')
            except ImportError:
                logging.error(
                    "Extraction of property texture values requires the Pillow module.")
                logging.error(
                    "To install: python3 -m pip install Pillow --user")
        elif "uri" in image:
            if isDataUri(image["uri"]):
                data = decodeDataUri(image["uri"])
                dims = imgutils.getImageDims(data, image["mimeType"])
                logging.debug(
                    f'Image dims: {dims} mimeType: {image["mimeType"]} len: {len(data)}')
                # if dims[0] * dims[1] > 32:
                #    logging.warning(
                #        f'{ftxName}:{propName} has too many values to print, {dims[0] * dims[1]}')
                #    return
                logging.debug(
                    f'Channels: {ftx["properties"][propName]["channels"]}')

                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(data))
                    imchan = im.getchannel(
                        ftx["properties"][propName]["channels"][0])
                    logging.info(
                        f'{propName} (channel {ftx["properties"][propName]["channels"][0]}) (only showing 4x4 pixels):')
                    denormalize = False
                    offset = 0
                    scale = 1
                    if "offset" in propClassDef:
                        offset = propClassDef["offset"]
                    if "scale" in propClassDef:
                        scale = propClassDef["scale"]
                    if "normalized" in propClassDef:
                        denormalize = propClassDef["normalized"]
                    if offset != 0 or scale != 1 or denormalize:
                        for x in range(0, min(4, im.width)):
                            row = []
                            for y in range(0, min(4, im.height)):
                                val = imchan.getpixel((x, y))
                                #logging.info(f'[{x}, {y}]: {val}')
                                row.append(applyOffsetScale(
                                    componentType, val, offset, scale, denormalize))
                            values.append(row)
                    else:
                        for x in range(0, min(4, im.width)):
                            row = []
                            for y in range(0, min(4, im.height)):
                                val = imchan.getpixel((x, y))
                                logging.info(f'[{x}, {y}]: {val}')
                                row.append(val)
                            values.append(row)
                except ImportError:
                    logging.error(
                        "Extraction of property texture values requires the Pillow module.")
                    logging.error(
                        "To install: python3 -m pip install Pillow --user")
            else:
                logging.error('External FeatureTextures not implemented')
                logging.debug(image)
        return values

    def getClasses(self):
        schema = self.getSchema()
        if schema is not None and "classes" in schema:
            return schema["classes"]
        return {}

    def getSchema(self):
        if self.mode is Mode.EXT_STRUCTURAL_METADATA:
            return self.doc["extensions"]["EXT_structural_metadata"]["schema"]
        elif self.mode == Mode.EXT_FEATURE_METADATA:
            return self.doc["extensions"]["EXT_feature_metadata"]["schema"]

    def getEnums(self):
        schema = self.getSchema()
        if schema is not None and "enums" in schema:
            return self.getSchema()["enums"]
        return {}

    def readScalarValues(self, propType, count, data):
        #typeByteSize = componentTypeSizeInBytes(propType)
        #if len(data) > count * typeByteSize:
        #    # struct.unpack will fail if the size is not correct...
        #    logging.warning(f'Type: {propType} shrinking buffer from {len(data)} to {count * typeByteSize}')
        #    data = data[0:count * typeByteSize]
        try:
            values = []
            if propType == 'UINT8':
                values = struct.unpack('<' + str(count) + 'B', data)
            elif propType == 'INT8':
                values = struct.unpack('<' + str(count) + 'b', data)
            elif propType == 'UINT16':
                values = struct.unpack('<' + str(count) + 'H', data)
            elif propType == 'INT16':
                values = struct.unpack('<' + str(count) + 'h', data)
            elif propType == 'UINT32':
                values = struct.unpack('<' + str(count) + 'I', data)
            elif propType == 'INT32':
                values = struct.unpack('<' + str(count) + 'i', data)
            elif propType == 'UINT64':
                values = struct.unpack('<' + str(count) + 'Q', data)
            elif propType == 'INT64':
                values = struct.unpack('<' + str(count) + 'q', data)
            elif propType == 'FLOAT32':
                values = struct.unpack('<' + str(count) + 'f', data)
            elif propType == 'FLOAT64':
                values = struct.unpack('<' + str(count) + 'd', data)
            else:
                raise ValueError(f'Unhandled scalar type: {propType}')
        except struct.error as e:
            logging.debug(f'propType: {propType} count: {count} data: {data} len(data): {len(data)}')
            raise e
        return values

    def readFixedSizeArrayValues(self, componentType, arrayCount, componentCount, data):
        values = []
        componentByteSize = componentTypeSizeInBytes(componentType)
        #logging.error(f'componentType: {componentType} componentByteSize: {componentByteSize}')
        elementSize = componentByteSize * componentCount
        #logging.info(f'elementSize: {elementSize} bufferByteLength: {len(data)}')
        if len(data) / elementSize < arrayCount:
            raise Exception(
                f'Array buffer too short, expected {arrayCount*elementSize} but got {len(data)} bytes.')
        #numArrayItems = int(bufferByteLength / elementSize)
        for i in range(0, arrayCount):
            rawbytes = data[i * elementSize:((i + 1) * elementSize)]
            #logging.info(f'rawbytes; {rawbytes}')
            if componentType == "INT8":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "b", rawbytes))
            elif componentType == "UINT8":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "B", rawbytes))
            elif componentType == "INT16":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "h", rawbytes))
            elif componentType == "UINT16":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "H", rawbytes))
            elif componentType == "INT32":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "i", rawbytes))
            elif componentType == "UINT32":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "I", rawbytes))
            elif componentType == "INT64":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "q", rawbytes))
            elif componentType == "UINT64":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "Q", rawbytes))
            elif componentType == "FLOAT32":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "f", rawbytes))
            elif componentType == "FLOAT64":
                values.append(struct.unpack(
                    "<" + str(componentCount) + "d", rawbytes))
            else:
                logging.error(
                    f'Unhandled array componentType {componentType}, skipping...')
        return values

    def readDynamicSizeArrayValues(self, propType, componentType, arrayOffsets=None, stringOffsets=None, data=None):
        if arrayOffsets is None:
            raise ValueError('arrayOffsets missing, got None')
        if data is None:
            raise ValueError('binary data missing, got None')
        values = []

        for i in range(0, len(arrayOffsets) - 1, 1):
            if propType == "STRING":
                if stringOffsets is None:
                    raise ValueError('stringOffsets missing, got None')
                numStrings = arrayOffsets[i + 1] - arrayOffsets[i]
                arrayItem = []
                for j in range(0, numStrings):
                    rawbytes = data[stringOffsets[arrayOffsets[i] + j]:stringOffsets[arrayOffsets[i] + j + 1]]
                    arrayItem.append(rawbytes.decode("utf8"))
                values.append(arrayItem)
            else:
                #logging.debug(f'arrayOffsets: {arrayOffsets} data: {data}')
                rawbytes = data[arrayOffsets[i]:arrayOffsets[i+1]]
                #logging.debug(f'componentType: {componentType} rawbytes: {rawbytes} len: {len(rawbytes)} i: {i} arrayOffset[i]: {arrayOffsets[i]} arrayOffset[i+1]: {arrayOffsets[i+1]}')
                typeByteSize = componentTypeSizeInBytes(componentType)
                componentCount = len(rawbytes) // typeByteSize
                values.append(self.readScalarValues(
                    componentType, componentCount, rawbytes))
        return values

    def getFeatureTablePropertyValues(self, ftName, propName):
        if ftName is None:
            if len(self.propertyTables) > 0:
                ftName = self.propertyTables.getTableName(0)
                logging.warning(
                    f'No FeatureTable name specified. Using first FeatureTable \'{ftName}\'')
        props = self.getFeatureTablePropertyNames(ftName)
        if propName not in props:
            raise Exception(
                f'Property {propName} not found in FeatureTable {ftName}')
        featureTable = self.propertyTables.getNamedTable(ftName)
        classes = self.getClasses()
        enums = self.getEnums()
        className = featureTable["class"]

        compatMap = {}

        if self.mode is Mode.EXT_FEATURE_METADATA:
            compatMap["bufferView"] = "bufferView"
            compatMap["stringOffsetBufferView"] = "stringOffsetBufferView"
            compatMap["arrayOffsetBufferView"] = "stringOffsetBufferView"
            compatMap["componentCount"] = "componentCount"
        elif self.mode is Mode.EXT_STRUCTURAL_METADATA:
            compatMap["bufferView"] = "values"
            compatMap["stringOffsetBufferView"] = "stringOffsets"
            compatMap["arrayOffsetBufferView"] = "arrayOffsets"
            compatMap["componentCount"] = "count"
        else:
            raise Exception('Unhandled metadata mode')

        bufferView = featureTable["properties"][propName][compatMap["bufferView"]]
        propType = None
        try:
            propType = classes[className]["properties"][propName]["type"]
            #logging.debug(f'{propName}: value type is {propType}')
        except Exception:
            logging.error(self.doc)
            raise Exception(
                f'prop: {propName} className: {className} classes: {classes}')

        buffer = self.buffers[self.doc["bufferViews"][bufferView]["buffer"]]
        bufferByteOffset = 0
        if "byteOffset" in self.doc["bufferViews"][bufferView]:
            bufferByteOffset = self.doc["bufferViews"][bufferView]["byteOffset"]
        bufferByteLength = self.doc["bufferViews"][bufferView]["byteLength"]

        isArrayProp = (self.mode == Mode.EXT_STRUCTURAL_METADATA and "array" in classes[className]["properties"][propName] and classes[className]["properties"][propName]["array"]) or (
            self.mode == Mode.EXT_FEATURE_METADATA and propType == "ARRAY")
        if isArrayProp:
            isFixedSizeArray = compatMap["componentCount"] in classes[className]["properties"][propName]
            if isFixedSizeArray:
                componentCount = classes[className]["properties"][propName][compatMap["componentCount"]]
                # logging.error(classes[className]["properties"][propName])
                if "componentType" in classes[className]["properties"][propName]:
                    componentType = classes[className]["properties"][propName]["componentType"]
                else:
                    if propType == 'BOOLEAN':
                        #logging.info(f'Read {componentCount * featureTable["count"]} BOOLEAN values ({math.ceil(featureTable["count"] * componentCount / 8)} bytes) from bufferView: {self.doc["bufferViews"][bufferView]}')
                        byteCount = math.ceil(
                            featureTable["count"] * componentCount / 8)
                        byteValues = struct.unpack(
                            '<' + str(byteCount) + 'B', buffer[bufferByteOffset:bufferByteOffset+min(byteCount, bufferByteLength)])
                        #logging.debug(f'byteValues: {byteValues}')
                        values = []
                        for i in range(0, featureTable["count"]):
                            componentValues = []
                            for j in range(0, componentCount):
                                byteIndex = (i*componentCount+j)//8
                                bitIndex = (i*componentCount+j) % 8
                                #logging.debug(f'i={i} j={j}: byteIndex: {byteIndex} bitIndex: {bitIndex} rawbits: {bin(byteValues[byteIndex])}')
                                val = (
                                    (byteValues[byteIndex] >> bitIndex) & 1) == 1
                                #logging.debug(f'{i}: {val}')
                                componentValues.append(val)
                            values.append(componentValues)
                        return values
                    elif propType == 'ENUM':
                        enumType = classes[className]["properties"][propName]["enumType"]
                        if enumType not in enums:
                            raise Exception(f'{enumType} not found in schema')
                        enumSchema = enums[enumType]
                        valueToEnumMap = {}
                        for item in enumSchema["values"]:
                            valueToEnumMap[item["value"]] = item["name"]
                        # logging.debug(valueToEnumMap)
                        enumValueType = 'UINT16'  # default type
                        if "valueType" in enumSchema:
                            enumValueType = enumSchema["valueType"]
                        enumValues = self.readFixedSizeArrayValues(
                            enumValueType, featureTable["count"], componentCount, buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])
                        values = []
                        for arrayValue in enumValues:
                            componentValue = []
                            for itemValue in arrayValue:
                                componentValue.append(
                                    valueToEnumMap[itemValue])
                            values.append(componentValue)
                        return values
                if self.mode == Mode.EXT_STRUCTURAL_METADATA:
                    logging.error(
                        f'ComponentCount {componentCount} type: {propType}')
                    componentCount = componentCount * \
                        getComponentCount(propType)

                values = self.readFixedSizeArrayValues(
                    componentType, featureTable["count"], componentCount, buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])
                if componentType != "STRING" and componentType != "BOOLEAN":
                    offset = 0
                    scale = 1
                    denormalize = False
                    if "offset" in classes[className]["properties"][propName]:
                        offset = classes[className]["properties"][propName]["offset"]
                    if "scale" in classes[className]["properties"][propName]:
                        scale = classes[className]["properties"][propName]["scale"]
                    if "normalized" in classes[className]["properties"][propName]:
                        denormalize = classes[className]["properties"][propName]["normalized"]
                    if offset != 0 or scale != 1 or denormalize != False:
                        newvalues = []
                        for arrayVal in values:
                            componentValue = []
                            for i, value in enumerate(arrayVal):
                                #logging.debug(f'Value: {value} unpacked: {applyOffsetScale(componentType, value, offset, scale, denormalize)}')
                                componentValue.append(applyOffsetScale(
                                    componentType, value, offset, scale, denormalize))
                            newvalues.append(componentValue)
                        return newvalues
                return values
            else:
                #logging.error(f'Handling dynamic arrays...')
                arrayOffsetType = 'UINT32'
                if "arrayOffsetType" in featureTable["properties"][propName]:
                    arrayOffsetType = featureTable["properties"][propName]["arrayOffsetType"]
                arrayOffsetBufferView = featureTable["properties"][propName][compatMap["arrayOffsetBufferView"]]
                arrayOffsetBuffer = self.buffers[self.doc["bufferViews"]
                                                 [arrayOffsetBufferView]["buffer"]]
                arrayOffsetStart = 0
                if "byteOffset" in self.doc["bufferViews"][arrayOffsetBufferView]:
                    arrayOffsetStart = self.doc["bufferViews"][arrayOffsetBufferView]["byteOffset"]
                arrayOffsetLen = self.doc["bufferViews"][arrayOffsetBufferView]["byteLength"]
                arrayOffsets = self.readScalarValues(
                    arrayOffsetType, featureTable["count"] + 1, arrayOffsetBuffer[arrayOffsetStart:arrayOffsetStart + arrayOffsetLen])
                #logging.debug(f'ArrayOffsets: {arrayOffsets}')
                bufferByteOffset = self.doc["bufferViews"][bufferView]["byteOffset"]
                bufferByteLength = self.doc["bufferViews"][bufferView]["byteLength"]

                stringOffsets = None
                if propType == "STRING":
                    stringOffsetType = 'UINT32'
                    if "stringOffsetType" in featureTable["properties"][propName]:
                        stringOffsetType = featureTable["properties"][propName]["stringOffsetType"]
                    stringOffsetBufferView = featureTable["properties"][
                        propName][compatMap["stringOffsetBufferView"]]
                    stringOffsetBuffer = self.buffers[self.doc["bufferViews"]
                                                      [stringOffsetBufferView]["buffer"]]
                    stringOffsetStart = 0
                    if "byteOffset" in self.doc["bufferViews"][stringOffsetBufferView]:
                        stringOffsetStart = self.doc["bufferViews"][stringOffsetBufferView]["byteOffset"]
                    stringOffsetLen = self.doc["bufferViews"][stringOffsetBufferView]["byteLength"]
                    stringOffsetCount = stringOffsetLen // componentTypeSizeInBytes(
                        stringOffsetType)
                    stringOffsets = self.readScalarValues(
                        stringOffsetType, stringOffsetCount, stringOffsetBuffer[stringOffsetStart:stringOffsetStart + stringOffsetLen])
                    #logging.debug(f'StringOffsets: {stringOffsets}')

                componentType = None
                if "componentType" in classes[className]["properties"][propName]:
                    componentType = classes[className]["properties"][propName]["componentType"]
                
                if componentType == 'ENUM':
                    enumType = classes[className]["properties"][propName]["enumType"]
                    if enumType not in enums:
                        raise Exception(f'{enumType} not found in schema')
                    enumSchema = enums[enumType]
                    valueToEnumMap = {}
                    for item in enumSchema["values"]:
                        valueToEnumMap[item["value"]] = item["name"]
                    logging.debug(valueToEnumMap)
                    enumValueType = 'UINT16'  # default type
                    if "valueType" in enumSchema:
                        enumValueType = enumSchema["valueType"]
                    enumValues = self.readDynamicSizeArrayValues(
                        propType, enumValueType, arrayOffsets, stringOffsets, buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])
                    values = []
                    for arrayValue in enumValues:
                        componentValue = []
                        for itemValue in arrayValue:
                            componentValue.append(
                                valueToEnumMap[itemValue])
                        values.append(componentValue)
                    return values
                else:
                    values = self.readDynamicSizeArrayValues(
                        propType, componentType, arrayOffsets, stringOffsets, buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])

                if componentType != "STRING" and componentType != "BOOLEAN":
                    offset = 0
                    scale = 1
                    denormalize = False
                    if "offset" in classes[className]["properties"][propName]:
                        offset = classes[className]["properties"][propName]["offset"]
                    if "scale" in classes[className]["properties"][propName]:
                        scale = classes[className]["properties"][propName]["scale"]
                    if "normalized" in classes[className]["properties"][propName]:
                        denormalize = classes[className]["properties"][propName]["normalized"]
                    if offset != 0 or scale != 1 or denormalize != False:
                        newvalues = []
                        for arrayVal in values:
                            componentValue = []
                            for i, value in enumerate(arrayVal):
                                #logging.debug(f'Value: {value} unpacked: {applyOffsetScale(componentType, value, offset, scale, denormalize)}')
                                componentValue.append(applyOffsetScale(
                                    componentType, value, offset, scale, denormalize))
                            newvalues.append(componentValue)
                        return newvalues
                return values
        elif propType == 'BOOLEAN':
            #logging.info(f'Read {featureTable["count"]} BOOLEAN values ({math.ceil(featureTable["count"]/8)} bytes) from bufferView: {self.doc["bufferViews"][bufferView]}')
            byteCount = math.ceil(featureTable["count"]/8)
            byteValues = struct.unpack('<' + str(byteCount) + 'B', buffer[self.doc["bufferViews"][bufferView]
                                                                          ["byteOffset"]:self.doc["bufferViews"][bufferView]["byteOffset"]+min(byteCount, self.doc["bufferViews"][bufferView]["byteLength"])])
            #logging.debug(f'byteValues: {byteValues}')
            values = []
            for i in range(0, featureTable["count"]):
                byteIndex = i//8
                bitIndex = i % 8
                #logging.debug(f'{i}: byteIndex: {byteIndex} bitIndex: {bitIndex}')
                val = ((byteValues[byteIndex] >> bitIndex) & 1) == 1
                #logging.debug(f'{i}: {val}')
                values.append(val)
            return values
        elif propType == 'ENUM':
            enumType = classes[className]["properties"][propName]["enumType"]
            if enumType not in enums:
                raise Exception(f'{enumType} not found in schema')
            enumSchema = enums[enumType]
            enumValueType = 'UINT16'  # default type
            if "valueType" in enumSchema:
                enumValueType = enumSchema["valueType"]
            enumValues = self.readScalarValues(
                enumValueType, featureTable["count"], buffer[bufferByteOffset:bufferByteOffset + bufferByteLength])
            valueToEnumMap = {}
            for item in enumSchema["values"]:
                valueToEnumMap[item["value"]] = item["name"]
            #logging.debug(f'valueToEnumMap: {valueToEnumMap}')
            #logging.debug(f'EnumSchema: {enumSchema}')
            #logging.debug(f'enumValues: {enumValues}')
            values = []
            for itemValue in enumValues:
                values.append(valueToEnumMap[itemValue])
            return values
        elif propType == 'INT32':
            #logging.info(f'Read {featureTable["count"]} INT32 values from bufferView: {self.doc["bufferViews"][bufferView]}')
            return struct.unpack('<' + str(featureTable["count"]) + 'i', buffer[self.doc["bufferViews"][bufferView]["byteOffset"]:self.doc["bufferViews"][bufferView]["byteOffset"]+self.doc["bufferViews"][bufferView]["byteLength"]])
        elif propType == 'UINT32':
            #logging.info(f'Read {featureTable["count"]} UINT32 values from bufferView: {self.doc["bufferViews"][bufferView]}')
            values = struct.unpack('<' + str(featureTable["count"]) + 'I', buffer[self.doc["bufferViews"][bufferView]
                                   ["byteOffset"]:self.doc["bufferViews"][bufferView]["byteOffset"]+self.doc["bufferViews"][bufferView]["byteLength"]])
            return values
        elif propType == 'UINT8':
            #logging.info(f'Read {featureTable["count"]} UINT8 values from bufferView: {self.doc["bufferViews"][bufferView]}')
            values = struct.unpack('<' + str(featureTable["count"]) + 'B', buffer[self.doc["bufferViews"][bufferView]
                                   ["byteOffset"]:self.doc["bufferViews"][bufferView]["byteOffset"]+self.doc["bufferViews"][bufferView]["byteLength"]])
            return values
        elif propType == 'FLOAT32':
            #logging.info(f'Read {featureTable["count"]} FLOAT32 values from bufferView: {self.doc["bufferViews"][bufferView]}')
            values = struct.unpack('<' + str(featureTable["count"]) + 'f', buffer[self.doc["bufferViews"][bufferView]
                                   ["byteOffset"]:self.doc["bufferViews"][bufferView]["byteOffset"]+self.doc["bufferViews"][bufferView]["byteLength"]])
            return values
        elif propType == 'STRING':
            if "offsetType" in featureTable["properties"][propName]:
                if featureTable["properties"][propName]["offsetType"] != "UINT32":
                    raise Exception(
                        f'Unhandled offsetType: {featureTable["properties"][propName]["offsetType"]}')
            try:
                stringOffsetBufferView = featureTable["properties"][propName][compatMap["stringOffsetBufferView"]]
                stringOffsetBuffer = self.buffers[self.doc["bufferViews"]
                                                  [stringOffsetBufferView]["buffer"]]
                buffer = self.buffers[self.doc["bufferViews"]
                                      [bufferView]["buffer"]]
                #logging.info(f'stringOffsetBufferView: {stringOffsetBufferView}')
                start = self.doc["bufferViews"][stringOffsetBufferView]["byteOffset"]
                length = self.doc["bufferViews"][stringOffsetBufferView]["byteLength"]
                #logging.info(f'string offset start: {start} length: {length} count: {featureTable["count"]} buffersLength: {len(self.buffers)}')
                typeBytesize = 4  # UINT32
                numOffsets = featureTable["count"] + 1
                # if more data than is needed, trim buffer
                values = []
                if length > numOffsets * typeBytesize:
                    # offsets are 8 byte aligned, so need to trim the padding due to how struct.unpack works
                    #logging.warning(f'filename: {filename} prop: {propName} has stringOffsetBufferView with byteLength {length}, expected {(featureTable["count"]+1) * typeBytesize}.')
                    length = (featureTable["count"]+1) * typeBytesize
                stringOffsets = struct.unpack(
                    "<" + str(numOffsets) + "I", stringOffsetBuffer[start:start+length])
                #logging.info(f'stringoffsets: {stringOffsets}')
                bufferByteOffset = self.doc["bufferViews"][bufferView]["byteOffset"]
                bufferByteLength = self.doc["bufferViews"][bufferView]["byteLength"]
                for i in range(0, len(stringOffsets)-1, 1):
                    rawbytes = buffer[bufferByteOffset +
                                      stringOffsets[i]:bufferByteOffset+stringOffsets[i+1]]
                    #logging.info(f'{i} of {len(stringOffsets)}: {rawbytes}')
                    values.append(rawbytes.decode("utf8"))
                    #logging.info(f'{i}: {string}')
                #logging.info(f'Read {featureTable["count"]} STRING values from bufferView: {self.doc["bufferViews"][bufferView]}')
                return values
            except Exception as e:
                raise Exception(
                    f'prop: {propName}, count: {featureTable["count"]} stringOffsetBufferView: {self.doc["bufferViews"][stringOffsetBufferView]} error: {e}')
                #logging.info(f'{propName} stringoffsets {i}: {stringOffsets} {stringOffsets[i]}, error: {e}')
        elif self.mode is Mode.EXT_STRUCTURAL_METADATA:
            componentCount = 0
            componentType = classes[className]["properties"][propName]["componentType"]
            if propType == 'SCALAR':
                return self.readScalarValues(componentType, featureTable["count"], buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])
            elif propType == 'VEC2':
                componentCount = 2
            elif propType == 'VEC3':
                componentCount = 3
            elif propType == 'VEC4':
                componentCount = 4
            elif propType == 'MAT2':
                componentCount = 4
            elif propType == 'MAT3':
                componentCount = 9
            elif propType == 'MAT4':
                componentCount = 16
            else:
                raise Exception(f'Unhandled property type: {propType}')

            #logging.error(f'ComponentCount {componentCount} type: {propType}')

            return self.readFixedSizeArrayValues(componentType, featureTable["count"], componentCount, buffer[bufferByteOffset:bufferByteOffset+bufferByteLength])
        else:
            logging.error(f'Unhandled type {propType}, skipping...')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--pretty', dest='prettyPrint',
                        action='store_true', help='Prett-print the JSON output')
    parser.add_argument('--no-pretty', dest='prettyPrint',
                        action='store_false', help='Don\'t pretty-print the JSON output')
    parser.set_defaults(prettyPrint=True)
    parser.add_argument('filepath', help='Path to gltf or glb file')
    try:
        args = parser.parse_args()
    except Exception:
        parser.print_help()
        exit(0)

    with open(args.filepath, "rb") as file:
        basepath = os.path.dirname(os.path.abspath(args.filepath))
        gltf = GltfDocument(file.read(), basepath)
        glbjson.printJson(gltf.doc, args.prettyPrint)
