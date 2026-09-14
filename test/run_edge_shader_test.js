// Node runner to execute headless Edge WebGL test
import { execFile } from 'child_process';
import path from 'path';
import fs from 'fs';

const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const htmlPath = path.resolve('test/stress_webgl_runner.html');
const fileUrl = 'file:///' + htmlPath.replace(/\\/g, '/');

const args = [
  '--headless',
  '--disable-gpu=false',
  '--use-gl=angle',
  '--virtual-time-budget=3000',
  '--dump-dom',
  fileUrl
];

console.log('Spawning Edge with URL:', fileUrl);

execFile(edgePath, args, { maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
  if (err) {
    console.error('Exec error:', err.message);
    process.exit(1);
  }
  
  // Extract content of <div id="test-results">
  const match = stdout.match(/<div id="test-results">([\s\S]*?)<\/div>/);
  if (match) {
    try {
      const cleanJson = match[1]
        .replace(/<br\s*[\/]?>/gi, "\n")
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');
      const parsed = JSON.parse(cleanJson);
      fs.writeFileSync('test/webgl_test_results.json', JSON.stringify(parsed, null, 2));
      console.log('Successfully written test/webgl_test_results.json');
    } catch (e) {
      console.error('JSON parse error:', e.message);
      fs.writeFileSync('test/raw_webgl_results.txt', match[1]);
    }
  } else {
    console.log('No test results div found. Raw stdout length:', stdout.length);
  }
});
