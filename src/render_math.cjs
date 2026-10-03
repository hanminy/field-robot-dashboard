const fs = require('node:fs');
const katex = require('../vendor/katex/katex.min.js');

try {
  const equations = JSON.parse(fs.readFileSync(0, 'utf8'));
  const rendered = equations.map(tex => katex.renderToString(tex, {
    output: 'mathml',
    displayMode: true,
    throwOnError: true,
    trust: false,
    strict: 'ignore', // Reviewed formulas also contain Unicode math and Korean text.
  }));
  process.stdout.write(JSON.stringify(rendered));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
