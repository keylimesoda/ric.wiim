'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const c = vm.createContext({});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname, '../AudioFlow.js'), 'utf8'), c);
let passed = 0;
function test(name, fn) { fn(); passed++; console.log('ok - ' + name); }
function event(s, type, extra = {}) { return c.reduce(s, {type, generation:s.generation, ...extra}); }
function checking() { return event(c.initial(), 'enable'); }
const ready = {ready:true, canInstall:true, canSetupFirewall:true, firewall:'allowed'};
test('toggle acknowledges intent immediately', () => {
  const s=checking(); assert.equal(s.wanted,true); assert.equal(s.phase,'checking'); assert.equal(s.effects[0],'check');
});
test('one request progresses through connection and playback', () => {
  let s=event(checking(),'checked',{check:ready}); assert.equal(s.phase,'connecting'); assert.equal(s.effects[0],'start');
  s=event(s,'progress',{phase:'buffering'}); assert.equal(s.phase,'buffering');
  s=event(s,'progress',{phase:'streaming'}); assert.equal(s.phase,'streaming'); assert.equal(s.wanted,true);
});
test('known firewall requirement is caught before starting playback', () => {
  const s=event(checking(),'checked',{check:{...ready,firewall:'needs-rule'}});
  assert.equal(s.phase,'needs-firewall'); assert.equal(s.wanted,true); assert.equal(s.effects.includes('start'),false);
});
test('successful authorization automatically resumes checking and playback', () => {
  let s=event(checking(),'checked',{check:{...ready,firewall:'needs-rule'}});
  s=event(s,'authorize'); assert.equal(s.phase,'authorizing');
  s=event(s,'authorized',{result:{ok:true}}); assert.equal(s.phase,'checking'); assert.equal(s.effects[0],'check');
  s=event(s,'checked',{check:ready}); assert.equal(s.phase,'connecting'); assert.equal(s.wanted,true);
});
test('missing tools followed by firewall setup stays in one request', () => {
  let s=event(checking(),'checked',{check:{...ready,ready:false}}); assert.equal(s.phase,'needs-tools');
  const generation=s.generation;
  s=event(event(s,'authorize'),'authorized',{result:{ok:true}});
  s=event(s,'checked',{check:{...ready,firewall:'needs-rule'}}); assert.equal(s.phase,'needs-firewall');
  s=event(event(s,'authorize'),'authorized',{result:{ok:true}});
  s=event(s,'checked',{check:ready}); assert.equal(s.phase,'connecting'); assert.equal(s.generation,generation);
});
test('authorization cancellation returns off with explanation', () => {
  let s=event(checking(),'checked',{check:{...ready,ready:false}});
  s=event(event(s,'authorize'),'authorized',{result:{ok:false,canceled:true}});
  assert.equal(s.phase,'off'); assert.equal(s.wanted,false); assert.equal(s.notice,'Setup canceled.');
});
test('turning off prevents delayed checks from starting audio', () => {
  let s=checking(); const generation=s.generation;
  s=event(s,'disable'); s=event(s,'stopped');
  s=event(s,'checked',{generation,check:ready}); assert.equal(s.phase,'off'); assert.equal(s.effects.length,0);
});
test('turning off during authorization prevents automatic resume', () => {
  let s=event(checking(),'checked',{check:{...ready,ready:false}}); s=event(s,'authorize');
  const generation=s.generation; s=event(s,'disable');
  s=event(s,'authorized',{generation,result:{ok:true}}); assert.equal(s.wanted,false); assert.equal(s.effects.length,0);
  s=event(s,'stopped'); assert.equal(s.phase,'off');
});
test('a prior attempt cannot alter a retry', () => {
  let s=checking(); const old=s.generation;
  s=event(s,'failed',{message:'offline'}); assert.equal(s.phase,'failed'); assert.equal(s.wanted,false);
  s=event(s,'enable'); s=event(s,'failed',{generation:old,message:'late failure'});
  assert.equal(s.phase,'checking'); assert.equal(s.error,'');
});
test('unknown firewall configuration attempts playback and surfaces connection failure', () => {
  let s=event(checking(),'checked',{check:{...ready,firewall:'unknown'}}); assert.equal(s.phase,'connecting');
  s=event(s,'network-help',{canSetupFirewall:true}); assert.equal(s.phase,'needs-firewall'); assert.equal(s.wanted,true);
});
test('check timeout and missing setup support provide a retryable failure', () => {
  let s=event(checking(),'failed',{message:'Checking took too long'}); assert.equal(s.phase,'failed');
  assert.equal(s.error,'Checking took too long'); assert.equal(c.needsAttention(s),true);
  s=event(checking(),'checked',{check:{ready:false,canInstall:false}}); assert.equal(s.phase,'failed');
});
console.log(passed+' audio-flow tests passed');
