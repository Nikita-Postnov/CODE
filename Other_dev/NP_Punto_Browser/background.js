// Isolated extension service worker. The native host receives ONLY "ru" or "en".
// Web page text, URLs, form values and clipboard contents never leave the page.
"use strict";
const HOST = "com.npcore.punto_layout";
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message !== "object") return false;
    const isSwitch = message.action === "np-punto-switch-layout";
    const isPing = message.action === "np-punto-test-native";
    if (!isSwitch && !isPing) return false;

    // Never grant any website external access to this listener.
    if (isSwitch && (
        !sender.tab || sender.tab.active !== true ||
        !["ru", "en"].includes(message.language)
    )) {
        sendResponse({ ok: false, status: "inactive_or_invalid" });
        return false;
    }
    if (isPing && (
        sender.tab || !String(sender.url || "").startsWith(chrome.runtime.getURL(""))
    )) {
        sendResponse({ ok: false, status: "unauthorized" });
        return false;
    }
    const request = isPing ? { action: "ping" } :
        { action: "switch", language: message.language };
    try {
        chrome.runtime.sendNativeMessage(HOST, request, response => {
            if (chrome.runtime.lastError) {
                sendResponse({ ok: false, status: "native_host_unavailable" });
                return;
            }
            sendResponse({
                ok: response?.ok === true || response?.status === "ready",
                status: typeof response?.status === "string"
                    ? response.status : "no_response",
            });
        });
    } catch (_error) {
        sendResponse({ ok: false, status: "native_host_unavailable" });
    }
    return true;
});
