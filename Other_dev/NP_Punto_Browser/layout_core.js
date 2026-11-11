/* Общее чистое ядро исправления раскладки. Не читает DOM и не обращается к сети. */
(function (root, factory) {
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    root.NPPuntoCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";
    const pairs = {
        q: "й", w: "ц", e: "у", r: "к", t: "е", y: "н", u: "г", i: "ш", o: "щ", p: "з",
        "[": "х", "]": "ъ", a: "ф", s: "ы", d: "в", f: "а", g: "п", h: "р", j: "о",
        k: "л", l: "д", ";": "ж", "'": "э", z: "я", x: "ч", c: "с", v: "м",
        b: "и", n: "т", m: "ь", ",": "б", ".": "ю", "`": "ё",
    };
    const enToRu = new Map(Object.entries(pairs));
    const ruToEn = new Map([...enToRu.entries()].map(([a, b]) => [b, a]));
    const defaultWords = [
        "привет", "спасибо", "здравствуйте", "пожалуйста", "сегодня", "завтра",
        "вчера", "хорошо", "плохо", "работа", "работает", "работать", "можно",
        "нужно", "конечно", "почему", "когда", "сколько", "какой", "какая",
        "какие", "сделать", "сделай", "проверить", "программа", "приветствие",
        "система", "настройки", "помощь", "сообщение", "вопрос", "ответ",
        "задача", "данные", "файл", "файлы", "папка", "проблема", "исправить",
        "исправление", "переключение", "раскладка", "пожалуй", "возможно",
        "добавить", "сохранить", "открыть", "закрыть", "запустить", "обновить",
        "загрузка", "проверка", "продолжить", "спокойно", "быстро", "удобно",
        "понятно", "готово", "проверено", "тестирование", "применить",
        "выбрать", "выбери", "поменять", "изменить", "запомнить", "написать",
        "должно", "должен", "должна", "проект", "проектов", "программист",
        "hello", "thanks", "please", "welcome", "today", "tomorrow", "yesterday",
        "good", "morning", "evening", "working", "settings", "update",
        "message", "problem", "program", "keyboard", "language", "layout",
        "change", "convert", "write", "open", "close", "check", "ready",
    ];
    function lettersKind(value) {
        const latin = /^[a-z]+$/i, russian = /^[а-яё]+$/i;
        if (latin.test(value)) return "en";
        if (russian.test(value)) return "ru";
        return null;
    }
    function convertText(value) {
        const text = String(value ?? "");
        const en = (text.match(/[a-z]/gi) || []).length;
        const ru = (text.match(/[а-яё]/gi) || []).length;
        if (en === 0 && ru === 0) return text;
        const table = en > ru ? enToRu : ruToEn;
        return [...text].map(char => {
            const mapped = table.get(char.toLowerCase());
            return mapped === undefined ? char : char !== char.toLowerCase() ? mapped.toUpperCase() : mapped;
        }).join("");
    }
    function normalizeWords(value) {
        const items = Array.isArray(value) ? value : String(value || "").split(/\r?\n/u);
        return [...new Set(items.map(x => String(x).trim().toLowerCase())
            .filter(word => word.length >= 4 && word.length <= 32 && lettersKind(word)))].slice(0, 5000);
    }
    function candidate(raw, words, previousWord = "") {
        if (raw.length < 4 || raw.length > 32 || !lettersKind(raw)) return null;
        const known = words instanceof Set ? words : new Set(normalizeWords(words));
        if (known.has(raw.toLowerCase())) return null;
        const converted = convertText(raw);
        if (!known.has(converted.toLowerCase()) || converted.toLowerCase() === raw.toLowerCase()) return null;
        const previousKind = lettersKind(previousWord);
        const targetKind = lettersKind(converted);
        const confidence = previousKind && targetKind && previousKind === targetKind ? 0.99 : 0.97;
        return { replacement: converted, confidence, reason: "dictionary" };
    }
    function findReplacement(prefix, configuration) {
        const rules = Array.isArray(configuration.rules) ? configuration.rules : [];
        for (const item of rules) {
            if (!item || typeof item.from !== "string" || typeof item.to !== "string" ||
                item.from.length < 2 || item.from.length > 64 || item.to.length > 256) continue;
            if (prefix.endsWith(item.from)) {
                const start = prefix.length - item.from.length;
                if (start > 0 && /[\p{L}\p{N}]/u.test(prefix[start - 1])) continue;
                return { start, before: item.from, replacement: item.to, reason: "rule" };
            }
        }
        const match = prefix.match(/[A-Za-zА-Яа-яЁё]+$/u);
        if (!match) return null;
        const start = prefix.length - match[0].length;
        const prev = prefix.slice(0, start).match(/[A-Za-zА-Яа-яЁё]+(?=[^A-Za-zА-Яа-яЁё]*$)/u);
        const words = new Set(normalizeWords([...(configuration.words || []), ...(configuration.learnedWords || [])]));
        const result = candidate(match[0], words, prev ? prev[0] : "");
        if (!result || result.confidence < 0.95) return null;
        return { start, before: match[0], replacement: result.replacement, reason: result.reason };
    }
    function isExcludedHost(hostname, values) {
        const host = String(hostname || "").toLowerCase();
        return (values || []).some(value => {
            const name = String(value || "").trim().toLowerCase().replace(/^\./u, "");
            return name && (host === name || host.endsWith("." + name));
        });
    }
    return Object.freeze({
        convertText, normalizeWords, candidate, findReplacement, isExcludedHost,
        lettersKind, defaultWords: Object.freeze(defaultWords.slice()),
    });
});
