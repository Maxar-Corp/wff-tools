#!/usr/bin/env python3

# Copyright 2021-2022, Maxar Technologies
# Written by erik.dahlstrom@maxar.com, bjorn.blissing@maxar.com

import sys
import os
import pathlib
import json
import argparse
import archive3tz as archive
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
import logging
import re
import index3tz
from string import Template


def getScriptPath():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def applyTemplate(templatePath, rootTilesetUri):
    template = bytes()
    with open(templatePath, mode='r') as file:
        content = Template(file.read())
        replaced = content.safe_substitute(rootTilesetUri=rootTilesetUri)
        template += bytes(replaced, "UTF-8")
    return template


def contentTypeFromFileExtension(fileExtension):
    contentTypes = {
        '.js': 'application/javascript',
        '.css': 'text/css',
        '.json': 'application/json',
        '.geojson': 'application/geo+json',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.ktx2': 'image/ktx2',
        '.html': 'text/html',
        '.ico': 'image/x-icon'
    }
    return contentTypes.get(fileExtension, 'application/octet-stream')


def isAcceptedContentEncoding(headers, contentEncoding):
    if not headers:
        return False
    acceptHeader = headers.get_all("Accept-Encoding")
    if not acceptHeader:
        return False
    accepted = set()
    for header in acceptHeader:
        accepted.update(
            encoding.strip().split(";", 1)[0]
            for encoding in header.split(",")
        )
    logging.debug(f'Client accepts encoding(s): {accepted}')
    return contentEncoding in accepted


def isTerrainPack(filepath):
    if not filepath.endswith(".json"):
        return False
    try:
        with open(filepath) as file:
            parsed = json.load(file)
            if "extensionsRequired" in parsed:
                if "MAXAR_content_3tz" in parsed["extensionsRequired"]:
                    return True
    except Exception:
        # logging.error(f'isTerrainPack error, {e}', e)
        return False
    return False


def rewriteTerrainPack(filepath):
    try:
        regExp3tz = r'\"([^\"]*\.3tz)\"'
        with open(filepath, "r") as file:
            contents = file.read()
            doc = json.loads(contents)
            if "MAXAR_content_3tz" in doc["extensionsRequired"]:
                doc["extensionsRequired"].remove("MAXAR_content_3tz")
            if "MAXAR_content_3tz" in doc["extensionsUsed"]:
                doc["extensionsUsed"].remove("MAXAR_content_3tz")
            if "tile" not in doc["extensions"]["3DTILES_metadata"]["schema"]["classes"]:
                logging.error('No \"tile\" class definition...')
                doc["extensions"]["3DTILES_metadata"]["schema"]["classes"]["tile"] = json.loads("""
          {
              "properties": {
                "max_height": {
                  "name": "Maximum Tile Height",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "TILE_MAXIMUM_HEIGHT"
                },
                "min_height": {
                  "name": "Minimum Tile Height",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "TILE_MINIMUM_HEIGHT"
                },
                "texture_resolution": {
                  "name": "Estimated Texture Resolution",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "MAXAR_TEXTURE_RESOLUTION"
                }
              }
          }""")
            newcontents = re.sub(
                regExp3tz, "\"\\1/tileset.json\"", json.dumps(doc))
            if newcontents:
                return bytes(newcontents, "utf-8")
    except Exception:
        logging.error('Rewrite terrainpack error')
        return bytes()
    return bytes()


