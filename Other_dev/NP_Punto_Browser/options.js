(() => {
    "use strict";
    const core = globalThis.NPPuntoCore;
    const el = id => document.getElementById(id);
    const defaults = {
        enabled: false, rulesEnabled: true, learnManual: false, words: core.defaultWords,
        learnedWords: [], rules: [], excludedHosts: [],
    };
    const lines = value => value.split(/\r?\n/u).map(x => x.trim()).filter(Boolean);
    function report(message, success = true) {
        el("status").textContent = message;
        el("status").style.color = success ? "inherit" : "#bf3333";
    }
    function load() {
        chrome.storage.local.get(defaults, values => {
            if (chrome.runtime.lastError) {
                report("Не удалось прочитать локальные настройки.", false);
                return;
            }
            el("enabled").checked = Boolean(values.enabled);
            el("rulesEnabled").checked = values.rulesEnabled !== false;
            el("learn").checked = Boolean(values.learnManual);
            el("words").value = (values.words || []).join("\n");
            el("hosts").value = (values.excludedHosts || []).join("\n");
            el("rules").value = (values.rules || []).map(r => r.from + " => " + r.to).join("\n");
            report("Настройки загружены. Подтверждённых слов: " + (values.learnedWords || []).length);
        });
    }
    function parseRules() {
        const rules = [];
        const seen = new Set();
        for (const line of lines(el("rules").value)) {
            const pos = line.indexOf("=>");
            if (pos === -1) {
                return { error: "Неверное правило: требуется разделитель =>." };
            }
            const from = line.slice(0, pos).trim();
            const to = line.slice(pos + 2).trim();
            if (!from || from.length > 64 || !to || to.length > 256 || rules.length >= 250) {
                return { error: "Проверьте длину и количество правил (до 250)." };
            }
            if (seen.has(from.toLowerCase())) {
                return { error: "Повторяющееся сокращение: " + from };
            }
            seen.add(from.toLowerCase());
            rules.push({ from, to });
        }
        return { rules };
    }

    el("testRule").addEventListener("click", () => {
        const { rules, error } = parseRules();
        const result = el("ruleTestResult");
        if (error) {
            result.textContent = error;
            return;
        }
        if (!el("rulesEnabled").checked) {
            result.textContent = "Правила выключены. Включите «Автоматически применять мои правила».";
            return;
        }
        const phrase = el("ruleTest").value.trimEnd();
        const found = core.findReplacement(phrase, {
            rules, rulesEnabled: true, autoEnabled: false,
        });
        result.textContent = found
            ? "Сработает: " + phrase.slice(0, found.start) + found.replacement
            : "Совпадающее правило не найдено.";
    });

    el("save").addEventListener("click", () => {
        const words = core.normalizeWords(lines(el("words").value));
        const hosts = [...new Set(lines(el("hosts").value).map(x => x.toLowerCase().replace(/^\./u, "")))];
        if (hosts.length > 300 || !hosts.every(x => /^[a-z0-9.-]+$/u.test(x) && x.includes(".") &&
            !x.startsWith(".") && !x.endsWith("."))) {
            report("Проверьте список доменов-исключений.", false);
            return;
        }
        const { rules, error } = parseRules();
        if (error) {
            report(error, false);
            return;
        }
        chrome.storage.local.set({
            enabled: el("enabled").checked,
            rulesEnabled: el("rulesEnabled").checked,
            learnManual: el("learn").checked,
            words, excludedHosts: hosts, rules,
        }, () => {
            if (chrome.runtime.lastError) {
                report("Ошибка сохранения: " + chrome.runtime.lastError.message, false);
                return;
            }
            report("Настройки сохранены. Слов: " + words.length + ". Правил: " + rules.length +
                ". Пользовательские правила: " + (el("rulesEnabled").checked ? "включены" : "выключены"));
        });
    });
    el("clear").addEventListener("click", () => {
        if (!confirm("Очистить только слова, запомненные после ручных исправлений?")) return;
        chrome.storage.local.set({ learnedWords: [] }, () => {
            report(chrome.runtime.lastError ? "Не удалось очистить словарь." : "Выученные слова очищены.",
                !chrome.runtime.lastError);
        });
    });
    load();
})();
