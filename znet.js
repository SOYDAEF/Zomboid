/* ZNet - conexión entre navegadores con WebRTC (sin librerías).
 *
 * Uso (pensado para llamarse también desde Python/pygbag, sin callbacks: se consulta con pop()):
 *   ZNet.config({signal:"ntfy"})     // opcional
 *   ZNet.host()                      // crea una sala; ZNet.code() da el código
 *   ZNet.join("ABC123")              // se une a una sala
 *   ZNet.status()                    // idle | hosting | joining | connected | error:...
 *   ZNet.send(texto [, idDestino])   // el anfitrión sin destino = a todos
 *   ZNet.pop()                       // "" o JSON {"from":id,"data":texto} / {"sys":"join"|"leave","from":id}
 *   ZNet.peers()                     // conexiones abiertas
 *   ZNet.close()
 *
 * El "primer contacto" (señalización) viaja por un servicio público (ntfy.sh); los datos del juego
 * van directos entre navegadores (WebRTC DataChannel). */
(function () {
  "use strict";
  var ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  var CHUNK = 15000;       // mensajes más largos se parten (algunos navegadores limitan ~16 KB)
  var SIG_CHUNK = 2800;    // ntfy limita cada mensaje a 4 KB
  var cfg = { signal: "ntfy", base: "https://ntfy.sh", prefix: "zomboid-rtc",
              stun: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"], max: 5 };
  var S = null;

  function fresh() {
    return { status: "idle", code: "", id: "", role: "", conns: {}, inbox: [], logs: [], stopSig: null,
             parts: {}, seq: 0, retry: null };
  }
  S = fresh();

  function log(m) { S.logs.push(m); if (S.logs.length > 300) S.logs.shift(); if (window.console) console.log("[ZNet] " + m); }
  function rid(n) {
    var a = new Uint32Array(n), s = "";
    (window.crypto || window.msCrypto).getRandomValues(a);
    for (var i = 0; i < n; i++) s += ALPHA[a[i] % ALPHA.length];
    return s;
  }
  function setErr(m) { S.status = "error:" + m; log("ERROR " + m); }

  /* ---------------- señalización ---------------- */
  function topic(room, to) { return cfg.prefix + "-" + room + "-" + to; }

  function sigSendRaw(room, to, text) {
    if (cfg.signal === "local")
      return fetch(cfg.base + "/sig/send?room=" + room + "&to=" + to, { method: "POST", body: text });
    return fetch(cfg.base + "/" + topic(room, to), { method: "POST", body: text });
  }
  function sigSend(room, to, obj) {          // parte los mensajes largos en trozos
    var text = JSON.stringify(obj), id = rid(6), n = Math.ceil(text.length / SIG_CHUNK), jobs = [];
    for (var i = 0; i < n; i++)
      jobs.push(sigSendRaw(room, to, JSON.stringify({ k: id, i: i, n: n, d: text.substr(i * SIG_CHUNK, SIG_CHUNK) })));
    return Promise.all(jobs).catch(function (e) { setErr("senalizacion: " + e); });
  }
  function sigListen(room, id, handler) {
    var parts = {}, stopped = false, es = null;
    function deliver(raw) {
      var m; try { m = JSON.parse(raw); } catch (e) { return; }
      if (m.k === undefined) return;
      var p = parts[m.k] || (parts[m.k] = { n: m.n, got: {}, c: 0 });
      if (!(m.i in p.got)) { p.got[m.i] = m.d; p.c++; }
      if (p.c === p.n) {
        delete parts[m.k];
        var s = ""; for (var i = 0; i < p.n; i++) s += p.got[i];
        try { handler(JSON.parse(s)); } catch (e) { log("señal inválida: " + e); }
      }
    }
    if (cfg.signal === "local") {
      (function loop() {
        if (stopped) return;
        fetch(cfg.base + "/sig/recv?room=" + room + "&id=" + id + "&wait=10")
          .then(function (r) { return r.json(); })
          .then(function (arr) { arr.forEach(deliver); loop(); })
          .catch(function () { setTimeout(loop, 1000); });
      })();
    } else {
      es = new EventSource(cfg.base + "/" + topic(room, id) + "/sse");
      es.onmessage = function (ev) {
        try { var d = JSON.parse(ev.data); if (d.event === "message") deliver(d.message); } catch (e) {}
      };
      es.onerror = function () { log("aviso: señalización reconectando"); };
    }
    return function () { stopped = true; if (es) es.close(); };
  }

  /* ---------------- WebRTC ---------------- */
  function newPC() { return new RTCPeerConnection({ iceServers: [{ urls: cfg.stun }] }); }
  function gathered(pc, ms) {
    return new Promise(function (res) {
      if (pc.iceGatheringState === "complete") return res();
      var t = setTimeout(res, ms);
      pc.addEventListener("icegatheringstatechange", function () {
        if (pc.iceGatheringState === "complete") { clearTimeout(t); res(); }
      });
    });
  }
  function openCount() {
    var n = 0; for (var k in S.conns) if (S.conns[k].dc && S.conns[k].dc.readyState === "open") n++;
    return n;
  }
  function wire(id, c) {
    var dc = c.dc;
    function gone(why) {                                // el otro jugador se fue (cierre o silencio)
      if (c.dead) return;
      c.dead = true;
      clearInterval(c.hb);
      log("fin de la conexión con " + id + " (" + why + ")");
      S.inbox.push(JSON.stringify({ sys: "leave", from: id }));
      if (S.conns[id] === c) delete S.conns[id];
      try { c.pc.close(); } catch (e) {}
      if (S.role === "client" && S.status === "connected") S.status = "error:se perdio la conexion con el anfitrion";
    }
    dc.onopen = function () {
      log("canal abierto con " + id);
      c.last = Date.now();
      c.hb = setInterval(function () {                  // latido: aviso cada 2 s; 10 s sin noticias = se fue
        if (dc.readyState === "open") { try { dc.send("\u0002"); } catch (e) {} }
        if (Date.now() - c.last > 10000) gone("sin respuesta");
      }, 2000);
      S.inbox.push(JSON.stringify({ sys: "join", from: id }));
      if (S.role === "client") S.status = "connected";
    };
    dc.onclose = function () { gone("canal cerrado"); };
    c.pc.addEventListener("connectionstatechange", function () {
      if (c.pc.connectionState === "failed" || c.pc.connectionState === "closed") gone(c.pc.connectionState);
    });
    dc.onmessage = function (ev) {
      var d = ev.data;
      if (typeof d !== "string") return;
      c.last = Date.now();
      if (d.charCodeAt(0) === 2) return;                // latido
      if (d.charCodeAt(0) === 1) {                       // trozo de un mensaje largo
        var q = d.slice(1).split("|"), mid = id + q[0], i = +q[1], n = +q[2], body = d.slice(d.indexOf("|", d.indexOf("|", d.indexOf("|") + 1) + 1) + 1);
        var p = S.parts[mid] || (S.parts[mid] = { n: n, got: {}, c: 0 });
        if (!(i in p.got)) { p.got[i] = body; p.c++; }
        if (p.c === p.n) {
          delete S.parts[mid];
          var s = ""; for (var j = 0; j < n; j++) s += p.got[j];
          S.inbox.push(JSON.stringify({ from: id, data: s }));
        }
      } else S.inbox.push(JSON.stringify({ from: id, data: d }));
    };
  }

  function hostOnHello(m) {
    var id = m.from;
    if (openCount() >= cfg.max) { sigSend(S.code, id, { t: "full" }); return; }
    if (S.conns[id]) { try { S.conns[id].pc.close(); } catch (e) {} }
    var pc = newPC(), c = { pc: pc, dc: pc.createDataChannel("game", { ordered: true }) };
    S.conns[id] = c; wire(id, c);
    pc.onconnectionstatechange = function () { log("host<->" + id + ": " + pc.connectionState); };
    pc.createOffer().then(function (o) { return pc.setLocalDescription(o); })
      .then(function () { return gathered(pc, 3000); })
      .then(function () { return sigSend(S.code, id, { t: "offer", from: "host", sdp: pc.localDescription.sdp }); })
      .catch(function (e) { log("oferta falló: " + e); });
  }
  function hostOnAnswer(m) {
    var c = S.conns[m.from];
    if (c) c.pc.setRemoteDescription({ type: "answer", sdp: m.sdp }).catch(function (e) { log("respuesta falló: " + e); });
  }
  function clientOnOffer(m) {
    if (S.conns.host) { try { S.conns.host.pc.close(); } catch (e) {} }
    var pc = newPC(), c = { pc: pc, dc: null };
    S.conns.host = c;
    pc.onconnectionstatechange = function () { log("cliente<->host: " + pc.connectionState); };
    pc.ondatachannel = function (ev) { c.dc = ev.channel; wire("host", c); if (c.dc.readyState === "open") c.dc.onopen(); };
    pc.setRemoteDescription({ type: "offer", sdp: m.sdp })
      .then(function () { return pc.createAnswer(); })
      .then(function (a) { return pc.setLocalDescription(a); })
      .then(function () { return gathered(pc, 3000); })
      .then(function () { return sigSend(S.code, "host", { t: "answer", from: S.id, sdp: pc.localDescription.sdp }); })
      .catch(function (e) { log("respuesta falló: " + e); });
  }

  /* ---------------- API ---------------- */
  var ZNet = {
    config: function (o) {
      if (typeof o === "string") { try { o = JSON.parse(o); } catch (e) { return; } }
      for (var k in o) cfg[k] = o[k];
    },
    host: function () {
      ZNet.close();
      S = fresh(); S.role = "host"; S.code = rid(6); S.id = "host"; S.status = "hosting";
      S.stopSig = sigListen(S.code, "host", function (m) {
        if (m.t === "hello") hostOnHello(m); else if (m.t === "answer") hostOnAnswer(m);
      });
      log("sala " + S.code + " creada");
      return S.code;
    },
    join: function (code) {
      ZNet.close();
      code = String(code || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
      if (code.length !== 6) { S = fresh(); setErr("el codigo tiene 6 caracteres"); return; }
      S = fresh(); S.role = "client"; S.code = code; S.id = rid(8); S.status = "joining";
      S.stopSig = sigListen(code, S.id, function (m) {
        if (m.t === "offer") clientOnOffer(m);
        else if (m.t === "full") setErr("la sala esta llena");
      });
      var tries = 0;
      function hello() {
        if (S.status !== "joining") return;
        if (++tries > 6) return setErr("no se encontro la sala (codigo correcto? el anfitrion sigue con la sala abierta?)");
        log("buscando sala " + code + " (intento " + tries + ")");
        sigSend(code, "host", { t: "hello", from: S.id });
        S.retry = setTimeout(hello, 6000);
      }
      setTimeout(hello, 400);                            // da tiempo a que la escucha quede activa
    },
    status: function () { return S.status; },
    code: function () { return S.code; },
    id: function () { return S.id; },
    peers: function () { return openCount(); },
    send: function (text, to) {
      text = String(text);
      var targets = to ? [to] : Object.keys(S.conns), sent = 0;
      targets.forEach(function (id) {
        var c = S.conns[id];
        if (!c || !c.dc || c.dc.readyState !== "open") return;
        if (text.length <= CHUNK) c.dc.send(text);
        else {
          var n = Math.ceil(text.length / CHUNK), mid = (++S.seq) + "";
          for (var i = 0; i < n; i++) c.dc.send("\u0001" + mid + "|" + i + "|" + n + "|" + text.substr(i * CHUNK, CHUNK));
        }
        sent++;
      });
      return sent;
    },
    pop: function () { return S.inbox.length ? S.inbox.shift() : ""; },
    buffered: function () {
      var b = 0; for (var k in S.conns) if (S.conns[k].dc) b += S.conns[k].dc.bufferedAmount; return b;
    },
    log: function () { return S.logs.join("\n"); },
    close: function () {
      if (S.retry) clearTimeout(S.retry);
      if (S.stopSig) S.stopSig();
      for (var k in S.conns) { try { S.conns[k].pc.close(); } catch (e) {} }
      S = fresh();
    }
  };
  window.ZNet = ZNet;
  window.addEventListener("pagehide", function () { try { ZNet.close(); } catch (e) {} });
})();
