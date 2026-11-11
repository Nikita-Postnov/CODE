/* Локальная обработка HTML-полей; содержимое ввода никуда не передаётся. */
(() => {
    "use strict";
    const core = globalThis.NPPuntoCore;
    if (!core || !globalThis.chrome?.storage?.local) return;

    const defaults = {
        enabled: false, learnManual: false,
        words: core.defaultWords, learnedWords: [], rules: [],
        excludedHosts: [],
    };
    let settings = { ...defaults };
    let lastChange = null;
    let applyingCorrection = false;

    function refresh() {
        chrome.storage.local.get(defaults, result => {
            if (chrome.runtime?.lastError) return;
            settings = { ...defaults, ...result };
        });
    }
    refresh();
    chrome.storage.onChanged.addListener((changes, area) => {
        if (area !== "local") return;
        for (const [key, change] of Object.entries(changes)) {
            if (Object.hasOwn(defaults, key)) settings[key] = change.newValue ?? defaults[key];
        }
    });

    function disabledOnThisSite() {
        return core.isExcludedHost(location.hostname, settings.excludedHosts);
    }

    function editingTarget(event) {
        const path = typeof event.composedPath === "function" ? event.composedPath() : [event.target];
        const target = path.find(node => node instanceof HTMLElement &&
            (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement ||
             node.isContentEditable));
        if (!target || disabledOnThisSite()) return null;
        if (target.closest("[data-np-punto-off], pre, code, [role='code'], [aria-readonly='true']")) return null;
        if (target instanceof HTMLInputElement) {
            const type = (target.type || "text").toLowerCase();
            if (!["text", "search"].includes(type) || target.readOnly || target.disabled) return null;
            const autocomplete = (target.autocomplete || "").toLowerCase();
            if (/password|one-time-code|cc-|off-secret/u.test(autocomplete)) return null;
            return target;
        }
        if (target instanceof HTMLTextAreaElement) {
            if (target.readOnly || target.disabled) return null;
            return target;
        }
        const editor = target.closest("[contenteditable]");
        if (!editor || editor.getAttribute("contenteditable") === "false" ||
            editor.closest("[role='code'], [data-np-punto-off]")) return null;
        return editor;
    }

    function isPlainField(field) {
        return field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement;
    }

    function dispatchInput(field, text) {
        field.dispatchEvent(new InputEvent("input", {
            bubbles: true, composed: true, inputType: "insertReplacementText", data: text,
        }));
    }

    function setPlainText(field, start, end, replacement) {
        const before = field.value.slice(start, end);
        field.setRangeText(replacement, start, end, "end");
        dispatchInput(field, replacement);
        return before;
    }

    function saveUndo(field, start, before, after, textNode = null) {
        lastChange = { field, start, before, after, textNode, when: Date.now() };
    }

    function autoReplacePlain(field, separator) {
        const caret = field.selectionStart;
        if (caret === null || caret !== field.selectionEnd) return false;
        const prefix = field.value.slice(0, caret);
        const found = core.findReplacement(prefix, settings);
        if (!found) return false;
        const original = found.before + separator;
        const replacement = found.replacement +
            core.correctedSeparator(separator, found.before, found.replacement);
        setPlainText(field, found.start, caret, replacement);
        saveUndo(field, found.start, original, replacement);
        return true;
    }

    function singleNodeSelection(editor) {
        const selection = document.getSelection();
        if (!selection || selection.rangeCount !== 1) return null;
        const range = selection.getRangeAt(0);
        const node = range.startContainer;
        if (node !== range.endContainer || node.nodeType !== Node.TEXT_NODE ||
            !editor.contains(node)) return null;
        return { range, node };
    }

    function replaceInEditable(editor, info, start, end, replacement) {
        // Rich-text-редакторы (включая ProseMirror) требуют штатной команды ввода.
        // Прямая замена TextNode не всегда обновляет их внутреннюю модель.
        const { node, range } = info;
        const previousText = node.data.slice(start, end);
        const selection = document.getSelection();
        const savedRange = range.cloneRange();
        const replaceRange = range.cloneRange();
        replaceRange.setStart(node, start);
        replaceRange.setEnd(node, end);
        selection.removeAllRanges();
        selection.addRange(replaceRange);
        let inserted = false;
        try {
            applyingCorrection = true;
            inserted = document.execCommand("insertText", false, replacement) === true;
        } catch (_error) {
            inserted = false;
        } finally {
            applyingCorrection = false;
            if (!inserted) {
                selection.removeAllRanges();
                selection.addRange(savedRange);
            }
        }
        if (!inserted) return false;
        const after = singleNodeSelection(editor);
        if (after && after.range.collapsed) {
            saveUndo(editor, after.range.startOffset - replacement.length,
                previousText, replacement, after.node);
        } else {
            lastChange = null;
        }
        return true;
    }

    function autoReplaceEditable(editor, separator) {
        const info = singleNodeSelection(editor);
        if (!info || !info.range.collapsed) return false;
        const { node, range } = info;
        const caret = range.startOffset;
        const prefix = node.data.slice(0, caret);
        const found = core.findReplacement(prefix, settings);
        if (!found) return false;
        const replacement = found.replacement +
            core.correctedSeparator(separator, found.before, found.replacement);
        return replaceInEditable(editor, info, found.start, caret, replacement);
    }

    document.addEventListener("beforeinput", event => {
        if (applyingCorrection) return;
        if (event.isTrusted) lastChange = null;
        if (!settings.enabled || event.defaultPrevented || event.isComposing ||
            event.inputType !== "insertText" || typeof event.data !== "string" ||
            !/^[ .,!?;:&@#$^|~]$/u.test(event.data)) return;
        const field = editingTarget(event);
        if (!field) return;
        let didReplace = false;
        try {
            didReplace = isPlainField(field)
                ? autoReplacePlain(field, event.data)
                : autoReplaceEditable(field, event.data);
        } catch (_error) {
            // Нестандартный редактор может отвергнуть изменение; штатный ввод остаётся.
            return;
        }
        if (didReplace) event.preventDefault();
    }, true);

    function manuallyConvert(field) {
        if (isPlainField(field)) {
            const start = field.selectionStart, end = field.selectionEnd;
            if (start === null || end === null || end <= start || end - start > 10000) return false;
            const source = field.value.slice(start, end);
            const converted = core.convertText(source);
            if (source === converted) return false;
            setPlainText(field, start, end, converted);
            saveUndo(field, start, source, converted);
            learn(source, converted);
            return true;
        }
        const info = singleNodeSelection(field);
        if (!info || info.range.collapsed) return false;
        const { node, range } = info;
        const start = range.startOffset, end = range.endOffset;
        if (end - start > 10000) return false;
        const source = node.data.slice(start, end);
        const converted = core.convertText(source);
        if (source === converted) return false;
        if (!replaceInEditable(field, info, start, end, converted)) return false;
        learn(source, converted);
        return true;
    }

    function learn(source, converted) {
        if (!settings.learnManual || !core.lettersKind(source) ||
            !core.lettersKind(converted) || converted.length < 4 ||
            converted.length > 32 || source.length > 32 || converted.length < 3) return;
        const word = converted.toLowerCase();
        const list = core.normalizeWords(settings.learnedWords);
        if (list.includes(word) || list.length >= 1000) return;
        settings.learnedWords = [...list, word];
        chrome.storage.local.set({ learnedWords: settings.learnedWords });
    }

    function undo(field) {
        const entry = lastChange;
        if (!entry || entry.field !== field || Date.now() - entry.when > 10000) return false;
        if (isPlainField(field)) {
            const end = entry.start + entry.after.length;
            if (field.value.slice(entry.start, end) !== entry.after ||
                field.selectionStart !== end || field.selectionEnd !== end) return false;
            setPlainText(field, entry.start, end, entry.before);
        } else {
            const info = singleNodeSelection(field);
            if (!info || !info.range.collapsed || info.node !== entry.textNode) return false;
            const end = entry.start + entry.after.length;
            if (info.node.data.slice(entry.start, end) !== entry.after ||
                info.range.startOffset !== end) return false;
            if (entry.start < 0 || !replaceInEditable(
                field, info, entry.start, end, entry.before)) return false;
        }
        lastChange = null;
        return true;
    }

    document.addEventListener("keydown", event => {
        if (event.defaultPrevented || event.isComposing) return;
        const field = editingTarget(event);
        if (!field) return;
        const manual = event.ctrlKey && event.altKey && event.shiftKey && event.key === "F8";
        const revert = !event.ctrlKey && event.altKey && event.shiftKey && event.key === "Backspace";
        if (!manual && !revert) return;
        const success = manual ? manuallyConvert(field) : undo(field);
        if (success) {
            event.preventDefault();
            event.stopPropagation();
        }
    }, true);

})();