def rewriteTerrainPackDropVectorLayers(filepath):
    try:
        regExp3tz = r'\"([^\"]*\.3tz)\"'
        with open(filepath, "r") as file:
            contents = file.read()
            doc = json.loads(contents)
            if "MAXAR_content_3tz" in doc["extensionsRequired"]:
                doc["extensionsRequired"].remove("MAXAR_content_3tz")
            if "MAXAR_content_3tz" in doc["extensionsUsed"]:
                doc["extensionsUsed"].remove("MAXAR_content_3tz")
            meshGroups = []
            for group in doc["extensions"]["3DTILES_metadata"]["groups"]:
                contentType = doc["extensions"]["3DTILES_metadata"]["groups"][group]["properties"]["content_type"]
                # logging.error(f'Found group: {group} {contentType}')
                if contentType == "MESH":
                    meshGroups.append(group)
            doc["root"]["children"] = list(filter(
                lambda child: child["content"]["extensions"]["3DTILES_metadata"]["group"] in meshGroups, doc["root"]["children"]))
            if "tile" not in doc["extensions"]["3DTILES_metadata"]["schema"]["classes"]:
                logging.error('No \"tile\" class definition...')
                doc["extensions"]["3DTILES_metadata"]["schema"]["classes"]["tile"] = json.loads("""
          {
              "properties": {
                "max_height": {
                  "name": "Maximum Tile Height",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "TILE_MAXIMUM_HEIGHT"
                },
                "min_height": {
                  "name": "Minimum Tile Height",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "TILE_MINIMUM_HEIGHT"
                },
                "texture_resolution": {
                  "name": "Estimated Texture Resolution",
                  "type": "FLOAT32",
                  "optional": true,
                  "semantic": "MAXAR_TEXTURE_RESOLUTION"
                }
              }
          }""")
            contents = json.dumps(doc)
            newcontents = re.sub(regExp3tz, "\"\\1/tileset.json\"", contents)
            if newcontents:
                return bytes(newcontents, "utf-8")
    except Exception:
        logging.error('Rewrite terrainpack error')
        return bytes()
    return bytes()


def stripMaxarContent3tz(fileContents):
    if fileContents is not None:
        try:
            if fileContents.compMethod != archive.ZIP_COMPRESSION_METHOD_STORE:
                # logging.warning(f'Server handling decompression, compMethod: {int.from_bytes(fileContents.compMethod, byteorder="little")}')
                # logging.debug(fileContents.data)
                tmp = archive.decompressFileContents(
                    fileContents.compMethod, fileContents.uncompSize, fileContents.data)
                fileContents.data = tmp

            doc = json.loads(fileContents.data)
            if "MAXAR_content_3tz" in doc["extensionsRequired"]:
                doc["extensionsRequired"].remove("MAXAR_content_3tz")
            if "MAXAR_content_3tz" in doc["extensionsUsed"]:
                doc["extensionsUsed"].remove("MAXAR_content_3tz")
            fileContents.data = bytes(json.dumps(doc), "utf-8")
            fileContents.compMethod = archive.ZIP_COMPRESSION_METHOD_STORE
            return fileContents
        except Exception as e:
            logging.error(f'Strip MAXAR_content_3tz failed: {e}')
            return None
    return None


