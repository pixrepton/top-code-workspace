const fs = require('fs');
const path = require('path');
const appJs = fs.readFileSync(path.resolve('daszek/public/app.js'), 'utf8');

function extractFunctionBody(source, signature) {
  const start = source.indexOf(signature);
  if (start < 0) {
    throw new Error('Function not found: ' + signature);
  }
  const nextFn = source.indexOf('\nfunction ', start + signature.length);
  const fnSrc = source.slice(start, nextFn < 0 ? undefined : nextFn).trim();
  const bodyStart = fnSrc.indexOf('{') + 1;
  const bodyEnd = fnSrc.lastIndexOf('}');
  return fnSrc.slice(bodyStart, bodyEnd);
}

const hrefBody = extractFunctionBody(appJs, 'function sanitizeMarkdownHref(href)');
const fnBody = extractFunctionBody(appJs, 'function renderMarkdown(text)');

// Minimal DOM that handles textContent/innerHTML for escaping
const texts = {};
let ctr = 0;
global.document = {
  createElement: () => {
    const id = ++ctr;
    texts[id] = '';
    return {
      set textContent(v) { texts[id] = String(v); },
      get textContent() { return texts[id]; },
      get innerHTML() {
        return texts[id]
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;');
      },
      set innerHTML(v) { texts[id] = String(v); },
    };
  },
};

// sanitizeMarkdownHref uses window.location.origin as URL base
global.window = { location: { origin: 'http://localhost' } };

// escapeHtml helper
const escapeHtml = (text) => {
  if (!text && text !== 0) return '';
  const d = global.document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
};

const sanitizeMarkdownHref = new Function('href', hrefBody);

// Create renderMarkdown — pass the same helpers the extracted body calls
const renderMarkdown = new Function('escapeHtml', 'document', 'sanitizeMarkdownHref', 'text', fnBody);
const rm = (t) => renderMarkdown(escapeHtml, global.document, sanitizeMarkdownHref, t);

// Tests
let pass = 0, fail = 0;
const t = (cond, msg) => { if (cond) pass++; else { console.log('FAIL:', msg); fail++; } };
const c = (hay, needle, msg) => {
  if (typeof hay === 'string' && hay.indexOf(needle) !== -1) pass++;
  else { console.log('FAIL:', msg, '- missing:', JSON.stringify(needle)); fail++; }
};

console.log('=== renderMarkdown tests ===');

c(rm('**bold**'), '<strong>bold</strong>', 'bold');
c(rm('*italic*'), '<em>italic</em>', 'italic');
c(rm('~~strike~~'), '<del>strike</del>', 'strikethrough');
c(rm('# H1'), '<h1>H1</h1>', 'h1');
c(rm('## H2'), '<h2>H2</h2>', 'h2');
c(rm('### H3'), '<h3>H3</h3>', 'h3');
c(rm('text `code` here'), '<code>code</code>', 'code');
c(rm('```\nprint(1)\n```'), '<pre>', 'fenced code pre tag');
c(rm('```\nprint(1)\n```'), 'print(1)', 'fenced code content');
c(rm('[link](http://x.com)'), 'href="http://x.com/"', 'link');
c(rm(':fire:'), '\u{1F525}', 'emoji');
c(rm(':unknown_xyz:'), ':unknown_xyz:', 'unknown emoji');
c(rm('- item'), '<li>item</li>', 'ul item');
c(rm('1. item'), '<li>item</li>', 'ol item');
c(rm('> quote'), '<blockquote>quote</blockquote>', 'blockquote');
c(rm('---'), '<hr>', 'hr');
c(rm('- [x] done'), 'checked', 'task checked');
c(rm('- [ ] todo'), 'task-list-item', 'task unchecked');
t(rm('<script>alert(1)</script>').indexOf('<script>') === -1, 'XSS protected');
c(rm('a\n\nb'), '</p><p>', 'paragraph break');
c(rm('a\nb'), '<br>', 'line break');
t(rm('') === '', 'empty');
t(rm(null) === '', 'null');

console.log(pass + '/' + (pass + fail) + ' passed');
process.exit(fail > 0 ? 1 : 0);
