/**
 * STLLoader for three.js r158 (global build).
 * Sourced from three/examples/js/loaders/STLLoader.js and inlined for offline use.
 */
(function () {
  class STLLoader extends THREE.Loader {
    constructor(manager) {
      super(manager);
      this.binary = true;
      this.littleEndian = true;
    }

    load(url, onLoad, onProgress, onError) {
      const loader = new THREE.FileLoader(this.manager);
      loader.setPath(this.path);
      loader.setResponseType("arraybuffer");
      loader.setRequestHeader(this.requestHeader);
      loader.setWithCredentials(this.withCredentials);
      loader.load(
        url,
        (data) => {
          try {
            onLoad(this.parse(data));
          } catch (e) {
            (onError || console.error)(e);
            this.manager.itemError(url);
          }
        },
        onProgress,
        onError
      );
    }

    parse(data) {
      return this.isBinary(data) ? this.parseBinary(data) : this.parseASCII(this.ensureString(data));
    }

    ensureString(buffer) {
      if (typeof buffer === "string") return buffer;
      return new TextDecoder().decode(new Uint8Array(buffer));
    }

    isBinary(data) {
      const reader = new DataView(data);
      const solid = [115, 111, 108, 105, 100]; // "solid"
      for (let off = 0; off < 5; off++) {
        if (
          reader.getUint8(off + 0, false) === solid[0] &&
          reader.getUint8(off + 1, false) === solid[1] &&
          reader.getUint8(off + 2, false) === solid[2] &&
          reader.getUint8(off + 3, false) === solid[3] &&
          reader.getUint8(off + 4, false) === solid[4]
        ) {
          return false; // ASCII
        }
      }
      const size = reader.byteLength;
      const faces = reader.getUint32(80, true);
      return size === 84 + 50 * faces;
    }

    parseBinary(data) {
      const reader = new DataView(data);
      const faces = reader.getUint32(80, true);

      const vertices = [];
      const normals = [];
      const normal = new THREE.Vector3();
      const v = new THREE.Vector3();

      for (let face = 0; face < faces; face++) {
        const start = 84 + face * 50;
        normal.x = reader.getFloat32(start, true);
        normal.y = reader.getFloat32(start + 4, true);
        normal.z = reader.getFloat32(start + 8, true);

        for (let i = 1; i <= 3; i++) {
          const stride = start + i * 12;
          v.x = reader.getFloat32(stride, true);
          v.y = reader.getFloat32(stride + 4, true);
          v.z = reader.getFloat32(stride + 8, true);
          vertices.push(v.x, v.y, v.z);
          normals.push(normal.x, normal.y, normal.z);
        }
      }

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
      geometry.computeBoundingBox();
      return geometry;
    }

    parseASCII(data) {
      const patternFace = /facet\\s+normal\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)/;
      const patternVertex = /vertex\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)\\s+([\\-\\+]?\\d*\\.?\\d+(?:[eE][\\-\\+]?\\d+)?)/;

      const vertices = [];
      const normals = [];
      const normal = new THREE.Vector3();
      let v1 = new THREE.Vector3();
      let v2 = new THREE.Vector3();
      let v3 = new THREE.Vector3();

      function addFace() {
        vertices.push(v1.x, v1.y, v1.z, v2.x, v2.y, v2.z, v3.x, v3.y, v3.z);
        normals.push(normal.x, normal.y, normal.z, normal.x, normal.y, normal.z, normal.x, normal.y, normal.z);
      }

      const lines = data.split("\\n");
      for (let i = 0; i < lines.length; i++) {
        let result;
        if ((result = patternFace.exec(lines[i])) !== null) {
          normal.set(parseFloat(result[1]), parseFloat(result[2]), parseFloat(result[3]));
        } else if ((result = patternVertex.exec(lines[i])) !== null) {
          const x = parseFloat(result[1]);
          const y = parseFloat(result[2]);
          const z = parseFloat(result[3]);
          if (v1.lengthSq() === 0) v1.set(x, y, z);
          else if (v2.lengthSq() === 0) v2.set(x, y, z);
          else {
            v3.set(x, y, z);
            addFace();
            v1.set(0, 0, 0);
            v2.set(0, 0, 0);
            v3.set(0, 0, 0);
          }
        }
      }

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
      geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
      geometry.computeBoundingBox();
      return geometry;
    }
  }

  THREE.STLLoader = STLLoader;
})();