class ServeFromDirectoryHandler(BaseHTTPRequestHandler):
    def __init__(self, filepath, resourcepath, rootTilesetPath, templatefilename, stripVectorLayers):
        self.archives = dict()
        self.regExp3tz = r"(.*\.3tz)[\/]?(.*)"
        self.resourcepath = resourcepath
        self.directory = filepath
        self.rootTilesetPath = rootTilesetPath
        rtp = pathlib.PurePath(rootTilesetPath)
        self.cesiumRootTilesetPath = rtp.with_name("cesium_" + rtp.name)
        self.templatefilename = templatefilename
        self.stripVectorLayers = stripVectorLayers

    def __call__(self, *args, **kwargs):
        """ Handle a request """
        super().__init__(*args, **kwargs)

    def getFile(self, path):
        cesiumRootFullPath = os.path.join(
            self.directory, self.cesiumRootTilesetPath)
        wasCesiumRoot = (path == cesiumRootFullPath)
        if wasCesiumRoot:
            path = os.path.join(self.directory, self.rootTilesetPath)
        match = re.match(self.regExp3tz, path)
        logging.debug(f"GetFile {path} matched: {match}")
        if match:
            innerPath = match.group(2)
            if not innerPath:
                innerPath = "tileset.json"
            if match.group(1) in self.archives:
                logging.debug(
                    f'Fetching {innerPath} from open archive {match.group(1)}')
                return self.archives[match.group(1)].getFile(innerPath)
            path3tz = match.group(1)
            self.archives[path3tz] = Single3tzArchive(path3tz)
            return self.archives[path3tz].getFile(innerPath)
        elif os.path.isfile(path):
            if isTerrainPack(path):
                if wasCesiumRoot and self.stripVectorLayers:
                    filecontents = rewriteTerrainPackDropVectorLayers(path)
                else:
                    filecontents = rewriteTerrainPack(path)
                return FileContents(filecontents, contentTypeFromFileExtension(pathlib.PurePath(path).suffix), archive.ZIP_COMPRESSION_METHOD_STORE, len(filecontents))
            with open(path, mode='rb') as file:
                filecontents = file.read()
                return FileContents(filecontents, contentTypeFromFileExtension(pathlib.PurePath(path).suffix), archive.ZIP_COMPRESSION_METHOD_STORE, len(filecontents))
        return None

    def do_GET(self):
        try:
            if self.path == '/':
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(bytes('<!doctype html>', 'utf-8'))
                self.wfile.write(bytes(
                    '<meta charset="UTF-8"><meta http-equiv="X-UA-Compatible" content="IE=edge"><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, minimum-scale=1, user-scalable=no">', 'utf-8'))
                self.wfile.write(
                    bytes('<style>@import url(resources/Cesium/bucket.css);</style>', 'utf-8'))
                self.wfile.write(
                    bytes('<script src="resources/Cesium/Cesium.js"></script>', 'utf-8'))
                self.wfile.write(
                    bytes('<div id="cesiumContainer" class="fullSize"></div>', 'utf-8'))
                self.wfile.write(bytes(
                    f'<script src="resources/{self.templatefilename}" defer></script>', 'utf-8'))
                self.wfile.write(bytes('</body></html>', 'utf-8'))
            elif self.path == "/favicon.ico":
                self.send_response(200)
                self.send_header(
                    'Content-type', contentTypeFromFileExtension(pathlib.PurePath(self.path).suffix))
                self.end_headers()
                with open(os.path.join(self.resourcepath, self.path[1:]), mode='rb') as file:
                    content = file.read()
                    self.wfile.write(content)
            elif self.path.startswith('/resources/'):
                path = os.path.join(self.resourcepath, self.path[11:])
                if os.path.exists(path):
                    self.send_response(200)
                else:
                    self.send_response(404)
                self.send_header(
                    "Content-type", contentTypeFromFileExtension(pathlib.PurePath(self.path).suffix))
                self.end_headers()
                if self.path[11:] == self.templatefilename:
                    self.wfile.write(applyTemplate(
                        path, self.cesiumRootTilesetPath))
                else:
                    with open(path, mode='rb') as file:
                        content = file.read()
                        self.wfile.write(content)
            else:
                self.send_response(200)
                fullpath = os.path.join(self.directory, self.path[1:])
                file = self.getFile(fullpath)
                if file is not None:
                    if file.compMethod == archive.ZIP_COMPRESSION_METHOD_DEFLATE and isAcceptedContentEncoding(self.headers, 'deflate'):
                        self.send_header('Content-Encoding', 'deflate')
                    elif file.compMethod == archive.ZIP_COMPRESSION_METHOD_ZSTD and isAcceptedContentEncoding(self.headers, 'zstd'):
                        self.send_header('Content-Encoding', 'zstd')
                    elif file.compMethod != archive.ZIP_COMPRESSION_METHOD_STORE:
                        logging.warning(
                            f'Server handling decompression, compMethod: {int.from_bytes(file.compMethod, byteorder="little")}')
                        file.data = archive.decompressFileContents(
                            file.compMethod, file.uncompSize, file.data)
                    self.send_header('Content-type', file.contentType)
                    self.send_header('Access-Control-Allow-Headers',
                                     'Content-Type,Authorization')
                    self.send_header(
                        'Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
                    self.end_headers()
                    self.wfile.write(file.data)
                else:
                    logging.error(f'#### FAILED TO FIND path: {self.path}')
                    self.send_response(404)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
        except Exception as e:
            logging.error(
                f'#### Got exception trying to fetch {self.path}, error: {e}')


class FileContents:
    def __init__(self, data, contentType, compMethod, uncompSize):
        self.data = data
        self.contentType = contentType
        self.compMethod = compMethod
        self.uncompSize = uncompSize

    def __str__(self):
        return f'compMethod: {self.compMethod}, contentType: {self.contentType}, uncompSize: {self.uncompSize} compDataSize: {len(self.data)}'


class Single3tzArchive:
    def __init__(self, containerpath):
        try:
            self.file = open(containerpath, mode='rb')
            self.cde = archive.getLastEntryInCentralDirectory(
                self.file, containerpath)
            lfh = archive.getLocalFileHeaderFromCentralDirectoryEntry(
                self.file, self.cde)
            if lfh.get('filename') == '@3dtilesIndex1@':
                logging.debug('Reading index content')
                indexContent = archive.getFileContentsFromLocalFileHeader(
                    self.file, lfh)
                self.index = archive.readIndex(indexContent)
            else:
                logging.warning('Building 3tz index for zip file...')
                try:
                    self.index = archive.readIndex(
                        index3tz.buildIndex(containerpath))
                except Exception as e:
                    logging.error(
                        f'Failed to build index for {pathlib.PurePath(containerpath).name}, error: {e}')
                    exit(-1)
        except Exception as e:
            logging.error(f'Failed to open 3tz file, {e}', e)

    def getFile(self, path):
        if not self.index:
            return None
        offset = archive.findLocalFileHeaderOffsetInIndex(self.index, path)
        if offset is None:
            logging.error(f'File not found: {path}')
            return None

        lfh2 = archive.getLocalFileHeaderAtOffset(self.file, offset)
        fileExtension = pathlib.PurePath(lfh2.get('filename')).suffix
        if lfh2.get('filename') != path:
            logging.error(f"Expected {path} but got {lfh2.get('filename')}")
            return None

        [compMethod, uncompSize, filecontents] = archive.getRawFileContentsFromLocalFileHeader(
            self.file, lfh2)
        # logging.debug(f'path: {path} compMethod: {compMethod} uncompSize: {uncompSize}')
        contentType = contentTypeFromFileExtension(fileExtension)
        return FileContents(filecontents, contentType, compMethod, uncompSize)


class Serve3tzHandler(BaseHTTPRequestHandler):
    def __init__(self, containerpath, resourcepath, rootTilesetPath, templatefilename):
        self.rootTilesetPath = rootTilesetPath
        self.basepath = pathlib.PurePath(containerpath).name
        rootArchive = Single3tzArchive(containerpath)
        self.archives = {self.basepath: rootArchive}
        if containerpath.endswith(".zip"):
            offset = archive.findLocalFileHeaderOffsetInIndex(
                rootArchive.index, self.rootTilesetPath)
            if offset is None:
                logging.warning(
                    f'Failed to find {self.rootTilesetPath}, trying to guess root tileset path...')
                guessPath = pathlib.PurePath(
                    containerpath).stem + "/tileset.json"
                offset = archive.findLocalFileHeaderOffsetInIndex(
                    rootArchive.index, guessPath)
                if offset is not None:
                    self.rootTilesetPath = guessPath
                else:
                    logging.error(
                        f'Failed to find root tileset in {containerpath}')
                    exit(-1)
        self.regExp3tzOrZip = r"(.*\.(3tz|zip))[\/]?(.*)"
        self.resourcepath = resourcepath
        self.templatefilename = templatefilename
        os.chdir(os.path.dirname(containerpath))

    def __call__(self, *args, **kwargs):
        """ Handle a request """
        super().__init__(*args, **kwargs)

    def getFile(self, path):
        match = re.match(self.regExp3tzOrZip, path)
        logging.debug(f"GetFile {path} matched: {match}")
        if match:
            logging.debug(f'Got match: {match.group(1)}: {match.group(3)}')
            if match.group(1) in self.archives:
                file = self.archives[match.group(1)].getFile(match.group(3))
                if match.group(3).endswith(".json"):
                    return stripMaxarContent3tz(file)
                return file
            path3tz = match.group(1)
            logging.debug(f'Opened new archive {path3tz}')
            self.archives[path3tz] = Single3tzArchive(path3tz)
            file = self.archives[path3tz].getFile(match.group(3))
            if match.group(3).endswith(".json"):
                return stripMaxarContent3tz(file)
            return file
        return None

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(bytes('<!doctype html>', 'utf-8'))
            self.wfile.write(bytes('<meta charset="UTF-8"><meta http-equiv="X-UA-Compatible" content="IE=edge"><meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, minimum-scale=1, user-scalable=no">', 'utf-8'))
            self.wfile.write(
                bytes('<style>@import url(resources/Cesium/bucket.css);</style>', 'utf-8'))
            self.wfile.write(
                bytes('<script src="resources/Cesium/Cesium.js"></script>', 'utf-8'))
            self.wfile.write(
                bytes('<div id="cesiumContainer" class="fullSize"></div>', 'utf-8'))
            self.wfile.write(bytes(
                f'<script src="resources/{self.templatefilename}" defer></script>', 'utf-8'))
            self.wfile.write(bytes('</body></html>', 'utf-8'))
        elif self.path == "/favicon.ico":
            self.send_response(200)
            self.send_header(
                'Content-type', contentTypeFromFileExtension(pathlib.PurePath(self.path).suffix))
            self.end_headers()
            with open(os.path.join(self.resourcepath, self.path[1:]), mode='rb') as file:
                content = file.read()
                self.wfile.write(content)
        elif self.path.startswith('/resources/'):
            path = os.path.join(self.resourcepath, self.path[11:])
            if os.path.exists(path):
                self.send_response(200)
            else:
                self.send_response(404)
            self.send_header(
                "Content-type", contentTypeFromFileExtension(pathlib.PurePath(self.path).suffix))
            self.end_headers()
            if self.path[11:] == self.templatefilename:
                self.wfile.write(applyTemplate(
                    path, self.basepath + "/" + self.rootTilesetPath))
            else:
                with open(path, mode='rb') as file:
                    content = file.read()
                    self.wfile.write(content)
        else:
            self.send_response(200)
            file = self.getFile(self.path[1:])
            if file is not None:
                if file.compMethod == archive.ZIP_COMPRESSION_METHOD_DEFLATE and isAcceptedContentEncoding(self.headers, 'deflate'):
                    self.send_header('Content-Encoding', 'deflate')
                elif file.compMethod == archive.ZIP_COMPRESSION_METHOD_ZSTD and isAcceptedContentEncoding(self.headers, 'zstd'):
                    self.send_header('Content-Encoding', 'zstd')
                elif file.compMethod != archive.ZIP_COMPRESSION_METHOD_STORE:
                    logging.warning(
                        f'Server handling decompression, compMethod: {int.from_bytes(file.compMethod, byteorder="little")}')
                    file.data = archive.decompressFileContents(
                        file.compMethod, file.uncompSize, file.data)
                self.send_header('Content-type', file.contentType)
                self.send_header('Access-Control-Allow-Headers',
                                 'Content-Type,Authorization')
                self.send_header('Access-Control-Allow-Methods',
                                 'GET,PUT,POST,DELETE')
                self.end_headers()
                self.wfile.write(file.data)
            else:
                logging.error(f'#### FAILED TO FIND path: {self.path}')
                self.send_response(404)
                self.send_header("Content-type", "application/json")
                self.end_headers()


def setup_logging(verbosity):
    base_loglevel = 30
    verbosity = min(verbosity, 2)
    loglevel = base_loglevel - (verbosity * 10)
    logging.basicConfig(level=loglevel,
                        format='%(message)s')


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    example_text = '''Example usage:
  Start a server to serve up a 3tz (viewable in a web browser at http://localhost:8080/):
    %(prog)s path/to/some.3tz --hostname=localhost --port=8080

  Serve a terrain pack directory (or a normal tileset.json):
    %(prog)s path/to/a/directory

  Serve using baseglobe.js template:
    %(prog)s path/to/baseglobe.3tz -j baseglobe.js
  '''

    description_text = '''A quick way to stream a 3tz dataset to CesiumJS or Vricon Explorer.

***WARNING: Not optimized for production use, only for quick testing.***'''

    parser = argparse.ArgumentParser(
        epilog=example_text,
        description=description_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('-v', '--verbose', action='count', dest='verbosity',
                        default=1, help="verbose output (repeat for increased verbosity)")
    parser.add_argument('-q', '--quiet', action='store_const', const=-1,
                        default=0, dest='verbosity', help="quiet output (show errors only)")
    parser.add_argument('-t', '--tileset', dest='rootTilesetPath',
                        help='Path to root tileset', default='tileset.json', required=False)
    parser.add_argument('-s', '--hostname', dest='hostname',
                        help='Host to serve as', default='localhost', required=False)
    parser.add_argument('-r', '--rootdir', dest='resourcePath', help='Root directory for static resources',
                        default=os.path.join(getScriptPath(), 'resources'), required=False)
    parser.add_argument('-p', '--port', dest='port',
                        help='Port to serve at', type=int, default=8080, required=False)
    parser.add_argument('-j', '--jstemplate', dest='templateFilename',
                        help='Filename of the javascript template, which must exist in the static resources directory', default='3tsSnippet.js', required=False)
    parser.add_argument('-csvl', '--cesium-strip-vector-layers', dest='stripVectorLayers',
                        help='Strip out all vector layers from terrain packs when serving to CesiumJS.', type=bool, default=False, required=False)
    parser.add_argument('filepath', help='Path to a 3tz, or a directory')
    try:
        args = parser.parse_args()
    except Exception:
        parser.print_help()
        exit(0)

    setup_logging(args.verbosity)

    if args.port != 8080 and args.port != 80:
        logging.warning(
            'Warning: using ports other than 80 or 8080 is unlikely to work in Chrome.')

    # sanitize the input paths
    resourcePathAbs = os.path.abspath(args.resourcePath)
    # logging.debug(f'resourcePathAbs: {resourcePathAbs}')
    if not os.path.isdir(resourcePathAbs):
        logging.error(f'Server root dir is not a directory: {resourcePathAbs}')
        exit(-1)
    filepathAbs = os.path.abspath(args.filepath)

    templatePathAbs = os.path.join(resourcePathAbs, args.templateFilename)
    if not os.path.exists(templatePathAbs) or not os.path.isfile(templatePathAbs):
        logging.error(f'Failed to find web template at path {templatePathAbs}')
        exit(-1)
    if not os.path.exists(filepathAbs):
        logging.error(f'Input path doesn\'t exist: {filepathAbs}')
        exit(-1)

    fileExtension = pathlib.PurePath(filepathAbs).suffix
    if os.path.isdir(filepathAbs) or (os.path.isfile(filepathAbs) and fileExtension == '.json'):
        if not os.path.isdir(filepathAbs):
            if os.path.basename(filepathAbs) != args.rootTilesetPath:
                logging.warning(
                    f'Note: using root tileset uri "{args.rootTilesetPath}", but in path basename was "{os.path.basename(filepathAbs)}"')
            filepathAbs = os.path.dirname(filepathAbs)
        logging.info(f'Serving content from {filepathAbs}')
        handler = ServeFromDirectoryHandler(
            filepathAbs, resourcePathAbs, args.rootTilesetPath, args.templateFilename, args.stripVectorLayers)
        logging.info(
            f'Serving root tileset as: http://{args.hostname}:{args.port}/{handler.directory + "/" + handler.rootTilesetPath}')
    elif os.path.isfile(filepathAbs) and (fileExtension == '.3tz' or fileExtension == '.zip'):
        logging.info(f'Serving from archive {filepathAbs}')
        handler = Serve3tzHandler(
            filepathAbs, resourcePathAbs, args.rootTilesetPath, args.templateFilename)
        logging.info(
            f'Serving root tileset as: http://{args.hostname}:{args.port}/{handler.basepath + "/" + handler.rootTilesetPath}')
    else:
        logging.error(f"Invalid input path: {args.filepath}")
        exit(-1)

    server = HTTPServer((args.hostname, args.port), handler)
    logging.info("Server started http://%s:%s" % (args.hostname, args.port))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

    server.server_close()
    logging.info("Server stopped.")
