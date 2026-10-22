// Bundles map/src/carte3d.js with the parts of the CesiumJS engine it uses, and copies the
// engine's runtime files (web workers, WebAssembly decoders, sky textures) next to it.
// Run after changing the map code or the Cesium version:  cd map && npm ci && npm run build
import { build } from 'esbuild';
import { cpSync, rmSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const version = JSON.parse(readFileSync('node_modules/cesium/package.json', 'utf8')).version;
const assets = '../site_static/assets';
const runtime = join(assets, `cesium-${version}`);          // versioned folder: safe with immutable caching
const src = 'node_modules/cesium/Build/Cesium';

for (const d of readdirSync(assets)) if (d.startsWith('cesium-')) rmSync(join(assets, d), { recursive: true });
mkdirSync(runtime, { recursive: true });
cpSync(join(src, 'Workers'), join(runtime, 'Workers'), { recursive: true });
cpSync(join(src, 'ThirdParty'), join(runtime, 'ThirdParty'), { recursive: true });
for (const f of ['approximateTerrainHeights.json', 'IAU2006_XYS', 'Images', 'Textures/SkyBox', 'Textures/moonSmall.jpg', 'Textures/waterNormals.jpg', 'Textures/waterNormalsSmall.jpg'])
  cpSync(join(src, 'Assets', f), join(runtime, 'Assets', f), { recursive: true });
cpSync('node_modules/cesium/LICENSE.md', join(runtime, 'LICENSE.md'));

await build({
  entryPoints: ['src/carte3d.js'], bundle: true, minify: true, format: 'esm', target: 'es2020',
  outfile: join(assets, 'carte3d.js'), legalComments: 'external', logLevel: 'warning',
  define: { __CESIUM_BASE__: JSON.stringify(`/assets/cesium-${version}/`) },
});
console.log(`Map bundle built with CesiumJS ${version}.`);
