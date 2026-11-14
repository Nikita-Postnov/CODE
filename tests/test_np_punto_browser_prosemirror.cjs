"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const core = require("../Other_dev/NP_Punto_Browser/layout_core.js");

const script = fs.readFileSync(
    path.join(__dirname, "../Other_dev/NP_Punto_Browser/content.js"), "utf8"
);

function fixture(parts, position = "element-caret") {
    const callbacks = new Map();
    class HTMLElement {
        constructor(tag = "div") {
            this.tagName = tag.toUpperCase();
            this.nodeType = 1;
            this.childNodes = [];
            this.parentNode = null;
            this.parentElement = null;
            this.isContentEditable = false;
        }
        append(node) {
            this.childNodes.push(node);
            node.parentNode = this;
            node.parentElement = this;
        }
        matches(selector) {
            if (selector.includes("p, li") && this.tagName === "P") return true;
            return false;
        }
        closest(selector) {
            if (selector === "[contenteditable]") {
                let current = this;
                while (current) {
                    if (current.explicitContenteditable) return current;
                    current = current.parentElement;
                }
                return null;
            }
            return null;
        }
        contains(node) {
            while (node) {
                if (node === this) return true;
                node = node.parentNode;
            }
            return false;
        }
    }
    class HTMLInputElement extends HTMLElement {}
    class HTMLTextAreaElement extends HTMLElement {}
    class InputEvent {
        constructor(name, options) { Object.assign(this, options); this.name = name; }
    }
    class TextNode {
        constructor(data) {
            this.nodeType = 3;
            this.data = data;
            this.parentNode = null;
            this.parentElement = null;
        }
    }
    const editor = new HTMLElement("div");
    editor.explicitContenteditable = true;
    editor.isContentEditable = true;
    const paragraph = new HTMLElement("p");
    paragraph.isContentEditable = true;
    editor.append(paragraph);
    for (const text of parts) paragraph.append(new TextNode(text));

    function textLength(node) {
        if (node.nodeType === 3) return node.data.length;
        return node.childNodes.reduce((sum, child) => sum + textLength(child), 0);
    }
    function textContent(node) {
        if (node.nodeType === 3) return node.data;
        return node.childNodes.map(textContent).join("");
    }
    function positionOf(container, offset) {
        let position = 0, found = false;
        function visit(node) {
            if (found) return;
            if (node === container) {
                if (node.nodeType === 3) position += offset;
                else {
                    for (let i = 0; i < offset; i++) position += textLength(node.childNodes[i]);
                }
                found = true;
                return;
            }
            if (node.nodeType === 3) {
                position += node.data.length;
            } else {
                for (const child of node.childNodes) visit(child);
            }
        }
        visit(paragraph);
        assert.ok(found, "Caret must belong to the current paragraph");
        return position;
    }
    class Range {
        constructor(startContainer, startOffset, endContainer = startContainer, endOffset = startOffset) {
            this.startContainer = startContainer;
            this.startOffset = startOffset;
            this.endContainer = endContainer;
            this.endOffset = endOffset;
            this._update();
        }
        _update() {
            this.collapsed = this.startContainer === this.endContainer &&
                this.startOffset === this.endOffset;
        }
        cloneRange() {
            return new Range(this.startContainer, this.startOffset,
                this.endContainer, this.endOffset);
        }
        selectNodeContents(node) {
            this.startContainer = node;
            this.startOffset = 0;
            this.endContainer = node;
            this.endOffset = node.nodeType === 3 ? node.data.length : node.childNodes.length;
            this._update();
        }
        setStart(node, offset) {
            this.startContainer = node;
            this.startOffset = offset;
            this._update();
        }
        setEnd(node, offset) {
            this.endContainer = node;
            this.endOffset = offset;
            this._update();
        }
        toString() {
            return textContent(paragraph).slice(
                positionOf(this.startContainer, this.startOffset),
                positionOf(this.endContainer, this.endOffset)
            );
        }
    }

    const first = paragraph.childNodes[0], last = paragraph.childNodes.at(-1);
    let activeRange;
    if (position === "element-caret") {
        activeRange = new Range(paragraph, paragraph.childNodes.length);
    } else if (position === "text-caret") {
        activeRange = new Range(last, last.data.length);
    } else if (position === "multi-selection") {
        activeRange = new Range(first, 0, last, last.data.length);
    } else {
        throw Error("Unknown selection type");
    }

    const selection = {
        rangeCount: 1,
        getRangeAt: () => activeRange,
        removeAllRanges() { this.rangeCount = 0; },
        addRange(range) { activeRange = range; this.rangeCount = 1; },
    };
    const document = {
        addEventListener(name, callback) {
            if (!callbacks.has(name)) callbacks.set(name, []);
            callbacks.get(name).push(callback);
        },
        getSelection() { return selection; },
        execCommand(command, unused, replacement) {
            assert.equal(command, "insertText");
            const range = selection.getRangeAt(0);
            const text = textContent(paragraph);
            const start = positionOf(range.startContainer, range.startOffset);
            const end = positionOf(range.endContainer, range.endOffset);
            const node = new TextNode(text.slice(0, start) + replacement + text.slice(end));
            paragraph.childNodes = [];
            paragraph.append(node);
            selection.addRange(new Range(node, start + replacement.length));
            return true;
        },
    };
    const chrome = {
        runtime: { lastError: null },
        storage: {
            local: {
                get(defaults, callback) { callback({ ...defaults, enabled: false }); },
                set() {},
            },
            onChanged: { addListener() {} },
        },
    };
    vm.runInNewContext(script, {
        document, chrome, NPPuntoCore: core, location: { hostname: "chatgpt.com" },
        HTMLElement, HTMLInputElement, HTMLTextAreaElement, InputEvent,
        Node: { TEXT_NODE: 3 }, setTimeout,
    });
    function key(key, modifiers = {}) {
        let prevented = false;
        const event = {
            target: paragraph,
            composedPath: () => [paragraph, editor],
            key,
            code: key,
            isComposing: false,
            defaultPrevented: false,
            ctrlKey: !!modifiers.ctrlKey,
            altKey: !!modifiers.altKey,
            shiftKey: !!modifiers.shiftKey,
            preventDefault() { prevented = true; },
            stopPropagation() {},
        };
        for (const callback of callbacks.get("keydown") || []) callback(event);
        return prevented;
    }
    return { paragraph, selection, key, getText: () => textContent(paragraph) };
}

test("Ctrl+Insert converts a split word at the end of a ProseMirror paragraph", () => {
    const f = fixture(["ghb", "dtn"]);
    assert.equal(f.key("Insert", { ctrlKey: true }), true);
    assert.equal(f.getText(), "привет");
});

test("Ctrl+Insert also converts a split word when caret is in the final text node", () => {
    const f = fixture(["ghb", "dtn"], "text-caret");
    assert.equal(f.key("Insert", { ctrlKey: true }), true);
    assert.equal(f.getText(), "привет");
});

test("Ctrl+Insert converts a cross-node selection without losing editor state", () => {
    const f = fixture(["xnj", " ntgthm"], "multi-selection");
    assert.equal(f.key("Insert", { ctrlKey: true }), true);
    assert.equal(f.getText(), "что теперь");
});

test("A synthetic browser bridge shortcut handles the same ProseMirror caret", () => {
    const f = fixture(["gh", "bdtn"]);
    assert.equal(f.key("F8", { ctrlKey: true, altKey: true, shiftKey: true }), true);
    assert.equal(f.getText(), "привет");
});
