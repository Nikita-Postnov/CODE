"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
    path.join(__dirname,"../Other_dev/NP_Punto_Browser/background.js"),"utf8"
);
function setup() {
    let listener;
    const sent=[];
    const chrome={
        runtime:{
            lastError:null,
            getURL:()=> "chrome-extension://abcdefghijklmnopabcdefghijklmnop/",
            onMessage:{addListener(fn){listener=fn;}},
            sendNativeMessage(host,message,callback){
                sent.push({host,message});
                callback({ok:true,status:message.action==="ping"?"ready":"switched"});
            },
        },
    };
    vm.runInNewContext(source,{chrome,Object,String});
    function send(message,sender={tab:{id:4,active:true}}) {
        let response;
        const waiting=listener(message,sender,value=>{response=value;});
        return {waiting,response};
    }
    return {send,sent,chrome};
}
test("Background forwards just RU/EN without text or URLs",()=>{
    const h=setup();
    const result=h.send({action:"np-punto-switch-layout",language:"ru",text:"private",url:"https://site"});
    assert.equal(result.waiting,true);
    assert.equal(result.response.status,"switched");
    assert.equal(h.sent.length,1);
    assert.equal(h.sent[0].host,"com.npcore.punto_layout");
    assert.deepEqual(JSON.parse(JSON.stringify(h.sent[0].message)),
        {action:"switch",language:"ru"});
});
test("Background rejects inactive tabs and arbitrary layouts",()=>{
    const h=setup();
    assert.equal(h.send({action:"np-punto-switch-layout",language:"fr"}).response.ok,false);
    assert.equal(h.send({action:"np-punto-switch-layout",language:"ru"},{tab:{id:4,active:false}}).response.ok,false);
    assert.equal(h.send({action:"np-punto-switch-layout",language:"ru"},{url:"https://attacker"}).response.ok,false);
    assert.equal(h.sent.length,0);
});
test("Extension options can ping native host without any key events",()=>{
    const h=setup();
    const result=h.send({action:"np-punto-test-native"},
        {url:"chrome-extension://abcdefghijklmnopabcdefghijklmnop/options.html"});
    assert.equal(result.waiting,true);
    assert.equal(result.response.status,"ready");
    assert.deepEqual(JSON.parse(JSON.stringify(h.sent[0].message)),{action:"ping"});
});
test("A website or another extension cannot invoke the options ping",()=>{
    const h=setup();
    const result=h.send({action:"np-punto-test-native"},{url:"https://site.example/"});
    assert.equal(result.response.ok,false);
    assert.equal(h.sent.length,0);
});
test("Native host failure does not block browser input",()=>{
    const h=setup();
    h.chrome.runtime.sendNativeMessage=(host,message,callback)=>{
        h.chrome.runtime.lastError={message:"Native host missing"};
        callback();
    };
    const result=h.send({action:"np-punto-switch-layout",language:"en"});
    assert.equal(result.response.ok,false);
    assert.equal(result.response.status,"native_host_unavailable");
});
