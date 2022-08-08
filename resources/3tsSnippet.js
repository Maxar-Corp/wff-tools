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

viewer.zoomTo(tileset);