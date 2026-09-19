const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

test('only the latest loan filter response updates the table', async () => {
  const source = fs.readFileSync(process.env.SOURCE_JS || 'static/app.js', 'utf8');
  const start = source.indexOf('async function loans() {');
  const end = source.indexOf('\nfunction entityForm()', start);
  const pending = [];
  const rendered = [];
  let status = 'active';
  const context = vm.createContext({
    user: {role: 'reader'},
    encodeURIComponent,
    api: path => new Promise(resolve => pending.push({path, resolve})),
    $: selector => selector === '#loan-status'
      ? {value: status}
      : {replaceChildren: value => rendered.push(value)},
    table: (_headers, rows) => rows,
    el: (_tag, text) => text,
  });
  vm.runInContext('let loanRequest=0;\n' + source.slice(start, end), context);
  const older = context.loans();
  status = 'returned';
  const newer = context.loans();
  assert.equal(pending[0].path, '/loans?status=active');
  assert.equal(pending[1].path, '/loans?status=returned');
  pending[1].resolve({items: [{title: 'Returned book', returned_at: '2026-09-19'}]});
  await newer;
  pending[0].resolve({items: [{title: 'Active book', returned_at: null}]});
  await older;
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0][0][0], 'Returned book');
});

