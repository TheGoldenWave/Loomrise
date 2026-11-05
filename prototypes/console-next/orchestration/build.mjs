import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';

await build({
  absWorkingDir: fileURLToPath(new URL('..', import.meta.url)),
  entryPoints: ['orchestration/canvas.jsx'],
  outfile: 'dist/orchestration.js',
  bundle: true, format: 'esm', minify: true, legalComments: 'eof',
  define: { 'process.env.NODE_ENV': '"production"' },
  target: ['es2022'],
});
