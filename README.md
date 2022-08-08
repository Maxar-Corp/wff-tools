# WFF Tools

Various tols for inspecting Well-Formed Format data (WFF).

## License
Apache 2.0

## Tools

### 3GM

A tool to inspect `EXT_feature_metadata` content.

**Usage**

```
3gm.py [--help] [--verbose] [--quiet]
       [--pretty] [--no-pretty] 
       [--feature-table FTNAME]
       [--feature-texture FTX]
       [--property PROPNAME]
       [--list-indices]
       filepath [filter]
```

**Examples**

List all FeatureTables in GLB inside 3tz using file filter:

`3gm.py myfiles/archived/some.3tz 0/0/0/0.glb`

List all property values from the LandCover FeatureTable:

`3gm.py --feature-table LandCover tile.glb`

List the 'name' property values from the LandCover FeatureTable:

`3gm.py --feature-table LandCover --property name tile.glb `

List the 'src' property with property indices for each value from the first found FeatureTable:

`3gm.py --property src --list-indices tile.glb`

### 3TJ

A tool to quickly inspect 3tz archive content.

**Usage**

```
3tj.py [--help] [--verbose] [--quiet]
       [--pretty] [--no-pretty] 
       [--extract] 
       containerpath [filepath]
```

**Examples**

Print the root tileset.json inside the 3tz:

`3tj.py /path/to/some.3tz`

Print the json part of a given GLB file inside the 3tz:

`3tj.py /path/to/some.3tz 0/0/0/0.glb`

Extract the given GLB file from inside the 3tz:

`3tj.py --extract /path/to/some.3tz 2/12/1823.glb`

### 3TS

A quick way to stream a 3tz dataset to CesiumJS or Vricon Explorer.

Use `UpdateCesiumJs` to install CesiumJS.

***WARNING**: Indended for test purposes only. Not optimized for production use.*

**Usage**

```
3ts.py [--help] [--verbose] [--quiet]
       [--tileset ROOTTILESETPATH]
       [--rootdir RESOURCEPATH]
       [--hostname HOSTNAME]
       [--port PORT]
       [--jstemplate TEMPLATEFILENAME]
       [--cesium-strip-vector-layers STRIPVECTORLAYERS]
       filepath
```

**Examples**

Start a server to serve up a 3tz (viewable in a web browser at `http://localhost:8080/`):

`3ts.py --hostname=localhost --port=8080 path/to/some.3tz`

Serve a terrain pack directory (or a normal tileset.json):

`3ts.py path/to/a/directory`

Serve using baseglobe.js template:

`3ts.py --jstemplate baseglobe.js path/to/baseglobe.3tz `

### GLBJSON

Prints the GLB JSON data to stdout.

**Usage**

```
glbjson.py [--help]
           [--pretty] [--no-pretty] 
           filepath
```

### GLTF

Prints the GLTF JSON data to stdout.

**Usage**

```
gltf.py [--help]
        [--pretty] [--no-pretty]
        filepath
```

### IMGUTILS

Parse image stats

**Usage**

```
imgutils.py [--help]
            filepath
```


### Index3TZ

A tool that builds a 3tz index file given a zip file.

**Usage**

```
index3tz.py [--help] [--verbose] [--quiet]
            [--stats]
            containerpath [outpath]
```

**Examples:**

Generate index file for zip:

`index3tz.py path/to/some.zip`

Inspect zip for offset packing (experiment):

`index3tz.py --stats --verbose path/to/some.zip `

### Stats

Print statistics to stdout for a given 3ts, 3tz or zip file.

**Usage**

```
stats.py [--help] [--verbose] [--quiet] 
         [--full] 
         [--keep-unique-threshold KEEPUNIQUE_THRESHOLD]
         [--use-3tz-index] [--no-use-3tz-index]
         filepath [filter]
```

### SubtreeJson

**Usage**

```
subtreejson.py [--help] [--pretty] [--no-pretty] 
               filepath
```


### UpdateCesiumJs

Updates Cesium code in the wff-tools repo

**Usage**

```
updateCesiumJs.py [--help] [--verbose] [--quiet]
                  [--clean] [--no-clean]
                  [--clone] [--no-clone]
                  [--cesium-branch CESIUMREPOBRANCH]
                  [--cesium-sha CESIUMREPOSHA]
                  [--update] [--no-update]
                  [--run-npm-install] [--no-run-npm-install]
                  [--build-cesium-release] [--no-cesium-release]
                  [--copy-cesium-build] [--no-copy-cesium-build]
                  [--cesium-repo-path CESIUMREPOPATH]
```

**Examples**

Install Cesium first time (full clone):

`updateCesiumJs.py --clone --run-npm-install`

Update a previous clone:

`updateCesiumJs.py --update`

Use a manually managed cesium repo (e.g for local testing of a fix in cesium):

`updateCesiumJs.py --no-clone --no-update --build-cesium-release --copy-cesium-build -vvv`

