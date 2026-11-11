"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../Other_dev/NP_Punto_Browser/layout_core.js");

test("Converts words in both keyboard directions", () => {
    assert.equal(core.convertText("ghbdtn"), "привет");
    assert.equal(core.convertText("Ghbdtn"), "Привет");
    assert.equal(core.convertText("привет"), "ghbdtn");
    assert.equal(core.convertText("Hello"), "Руддщ");
});

test("Only recognized words qualify for automatic correction", () => {
    assert.equal(core.candidate("ghbdtn", ["привет"]).replacement, "привет");
    assert.equal(core.candidate("привет", ["привет"]), null);
    assert.equal(core.candidate("abcd", ["привет"]), null);
    assert.equal(core.candidate("abc2", ["привет"]), null);
    assert.equal(core.candidate("a", ["привет"]), null);
    assert.equal(core.candidate("mixж", ["привет"]), null);
});

test("Applies configured rules with boundaries before dictionary", () => {
    const settings = {words: ["привет"], rules: [{from:"brb",to:"be right back"}]};
    assert.deepEqual(core.findReplacement("brb", settings), {
        start:0,before:"brb",replacement:"be right back",reason:"rule",
    });
    assert.equal(core.findReplacement("foobarbrb",settings), null);
    assert.equal(core.findReplacement("hello ghbdtn",settings).replacement,"привет");
    assert.equal(core.findReplacement("hello world",settings), null);
});

test("Excludes domain and all subdomains without matching lookalikes", () => {
    assert.equal(core.isExcludedHost("example.org",["example.org"]),true);
    assert.equal(core.isExcludedHost("mail.example.org",["example.org"]),true);
    assert.equal(core.isExcludedHost("notexample.org",["example.org"]),false);
    assert.equal(core.isExcludedHost("example.org.invalid",["example.org"]),false);
});

test("Normalizes dictionary and rejects mixed tokens", () => {
    assert.deepEqual(core.normalizeWords("  ПРИВЕТ\nпривет\n123\nhello\n"),["привет","hello"]);
    assert.equal(core.lettersKind("Тест"),"ru");
    assert.equal(core.lettersKind("test"),"en");
    assert.equal(core.lettersKind("test123"),null);
});
