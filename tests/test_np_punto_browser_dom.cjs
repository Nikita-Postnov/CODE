"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../Other_dev/NP_Punto_Browser/layout_core.js");

const script = fs.readFileSync(path.join(__dirname, "../Other_dev/NP_Punto_Browser/content.js"), "utf8");

function harness(initial, rich = false, overrides = {}) {
    const callbacks = new Map();
    const pendingTimers = [];
    class HTMLElement {
        constructor() { this.isContentEditable = false; }
        closest(selector) {
            if (this.isContentEditable && selector === "[contenteditable]") return this;
            return null;
        }
        getAttribute(name) { return name === "contenteditable" && this.isContentEditable ? "true" : null; }
        dispatchEvent() { return true; }
    }
    class HTMLInputElement extends HTMLElement {
        constructor(value) {
            super();
            this.type = "text"; this.value = value;
            this.selectionStart = value.length; this.selectionEnd = value.length;
            this.autocomplete = ""; this.readOnly = false; this.disabled = false;
        }
        setRangeText(text, a, b) {
            this.value = this.value.slice(0,a) + text + this.value.slice(b);
            this.selectionStart = this.selectionEnd = a + text.length;
        }
    }
    class HTMLTextAreaElement extends HTMLInputElement {}
    class InputEvent {
        constructor(type, options) { this.type = type; Object.assign(this, options); }
    }
    class Range {
        constructor(node, start, end = start) {
            this.startContainer = node; this.endContainer = node;
            this.startOffset = start; this.endOffset = end;
            this.collapsed = start === end;
        }
        cloneRange() { return new Range(this.startContainer, this.startOffset, this.endOffset); }
        setStart(node, n) { this.startContainer = node; this.startOffset = n; this.collapsed = this.startOffset === this.endOffset; }
        setEnd(node, n) { this.endContainer = node; this.endOffset = n; this.collapsed = this.startOffset === this.endOffset; }
        collapse() { this.endContainer = this.startContainer; this.endOffset = this.startOffset; this.collapsed = true; }
    }
    const node = {nodeType:3, data:initial};
    const editor = new HTMLElement();
    editor.isContentEditable = true;
    editor.contains = target => target === node;
    let activeRange = new Range(node,initial.length);
    const selection = {
        rangeCount:1, getRangeAt:()=>activeRange,
        removeAllRanges(){this.rangeCount=0;},
        addRange(range){ activeRange=range; this.rangeCount=1; },
    };
    const doc = {
        addEventListener(name,cb) {
            if(!callbacks.has(name))callbacks.set(name,[]);
            callbacks.get(name).push(cb);
        },
        getSelection:()=>selection,
        execCommand(command,ignored,text) {
            assert.equal(command,"insertText");
            const current = selection.getRangeAt(0);
            node.data = node.data.slice(0,current.startOffset)+text+node.data.slice(current.endOffset);
            selection.addRange(new Range(node,current.startOffset+text.length));
            return true;
        },
    };
    const chrome = {
        runtime:{lastError:null},
        storage:{
            local:{
                get(defaults,cb){cb({...defaults,enabled:true,...overrides});},
                set(){},
            },
            onChanged:{addListener(){}},
        },
    };
    const field = rich ? editor : new HTMLInputElement(initial);
    const context = {
        NPPuntoCore:core, chrome, document:doc, location:{hostname:"chatgpt.com"},
        setTimeout:cb => {pendingTimers.push(cb);return pendingTimers.length;},
        HTMLElement, HTMLInputElement, HTMLTextAreaElement, InputEvent,
        Node:{TEXT_NODE:3}, Date, Object, String,
    };
    vm.runInNewContext(script,context);
    function fire(value) {
        let prevented = false;
        const event = {
            target:field, data:value, isTrusted:true,
            inputType:"insertText",isComposing:false,defaultPrevented:false,
            composedPath:()=>[field],
            preventDefault(){prevented=true;},
            stopPropagation(){},
        };
        for(const listener of callbacks.get("beforeinput") || []) listener(event);
        return prevented;
    }
    function fireKey(key, modifiers = {}) {
        let prevented = false;
        const event = {
            target:field, key, isTrusted:true, isComposing:false,defaultPrevented:false,
            altKey:modifiers.altKey || false,
            shiftKey:modifiers.shiftKey || false,
            ctrlKey:modifiers.ctrlKey || false,
            composedPath:()=>[field],
            preventDefault(){prevented=true;},
            stopPropagation(){},
        };
        for(const listener of callbacks.get("keydown") || []) listener(event);
        return prevented;
    }
    function fireNative(separator, domSeparator = separator) {
        const wasPrevented = fire(separator);
        if (wasPrevented) return true;
        if (rich) {
            const range = selection.getRangeAt(0);
            const caret = range.startOffset;
            node.data = node.data.slice(0, caret) + domSeparator + node.data.slice(caret);
            selection.addRange(new Range(node, caret + domSeparator.length));
        } else {
            const caret = field.selectionStart;
            field.setRangeText(domSeparator, caret, caret);
        }
        const event = {
            target:field, data:separator, inputType:"insertText",
            isTrusted:true, isComposing:false, composedPath:()=>[field],
        };
        for (const listener of callbacks.get("input") || []) listener(event);
        return false;
    }
    function flushTimers() {
        while (pendingTimers.length) pendingTimers.shift()();
    }
    return {field,node,selection,fire,fireKey,fireNative,flushTimers};
}

