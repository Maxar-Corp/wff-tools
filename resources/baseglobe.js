//Cesium.ExperimentalFeatures.enableModelExperimental = true;

var viewer = new Cesium.Viewer('cesiumContainer', {
  animation: false,
  skyBox: false,
  skyAtmosphere: false,
  globe: false,
  infoBox: false,
  homeButton: false,
  baseLayerPicker: false,
  sceneModePicker: false,
  selectionIndicator: false,
  geocoder: false,
  //imageryProvider: new TileMapServiceImageryProvider({}),
  navigationHelpButton: false,
  navigationInstructionsInitiallyVisible: false,
  scene3DOnly: true,
  terrainProvider: undefined,
  timeline: false,
  fullscreenButton: false
});

// hide credits
viewer.scene.frameState.creditDisplay.container.style.display = 'none';

var scene = viewer.scene;
var tileset = viewer.scene.primitives.add(new Cesium.Cesium3DTileset({
  url: '${rootTilesetUri}',
  debugShowBoundingVolume: false,
  debugShowGeometricError: false,
  debugShowContentBoundingVolume: false,
  debugShowRenderingStatistics: false,
  debugShowUrl: false
//  , featureIdIndex: 2
}));

function getCameraOptions() {
  return {
    "destination": viewer.camera.positionWC.clone(),
    "orientation" : { 
      "direction": viewer.camera.directionWC.clone(), 
      "up": viewer.camera.upWC.clone()
    }
  };
}

document.addEventListener("copy", event => {
  jsonStr = JSON.stringify(getCameraOptions());
  event.clipboardData.setData("text/plain", jsonStr);
  event.preventDefault();
});

document.addEventListener("paste", event => {
  if (event.clipboardData) {
    str = event.clipboardData.getData("text/plain");
    try {
      jsonStr = JSON.parse(str);
      if (!jsonStr.destination) {
        //console.log(`not a camera setting: ${jsonStr}`)
        return;
      }
    }
    catch(err) {
      //console.log(`got err: ${err}`)
      return;
    }

    viewer.camera.setView(jsonStr);  
  }
});

// HTML overlay for showing feature name on mouseover
var nameOverlay = document.createElement("div");
viewer.container.appendChild(nameOverlay);
nameOverlay.className = "backdrop";
nameOverlay.style.display = "none";
nameOverlay.style.position = "absolute";
nameOverlay.style.bottom = "0";
nameOverlay.style.left = "0";
nameOverlay.style["pointer-events"] = "none";
nameOverlay.style.padding = "4px";
nameOverlay.style.backgroundColor = "black";
nameOverlay.style.whiteSpace = "pre-line";
nameOverlay.style.fontSize = "12px";

var enablePicking = true;
var handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction(function (movement) {
  if (enablePicking) {
    var pickedObject = viewer.scene.pick(movement.endPosition);
    if (pickedObject instanceof Cesium.Cesium3DTileFeature) {
      nameOverlay.style.display = "block";
      nameOverlay.style.bottom =
        viewer.canvas.clientHeight - movement.endPosition.y + "px";
      nameOverlay.style.left = movement.endPosition.x + "px";
      var propertyNames = pickedObject.getPropertyNames();
      var length = propertyNames.length;
      var message = "";
      for (var i = 0; i < length; ++i) {
        var propertyName = propertyNames[i];
        message += `${propertyName}: ${pickedObject.getProperty(propertyName)}\n`
      }
      //message += "Feature ID: " + pickedObject._batchId;
      nameOverlay.textContent = message;
    } else {
      nameOverlay.style.display = "none";
    }
  } else {
    nameOverlay.style.display = "none";
  }
}, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

var NOTHING_SELECTED = 12;
var selectFeatureShader = new Cesium.CustomShader({
  uniforms: {
    u_selectedFeature: {
      type: Cesium.UniformType.FLOAT,
      value: NOTHING_SELECTED,
    },
  },
  lightingModel: Cesium.LightingModel.PBR,
  fragmentShaderText: [
    "const float NOTHING_SELECTED = 12.0;",
    "void fragmentMain(FragmentInput fsInput, inout czm_modelMaterial material) {",
    "  // NOTE: This is exposing internal details of the shader. It would be better if this was added to fsInput somewhere...",
    "  float featureId = floor(texture2D(FEATURE_ID_TEXTURE, FEATURE_ID_TEXCOORD).FEATURE_ID_CHANNEL * 255.0 + 0.5);",
    "",
    "  if (u_selectedFeature < NOTHING_SELECTED && featureId == u_selectedFeature) {",
    "    material.specular = vec3(1.00, 0.85, 0.57);",
    "    material.roughness = 0.3;",
    "  }",
    "}",
  ].join("\n"),
});

var clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction(function (movement) {
  if (enablePicking) {
    var pickedObject = scene.pick(movement.position);
    if (pickedObject) {
      console.log(pickedObject)
    }
    if (
      Cesium.defined(pickedObject) &&
      Cesium.defined(pickedObject._batchId)
    ) {
      selectFeatureShader.setUniform(
        "u_selectedFeature",
        pickedObject._batchId
      );
    } else {
      selectFeatureShader.setUniform(
        "u_selectedFeature",
        NOTHING_SELECTED
      );
    }
  }
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

var classificationStyle = new Cesium.Cesium3DTileStyle({
  color: "color(${color})",
});

var landCoverStyle = new Cesium.Cesium3DTileStyle({
  defines: {
    LandCoverColor: "rgb(${color}[0], ${color}[1], ${color}[2])",
  },
  color:
    "${LandCoverColor} === vec4(1.0) ? rgb(254, 254, 254) : ${LandCoverColor}",
});

// Dummy shader that sets the UNLIT lighting mode. For use with the classification style
var emptyFragmentShader =
  "void fragmentMain(FragmentInput fsInput, inout czm_modelMaterial material) {}";
var unlitShader = new Cesium.CustomShader({
  lightingModel: Cesium.LightingModel.UNLIT,
  fragmentShaderText: emptyFragmentShader,
});

function defaults() {
  tileset.style = undefined;
  tileset.customShader = unlitShader;
  tileset.colorBlendMode = Cesium.Cesium3DTileColorBlendMode.HIGHLIGHT;
  tileset.colorBlendAmount = 0.5;
}

function showClassification() {
  defaults();
  tileset.style = classificationStyle;
  tileset.colorBlendMode = Cesium.Cesium3DTileColorBlendMode.MIX;
}

function showLandcover() {
  defaults();
  tileset.style = landCoverStyle;
  tileset.colorBlendMode = Cesium.Cesium3DTileColorBlendMode.MIX;
}

showLandcover();

viewer.zoomTo(tileset);

