"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../Other_dev/NP_Punto_Browser/layout_core.js");

test("Converts words in both keyboard directions", () => {
    assert.equal(core.convertText("ghbdtn"), "привет");
    assert.equal(core.convertText("Ghbdtn"), "Привет");
    assert.equal(core.convertText("привет"), "ghbdtn");
    assert.equal(core.convertText("Hello"), "Руддщ");
    assert.equal(core.convertText("xnj ntgthm evttn&"), "что теперь умеет?");
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

test("Screenshot case: common ChatGPT phrase is automatically recognized", () => {
    const options = { words: core.defaultWords, rules: [] };
    assert.deepEqual(core.findReplacement("xnj", options), {
        start: 0, before: "xnj", replacement: "что", reason: "dictionary",
    });
    assert.equal(core.findReplacement("ntgthm", options).replacement, "теперь");
    assert.equal(core.findReplacement("evttn", options).replacement, "умеет");
    assert.deepEqual(core.findReplacement("xnj ntgthm evttn", options), {
        start: 0, before: "xnj ntgthm evttn",
        replacement: "что теперь умеет", reason: "known-phrase",
    });
    assert.equal(core.correctedSeparator("&", "evttn", "умеет"), "?");
    assert.equal(core.correctedSeparator("&", "work", "work"), "&");
});

test("Known valid English sentences are not corrected accidentally", () => {
    const options = {words: core.defaultWords, rules: []};
    assert.equal(core.findReplacement("hello", options), null);
    assert.equal(core.findReplacement("hello world", options), null);
    assert.equal(core.findReplacement("working today", options), null);
});

test("Ctrl+Ins converts the last layout run before caret without dictionary", () => {
    const prefix = "привет ghbdtn";
    assert.deepEqual(core.findRunBeforeCaret(prefix, prefix.length), {
        start: 7, end: prefix.length, before: "ghbdtn", replacement: "привет",
    });
    const phrase = "xnj ntgthm evttn&";
    assert.equal(
        core.findRunBeforeCaret(phrase, phrase.length).replacement,
        "что теперь умеет?",
    );
    const mixed = "ctrl+ins не работают";
    assert.equal(
        core.findRunBeforeCaret(mixed, mixed.length).replacement,
        "yt hf,jnf.n",
    );
});

test("Ctrl+Ins has safe line and caret boundaries", () => {
    assert.equal(core.findRunBeforeCaret("ghbdtn\n", 7), null);
    assert.equal(core.findRunBeforeCaret("ghbdtn", 0), null);
    assert.equal(core.findRunBeforeCaret("ghbdtn", 100), null);
    assert.equal(core.findRunBeforeCaret("", 0), null);
    const multiline = "привет\nghbdtn";
    const found = core.findRunBeforeCaret(multiline, multiline.length);
    assert.equal(found.start, 7);
    assert.equal(found.replacement, "привет");
});

test("User rules are independent of dictionary auto correction", () => {
    const config = {
        autoEnabled:false, rulesEnabled:true,
        rules:[{from:"BRB",to:"be right back"}],
    };
    assert.deepEqual(core.findReplacement("brb",config), {
        start:0,before:"brb",replacement:"be right back",reason:"rule",
    });
    assert.equal(core.findReplacement("ghbdtn", config), null);
    assert.equal(core.findReplacement("BRB", {...config,rulesEnabled:false}), null);
});

test("User rule matching ignores case and does not expand within other words", () => {
    const config = {
        autoEnabled:false,
        rules:[{from:"брб",to:"Буду рад помочь"}],
    };
    assert.equal(core.findReplacement("БРБ",config).replacement,"Буду рад помочь");
    assert.equal(core.findReplacement("тестБРБ",config),null);
    assert.equal(core.findReplacement("тест_БРБ",config),null);
    assert.equal(core.findReplacement("тест2БРБ",config),null);
    assert.equal(core.findReplacement("тест БРБ",config).replacement,"Буду рад помочь");
});

test("Most specific rule wins regardless of its position in the list", () => {
    const config = {
        autoEnabled:false,
        rules:[
            {from:"б",to:"one"}, {from:"аб",to:"two"}, {from:"АБ",to:"three"}
        ],
    };
    assert.deepEqual(core.findReplacement("аб",config),{
        start:0,before:"аб",replacement:"two",reason:"rule",
    });
    assert.equal(core.findReplacement("шаб",config),null);
});

test("Rules with different layouts preserve their literal replacement", () => {
    const config = {
        autoEnabled:false, rulesEnabled:true,
        rules:[{from:"brb",to:"Скоро вернусь!"}],
    };
    assert.equal(core.findReplacement("brb",config).replacement,"Скоро вернусь!");
    assert.equal(core.findReplacement("ghbdtn", {...config,autoEnabled:true}).replacement,"привет");
});