test("Plain ChatGPT-like input corrects whole phrase on final punctuation",()=>{
    const h=harness("xnj ntgthm evttn");
    assert.equal(h.fire("&"),true);
    assert.equal(h.field.value,"что теперь умеет?");
    assert.equal(h.field.selectionStart,"что теперь умеет?".length);
});

test("Plain input fixes first three-letter word immediately after space",()=>{
    const h=harness("xnj");
    assert.equal(h.fire(" "),true);
    assert.equal(h.field.value,"что ");
});

test("React-style contenteditable changes through native insertText command",()=>{
    const h=harness("xnj ntgthm evttn",true);
    assert.equal(h.fire("&"),true);
    assert.equal(h.node.data,"что теперь умеет?");
    assert.equal(h.selection.getRangeAt(0).startOffset,"что теперь умеет?".length);
});

test("Normal English is not rewritten",()=>{
    const h=harness("hello world");
    assert.equal(h.fire(" "),false);
    assert.equal(h.field.value,"hello world");
});

test("ChatGPT-style correction is undoable through native editor insertion",()=>{
    const h=harness("xnj ntgthm evttn",true);
    assert.equal(h.fire("&"),true);
    assert.equal(h.node.data,"что теперь умеет?");
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"xnj ntgthm evttn&");
});

test("Ctrl+Ins converts text before caret in a simple browser input",()=>{
    const h=harness("ghbdtn");
    assert.equal(h.fireKey("Insert",{ctrlKey:true}),true);
    assert.equal(h.field.value,"привет");
    assert.equal(h.field.selectionStart,6);
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.field.value,"ghbdtn");
});

test("Ctrl+Ins converts text before caret inside ChatGPT-style editor",()=>{
    const h=harness("xnj ntgthm evttn&",true);
    assert.equal(h.fireKey("Insert",{ctrlKey:true}),true);
    assert.equal(h.node.data,"что теперь умеет?");
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"xnj ntgthm evttn&");
});

