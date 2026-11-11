"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../Other_dev/NP_Punto_Browser/layout_core.js");

const source = fs.readFileSync(
    path.join(__dirname, "../Other_dev/NP_Punto_Browser/options.js"), "utf8",
);

function setup(initial = {}) {
    const elements = {};
    const storage = {...initial};
    for (const key of [
        "enabled", "rulesEnabled", "learn", "words", "hosts", "rules",
        "ruleTest", "ruleTestResult", "testRule", "save", "clear", "status",
    ]) {
        elements[key] = {
            value:"", checked:false, textContent:"", style:{}, handlers:{},
            addEventListener(event, callback) { this.handlers[event] = callback; },
        };
    }
    const chrome = {
        runtime: { lastError:null },
        storage: {
            local: {
                get(defaults, callback) { callback({...defaults, ...storage}); },
                set(data, callback) { Object.assign(storage, data); callback?.(); },
            },
        },
    };
    const context = {
        NPPuntoCore: core,
        document: { getElementById: name => elements[name] },
        chrome,
        confirm: () => true,
        Set, Boolean, Object, String,
    };
    vm.runInNewContext(source, context);
    const click = id => elements[id].handlers.click();
    return {elements,storage,click};
}

test("Stored rules are loaded and independently enabled by default", () => {
    const h=setup({
        enabled:false,
        rules:[{from:"brb",to:"be right back"}],
    });
    assert.equal(h.elements.enabled.checked, false);
    assert.equal(h.elements.rulesEnabled.checked, true);
    assert.equal(h.elements.rules.value, "brb - be right back");
});

test("Rule preview checks current edits without saving", () => {
    const h=setup({enabled:false});
    h.elements.rules.value="brb => be right back";
    h.elements.ruleTest.value="BRB";
    h.click("testRule");
    assert.equal(h.elements.ruleTestResult.textContent,"Сработает: be right back");
    assert.equal(h.storage.rules,undefined);
});

test("Saving keeps dictionary off but enables and persists rules", () => {
    const h=setup({enabled:false});
    h.elements.rules.value="brb => be right back";
    h.click("save");
    assert.equal(h.storage.enabled,false);
    assert.equal(h.storage.rulesEnabled,true);
    assert.deepEqual(Array.from(h.storage.rules,x=>({...x})),[
        {from:"brb",to:"be right back"},
    ]);
    assert.match(h.elements.status.textContent,/Правил: 1/);
});

test("Rule preview explains explicitly disabled rules", () => {
    const h=setup({rulesEnabled:false});
    h.elements.rules.value="brb => be right back";
    h.elements.ruleTest.value="brb";
    h.click("testRule");
    assert.match(h.elements.ruleTestResult.textContent,/Правила выключены/);
});

test("Malformed and duplicate rules are rejected on save", () => {
    const h=setup();
    h.elements.rules.value="brb";
    h.click("save");
    assert.equal(h.storage.rules,undefined);
    assert.match(h.elements.status.textContent,/сокращение - полный текст/);
    h.elements.rules.value="brb => ответ\nBRB => другой ответ";
    h.click("save");
    assert.equal(h.storage.rules,undefined);
    assert.match(h.elements.status.textContent,/Повторяющееся/);
});

test("Saved rules can be disabled independently of word conversion", () => {
    const h=setup({enabled:true,rulesEnabled:true});
    h.elements.rules.value="brb => be right back";
    h.elements.rulesEnabled.checked=false;
    h.click("save");
    assert.equal(h.storage.enabled,true);
    assert.equal(h.storage.rulesEnabled,false);
    assert.equal(h.storage.rules[0].from,"brb");
});

test("New preferred dash format saves and previews ща - сейчас",()=>{
    const h=setup({enabled:false, rulesEnabled:true});
    h.elements.rules.value="ща - сейчас";
    h.elements.ruleTest.value="ЩА";
    h.click("testRule");
    assert.equal(h.elements.ruleTestResult.textContent, "Сработает: сейчас");
    h.click("save");
    assert.deepEqual(Array.from(h.storage.rules,x=>({...x})),[
        {from:"ща",to:"сейчас"},
    ]);
    assert.equal(h.storage.rulesEnabled,true);
});

test("Old arrow rule format remains compatible on update",()=>{
    const h=setup({rules:[{from:"ща",to:"сейчас"}]});
    assert.equal(h.elements.rules.value,"ща - сейчас");
    h.elements.rules.value="ща => сейчас";
    h.click("save");
    assert.equal(h.storage.rules[0].from,"ща");
    assert.equal(h.storage.rules[0].to,"сейчас");
});

test("Dashes within rule output are preserved",()=>{
    const h=setup();
    h.elements.rules.value="бт - бета-тест";
    h.click("save");
    assert.equal(h.storage.rules[0].to,"бета-тест");
});