test("Synthetic bridge shortcut works without a text selection",()=>{
    const h=harness("ghbdtn",true);
    assert.equal(h.fireKey("F8",{ctrlKey:true,altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"привет");
});

test("Ctrl+Ins converts selection instead of unrelated text",()=>{
    const h=harness("привет ghbdtn");
    h.field.selectionStart=7;
    h.field.selectionEnd=13;
    assert.equal(h.fireKey("Insert",{ctrlKey:true}),true);
    assert.equal(h.field.value,"привет привет");
});

test("Ctrl+Ins is ignored in password fields and with ambiguous combinations",()=>{
    const h=harness("ghbdtn");
    h.field.type="password";
    assert.equal(h.fireKey("Insert",{ctrlKey:true}),false);
    assert.equal(h.field.value,"ghbdtn");
    h.field.type="text";
    assert.equal(h.fireKey("Insert",{ctrlKey:true,altKey:true}),false);
    assert.equal(h.field.value,"ghbdtn");
});

test("Browser Ctrl+Ins stays local to current editor and prevents default only on success",()=>{
    const h=harness("hello world");
    // An existing English phrase changes only on an explicit manual request.
    assert.equal(h.fireKey("Insert",{ctrlKey:true}),true);
    assert.equal(h.field.value,"руддщ цщкдв");
});

test("User rule works even with dictionary correction switched off in a plain input",()=>{
    const h=harness("brb", false, {
        enabled:false, rulesEnabled:true,
        rules:[{from:"brb",to:"be right back"}],
    });
    assert.equal(h.fireNative(" "),false);
    h.flushTimers();
    assert.equal(h.field.value,"be right back ");
});

test("Custom rule expands inside a ChatGPT-style editor without layout autocorrection",()=>{
    const h=harness("БРБ", true, {
        enabled:false, rulesEnabled:true,
        rules:[{from:"брб",to:"Буду рад помочь"}],
    });
    assert.equal(h.fireNative(" "),false);
    h.flushTimers();
    assert.equal(h.node.data,"Буду рад помочь ");
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"БРБ ");
});

test("Rule delimiter is retained verbatim, even when replacement changes language",()=>{
    const h=harness("brb", false, {
        enabled:false, rulesEnabled:true,
        rules:[{from:"brb",to:"вернулся"}],
    });
    assert.equal(h.fireNative("&"),false);
    h.flushTimers();
    assert.equal(h.field.value,"вернулся&");
});

test("Disabling custom rules does not accidentally enable dictionary correction",()=>{
    const h=harness("brb", false, {
        enabled:false, rulesEnabled:false,
        rules:[{from:"brb",to:"be right back"}],
    });
    assert.equal(h.fireNative(" "),false);
    h.flushTimers();
    assert.equal(h.field.value,"brb ");
});

test("Disabled rules do not suppress normal dictionary correction",()=>{
    const h=harness("ghbdtn", true, {
        enabled:true, rulesEnabled:false,
        rules:[{from:"ghbdtn",to:"Другое"}],
    });
    assert.equal(h.fire(" "),true);
    assert.equal(h.node.data,"привет ");
});

test("Partial rule inside a larger word is not expanded",()=>{
    const h=harness("xbrb", false, {
        enabled:false, rulesEnabled:true,
        rules:[{from:"brb",to:"be right back"}],
    });
    assert.equal(h.fireNative(" "),false);
    h.flushTimers();
    assert.equal(h.field.value,"xbrb ");
});

test("Real user case: saved ща - сейчас rule replaces text after native space in ChatGPT",()=>{
    const h=harness("ща", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    assert.equal(h.fireNative(" "),false);
    assert.equal(h.node.data,"ща ");
    h.flushTimers();
    assert.equal(h.node.data,"сейчас ");
    assert.equal(h.selection.getRangeAt(0).startOffset,7);
});

test("Real user case: user rule corrects after native space in plain input",()=>{
    const h=harness("ща", false, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    assert.equal(h.fireNative(" "),false);
    h.flushTimers();
    assert.equal(h.field.value,"сейчас ");
});

test("Post-input rule does not affect other words or force unsupported replacements",()=>{
    const h=harness("пища", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    h.fireNative(" ");
    h.flushTimers();
    assert.equal(h.node.data,"пища ");
});

test("Post-input rules allow regular punctuation and preserve it exactly",()=>{
    const h=harness("ща", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    h.fireNative("!");
    h.flushTimers();
    assert.equal(h.node.data,"сейчас!");
});

test("Changing field text before scheduled rule safely cancels pending action",()=>{
    const h=harness("ща", false, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    h.fireNative(" ");
    h.field.setRangeText("д",3,3);
    h.flushTimers();
    assert.equal(h.field.value,"ща д");
});

test("Post-input rich text correction remains undoable",()=>{
    const h=harness("ща", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    h.fireNative(" ");
    h.flushTimers();
    assert.equal(h.node.data,"сейчас ");
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"ща ");
});

test("Chrome contenteditable NBSP is accepted when Space generates U+00A0 in DOM",()=>{
    const h=harness("ща", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    // InputEvent.data is a regular space, but contenteditable stores NBSP.
    h.fireNative(" ", "\u00a0");
    h.flushTimers();
    assert.equal(h.node.data,"сейчас ");
    assert.equal(h.fireKey("Backspace",{altKey:true,shiftKey:true}),true);
    assert.equal(h.node.data,"ща\u00a0");
});

test("NBSP after user typing never triggers replacement without matching rule",()=>{
    const h=harness("пища", true, {
        enabled:false, rulesEnabled:true, rules:[{from:"ща",to:"сейчас"}],
    });
    h.fireNative(" ", "\u00a0");
    h.flushTimers();
    assert.equal(h.node.data,"пища\u00a0");
});
